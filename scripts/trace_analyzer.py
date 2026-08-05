#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/trace_analyzer.py dynamic trace comparison (WP2)
Author: Toylog | Version: v0.2 | Purpose: generate same-stimulus golden/buggy VCD
via iverilog + dump injection, then compare cycle-aligned signals to produce:
  first_anomaly_cycle, key_signal_diffs, stuck_signals.
Output per sample: samples/<dir>/<sample>/trace_analysis.json
Usage (in WSL): python3 scripts/trace_analyzer.py --samples s07 [--samples-dir bugs]
"""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))
from vcd_parser import VcdParser  # noqa: E402

BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
DEEP = os.path.join(REPO_ROOT, "samples", "deep")
TRACE_ROOT = os.path.join(REPO_ROOT, "experiments", "runs", ".trace")
KEY_SIGS = [
    "rst_n", "wr_en", "rd_en", "cnt_en", "en", "start", "valid", "ready",
    "state", "state_d", "cnt", "cnt_d", "count", "count_d", "step_cnt", "step_cnt_d",
    "head", "tail", "full", "empty", "half_full", "full_d", "empty_d",
    "done", "timeout_irq", "op", "op_d", "a", "b", "a_d", "b_d", "alu_out", "alu_out_d",
    "data_in", "din", "dout",
    "tx_start", "tx_data", "txd", "tx_busy", "bit_cnt", "baud_cnt", "baud_tick",
    "rxd", "rx_busy", "rx_data", "rx_valid", "rx_ready",
    "ACLK", "ARESETN", "S_AXI_AWADDR", "S_AXI_AWVALID", "S_AXI_AWREADY",
    "S_AXI_WDATA", "S_AXI_WSTRB", "S_AXI_WVALID", "S_AXI_WREADY",
    "S_AXI_BRESP", "S_AXI_BVALID", "S_AXI_BREADY",
    "S_AXI_ARADDR", "S_AXI_ARVALID", "S_AXI_ARREADY",
    "S_AXI_RDATA", "S_AXI_RRESP", "S_AXI_RVALID", "S_AXI_RREADY",
    "reg0", "reg1", "reg2", "reg3", "aw_done", "w_done",
]
MODULE_CLK = {
    "fifo_sync": "clk", "fsm_ctrl": "clk", "uart_tx": "clk",
    "uart_rx": "clk", "axi_lite_slave": "ACLK", "counter_alu": "clk",
}
DL = "$" + "dumpfile"
DV = "$" + "dumpvars"


def _inject_dump(tb_src):
    """Insert dump initial block right after module declaration (idempotent)."""
    if "dumpfile" in tb_src:
        return tb_src
    m = re.search(r"module\s+(tb_\w+)\s*;", tb_src)
    if not m:
        return tb_src
    q = chr(34)
    block = (
        "\n    initial begin\n"
        "        " + DL + "(" + q + "trace.vcd" + q + ");\n"
        "        " + DV + "(0);\n"
        "    end\n"
    )
    return tb_src[: m.end()] + block + tb_src[m.end():]


def _compile_sim(work, design_src_name, top, timeout):
    """iverilog compile design+tb, run vvp -> trace.vcd. Return (ok, err)."""
    try:
        r = subprocess.run(
            ["iverilog", "-g2012", design_src_name, "tb_weak.sv", "-s", top, "-o", "sim.out"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=work,
        )
        if r.returncode != 0:
            return False, (r.stdout + r.stderr)[-500:]
        r2 = subprocess.run(["vvp", "sim.out"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, cwd=work)
        vcd = os.path.join(work, "trace.vcd")
        return (os.path.isfile(vcd) and os.path.getsize(vcd) > 0), (r2.stdout + r2.stderr)[-300:]
    except Exception as e:
        return False, repr(e)[:200]


def _generate_vcd(sample_dir, design_src_name, tb_top, tag, timeout):
    """Run same-stimulus sim for one design; return vcd path or None."""
    work = os.path.join(TRACE_ROOT, tag)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    shutil.copy(os.path.join(sample_dir, design_src_name), os.path.join(work, design_src_name))
    tb = open(os.path.join(sample_dir, "tb_weak.sv"), encoding="utf-8").read()
    open(os.path.join(work, "tb_weak.sv"), "w", encoding="utf-8").write(_inject_dump(tb))
    for extra in ("uart_tx.sv",):
        sp = os.path.join(sample_dir, extra)
        if os.path.isfile(sp):
            shutil.copy(sp, os.path.join(work, extra))
    ok, err = _compile_sim(work, design_src_name, tb_top, timeout)
    vcd = os.path.join(work, "trace.vcd")
    if ok and os.path.isfile(vcd):
        return vcd
    return None


def _cycle_compare(golden_vcd, buggy_vcd, clk_sig):
    """Compare cycle-aligned traces; return analysis dict."""
    gp = VcdParser(golden_vcd, clk_sig=clk_sig).parse()
    bp = VcdParser(buggy_vcd, clk_sig=clk_sig).parse()
    sigs = [s for s in KEY_SIGS if s in set(gp.all_signals()) and s in set(bp.all_signals())]
    gt = gp.state_trace(sigs)
    bt = bp.state_trace(sigs)
    n = min(len(gt), len(bt))
    first_anomaly = None
    diffs = {}
    for i in range(n):
        for s in sigs:
            gv = gt[i].get(s)
            bv = bt[i].get(s)
            if gv != bv and s not in diffs:
                diffs[s] = i
                if first_anomaly is None:
                    first_anomaly = i
    stuck = []
    if first_anomaly is not None:
        for s in sigs:
            gvals = [gt[i].get(s) for i in range(first_anomaly, n)]
            bvals = [bt[i].get(s) for i in range(first_anomaly, n)]
            g_unique = {v for v in gvals if v is not None}
            b_unique = {v for v in bvals if v is not None}
            if len(g_unique) > 1 and len(b_unique) <= 1:
                stuck.append(s)
    return {
        "first_anomaly_cycle": first_anomaly,
        "key_signal_diffs": sorted(diffs.items(), key=lambda x: x[1]),
        "stuck_signals": sorted(stuck),
        "cycles_compared": n,
    }


def analyze_sample(sample_dir, sample_id, clk_sig, timeout):
    out = {"sample": sample_id, "ok": False, "error": "", "analysis": None}
    try:
        meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    except Exception:
        meta = {}
    top = meta.get("module")
    if not top:
        out["error"] = "no module in meta"
        return out
    clk = clk_sig or MODULE_CLK.get(top, "clk")
    tb_src = open(os.path.join(sample_dir, "tb_weak.sv"), encoding="utf-8").read()
    tm = re.search(r"module\s+(tb_\w+)", tb_src)
    tb_top = tm.group(1) if tm else None
    golden_vcd = _generate_vcd(sample_dir, "golden.v", tb_top, sample_id + "_g", timeout)
    buggy_vcd = _generate_vcd(sample_dir, "buggy.v", tb_top, sample_id + "_b", timeout)
    if not golden_vcd or not buggy_vcd:
        out["error"] = "vcd gen fail (g=%s b=%s)" % (bool(golden_vcd), bool(buggy_vcd))
        return out
    try:
        analysis = _cycle_compare(golden_vcd, buggy_vcd, clk)
        out["ok"] = True
        out["analysis"] = analysis
        out["clk_sig"] = clk
        ap = os.path.join(sample_dir, "trace_analysis.json")
        with open(ap, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception as e:
        out["error"] = repr(e)[:300]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="s07")
    ap.add_argument("--samples-dir", default="bugs", choices=["bugs", "deep"])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--clk", default=None)
    args = ap.parse_args(argv)
    base = BUGS if args.samples_dir == "bugs" else DEEP
    samples = [s.strip() for s in args.samples.split(",") if s.strip()]
    os.makedirs(TRACE_ROOT, exist_ok=True)
    done = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = []
        for sid in samples:
            sdir = os.path.join(base, sid)
            if not os.path.isdir(sdir):
                print("skip no dir %s" % sid, flush=True)
                continue
            futs.append(ex.submit(analyze_sample, sdir, sid, args.clk, args.timeout))
        for fu in as_completed(futs):
            r = fu.result()
            done.append(r)
            a = r.get("analysis") or {}
            print("[%s] ok=%s first_anomaly=%s diffs=%d stuck=%d err=%s" % (
                r["sample"], r["ok"], a.get("first_anomaly_cycle"),
                len(a.get("key_signal_diffs", [])), len(a.get("stuck_signals", [])),
                r.get("error", "")[:80]), flush=True)
    ok = sum(1 for r in done if r["ok"])
    print("== done: ok=%d/%d ==" % (ok, len(done)), flush=True)
    return 0 if ok == len(done) else 1


if __name__ == "__main__":
    sys.exit(main())
