#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段 3：k-归纳可行性扫描（34 个 golden 设计）。

对每个 golden 设计跑 sby prove 模式（k-induction），统计收敛率。
- PROVE  ：Temporal induction successful（归纳证明收敛）
- PASS   ：BMC 通过但无归纳证明（非收敛）
- TIMEOUT：超过预算（资源限制）
- FAIL   ：发现反例（golden 不应发生；数据异常）
- ERROR  ：工具链/脚本错误

门禁（方案）：收敛率 >= 80% -> 判据升级可行；< 80% -> 断言增强优先。

用法（WSL）：
  python3 scripts/kinduction_feasibility.py [--samples s04,s05] [--timeout 600] [--depth-mult 2]
"""
import argparse
import json
import os
import re
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
from evaluator import formal_check  # noqa: E402

BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
DEEP = os.path.join(REPO_ROOT, "samples", "deep")
WORK = os.path.join(REPO_ROOT, "experiments", "runs", "_kinduction_work")

BASE_DEPTHS = {
    "fifo_sync": 12, "uart_tx": 12, "fsm_ctrl": 12, "counter_alu": 12,
    "axi_lite_slave": 16, "uart_rx": 24,
}


def meta_module(sample_dir):
    p = os.path.join(sample_dir, "meta.json")
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("module", "?")
        except Exception:
            pass
    return "?"


def build_prove_sby(sample_dir, depth):
    golden = os.path.join(sample_dir, "golden.v")
    if not os.path.isfile(golden):
        return None, "no golden.v"
    module = meta_module(sample_dir)
    sby = ("# PreCex k-induction feasibility (prove mode on golden)\n"
           "[tasks]\nprove\n\n"
           "[options]\nprove: mode prove\nprove: depth %d\nprove: timeout 600\n\n"
           "[engines]\nprove: smtbmc z3\n\n"
           "[script]\nread -sv -formal golden.v\nprep -top %s\n\n"
           "[files]\ngolden.v\n" % (depth, module))
    return sby, None


def classify(out):
    if "Temporal induction successful" in out or "successful proof" in out:
        return "PROVE"
    base_pass = "returned pass for basecase" in out
    induction_fail = ("FAIL for induction" in out) or ("DONE (UNKNOWN" in out)
    if base_pass and induction_fail:
        # 基例通过（BMC 深度内安全）但归纳步不收敛 -> 非归纳性质，属 PASS-without-proof
        return "PASS"
    if "DONE (FAIL" in out or "Assert failed" in out or "Reached cover" in out:
        return "FAIL"
    if "DONE (PASS" in out or "BMC successful" in out or "Successfully" in out:
        return "PASS"
    if "TIMEOUT" in out or "timeout" in out.lower():
        return "TIMEOUT"
    return "ERROR"


def scan_one(sample_dir, sid, timeout, depth_mult):
    module = meta_module(sample_dir)
    base = BASE_DEPTHS.get(module, 12)
    depth = max(1, int(base * depth_mult))
    sby_text, err = build_prove_sby(sample_dir, depth)
    if sby_text is None:
        return {"sample": sid, "module": module, "depth": depth, "result": "ERROR", "error": err}
    work = os.path.join(WORK, sid)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "golden.v"), "w", encoding="utf-8") as f:
        f.write(open(os.path.join(sample_dir, "golden.v"), encoding="utf-8").read())
    with open(os.path.join(work, "prove.sby"), "w", encoding="utf-8") as f:
        f.write(sby_text)
    try:
        res = formal_check(os.path.join(work, "prove.sby"), timeout=timeout,
                           run_script=None, sby="sby", cwd=work,
                           design_dir=os.path.join(work, "prove_out"))
    except Exception as e:
        return {"sample": sid, "module": module, "depth": depth, "result": "ERROR",
                "error": repr(e)[:200]}
    out = (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
    # 统一用本脚本分类器：induction 阶段的反例（基例通过+归纳不收敛）必须归为 PASS-without-proof，
    # 不能采用 evaluator 的 fail（那是 BMC 口径）。
    result = classify(out)
    return {"sample": sid, "module": module, "depth": depth, "result": result,
            "elapsed": res.get("elapsed"), "error": (res.get("error") or "")[:120]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--depth-mult", type=float, default=1.0)
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "experiments", "runs", "kinduction_feasibility.json"))
    ap.add_argument("--include-deep", action="store_true")
    args = ap.parse_args()

    sel = set(x.strip() for x in args.samples.split(",") if x.strip())
    targets = []
    for base, label in ((BUGS, "bugs"), (DEEP, "deep")):
        if base == DEEP and not args.include_deep:
            continue
        if not os.path.isdir(base):
            continue
        for sid in sorted(os.listdir(base)):
            sp = os.path.join(base, sid)
            if os.path.isdir(sp) and os.path.isfile(os.path.join(sp, "golden.v")):
                if sel and sid not in sel:
                    continue
                targets.append((sid, sp))
    print("[kinduction] targets=%d timeout=%s depth_mult=%s" % (len(targets), args.timeout, args.depth_mult), flush=True)
    os.makedirs(WORK, exist_ok=True)
    results = []
    for sid, sp in targets:
        print("[kinduction] %s" % sid, flush=True)
        r = scan_one(sp, sid, args.timeout, args.depth_mult)
        results.append(r)
        print("   -> %s (depth=%s) %s" % (r["result"], r["depth"], r.get("error", "")), flush=True)
    prov = sum(1 for r in results if r["result"] == "PROVE")
    pas = sum(1 for r in results if r["result"] == "PASS")
    fail = sum(1 for r in results if r["result"] == "FAIL")
    to = sum(1 for r in results if r["result"] == "TIMEOUT")
    err = sum(1 for r in results if r["result"] == "ERROR")
    n = len(results)
    converged = prov / n if n else 0.0
    summary = {"total": n, "prove": prov, "pass": pas, "fail": fail, "timeout": to,
               "error": err, "convergence_rate": round(converged, 4)}
    print("[kinduction] SUMMARY %s" % json.dumps(summary, ensure_ascii=False))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)
    print("[kinduction] saved -> %s" % args.out)


if __name__ == "__main__":
    main()
