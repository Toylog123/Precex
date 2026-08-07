#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段 2a：证据卫生消融（2x2 分解实验 + eq_sem/off8 纠偏验证）。

变体：
  - base      ：复现当前 C 证据 + 原始 prompt（对照）
  - hygiene   ：行号标注设计 + failed_line->assert_line 语义纠偏 + 绝对行号指令
  - cot       ：hygiene + 分步推理指令
  - handshake ：hygiene + 静默信号语义（TraceAnalyzer key_signal_diffs 注入）

用法（WSL）：
  python3 scripts/run_hygiene_ablation.py --group eq_sem --variant hygiene --out experiments/runs/hygiene_eq_sem.json
  python3 scripts/run_hygiene_ablation.py --group s15 --variant base,hygiene,cot,handshake --out experiments/runs/hygiene_s15_2x2.json
"""
import argparse
import json
import os
import re
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from llm_client import LLMClient  # noqa: E402
from prompt_templates import SYSTEM_PROMPT, sanitize_design_text  # noqa: E402
from run_prestudy import parse_llm_output, apply_unified_diff  # noqa: E402
import evaluator  # noqa: E402
import run_experiments as rex  # noqa: E402

OUTPUT_FORMAT = rex.build_prompt.__globals__["OUTPUT_FORMAT"]

GROUPS = {
    "eq_sem": ["s08", "s11", "s17", "s18", "s22", "s32"],
    "off8": ["s05", "s06", "s13", "s16", "s20", "s21", "s23", "s26", "s30", "s31", "s35", "s36"],
    "deep_bd": ["s38", "s39", "s40", "s41", "s42"],
    "s15": ["s15"],
    "near1_other": ["s10", "s15", "s16", "s29", "s30", "s31", "s34"],
}

EQ_SEM_SEEDS = {"s08": [0, 1, 2], "s11": [0], "s17": [0, 1, 2], "s18": [1],
                "s22": [0], "s32": [0, 1, 2]}
OFF8_SEEDS = {"s05": [0], "s06": [0, 2], "s13": [2], "s16": [2], "s20": [1],
              "s21": [0, 1, 2], "s23": [1], "s26": [1, 2], "s30": [1],
              "s31": [2], "s35": [2], "s36": [2]}
# near1 (dev<=1) + other (真实 miss)：s15 已由 s15 组覆盖，这里只补 C 设置其余 miss
NEAR1_OTHER_TARGETS = [("s10", 1), ("s16", 1), ("s29", 0), ("s29", 1), ("s29", 2),
                       ("s30", 2), ("s31", 0), ("s34", 0), ("s34", 2)]
DEEP_BD_TARGETS = [
    ("s38", "B", 1), ("s39", "B", 0), ("s39", "B", 1), ("s40", "A", 2),
    ("s41", "A", 0), ("s42", "B", 0), ("s42", "B", 2), ("s40", "D", 1),
    ("s40", "D", 2), ("s38", "C", 2), ("s38", "D", 0), ("s38", "D", 2),
]


def _load_json(p):
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def number_design(design):
    lines = design.split("\n")
    return "\n".join("%4d: %s" % (i, ln) for i, ln in enumerate(lines, 1))


def _sanitize_diff_lines(diff_text):
    """LLM 在行号标注设计下可能把行号前缀带进 diff 内容行，剥离之。"""
    if not diff_text:
        return diff_text
    out = []
    for ln in diff_text.split("\n"):
        if ln.startswith(("-", "+")):
            body = ln[1:]
            m = re.match(r"^\s*\d+:\s*(.*)$", body)
            if m:
                out.append(ln[0] + m.group(1))
                continue
        out.append(ln)
    return "\n".join(out)


def build_hygiene_prompt(setting, sample_dir, meta, variant):
    design = sanitize_design_text(open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read())
    assertions = rex._extract_inline_assertions(design)
    ev_text = rex._build_evidence_text(setting, sample_dir)

    prompt = "请定位并修复以下 RTL 设计中的跨周期行为缺陷（L3：弱 tb 通过但形式验证失败）。\n\n"
    shown_design = number_design(design) if variant != "base" else design
    prompt += "【设计文件 buggy.sv】\n[systemverilog 代码开始]\n%s\n[systemverilog 代码结束]\n\n" % shown_design
    prompt += "【强断言（失效断言即形式失败点）】\n[systemverilog 代码开始]\n%s\n[systemverilog 代码结束]\n\n" % assertions

    if variant != "base":
        try:
            obj = json.loads(ev_text)
            if isinstance(obj, dict) and "failed_line" in obj:
                obj["assert_line"] = obj.pop("failed_line")
                obj["_note"] = "assert_line 是断言行（断言所在行），不是缺陷行；缺陷通常在数据通路/状态机中更早的行。"
                ev_text = json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            pass

    ev_label = "【证据段 C：反例语义化（周期事件表+状态轨迹+故障锥+NL 摘要）】" if setting == "C" else "【证据段】"
    prompt += ev_label + "\n[证据内容开始]\n" + ev_text + "\n[证据内容结束]\n\n"

    if variant != "base":
        prompt += ("【行号约定】line 必须是 buggy.sv 文件中从第 1 行起的绝对行号（设计代码中带行号前缀，"
                   "以其为准）。证据/断言段中的行号仅供参考——断言行不等于缺陷行。"
                   "diff 中不要带行号前缀。\n\n")
    if variant in ("cot", "handshake_cot"):
        prompt += ("【推理步骤】请按以下顺序分析后再给 diff：\n"
                   "1) 从证据中列出失败窗口内关键状态变量的期望值与实际值；\n"
                   "2) 找出第一个偏离期望的信号（或应翻转未翻转的信号）及其所在行；\n"
                   "3) 沿数据依赖推断根因行；\n"
                   "4) 生成最小 unified diff。\n\n")
    if variant in ("handshake", "handshake_cot", "handshake_v2"):
        ta = _load_json(os.path.join(sample_dir, "trace_analysis.json"))
        an = ta.get("analysis") or {}
        rows = []
        if an.get("first_anomaly_cycle") is not None:
            rows.append("首个异常周期=%s" % an["first_anomaly_cycle"])
        ksd = an.get("key_signal_diffs") or []
        if ksd:
            rows.append("应翻转未翻转信号=%s" % json.dumps(ksd, ensure_ascii=False))
        ss = an.get("stuck_signals") or []
        if ss:
            rows.append("静默信号=%s" % json.dumps(ss, ensure_ascii=False))
        if variant == "handshake_v2":
            dd = an.get("diff_detail") or {}
            if dd:
                rows.append("逐周期期望(golden)vs实际(buggy)值序列=" +
                            json.dumps(dd, ensure_ascii=False))
        if rows:
            prompt += ("【静默信号分析（TraceAnalyzer 动态切片）】%s\n"
                       "说明：这些信号在失败窗口内应翻转/变化但未变化，是握手/时序缺陷的直接证据。\n\n"
                       % "；".join(rows))
    prompt += "【元数据】error_type=%s module=%s\n" % (meta.get("error_type", "?"), meta.get("module", "?"))
    prompt += OUTPUT_FORMAT
    return prompt


def run_one(sample_dir, sample_id, setting, seed, variant, llm, out_dir, mock=False):
    meta = _load_json(os.path.join(sample_dir, "meta.json"))
    prompt = build_hygiene_prompt(setting, sample_dir, meta, variant)
    result = {"sample": sample_id, "setting": setting, "seed": seed, "variant": variant,
              "loc_line": None, "loc_top1": False, "loc_dev": None, "verdict": None,
              "repair_pass": False, "diff_text": "", "errors": [], "reason": ""}
    try:
        res = llm.chat(
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": prompt}],
            tag="hygiene:%s:%s:%s:%d" % (sample_id, setting, variant, seed),
            max_tokens=65536,
        )
    except Exception as e:
        result["errors"].append("llm: %s" % repr(e)[:300])
        return result
    result["input_tokens"] = res.get("input_tokens", 0)
    result["output_tokens"] = res.get("output_tokens", 0)
    result["cost"] = res.get("cost", 0.0)
    content = res.get("content", "")
    result["llm_raw"] = content
    loc, diff_text = parse_llm_output(content)
    result["loc_line"] = loc.get("line")
    result["reason"] = loc.get("reason", "")
    result["signals"] = loc.get("signals", "")
    result["diff_text"] = (diff_text or "")[:4000]
    buggy_lines = meta.get("buggy_inject_lines") or []
    if not buggy_lines:
        gl = meta.get("inject_line")
        bl = meta.get("buggy_inject_line", (gl + rex.BUGGY_HEADER_OFFSET) if gl else None)
        if bl:
            buggy_lines = [bl]
    loc_ln = loc.get("line")
    result["loc_top1"] = loc_ln in buggy_lines if buggy_lines else False
    if buggy_lines and loc_ln is not None:
        result["loc_dev"] = min(abs(loc_ln - x) for x in buggy_lines)
    if not diff_text:
        result["errors"].append("no diff")
        return result
    design = sanitize_design_text(open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read())
    ok, patched, err = apply_unified_diff(design, _sanitize_diff_lines(diff_text))
    if not ok:
        result["errors"].append("diff apply: %s" % err[:200])
        return result
    work = os.path.join(out_dir, "%s_%s_%s_seed%d" % (sample_id, setting, variant, seed))
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
        f.write(patched)
    for fname in ("tb_weak.sv", "verify.sby", "verify_repair.sby", "uart_tx.sv"):
        src = os.path.join(sample_dir, fname)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(work, fname))
    tb_top = None
    tb_path = os.path.join(work, "tb_weak.sv")
    if os.path.isfile(tb_path):
        m = re.search(r"module\s+(tb_\w+)", open(tb_path, encoding="utf-8").read())
        if m:
            tb_top = m.group(1)
    try:
        ev = evaluator.evaluate(work, {"run_formal": True, "verbose": False, "tb_top": tb_top})
        result["verdict"] = ev["verdict"]
        result["repair_pass"] = ev["verdict"] == "PASS"
    except Exception as e:
        result["errors"].append("evaluate: %s" % repr(e)[:200])
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=sorted(GROUPS))
    ap.add_argument("--variant", default="hygiene",
                    help="base,hygiene,cot,handshake,handshake_cot（逗号分隔跑多个）")
    ap.add_argument("--settings", default="C", help="C 或 A,B,C,D")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--out", required=True)
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    variants = [v.strip() for v in args.variant.split(",") if v.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    settings = [s.strip() for s in args.settings.split(",") if s.strip()]

    llm = LLMClient(provider=args.provider, mock=args.mock)
    out_dir = os.path.join(REPO_ROOT, "experiments", "runs", "_hygiene_work")
    os.makedirs(out_dir, exist_ok=True)

    targets = []
    if args.group == "s15":
        for sid in GROUPS["s15"]:
            sp = os.path.join(REPO_ROOT, "samples", "bugs", sid)
            for setting in settings:
                for seed in seeds:
                    targets.append((sid, sp, setting, seed))
    elif args.group == "deep_bd":
        for sid, setting, seed in DEEP_BD_TARGETS:
            if sid not in GROUPS["deep_bd"]:
                continue
            sp = os.path.join(REPO_ROOT, "samples", "deep", sid)
            targets.append((sid, sp, setting, seed))
    elif args.group == "eq_sem":
        for sid in GROUPS["eq_sem"]:
            sp = os.path.join(REPO_ROOT, "samples", "bugs", sid)
            for seed in EQ_SEM_SEEDS.get(sid, seeds):
                targets.append((sid, sp, "C", seed))
    elif args.group == "off8":
        for sid in GROUPS["off8"]:
            sp = os.path.join(REPO_ROOT, "samples", "bugs", sid)
            for seed in OFF8_SEEDS.get(sid, seeds):
                targets.append((sid, sp, "C", seed))
    elif args.group == "near1_other":
        for sid, seed in NEAR1_OTHER_TARGETS:
            sp = os.path.join(REPO_ROOT, "samples", "bugs", sid)
            targets.append((sid, sp, "C", seed))

    # 断点续跑：加载已有结果并按 (sample, setting, seed, variant) 去重，
    # 避免中断重启后整组重跑造成 API 重复花费（deep_bd 两次事故的教训）
    data0 = _load_json(args.out)
    results = [r for r in data0.get("results", []) if isinstance(r, dict)]
    done = {(r.get("sample"), r.get("setting"), r.get("seed"), r.get("variant"))
            for r in results if r.get("sample") and r.get("variant")}

    def _flush():
        # 每样本增量落盘：进程异常退出时已完成的样本不丢失
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump({"group": args.group, "variants": variants, "results": results},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            print("[hygiene] WARN flush failed: %r" % (e,), flush=True)

    for sid, sp, setting, seed in targets:
        for variant in variants:
            key = (sid, setting, seed, variant)
            if key in done:
                print("[hygiene] skip %s %s %s seed%d variant=%s (done)" % (sid, setting, args.group, seed, variant), flush=True)
                continue
            print("[hygiene] %s %s %s seed%d variant=%s" % (sid, setting, args.group, seed, variant), flush=True)
            try:
                r = run_one(sp, sid, setting, seed, variant, llm, out_dir, mock=args.mock)
            except Exception as e:  # noqa: BLE001
                print("[hygiene] ERROR %s: %r" % (sid, e), flush=True)
                r = {"sample": sid, "setting": setting, "seed": seed, "variant": variant,
                     "loc_line": None, "loc_top1": False, "loc_dev": None, "verdict": None,
                     "repair_pass": False, "diff_text": "", "errors": ["run_one: %s" % repr(e)[:300]], "reason": ""}
            results.append(r)
            done.add(key)
            _flush()
            print("   -> loc=%s top1=%s verdict=%s errs=%d" % (
                r.get("loc_line"), r.get("loc_top1"), r.get("verdict"), len(r.get("errors", []))), flush=True)
    n = len(results)
    n_ok = sum(1 for r in results if r.get("loc_top1"))
    print("[hygiene] done %d runs, loc_top1 %d/%d" % (n, n_ok, n))


if __name__ == "__main__":
    main()
