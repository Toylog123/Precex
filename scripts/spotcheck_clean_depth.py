# -*- coding: utf-8 -*-
"""Clean-criterion depth spotcheck for leakfix clean repairs.
Usage: python3 scripts/spotcheck_clean_depth.py [--limit N] [--samples s17,s36]
"""
import argparse, glob, json, os, re, shutil, sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
import evaluator
from run_prestudy import apply_unified_diff

BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
RUNS = os.path.join(REPO_ROOT, "experiments", "runs")
WORK = os.path.join(RUNS, ".clean_depth")

MODULES = {
    "fifo_sync": (12, 24),
    "uart_tx": (12, 24),
    "uart_rx": (24, 48),
    "axi_lite_slave": (16, 32),
    "fsm_ctrl": (12, 24),
    "counter_alu": (12, 24),
}

def load_clean():
    rows = []
    for f in sorted(glob.glob(os.path.join(RUNS, "leakfix_[0-9].json"))):
        d = json.load(open(f, encoding="utf-8"))
        rs = d.get("results", d) if isinstance(d, dict) else d
        rows.extend(rs)
    seen, out = set(), []
    for r in rows:
        k = (r.get("sample"), r.get("setting"), r.get("seed"))
        if k in seen:
            continue
        seen.add(k); out.append(r)
    return out

def meta_of(sid):
    p = os.path.join(BUGS, sid, "meta.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--samples", default="")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()
    sel = set(x.strip() for x in args.samples.split(",") if x.strip())
    rows = load_clean()
    by = {}
    for r in rows:
        by.setdefault(r["sample"], []).append(r)
    todo = []
    for sid in sorted(by):
        if sel and sid not in sel:
            continue
        meta = meta_of(sid)
        mod = meta.get("module", "")
        if mod not in MODULES:
            continue
        picked = None
        for pref in ("B", "A", "C"):
            for r in by[sid]:
                if r["setting"] == pref and (r.get("diff_text") or "").strip():
                    picked = r; break
            if picked:
                break
        if not picked:
            continue
        todo.append((sid, picked, mod))
    if args.limit > 0:
        todo = todo[:args.limit]
    print("[spotcheck] targets=%d" % len(todo), flush=True)
    os.makedirs(WORK, exist_ok=True)
    out = []
    for sid, r, mod in todo:
        base_depth, deep_depth = MODULES[mod]
        d = os.path.join(WORK, "%s_%s_%d" % (sid, r["setting"], r["seed"]))
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        buggy = open(os.path.join(BUGS, sid, "buggy.v"), encoding="utf-8").read()
        ok, patched, err = apply_unified_diff(buggy, r["diff_text"])
        if not ok:
            out.append({"sample": sid, "setting": r["setting"], "seed": r["seed"], "module": mod,
                        "apply": "FAIL", "error": (err or "")[:200]})
            print("[%d] %s apply FAIL" % (len(out), sid), flush=True)
            continue
        with open(os.path.join(d, "buggy.v"), "w", encoding="utf-8") as f:
            f.write(patched)
        for fname in ("tb_weak.sv", "verify.sby"):
            sp = os.path.join(BUGS, sid, fname)
            if os.path.isfile(sp):
                shutil.copy(sp, os.path.join(d, fname))
        if mod == "uart_rx":
            up = os.path.join(BUGS, sid, "uart_tx.sv")
            if os.path.isfile(up):
                shutil.copy(up, os.path.join(d, "uart_tx.sv"))
        tb = os.path.join(d, "tb_weak.sv")
        tb_top = None
        if os.path.isfile(tb):
            m = re.search(r"modules+(w+)", open(tb, encoding="utf-8").read())
            if m:
                tb_top = m.group(1)
        ev = evaluator.evaluate(d, {"run_formal": True, "verbose": False, "tb_top": tb_top,
                                    "formal_timeout": args.timeout, "depth_override": deep_depth})
        res = {"sample": sid, "setting": r["setting"], "seed": r["seed"], "module": mod,
               "base_depth": base_depth, "deep_depth": deep_depth,
               "verdict": ev["verdict"], "formal": ev["formal"].get("result"),
               "exit_code": ev["formal"].get("exit_code")}
        out.append(res)
        print("[%d] %s/%s/%d mod=%s depth=%d->%d verdict=%s formal=%s" % (
            len(out), sid, r["setting"], r["seed"], mod, base_depth, deep_depth,
            ev["verdict"], ev["formal"].get("result")), flush=True)
    passes = sum(1 for x in out if x.get("verdict") == "PASS")
    print()
    print("=== CLEAN DEPTH SPOTCHECK SUMMARY ===")
    print("total=%d PASS=%d non-pass=%d" % (len(out), passes, len(out) - passes))
    for x in out:
        if x.get("verdict") != "PASS":
            print("NON-PASS:", json.dumps(x, ensure_ascii=False))
    with open(os.path.join(RUNS, "clean_depth_spotcheck.json"), "w", encoding="utf-8") as f:
        json.dump({"modules": MODULES, "total": len(out), "pass": passes, "results": out},
                  f, ensure_ascii=False, indent=2)
    print("written: experiments/runs/clean_depth_spotcheck.json")

if __name__ == "__main__":
    main()
