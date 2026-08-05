#!/usr/bin/env python3
# PreCex - scripts/llm_interpretability.py 多 LLM 证据可解释性评分（P2）
# 作者：Toylog | 版本：v0.1 | 功能概述：对 BugBench-PS 样本的 C/D 证据表示做 5 维 Likert
#   可解释性评分 + 行为代理定位（Top-1 行号），多提供商独立评分（temperature=0），
#   计算 ICC 组内相关系数与各维度分布，结果落盘 experiments/runs/llm_scores/（不入库），
#   token 记账由 llm_client 强制（账本 provider 字段区分）。
# 用法：
#   python3 scripts/llm_interpretability.py [--providers deepseek,minimax] [--samples s04-s37]
#       [--n 10] [--seed 20260804] [--mock] [--out experiments/runs/llm_scores]
"""PreCex 多 LLM 可解释性评分。"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
from llm_client import LLMClient, configured_providers, TokenLedger  # noqa: E402

SAMPLES_BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
DEFAULT_OUT = os.path.join(REPO_ROOT, "experiments", "runs", "llm_scores")
DIMS = ["completeness", "readability", "causality", "actionability", "trustworthiness"]
DIM_CN = {"completeness": "完整性", "readability": "可读性", "causality": "因果性",
          "actionability": "可操作性", "trustworthiness": "可信度"}
MAX_BUDGET_USD = 2.0

SYSTEM_PROMPT = """你是 PreCex 项目的证据质量评审员。你的任务是评估一段"缺陷定位证据"对 RTL 跨周期缺陷定位的可解释性。
你会收到：1) 设计文件（SystemVerilog，可能含缺陷）；2) 失效的强断言；3) 由工具自动生成的定位证据（反例语义化 或 FVDebug 式因果图）。
请独立地评估证据，不要臆测证据之外的信息。对 5 个维度各打 1-5 分（整数），并给出你基于该证据能给出的最可能的缺陷行号 Top-1。
只输出一个 JSON 对象，不要输出任何其他文字、解释或代码块标记。"""


def expand_samples(spec):
    ids = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^s(\d+)-s(\d+)$", part)
        if m:
            ids += ["s%02d" % i for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            ids.append(part)
    seen = set()
    out = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_inline_assertions(design):
    m = re.search(r"//.*?内联强断言.*?\n(.*?)\n\s*endmodule\b", design, re.S)
    if m:
        return m.group(1).strip()
    lines = design.splitlines()
    out = []
    for i, ln in enumerate(lines, 1):
        if "assert" in ln and "//" not in ln.split("assert")[0]:
            out.append("%4d: %s" % (i, ln))
    return "\n".join(out) if out else "（未提取到独立断言段，断言已内联于设计）"


def slim_semantics_text(sample_dir):
    """C 证据文本：与 run_experiments.py _SLIM_C 同协议（窗口 fail_step±4 + 每 8 拍采样 + 摘要截 300 字）。"""
    p = os.path.join(sample_dir, "semantics.json")
    with open(p, "r", encoding="utf-8") as f:
        s = json.load(f)
    fs = s.get("fail_step")

    def _ds(seq):
        if not seq:
            return seq
        out = []
        lo = max(0, (fs - 4) if fs is not None else 0)
        for i, item in enumerate(seq):
            cyc = item.get("cycle") if isinstance(item, dict) else i
            try:
                cyc = int(cyc)
            except (TypeError, ValueError):
                cyc = i
            if cyc >= lo or i % 8 == 0:
                out.append(item)
        return out

    slim = {
        "module": s.get("module"),
        "error_type": s.get("error_type"),
        "fail_stage": s.get("fail_stage"),
        "fail_step": fs,
        "failed_line": s.get("failed_line"),
        "trigger_condition": s.get("trigger_condition"),
        "fault_cone": s.get("fault_cone"),
        "cycle_events": _ds(s.get("cycle_events") or []),
        "state_trace": _ds(s.get("state_trace") or []),
    }
    ts = (s.get("text_summary") or "").strip()
    if ts:
        slim["text_summary"] = ts[:300] + ("…" if len(ts) > 300 else "")
    return json.dumps(slim, ensure_ascii=False, indent=2)


def d_evidence_text(sample_dir):
    """D 证据文本：FVDebug 式因果图（与 run_experiments.py D 分支同协议）。"""
    ev_path = os.path.join(sample_dir, "evidence.json")
    sem_path = os.path.join(sample_dir, "semantics.json")
    ev = {}
    sem = {}
    if os.path.isfile(ev_path):
        with open(ev_path, "r", encoding="utf-8") as f:
            ev = json.load(f)
    if os.path.isfile(sem_path):
        with open(sem_path, "r", encoding="utf-8") as f:
            sem = json.load(f)
    parts = ["## FVDebug 式因果图（D 设置：反例自动提取，无 LLM 生成）",
             "### 失败断言",
             "module=%s | error_type=%s | fail_stage=%s | fail_step=%s" % (
                 ev.get("module"), ev.get("error_type"), ev.get("fail_stage"), ev.get("fail_step")),
             "### 根因节点（fault_cone，按影响排序）"]
    for node in (sem.get("fault_cone") or []):
        parts.append("- %s" % (node if isinstance(node, str) else json.dumps(node, ensure_ascii=False)))
    parts.append("### 因果链状态轨迹（全周期可读信号名）")
    for row in (sem.get("state_trace") or []):
        parts.append("cyc%s: %s" % (row.get("cycle", "?"), json.dumps(row, ensure_ascii=False)))
    parts.append("### 触发条件")
    parts.append(str(sem.get("trigger_condition") or ev.get("trigger_condition") or "?"))
    return "\n".join(parts)


def build_user_prompt(sample_dir, setting):
    design = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    assertions = extract_inline_assertions(design)
    if setting == "C":
        ev_label = "【证据：反例语义化（周期事件表+状态轨迹+故障锥+NL 摘要）】"
        ev_text = slim_semantics_text(sample_dir)
    elif setting == "B":
        ev_label = "【证据：原始反例日志（B 基线）】"
        p = os.path.join(sample_dir, "cex.log")
        cex = open(p, encoding="utf-8", errors="replace").read() if os.path.isfile(p) else "（无 cex.log）"
        ev_text = cex[:2500]
    elif setting == "BH":
        ev_label = "【证据：结构化+握手分析（BH）】"
        ev_path = os.path.join(sample_dir, "evidence.json")
        ev = {}
        if os.path.isfile(ev_path):
            with open(ev_path, encoding="utf-8") as f:
                ev = json.load(f)
        ev_safe = {k: v for k, v in ev.items()
                   if k not in ("inject_line", "inject_desc", "diff", "buggy_inject_line")}
        parts = ["### 结构化证据（evidence.json）",
                 json.dumps(ev_safe, ensure_ascii=False, indent=2)[:1800]]
        sem_path = os.path.join(sample_dir, "semantics.json")
        if os.path.isfile(sem_path):
            sem = json.load(open(sem_path, encoding="utf-8"))
            parts.append("### 动态切片摘要")
            parts.append(json.dumps({k: sem.get(k) for k in
                                     ("fail_step", "trigger_condition", "fault_cone")},
                                    ensure_ascii=False)[:800])
        ev_text = "\n".join(parts)
    else:
        ev_label = "【证据：FVDebug 式因果图（失败断言+根因节点+因果链+触发条件）】"
        ev_text = d_evidence_text(sample_dir)
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    prompt = (
        "【设计文件 buggy.v（可能含缺陷）】\n[systemverilog 代码开始]\n" + design +
        "\n[systemverilog 代码结束]\n\n"
        "【失效强断言】\n[systemverilog 代码开始]\n" + assertions +
        "\n[systemverilog 代码结束]\n\n"
        + ev_label + "\n[证据内容开始]\n" + ev_text + "\n[证据内容结束]\n\n"
        "【元数据】module=%s | error_type=%s（不提供缺陷行号，请基于证据独立判断）\n\n"
        % (meta.get("module", "?"), meta.get("error_type", "?"))
    )
    prompt += (
        "【打分维度（1-5 分整数）】\n"
        "1. completeness 完整性：证据是否包含定位所需的全部关键信息（失败断言、信号、周期、触发条件）\n"
        "2. readability 可读性：结构清晰、无冗余/噪声，可快速阅读\n"
        "3. causality 因果性：是否呈现根因→中间状态→失效的因果链\n"
        "4. actionability 可操作性：能否据此直接推断缺陷位置（模块/信号/行号/条件）\n"
        "5. trustworthiness 可信度：信息可核验（与反例/断言一致）、无臆测成分\n\n"
        "只输出一个 JSON 对象，不要输出任何其他文字、解释、代码块标记或 think 标签。\n"
        "【输出 JSON 格式（严格）】\n"
        '{"scores": {"completeness": 1, "readability": 1, "causality": 1, "actionability": 1, '
        '"trustworthiness": 1}, "loc_line": <整数或 null>, "signals": ["信号1"], "reason": "一句话"}'
    )
    return prompt


def parse_json_score(content):
    """从模型输出提取 JSON 对象；容忍 think 标签/前后缀/代码块标记/截断 JSON。

    处理流程：1) 剥离 <think>...</think> 与代码块标记；2) 取首个 { 到最后一个 }；
    3) 直接 json.loads；4) 失败则尝试修复截断（补引号/括号）后再解析。
    """
    if not content:
        return None
    c = content
    c = re.sub(r"<think>.*?</think>", "", c, flags=re.S)
    c = re.sub(r"\`\`\`[a-zA-Z]*", "", c)
    c = re.sub(r"\`", "", c)
    start = c.find("{")
    end = c.rfind("}")
    if start < 0 or end <= start:
        return None
    cand = c[start:end + 1]
    try:
        return json.loads(cand)
    except json.JSONDecodeError:
        pass
    fixed = _repair_json(cand)
    if fixed is not None:
        return fixed
    return None


def _repair_json(cand):
    """轻量截断修复：尝试补齐缺失的右括号/引号；失败返回 None。"""
    for suffix in ("}", "}}", "}]}", '"}}', '"}}'):
        trial = cand.rstrip().rstrip(", ") + suffix
        try:
            return json.loads(trial)
        except json.JSONDecodeError:
            continue
    last_comma = cand.rfind(",")
    if last_comma > 0:
        trial = cand[:last_comma].rstrip() + "}"
        try:
            return json.loads(trial)
        except json.JSONDecodeError:
            pass
    return None


def true_line(meta):
    buggy = meta.get("buggy_inject_line")
    if buggy:
        return buggy
    golden = meta.get("inject_line")
    return (golden + 4) if golden else None


def icc21(mat):
    """ICC(2,1) Shrout-Fleiss：mat = n_targets × k_raters。"""
    n = len(mat)
    k = len(mat[0]) if mat else 0
    if n < 3 or k < 2:
        return None
    sums_t = [sum(row) for row in mat]
    sums_r = [sum(mat[i][j] for i in range(n)) for j in range(k)]
    grand = sum(sums_t)
    N = n * k
    ss_total = sum(x * x for row in mat for x in row) - grand * grand / N
    ss_r = sum(sr * sr for sr in sums_r) / n - grand * grand / N
    ss_t = sum(st * st for st in sums_t) / k - grand * grand / N
    ss_e = ss_total - ss_r - ss_t
    df_r, df_t, df_e = k - 1, n - 1, (n - 1) * (k - 1)
    if df_e <= 0:
        return None
    ms_r = ss_r / df_r
    ms_t = ss_t / df_t
    ms_e = ss_e / df_e
    if ms_e <= 0:
        return None
    denom = ms_t + (k - 1) * ms_e + k * (ms_r - ms_e) / n
    if denom <= 0:
        return None
    return (ms_t - ms_e) / denom


def main(argv=None):
    ap = argparse.ArgumentParser(prog="llm_interpretability.py")
    ap.add_argument("--providers", default=None, help="逗号分隔；默认取全部已配置 provider")
    ap.add_argument("--samples", default="s04-s37")
    ap.add_argument("--samples-dir", default="bugs", help="样本子目录：bugs/deep")
    ap.add_argument("--settings", default="C,D", help="评分设置：C/D/B/BH")
    ap.add_argument("--n", type=int, default=10, help="每设置抽取样本数（默认 10）")
    ap.add_argument("--seed", type=int, default=20260804)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--recompute", action="store_true",
                    help="仅基于 out/all.json 重算统计，不调用 LLM")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-budget", type=float, default=MAX_BUDGET_USD)
    args = ap.parse_args(argv)

    samples_root = os.path.join(os.path.dirname(SAMPLES_BUGS), args.samples_dir)
    if not os.path.isdir(samples_root):
        print("error: 样本目录不存在 %s" % samples_root)
        return 2
    settings = [s.strip() for s in args.settings.split(",") if s.strip()]
    sample_ids = [s for s in expand_samples(args.samples)
                  if os.path.isdir(os.path.join(samples_root, s))]
    eligible = []
    for sid in sample_ids:
        d = os.path.join(samples_root, sid)
        need = ["buggy.v", "meta.json", "evidence.json", "semantics.json"]
        if all(os.path.isfile(os.path.join(d, f)) for f in need):
            eligible.append(sid)
    if len(eligible) < args.n:
        print("warning: 合格样本 %d < n=%d，将全部使用" % (len(eligible), args.n))
    # 按模块分层轮询抽样（确定性，seed 仅用于打散模块内顺序）
    groups = {}
    for sid in eligible:
        meta = json.load(open(os.path.join(samples_root, sid, "meta.json"), encoding="utf-8"))
        groups.setdefault(meta.get("module", "?"), []).append(sid)
    for mod in groups:
        rng = __import__("random").Random(args.seed + sum(ord(c) for c in mod))
        rng.shuffle(groups[mod])
    selected = []
    while len(selected) < args.n and any(groups.values()):
        for mod in sorted(groups):
            if groups[mod] and len(selected) < args.n:
                selected.append(groups[mod].pop(0))
    print("[sample] 选中 %d 个样本（模块分层）：%s" % (len(selected), ",".join(selected)))

    providers = (args.providers.split(",") if args.providers else configured_providers())
    providers = [p.strip() for p in providers if p.strip()]
    print("[providers] 已配置可用：%s" % ",".join(providers))
    if not providers:
        print("error: 无可用 provider（.env 未配置任何 API key）")
        return 2

    os.makedirs(args.out, exist_ok=True)
    session = "interp-%s" % time.strftime("%Y%m%d%H%M%S")
    units = [(sid, setting) for sid in selected for setting in settings]

    if args.recompute:
        allp = os.path.join(args.out, "all.json")
        if not os.path.isfile(allp):
            print("error: %s 不存在" % allp)
            return 2
        rows = json.load(open(allp, encoding="utf-8"))
        providers = sorted({r.get("provider") for r in rows if r.get("provider")})
        settings = [r["setting"] for r in rows if r.get("setting")]
        settings = list(dict.fromkeys(settings))
        selected = list(dict.fromkeys(r.get("sample") for r in rows if r.get("sample")))
        units = [(sid, s) for sid in selected for s in settings]
        session = rows[0].get("session") or session if rows else session

    def run_unit(sid, setting, prov):
        client = LLMClient(provider=prov, temperature=0, max_retries=2, timeout=240,
                           session=session, mock=args.mock)
        prompt = build_user_prompt(os.path.join(samples_root, sid), setting)
        extra_kw = {"response_format": {"type": "json_object"}}
        if prov in ("minimax", "deepseek"):
            # 两模型默认思考会先输出大段 think 再 JSON 且易触顶截断；禁思考后直接输出 JSON（实测有效）
            extra_kw["thinking"] = {"type": "disabled"}
        res = client.chat(
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": prompt}],
            tag="interp:%s:%s:%s" % (sid, setting, prov),
            max_tokens=1500,
            **extra_kw,
        )
        parsed = parse_json_score(res["content"])
        scores = (parsed or {}).get("scores") or {}
        meta = json.load(open(os.path.join(samples_root, sid, "meta.json"), encoding="utf-8"))
        true = true_line(meta)
        loc = parsed.get("loc_line") if parsed else None
        return {
            "sample": sid, "setting": setting, "provider": prov, "model": client.model,
            "scores": {d: scores.get(d) for d in DIMS},
            "loc_line": loc, "loc_top1": bool(true is not None and loc == true),
            "true_line": true, "signals": (parsed or {}).get("signals") or [],
            "reason": (parsed or {}).get("reason") or "",
            "input_tokens": res["input_tokens"], "output_tokens": res["output_tokens"],
            "cost": res["cost"], "mode": res["mode"], "parse_ok": parsed is not None,
        }

    if not args.recompute:
        rows = []
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(run_unit, sid, setting, prov): (sid, setting, prov)
                    for (sid, setting) in units for prov in providers}
            for fut in futs:
                try:
                    rows.append(fut.result())
                except Exception as e:
                    sid, setting, prov = futs[fut]
                    rows.append({"sample": sid, "setting": setting, "provider": prov, "error": str(e)[:300]})
                    print("[FAIL] %s/%s/%s: %s" % (sid, setting, prov, str(e)[:200]))

    # 落盘：逐 provider 原始 JSON + 汇总
    per_provider = {}
    for prov in providers:
        per_provider[prov] = [r for r in rows if r.get("provider") == prov]
        with open(os.path.join(args.out, "%s.json" % prov), "w", encoding="utf-8") as f:
            json.dump(per_provider[prov], f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "all.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    # 维度统计 + ICC（按设置分组；仅统计解析成功且 5 维齐全的记录）
    def valid(r):
        return r.get("parse_ok") and all(r.get("scores", {}).get(d) is not None for d in DIMS)

    ok = [r for r in rows if valid(r)]
    stats = {"units": len(units), "rows": len(rows), "ok": len(ok),
             "parse_fail": [r for r in rows if not r.get("parse_ok")]}
    icc = {}
    dim_stats = {}
    for setting in settings:
        subset = [r for r in ok if r["setting"] == setting]
        if not subset:
            continue
        dim_stats[setting] = {}
        for d in DIMS:
            vals = [r["scores"][d] for r in subset]
            dim_stats[setting][d] = {
                "mean": round(sum(vals) / len(vals), 3),
                "min": min(vals), "max": max(vals),
                "by_provider": {p: round(sum(r["scores"][d] for r in subset if r["provider"] == p) /
                                         max(1, sum(1 for r in subset if r["provider"] == p)), 3)
                                for p in providers},
            }
        provs = sorted({r["provider"] for r in subset})
        if len(provs) >= 2:
            icc[setting] = {}
            for d in DIMS:
                mat = []
                by_target = {}
                for r in subset:
                    by_target.setdefault(r["sample"], {})[r["provider"]] = r["scores"][d]
                for sid in by_target:
                    row = [by_target[sid].get(p) for p in provs]
                    if all(x is not None for x in row):
                        mat.append(row)
                if len(mat) >= 3:
                    v = icc21(mat)
                    icc[setting][d] = round(v, 3) if v is not None else None
                else:
                    icc[setting][d] = None
    # 行为代理定位精度
    loc_acc = {}
    for setting in settings:
        subset = [r for r in rows if r.get("setting") == setting and r.get("loc_line") is not None]
        loc_acc[setting] = {}
        for p in providers:
            sub = [r for r in subset if r.get("provider") == p]
            loc_acc[setting][p] = {
                "n": len(sub),
                "top1": round(sum(1 for r in sub if r.get("loc_top1")) / max(1, len(sub)), 3),
            }
        loc_acc[setting]["all"] = {
            "n": len(subset),
            "top1": round(sum(1 for r in subset if r.get("loc_top1")) / max(1, len(subset)), 3),
        }
    stats["dim_stats"] = dim_stats
    stats["icc"] = icc
    stats["loc_acc"] = loc_acc
    stats["samples_root"] = samples_root
    stats["settings"] = settings
    stats["session"] = session
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # 记账核对（本 session 成本）
    led = TokenLedger().read()
    sess_cost = sum(r.get("cost") or 0 for r in led if r.get("session") == session)
    stats["session_cost"] = round(sess_cost, 6)
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print("\n==== 结果摘要 ====")
    print("样本数=%d 单元数=%d 调用数=%d 解析成功=%d 解析失败=%d 成本=$%.4f" % (
        len(selected), len(units), len(rows), len(ok), len(rows) - len(ok), sess_cost))
    for setting in settings:
        ds = dim_stats.get(setting, {})
        line = " | ".join("%s=%s" % (DIM_CN[d], ds.get(d, {}).get("mean")) for d in DIMS)
        print("[%s] 维度均分: %s" % (setting, line))
        print("[%s] ICC(2,1): %s" % (setting, icc.get(setting)))
        print("[%s] loc_top1: %s" % (setting, loc_acc.get(setting, {}).get("all")))
    if sess_cost > args.max_budget:
        print("warning: 本 session 成本 $%.4f 超过预算 $%.2f" % (sess_cost, args.max_budget))
    return 0 if not stats["parse_fail"] and ok else 1


if __name__ == "__main__":
    sys.exit(main())
