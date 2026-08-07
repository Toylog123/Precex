# -*- coding: utf-8 -*-
"""BMC depth scan over REPAIRED designs (1x-2x-4x-8x-10x)."""
import os, sys, json, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "harness"))
from evaluator import formal_check
from run_prestudy import apply_unified_diff

BASE_DEPTHS = {
    "fifo_sync": 12, "uart_tx": 12, "fsm_ctrl": 12, "counter_alu": 12,
    "axi_lite_slave": 16, "uart_rx": 24,
}
DIFF_SOURCES = [
    os.path.join(REPO, "experiments", "runs", "leakfix_merged_clean.json"),
    os.path.join(REPO, "experiments", "runs", "leakfix_D.json"),
    os.path.join(REPO, "experiments", "runs", "exp_c_ds_full.json"),
]


def load_repairs():
    repairs = {}
    for src in DIFF_SOURCES:
        if not os.path.isfile(src):
            continue
        with open(src, encoding="utf-8") as f:
            data = json.load(f)
        for r in data.get("results", []):
            sid = r.get("sample")
            diff = r.get("diff_text")
            verdict = r.get("verdict")
            if not sid or not diff or verdict != "PASS":
                continue
            repairs.setdefault(sid, []).append({
                "setting": r.get("setting"), "seed": r.get("seed"), "diff": diff,
            })
    out = {}
    for sid, items in repairs.items():
        seen = set()
        uniq = []
        for it in items:
            k = (it["setting"], it["seed"])
            if k not in seen:
                seen.add(k)
                uniq.append(it)
        out[sid] = uniq
    return out


def _compile_ok(text, sample_dir, top=None):
    """对补丁后的设计做 iverilog 语法自检（不生成可执行文件）。"""
    import subprocess
    work = os.path.join(REPO, "experiments", "runs", "_depth_work", "_syncheck")
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "syncheck.v"), "w", encoding="utf-8") as f:
        f.write(text)
    cmd = ["iverilog", "-g2012", "-tnull", os.path.join(work, "syncheck.v")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        if r.returncode == 0:
            return True, ""
        err = (r.stderr or "")[-800:]
        return False, err
    except Exception as e:
        return False, str(e)


def _pick_valid_repair(buggy_text, repairs):
    """按 (setting,seed) 顺序尝试每个候选：diff 内容匹配应用 + 语法自检。"""
    errs = []
    for it in repairs:
        ok, patched, err = apply_unified_diff(buggy_text, it["diff"])
        if not ok:
            errs.append("%s/%s apply:%s" % (it.get("setting"), it.get("seed"), err))
            continue
        ok2, cerr = _compile_ok(patched, None)
        if not ok2:
            errs.append("%s/%s compile:%s" % (it.get("setting"), it.get("seed"), (cerr or "")[:200]))
            continue
        return patched, it, ""
    return None, None, "; ".join(errs)[:1200]

def scan_repaired(sample_dir, repairs, timeout=900.0):
    sid = os.path.basename(sample_dir)
    buggy_path = os.path.join(sample_dir, "buggy.v")
    sby_path = os.path.join(sample_dir, "verify.sby")
    if not (os.path.isfile(buggy_path) and os.path.isfile(sby_path)):
        return {"sample": sid, "error": "missing files"}
    with open(buggy_path, encoding="utf-8") as f:
        buggy_text = f.read()
    with open(sby_path, encoding="utf-8") as f:
        sby_text = f.read()
    meta_path = os.path.join(sample_dir, "meta.json")
    module = "?"
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            module = json.load(f).get("module", "?")
    base = BASE_DEPTHS.get(module, 12)
    depths = []
    d = base
    while d <= base * 10:
        depths.append(d)
        d *= 2
    results = {}
    if not repairs:
        return {"sample": sid, "error": "no repair", "depths": depths, "results": {}}
    repaired, it, apply_err = _pick_valid_repair(buggy_text, repairs)
    if repaired is None:
        return {"sample": sid, "error": "no valid repair: %s" % apply_err,
                "depths": depths, "results": {}, "repair_setting": None}
    work = os.path.join(REPO, "experiments", "runs", "_depth_work", sid)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
        f.write(repaired)
    with open(os.path.join(work, "verify.sby"), "w", encoding="utf-8") as f:
        f.write(sby_text)
    for depth in depths:
        design_dir = os.path.join(work, "bmc_%d" % depth)
        # 断点续跑：已有明确 PASS/FAIL status 则复用，不重复跑
        status_path = os.path.join(design_dir, "status")
        cached = None
        if os.path.isfile(status_path):
            with open(status_path, encoding="utf-8") as f:
                head = (f.read(32) or "").strip().upper()
            if head.startswith("PASS") or head.startswith("FAIL"):
                cached = head.split()[0]
        if cached:
            results[str(depth)] = cached
            print("  [%s] depth=%d -> %s (cached)" % (sid, depth, cached), flush=True)
            continue
        os.makedirs(design_dir, exist_ok=True)
        res = formal_check(
            os.path.join(work, "verify.sby"), timeout=timeout,
            run_script=None, sby="sby", cwd=work,
            design_dir=design_dir, depth_override=depth,
        )
        r = res.get("result")
        results[str(depth)] = r.upper() if r else "UNKNOWN"
        print("  [%s] depth=%d -> %s" % (sid, depth, results[str(depth)]), flush=True)
    return {
        "sample": sid, "base_depth": base, "depths": depths,
        "results": results, "repair_setting": it.get("setting"), "work_dir": work,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=os.path.join(REPO, "experiments", "runs", "depth_scan_repaired.json"))
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()
    repairs = load_repairs()
    print("[depth] loaded repairs for %d samples" % len(repairs), flush=True)
    samples = []
    if args.sample:
        samples = [os.path.join(REPO, "samples", "bugs", args.sample)]
    elif args.all:
        bugs = os.path.join(REPO, "samples", "bugs")
        for sid in sorted(os.listdir(bugs)):
            sp = os.path.join(bugs, sid)
            if os.path.isdir(sp) and sid in repairs:
                samples.append(sp)
    results = []
    for sp in samples:
        sid = os.path.basename(sp)
        print("[depth] %s" % sid, flush=True)
        r = scan_repaired(sp, repairs.get(sid, []), timeout=args.timeout)
        results.append(r)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("[depth] saved %d samples -> %s" % (len(results), args.out))


if __name__ == "__main__":
    main()
