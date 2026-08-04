#!/usr/bin/env python3
# PreCex - scripts/run_experiments.py 主实验批量评测（M1 数据集 s04-s37）
# 作者：Toylog | 版本：v0.1 | 功能概述：对 samples/bugs 下 L3 样本批量跑 A/B/C × 3 随机种子评测：
#   - 证据链：A=cex 原始日志/VCD，B=evidence.json（结构化），C=semantics.json（反例语义化）
#   - LLM 定位+修复 → evaluator 三通过判定（compile/sim/formal，修复后期望 PASS）
#   - 指标：loc_top1 / repair_pass / verdict / tokens / cost / attempts
#   - 输出 experiments/runs/experiments_results.json + .csv（不入库），token 记账由 llm_client 强制
# 用法：
#   python3 scripts/run_experiments.py [--samples s04-s37] [--settings A,B,C]
#            [--seeds 0,1,2] [--retries 2] [--mock] [--out ...]
"""
PreCex 主实验批量评测。
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from llm_client import LLMClient  # noqa: E402
from prompt_templates import SYSTEM_PROMPT, build_prompt  # noqa: E402
from run_prestudy import parse_llm_output, apply_unified_diff  # noqa: E402
import evaluator  # noqa: E402

SAMPLES_BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
DEFAULT_OUT = os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results.json")
BUGGY_HEADER_OFFSET = 4  # buggy.v 头注释偏移（与 bug_injector 一致）：缺陷行号 = inject_line + 4



def expand_samples(spec):
    ids = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^s(\d+)-s(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            ids += ["s%02d" % i for i in range(lo, hi + 1)]
        else:
            ids.append(part)
    seen = set()
    out = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extract_inline_assertions(design):
    """提取内联断言段（buggy.v 中『内联强断言』标记之后、endmodule 前）。"""
    m = re.search(r"//.*?内联强断言.*?\n(.*?)\n\s*endmodule\b", design, re.S)
    if m:
        return m.group(1).strip()
    # 回退：提取所有 assert 行（含上下文），供 LLM 了解断言约束
    lines = design.splitlines()
    out = []
    for i, ln in enumerate(lines, 1):
        if "assert" in ln and "//" not in ln.split("assert")[0]:
            out.append("%4d: %s" % (i, ln))
    return "\n".join(out) if out else "（未提取到独立断言段，断言已内联于设计）"


def run_one(sample_dir, sample_id, setting, seed, llm, out_dir, mock=False, retries=2):
    """单个 (sample, setting, seed) 评测。返回结果 dict。"""
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    design = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    assertions = _extract_inline_assertions(design)
    ev_text = _build_evidence_text(setting, sample_dir)
    prompt = build_prompt(setting, design, assertions, ev_text, meta)
    prompt += "\n【重复试验】seed=%d（独立抽样标识，请独立判断）\n" % seed

    result = {
        "sample": sample_id, "setting": setting, "seed": seed, "mock": mock,
        "inject_line": meta.get("inject_line"), "error_type": meta.get("error_type"),
        "loc_top1": False, "loc_line": None, "reason": "", "signals": "",
        "repair_pass": False, "verdict": None, "attempts": 0,
        "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
        "diff_text": "", "errors": [], "llm_raw": "",
    }
    llm_out_dir = os.path.join(os.path.dirname(DEFAULT_OUT), "llm_outputs")
    os.makedirs(llm_out_dir, exist_ok=True)
    for attempt in range(retries + 1):
        result["attempts"] = attempt + 1
        try:
            res = llm.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tag="exp:%s:%s:seed%d" % (sample_id, setting, seed),
            )
        except Exception as e:
            result["errors"].append("attempt %d: llm call failed: %s" % (attempt, e))
            continue
        result["input_tokens"] += res["input_tokens"]
        result["output_tokens"] += res["output_tokens"]
        result["cost"] += res["cost"]
        content = res["content"]
        result["llm_raw"] = content
        with open(os.path.join(llm_out_dir, "%s_%s_seed%d_a%d.txt" % (sample_id, setting, seed, attempt)),
                  "w", encoding="utf-8") as f:
            f.write(content)
        loc, diff_text = parse_llm_output(content)
        result["loc_line"] = loc["line"]
        result["signals"] = loc["signals"]
        result["reason"] = loc["reason"]
        result["diff_text"] = (diff_text or "")[:4000]
        # loc_top1 判据：LLM 看到的是带头注释的 buggy.v，行号须对 buggy_inject_line；
        # 旧样本无该字段时回退 inject_line（golden 行号，仅近似）
        golden_line = meta.get("inject_line")
        buggy_line = meta.get("buggy_inject_line", (golden_line + BUGGY_HEADER_OFFSET) if golden_line else None)
        result["loc_top1"] = (loc["line"] == buggy_line)
        if not diff_text:
            result["errors"].append("attempt %d: no diff" % attempt)
            continue
        ok, patched, err = apply_unified_diff(design, diff_text)
        if not ok:
            result["errors"].append("attempt %d: diff apply failed: %s" % (attempt, err))
            continue
        work = os.path.join(out_dir, "%s_%s_seed%d_a%d" % (sample_id, setting, seed, attempt))
        os.makedirs(work, exist_ok=True)
        with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
            f.write(patched)
        for fname in ("tb_weak.sv", "verify.sby"):
            src = os.path.join(sample_dir, fname)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(work, fname))
        # 修复验证优先 prove 模式（k-induction，充分性更强）；无则回退 bmc
        rp_src = os.path.join(sample_dir, "verify_repair.sby")
        if os.path.isfile(rp_src):
            shutil.copy(rp_src, os.path.join(work, "verify_repair.sby"))
            if os.path.isfile(os.path.join(work, "verify.sby")):
                os.remove(os.path.join(work, "verify.sby"))
        # uart_rx 回环依赖
        if meta.get("module") == "uart_rx":
            src = os.path.join(sample_dir, "uart_tx.sv")
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(work, "uart_tx.sv"))
        tb_top = None
        tb_path = os.path.join(work, "tb_weak.sv")
        if os.path.isfile(tb_path):
            m = re.search(r"module\s+(tb_\w+)", open(tb_path, encoding="utf-8").read())
            if m:
                tb_top = m.group(1)
        ev = evaluator.evaluate(work, {"run_formal": True, "verbose": False, "tb_top": tb_top})
        result["verdict"] = ev["verdict"]
        result["verify_elapsed"] = {
            "compile": ev["compile"].get("elapsed"),
            "sim": ev["sim"].get("elapsed"),
            "formal": ev["formal"].get("elapsed"),
        }
        if ev["verdict"] == "PASS":
            result["repair_pass"] = True
            break
        result["errors"].append("attempt %d: verdict=%s formal=%s" % (
            attempt, ev["verdict"], ev["formal"].get("result")))
    return result


def _build_evidence_text(setting, sample_dir):
    """按设置读取证据文本（A/B/C），与 prompt_templates.build_evidence_text 同协议。"""
    if setting == "A":
        parts = []
        log = os.path.join(sample_dir, "cex.log")
        vcd = os.path.join(sample_dir, "cex.vcd")
        if os.path.isfile(log):
            with open(log, "r", encoding="utf-8", errors="replace") as f:
                parts.append("[cex.log]" + chr(10) + f.read())
        if os.path.isfile(vcd):
            with open(vcd, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
                if len(lines) > 160:
                    body = (chr(10).join(lines[:120]) + chr(10) + "...（中段省略）..."
                            + chr(10) + chr(10).join(lines[-40:]))
                else:
                    body = chr(10).join(lines)
                parts.append("[cex.vcd 原始波形]" + chr(10) + body)
        return chr(10).join(parts)
    if setting == "B":
        p = os.path.join(sample_dir, "evidence.json")
        if not os.path.isfile(p):
            return "（evidence.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    if setting == "C":
        p = os.path.join(sample_dir, "semantics.json")
        if not os.path.isfile(p):
            return "（semantics.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    raise ValueError("setting 必须是 A/B/C")


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    samples = ["s04-s37"]
    settings = ["A", "B", "C"]
    seeds = [0, 1, 2]
    mock = False
    retries = 2
    out_path = DEFAULT_OUT
    verbose = False
    if "--samples" in argv:
        samples = argv[argv.index("--samples") + 1].split(",")
    if "--settings" in argv:
        settings = argv[argv.index("--settings") + 1].split(",")
    if "--seeds" in argv:
        seeds = [int(x) for x in argv[argv.index("--seeds") + 1].split(",")]
    tasks_arg = []
    if "--tasks" in argv:
        tasks_arg = argv[argv.index("--tasks") + 1].split(",")

    if "--mock" in argv:
        mock = True
    if "--retries" in argv:
        retries = int(argv[argv.index("--retries") + 1])
    if "--out" in argv:
        out_path = argv[argv.index("--out") + 1]
    if "--verbose" in argv:
        verbose = True

    sample_ids = expand_samples(",".join(samples))
    dirs = {}
    for sid in sample_ids:
        p = os.path.join(SAMPLES_BUGS, sid)
        if os.path.isdir(p):
            dirs[sid] = p
        else:
            print("warning: 跳过未找到样本 %s" % sid)

    task_filter = None
    if tasks_arg:
        task_filter = set()
        for t in tasks_arg:
            parts = t.strip().split("/")
            if len(parts) == 3:
                task_filter.add((parts[0], parts[1], int(parts[2])))
            else:
                raise SystemExit("--tasks needs sXX/S/seed format: %s" % t)
        keep_s = sorted({t[0] for t in task_filter})
        keep_st = sorted({t[1] for t in task_filter})
        keep_sd = sorted({t[2] for t in task_filter})
        dirs = {s: dirs[s] for s in keep_s if s in dirs}
        settings = keep_st
        seeds = keep_sd

    llm = LLMClient(mock=mock, temperature=0.2)
    out_dir = tempfile.mkdtemp(prefix="exp_work_")
    results = []
    total = len(dirs) * len(settings) * len(seeds)
    idx = 0
    # 增量写入：每完成一条 append 一行到 <out>.partial.jsonl，中断不丢进度；启动时跳过已完成键（断点续跑）
    partial_path = out_path + ".partial.jsonl"
    done_keys = set()
    if os.path.isfile(partial_path):
        with open(partial_path, "r", encoding="utf-8") as pf:
            for ln in pf:
                ln = ln.strip()
                if not ln: continue
                try:
                    prev = json.loads(ln)
                    done_keys.add((prev["sample"], prev["setting"], prev["seed"]))
                    results.append(prev)
                except Exception:
                    pass
    for sid in sorted(dirs):
        for st in settings:
            for sd in seeds:
                idx += 1
                key = (sid, st, sd)
                if task_filter is not None and key not in task_filter:
                    continue
                if key in done_keys:
                    print("[skip %d/%d] %s/%s/seed%d (已存在，续跑跳过)" % (idx, total, sid, st, sd), flush=True)
                    continue
                print("[run %d/%d] sample=%s setting=%s seed=%d mock=%s" % (
                    idx, total, sid, st, sd, mock), flush=True)
                r = run_one(dirs[sid], sid, st, sd, llm, out_dir, mock=mock, retries=retries)
                print("[result] %s/%s/seed%d loc_top1=%s repair=%s verdict=%s cost=%.4f tokens=%d" % (
                    sid, st, sd, r["loc_top1"], r["repair_pass"], r["verdict"],
                    r["cost"], r["input_tokens"] + r["output_tokens"]), flush=True)
                results.append(r)
                with open(partial_path, "a", encoding="utf-8") as pf:
                    pf.write(json.dumps(r, ensure_ascii=False) + chr(10))
    shutil.rmtree(out_dir, ignore_errors=True)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"samples": sorted(dirs), "settings": settings, "seeds": seeds,
                   "results": results}, f, ensure_ascii=False, indent=2)
    csv_path = os.path.splitext(out_path)[0] + ".csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "sample", "setting", "seed", "loc_top1", "loc_line", "inject_line",
            "repair_pass", "verdict", "attempts", "input_tokens", "output_tokens",
            "cost", "reason"])
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    _write_summary(out_path, results)
    print("[done] results -> %s" % out_path)
    print("[csv]   -> %s" % csv_path)
    return 0


def _write_summary(out_path, results):
    """按 (sample, setting) 聚合 3 种子：loc_top1 均值/修复率/verdict 分布，输出 *summary.csv。"""
    agg = {}
    for r in results:
        key = (r["sample"], r["setting"])
        agg.setdefault(key, []).append(r)
    sum_path = os.path.splitext(out_path)[0] + "_summary.csv"
    with open(sum_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["sample", "setting", "n", "loc_top1_mean", "repair_pass_mean",
                    "pass_verdict", "fail_verdict", "inconc_verdict", "avg_cost"])
        for key in sorted(agg):
            rs = agg[key]
            n = len(rs)
            w.writerow([
                key[0], key[1], n,
                "%.3f" % (sum(1 for x in rs if x["loc_top1"]) / n),
                "%.3f" % (sum(1 for x in rs if x["repair_pass"]) / n),
                sum(1 for x in rs if x["verdict"] == "PASS"),
                sum(1 for x in rs if x["verdict"] == "FAIL"),
                sum(1 for x in rs if x["verdict"] in ("INCONCLUSIVE", "BROKEN")),
                "%.4f" % (sum(x["cost"] for x in rs) / n),
            ])
    print("[summary] -> %s" % sum_path)


if __name__ == "__main__":
    sys.exit(main())
