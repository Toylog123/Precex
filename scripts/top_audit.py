#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/top_audit.py 顶层互联审计（接口行为签名, WP4）

对每个 (sample, setting, seed) 修复后 RTL 与 golden 施加同一弱 tb 激励，
逐周期比对模块输出端口（接口行为签名）。输出接口签名一致率报告。

用法（WSL）:
  python3 scripts/top_audit.py --jobs 6 --out experiments/runs/top_audit_report.json
  python3 scripts/top_audit.py --samples s17 --limit-rows 3   # 冒烟
"""
from __future__ import annotations
import argparse, json, os, re, shutil, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))
import trace_analyzer as ta  # noqa: E402
from run_prestudy import apply_unified_diff  # noqa: E402
from vcd_parser import VcdParser  # noqa: E402

DEFAULT_RESULTS = [
    os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results_parallel.json"),
    os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results_ds_full3.json"),
]
DEFAULT_OUT = os.path.join(REPO_ROOT, "experiments", "runs", "top_audit_report.json")
TMP_ROOT = os.path.join(REPO_ROOT, "experiments", "runs", ".top_audit")

MODULE_OUTPUT_SIGS = {
    "fifo_sync": ["dout", "full", "empty", "half_full"],
    "fsm_ctrl": ["done", "timeout_irq", "state"],
    "uart_tx": ["txd", "tx_busy"],
    "uart_rx": ["rx_valid", "rx_data", "rx_busy"],
    "axi_lite_slave": [
        "S_AXI_AWREADY", "S_AXI_WREADY", "S_AXI_BRESP", "S_AXI_BVALID",
        "S_AXI_ARREADY", "S_AXI_RDATA", "S_AXI_RRESP", "S_AXI_RVALID",
    ],
    "counter_alu": ["cnt", "alu_out"],
}


def _signature_compare(golden_vcd, repaired_vcd, out_sigs, clk_sig):
    gp = VcdParser(golden_vcd, clk_sig=clk_sig).parse()
    rp = VcdParser(repaired_vcd, clk_sig=clk_sig).parse()
    gs = set(gp.all_signals())
    rs = set(rp.all_signals())
    sigs = [s for s in out_sigs if s in gs and s in rs]
    gt = gp.state_trace(sigs)
    rt = rp.state_trace(sigs)
    n = min(len(gt), len(rt))
    first_diff = None
    diff_sigs = {}
    for i in range(n):
        for s in sigs:
            gv, rv = gt[i].get(s), rt[i].get(s)
            if gv != rv and s not in diff_sigs:
                diff_sigs[s] = i
                if first_diff is None:
                    first_diff = i
    return {
        "sigs_compared": sigs,
        "cycles_compared": n,
        "first_diff_cycle": first_diff,
        "diff_sigs": diff_sigs,
        "match": first_diff is None and len(sigs) > 0,
    }


def audit_row(row, timeout):
    sid, setting, seed = row["sample"], row["setting"], row["seed"]
    out = {
        "sample": sid, "setting": setting, "seed": seed,
        "module": None, "match": None, "error": "",
        "first_diff_cycle": None, "diff_sigs": [], "sigs_compared": [],
        "cycles_compared": 0,
    }
    sample_dir = ta._find_sample_dir(sid) if hasattr(ta, "_find_sample_dir") else None
    if sample_dir is None:
        for base in (ta.BUGS, ta.DEEP):
            p = os.path.join(base, sid)
            if os.path.isdir(p):
                sample_dir = p
                break
    if sample_dir is None:
        out["error"] = "no_sample"
        return out
    meta = {}
    try:
        meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    except Exception:
        pass
    module = meta.get("module")
    out["module"] = module
    clk = ta.MODULE_CLK.get(module, "clk")
    out_sigs = MODULE_OUTPUT_SIGS.get(module, [])
    golden_vcd = os.path.join(ta.TRACE_ROOT, sid + "_g", "trace.vcd")
    if not os.path.isfile(golden_vcd):
        tb_src = open(os.path.join(sample_dir, "tb_weak.sv"), encoding="utf-8").read()
        tm = re.search(r"module\s+(tb_\w+)", tb_src)
        golden_vcd = ta._generate_vcd(sample_dir, "golden.v", tm.group(1) if tm else None,
                                      sid + "_g", timeout)
    if not golden_vcd or not os.path.isfile(golden_vcd):
        out["error"] = "no_golden_vcd"
        return out
    diff = row.get("diff_text") or ""
    if not diff.strip():
        out["error"] = "no_diff"
        return out
    buggy_src = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    ok, patched, err = apply_unified_diff(buggy_src, diff)
    if not ok:
        out["error"] = "diff_fail:" + (err or "")[:100]
        return out
    # 临时样本目录：patched 写为 buggy.v + tb + 依赖
    tmp = os.path.join(TMP_ROOT, "%s_%s_%d" % (sid, setting, seed))
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(tmp, "buggy.v"), "w", encoding="utf-8") as f:
        f.write(patched)
    shutil.copy(os.path.join(sample_dir, "tb_weak.sv"), os.path.join(tmp, "tb_weak.sv"))
    for extra in ("uart_tx.sv",):
        sp = os.path.join(sample_dir, extra)
        if os.path.isfile(sp):
            shutil.copy(sp, os.path.join(tmp, extra))
    tb_src = open(os.path.join(tmp, "tb_weak.sv"), encoding="utf-8").read()
    tm = re.search(r"module\s+(tb_\w+)", tb_src)
    repaired_vcd = ta._generate_vcd(tmp, "buggy.v", tm.group(1) if tm else None,
                                    "%s_%s_%d_ta" % (sid, setting, seed), timeout)
    if not repaired_vcd:
        out["error"] = "repaired_sim_fail"
        return out
    try:
        r = _signature_compare(golden_vcd, repaired_vcd, out_sigs, clk)
        out.update(r)
    except Exception as e:
        out["error"] = repr(e)[:200]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", action="append", default=None)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--limit-rows", type=int, default=None)
    ap.add_argument("--samples", default=None)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)

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
    if args.samples:
        want = {s.strip() for s in args.samples.split(",") if s.strip()}
        rows = [r for r in rows if r.get("sample") in want]
    if args.limit_rows:
        rows = rows[: args.limit_rows]
    print("rows: %d, jobs: %d" % (len(rows), args.jobs), flush=True)
    if not rows:
        return 1
    os.makedirs(TMP_ROOT, exist_ok=True)
    lock = threading.Lock()
    out_rows = []
    t0 = time.time()

    def _run(r):
        row = audit_row(r, args.timeout)
        with lock:
            out_rows.append(row)
            print("[%d] %s/%s/%d module=%s match=%s first_diff=%s err=%s" % (
                len(out_rows), row["sample"], row["setting"], row["seed"],
                row["module"], row["match"], row["first_diff_cycle"], (row.get("error") or "")[:60],
            ), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(_run, r) for r in rows]
        for _ in as_completed(futs):
            pass
    n_total = len(out_rows)
    n_match = sum(1 for x in out_rows if x.get("match") is True)
    n_mismatch = sum(1 for x in out_rows if x.get("match") is False)
    n_err = sum(1 for x in out_rows if x.get("match") is None)
    by_module = {}
    for x in out_rows:
        bm = by_module.setdefault(x["module"], {"total": 0, "match": 0, "mismatch": 0, "err": 0})
        bm["total"] += 1
        if x.get("match") is True:
            bm["match"] += 1
        elif x.get("match") is False:
            bm["mismatch"] += 1
        else:
            bm["err"] += 1
    for bm in by_module.values():
        bm["match_rate"] = round(100.0 * bm["match"] / max(1, bm["total"]), 1)
    summary = {
        "total": n_total, "match": n_match, "mismatch": n_mismatch, "error": n_err,
        "match_rate": round(100.0 * n_match / max(1, n_total), 1),
        "by_module": by_module, "elapsed": round(time.time() - t0, 1),
    }
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": out_rows}, f, ensure_ascii=False, indent=2)
    print("[done] -> %s" % args.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())