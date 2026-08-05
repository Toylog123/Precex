#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/adaptive_bmc.py adaptive BMC depth verification (WP1)
Author: Toylog | Version: v0.1 | Purpose: rebuild repaired RTL from saved diffs,
then run golden-first adaptive-depth BMC: depths base*1.5 -> *2 -> *4,
checking repaired RTL and golden at each depth. Output max_passed_depth report.
Usage: python3 scripts/adaptive_bmc.py [--results <json>] [--jobs 8] [--depths 1.5,2,4]
      [--timeout 180] [--limit-rows N] [--out <json>]
"""
from __future__ import annotations
import argparse, json, math, os, re, shutil, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
from run_prestudy import apply_unified_diff  # noqa: E402
import evaluator  # noqa: E402

BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
DEEP = os.path.join(REPO_ROOT, "samples", "deep")
DEFAULT_RESULTS = [
    os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results_parallel.json"),
    os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results_ds_full3.json"),
]
DEFAULT_OUT = os.path.join(REPO_ROOT, "experiments", "runs", "adaptive_bmc_report.json")
WORK_ROOT = os.path.join(REPO_ROOT, "experiments", "runs", ".adaptive_bmc")


def _find_sample_dir(sample_id):
    for base in (BUGS, DEEP):
        p = os.path.join(base, sample_id)
        if os.path.isdir(p):
            return p
    return None


def _read_depth(sby_path):
    try:
        with open(sby_path, "r", encoding="utf-8") as f:
            m = re.search(r"(?m)^bmc:\s*depth\s+(\d+)\s*$", f.read())
        return int(m.group(1)) if m else None
    except OSError:
        return None






def _make_workdir(sample_dir, tag, patched_src):
    d = os.path.join(WORK_ROOT, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "buggy.v"), "w", encoding="utf-8") as f:
        f.write(patched_src)
    for fname in ("tb_weak.sv", "verify.sby", "verify_golden.sby"):
        sp = os.path.join(sample_dir, fname)
        if os.path.isfile(sp):
            shutil.copy(sp, os.path.join(d, fname))
    # golden 对照需要 golden.v（verify_golden.sby 的 [files] 引用）
    gp = os.path.join(sample_dir, "golden.v")
    if os.path.isfile(gp):
        shutil.copy(gp, os.path.join(d, "golden.v"))
    meta_p = os.path.join(sample_dir, "meta.json")
    if os.path.isfile(meta_p):
        try:
            meta = json.load(open(meta_p, encoding="utf-8"))
        except Exception:
            meta = {}
        if meta.get("module") == "uart_rx":
            up = os.path.join(sample_dir, "uart_tx.sv")
            if os.path.isfile(up):
                shutil.copy(up, os.path.join(d, "uart_tx.sv"))
    return d

def _formal_at_depth(workdir, sby_name, depth, timeout):
    sby_file = os.path.join(workdir, sby_name)
    if not os.path.isfile(sby_file):
        return {"result": "no_sby", "exit_code": None, "elapsed": 0.0}
    t0 = time.time()
    res = evaluator.formal_check(
        sby_file, timeout=timeout, cwd=workdir,
        design_dir=os.path.join(workdir, ".sby_%s" % depth),
        depth_override=depth,
    )
    res["elapsed"] = round(time.time() - t0, 2)
    return res

def _tb_top(workdir):
    tb = os.path.join(workdir, "tb_weak.sv")
    if not os.path.isfile(tb):
        return None
    m = re.search(r"module\s+(tb_\w+)", open(tb, encoding="utf-8").read())
    return m.group(1) if m else None


def run_adaptive(row, depths, timeout, limit):
    sid, setting, seed = row["sample"], row["setting"], row["seed"]
    out = {
        "sample": sid, "setting": setting, "seed": seed,
        "old_repair_pass": row.get("repair_pass"), "attempts": row.get("attempts"),
        "module": None, "base_depth": None, "depths_tried": [], "results": [],
        "max_passed_depth": None, "verdict": "ERROR", "apply": "OK",
    }
    sample_dir = _find_sample_dir(sid)
    if sample_dir is None:
        out["apply"] = "NO_SAMPLE"; out["verdict"] = "SKIP"; return out
    meta = {}
    try:
        meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
        out["module"] = meta.get("module")
    except Exception:
        pass
    base = _read_depth(os.path.join(sample_dir, "verify.sby"))
    out["base_depth"] = base
    if not base:
        out["apply"] = "NO_DEPTH"; out["verdict"] = "SKIP"; return out
    diff = row.get("diff_text") or ""
    if not diff.strip():
        out["apply"] = "NO_DIFF"; out["verdict"] = "SKIP"; return out
    buggy_src = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    ok, patched, err = apply_unified_diff(buggy_src, diff)
    if not ok:
        out["apply"] = "DIFF_FAIL"; out["verdict"] = "SKIP"; out["error"] = (err or "")[:200]; return out
    workdir = _make_workdir(sample_dir, "%s_%s_%d" % (sid, setting, seed), patched)
    try:
        tb_top = _tb_top(workdir)
        files = [os.path.join(workdir, "buggy.v")]
        if tb_top:
            files.append(os.path.join(workdir, "tb_weak.sv"))
        if meta.get("module") == "uart_rx":
            up = os.path.join(workdir, "uart_tx.sv")
            if os.path.isfile(up):
                files.append(up)
        sim = evaluator.sim_check(files, top=tb_top, out_bin=os.path.join(workdir, "sim.out"), cwd=workdir)
        out["sim_ok"] = sim["ok"]
    except Exception as e:
        out["sim_ok"] = False
        out["sim_error"] = repr(e)[:200]
    seq = [int(math.ceil(base * m)) for m in depths]
    prev_pass = True
    for d in seq:
        repaired = _formal_at_depth(workdir, "verify.sby", d, timeout)
        golden = _formal_at_depth(workdir, "verify_golden.sby", d, timeout)
        row_res = {
            "depth": d,
            "repaired": repaired.get("result"),
            "repaired_exit": repaired.get("exit_code"),
            "repaired_elapsed": repaired.get("elapsed"),
            "golden": golden.get("result"),
            "golden_exit": golden.get("exit_code"),
            "golden_elapsed": golden.get("elapsed"),
        }
        out["depths_tried"].append(d)
        out["results"].append(row_res)
        depth_pass = (
            repaired.get("result") in ("pass", "prove")
            and golden.get("result") in ("pass", "prove")
            and prev_pass
        )
        if depth_pass:
            out["max_passed_depth"] = d
            out["verdict"] = "PASS"
        else:
            out["verdict"] = "LIMITED"
            out["fail_reason"] = (
                "repaired_fail"
                if row_res.get("repaired") not in ("pass", "prove")
                else "golden_fail"
            )
            break
        prev_pass = depth_pass
        if limit and d >= limit:
            out["verdict"] = "LIMITED"; out["fail_reason"] = "depth_limit"; break
    out["sufficient"] = out["verdict"] == "PASS" and (
        out["max_passed_depth"] is not None
        and out["max_passed_depth"] >= (out["base_depth"] or 0) + 2
    )
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", action="append", default=None)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--depths", default="1.5,2,4")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--limit-rows", type=int, default=None)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    depths = [float(x) for x in args.depths.split(",") if x.strip()]
    rows = []
    seen = set()
    for rf in (args.results or DEFAULT_RESULTS):
        if not os.path.isfile(rf):
            print("skip missing results: %s" % rf, flush=True)
            continue
        data = json.load(open(rf, encoding="utf-8"))
        for r in data.get("results", []):
            key = (r.get("sample"), r.get("setting"), r.get("seed"))
            if key in seen:
                continue
            seen.add(key)
            if (r.get("diff_text") or "").strip():
                rows.append(r)
    if args.limit_rows:
        rows = rows[: args.limit_rows]
    print("rows with diff: %d, jobs: %d, depths: %s" % (len(rows), args.jobs, depths), flush=True)
    if not rows:
        print("no rows; exit 1", flush=True)
        return 1
    os.makedirs(WORK_ROOT, exist_ok=True)
    lock = threading.Lock()
    out = []
    t_start = time.time()

    def _run(r):
        row = run_adaptive(r, depths, args.timeout, args.limit)
        with lock:
            out.append(row)
            print("[%d] %s/%s/%d base=%s max=%s verdict=%s sim=%s" % (
                len(out), row["sample"], row["setting"], row["seed"],
                row["base_depth"], row["max_passed_depth"], row["verdict"], row.get("sim_ok"),
            ), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(_run, r) for r in rows]
        for _ in as_completed(futs):
            pass
    elapsed = round(time.time() - t_start, 1)
    n_pass = sum(1 for x in out if x["verdict"] == "PASS")
    n_limited = sum(1 for x in out if x["verdict"] == "LIMITED")
    n_skip = sum(1 for x in out if x["verdict"] == "SKIP")
    n_sufficient = sum(1 for x in out if x.get("sufficient"))
    summary = {
        "total": len(out), "pass": n_pass, "limited": n_limited, "skip": n_skip,
        "sufficient": n_sufficient,
        "pass_rate": round(100.0 * n_pass / max(1, len(out)), 1),
        "sufficient_rate": round(100.0 * n_sufficient / max(1, len(out)), 1),
        "elapsed": elapsed,
    }
    print("\n=== SUMMARY ===", flush=True)
    for k, v in summary.items():
        print("%s: %s" % (k, v), flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": out}, f, ensure_ascii=False, indent=2)
    print("[done] -> %s" % args.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
