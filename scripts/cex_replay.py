#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/cex_replay.py 形式反例激励重放 (WP2 精化)

对弱 tb 未触发缺陷的 None 样本（s33/s39/s40/s42），用 sby cex.vcd 的反例激励
驱动 golden 仿真，与 buggy cex 逐周期对比，得到 first_anomaly / stuck_signals。

输出：samples/<dir>/<sample>/trace_analysis_replay.json
用法（WSL）：python3 scripts/cex_replay.py --samples s33 --samples-dir bugs
"""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))
from vcd_parser import VcdParser  # noqa: E402

BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
DEEP = os.path.join(REPO_ROOT, "samples", "deep")
WORK_ROOT = os.path.join(REPO_ROOT, "experiments", "runs", ".cex_replay")
MODULE_CLK = {
    "fifo_sync": "clk", "fsm_ctrl": "clk", "uart_tx": "clk",
    "uart_rx": "clk", "axi_lite_slave": "ACLK", "counter_alu": "clk",
}
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


def parse_ports(golden_src, module):
    """解析 golden.v 端口：返回 (input_names, output_names)。"""
    inputs, outputs = [], []
    for line in golden_src.splitlines():
        t = line.strip()
        m = re.match(r"input\s+(?:wire|reg)?\s*(?:\[[^\]]+\])?\s*(\w+)\s*,?", t)
        if m:
            inputs.append(m.group(1))
            continue
        m = re.match(r"output\s+(?:wire|reg)?\s*(?:\[[^\]]+\])?\s*(\w+)\s*,?", t)
        if m:
            outputs.append(m.group(1))
    return inputs, outputs


def _cex_widths(vcd_parser):
    """VCD $var 声明 -> {signal_name: width}（以真实综合后位宽为准）。"""
    w = {}
    for vid, name in vcd_parser.id2sig.items():
        width = vcd_parser.id2width.get(vid, 1)
        if name not in w or width > w[name]:
            w[name] = width
    return w


def _vcd_value_to_reglit(v, width):
    """VCD 值字符串 -> Verilog 字面量。"""
    v = v.strip()
    if width == 1:
        if v in ("0", "1", "x", "z"):
            return "%s'b%s" % (1, v)
        return "1'bx"
    v = v.replace("X", "x").replace("Z", "z")
    if v and set(v) <= set("01xz"):
        return "%d'b%s" % (width, v)
    return "%d'bx" % width


def build_replay_tb(rows, inputs, outputs, clk_name, module):
    """生成重放 tb：按 cex 原始时间轴驱动（step k 输入在 t=10k，时钟上升沿同拍），
    使 VcdParser 周期桶与 cex.vcd 完全对齐（首沿 t=0）。"""
    decls, drives0, per_step = [], [], []
    for name, w in inputs:
        decls.append("    reg [%d:0] %s;" % (w - 1, name))
    for name in outputs:
        decls.append("    wire %s;" % name)
    # step 0 输入（rows[1]；rows[0] 为空初始桶）
    for name, w in inputs:
        if name == clk_name:
            continue
        drives0.append("        %s = %s;" % (name, _vcd_value_to_reglit(str(rows[1].get(name)), w)))
    in_names = [n for n, _ in inputs]
    port_list = ", ".join([".%s(%s)" % (n, n) for n in in_names] + [".%s(%s)" % (n, n) for n in outputs])
    lines = []
    lines.append("`timescale 1ns/1ps")
    lines.append("module tb_replay;")
    lines.extend(decls)
    lines.append("    %s uut (%s);" % (module, port_list))
    lines.append("    initial begin")
    lines.append('        $dumpfile("replay.vcd");')
    lines.append("        $dumpvars(0);")
    lines.append("        %s = 1'b0;" % clk_name)
    for d in drives0:
        lines.append(d)
    lines.append("        %s = 1'b1;   // 首沿 t=0，与 cex 对齐" % clk_name)
    lines.append("        #5 %s = 1'b0;" % clk_name)
    # 后续 step：t=10k 更新输入并拉高，t=10k+5 拉低
    for i in range(2, len(rows)):
        lines.append("        #10")
        for name, w in inputs:
            if name == clk_name:
                continue
            lines.append("        %s = %s;" % (name, _vcd_value_to_reglit(str(rows[i].get(name)), w)))
        lines.append("        %s = 1'b1;" % clk_name)
        lines.append("        #5 %s = 1'b0;" % clk_name)
    lines.append("        #5 $finish;")
    lines.append("    end")
    lines.append("endmodule")
    return "\n".join(lines)


def _compile_sim(work, tb_name, top, timeout):
    srcs = sorted(f for f in os.listdir(work) if f.endswith((".v", ".sv")))
    try:
        r = subprocess.run(["iverilog", "-g2012"] + srcs + ["-s", tb_name, "-o", "sim.out"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=work)
        if r.returncode != 0:
            return False, (r.stdout + r.stderr)[-500:]
        r2 = subprocess.run(["vvp", "sim.out"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, cwd=work)
        return True, (r2.stdout + r2.stderr)[-300:]
    except Exception as e:
        return False, repr(e)[:200]


def analyze_sample(sample_dir, sample_id, timeout):
    out = {"sample": sample_id, "ok": False, "error": "", "analysis": None}
    try:
        meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    except Exception:
        meta = {}
    module = meta.get("module")
    if not module:
        out["error"] = "no module"; return out
    clk = MODULE_CLK.get(module, "clk")
    cex_vcd = os.path.join(sample_dir, "cex.vcd")
    if not os.path.isfile(cex_vcd):
        out["error"] = "no cex.vcd"; return out
    golden_src = open(os.path.join(sample_dir, "golden.v"), encoding="utf-8").read()
    inputs, outputs = parse_ports(golden_src, module)
    input_names = set(inputs)
    # 解析 cex（buggy 反例）
    try:
        cp = VcdParser(cex_vcd, clk_sig=clk).parse()
        sigs_cex = set(cp.all_signals())
        cex_w = _cex_widths(cp)
        in_sigs = [n for n in inputs if n in sigs_cex]
        inputs_w = [(n, cex_w.get(n, 1)) for n in in_sigs]
        rows = cp.state_trace(in_sigs + ["smt_step"])
    except Exception as e:
        out["error"] = "cex parse fail: %s" % repr(e)[:120]; return out
    if len(rows) < 2:
        out["error"] = "cex rows too few (%d)" % len(rows); return out
    work = os.path.join(WORK_ROOT, sample_id)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "golden.v"), "w", encoding="utf-8") as f:
        f.write(golden_src)
    tb = build_replay_tb(rows, inputs_w, outputs, clk, module)
    with open(os.path.join(work, "tb_replay.sv"), "w", encoding="utf-8") as f:
        f.write(tb)
    ok, err = _compile_sim(work, "tb_replay", "tb_replay", timeout)
    if not ok:
        out["error"] = "replay sim fail: %s" % (err or "")[-300:]; return out
    replay_vcd = os.path.join(work, "replay.vcd")
    if not os.path.isfile(replay_vcd) or os.path.getsize(replay_vcd) == 0:
        out["error"] = "replay vcd empty"; return out
    # 逐 step 对比 golden replay vs buggy cex
    # 对齐规则（实测）：golden cycle i == cex smt_step i（i>=1）；
    # 排除输入信号（重放保真由构造保证，轨迹表示上输入值差一拍）
    try:
        gp = VcdParser(replay_vcd, clk_sig=clk).parse()
        gs = set(gp.all_signals())
        in_set = set(in_sigs)
        sigs = [s for s in KEY_SIGS if s not in in_set and s in gs and s in sigs_cex]
        gt = gp.state_trace(sigs)
        bt = cp.state_trace(sigs + ["smt_step"])

        def _norm(v):
            if v is None:
                return None
            v = v.strip().lower()
            if v and set(v) <= set("01") and len(v) > 1:
                return str(int(v, 2))
            return v

        def _hold(trace_rows):
            out = []
            last = {}
            for row in trace_rows:
                for s in sigs:
                    v = row.get(s)
                    if v is not None:
                        last[s] = _norm(v)
                out.append(dict(last))
            return out

        g_hold = _hold(gt)
        b_step = {}
        last = {}
        for row in bt:
            st = row.get("smt_step")
            for s in sigs:
                v = row.get(s)
                if v is not None:
                    last[s] = _norm(v)
            if isinstance(st, str) and st.strip().isdigit():
                b_step[int(st, 2)] = dict(last)
        n = min(len(g_hold) - 1, max(b_step) if b_step else 0)
        first_anomaly = None
        diffs = {}
        for i in range(1, n + 1):
            gv2, bv2 = g_hold[i], b_step.get(i)
            if bv2 is None:
                continue
            for s in sigs:
                if gv2.get(s) != bv2.get(s) and s not in diffs:
                    diffs[s] = i
                    if first_anomaly is None:
                        first_anomaly = i
        stuck = []
        if first_anomaly is not None:
            for s in sigs:
                gvals = [g_hold[i].get(s) for i in range(first_anomaly, n + 1)]
                bvals = [b_step.get(i, {}).get(s) for i in range(first_anomaly, n + 1)]
                gu = {v for v in gvals if v is not None}
                bu = {v for v in bvals if v is not None}
                if len(gu) > 1 and len(bu) <= 1:
                    stuck.append(s)
        analysis = {
            "evidence": "cex_replay",
            "cex_steps": len(rows) - 1,
            "first_anomaly_cycle": first_anomaly,
            "key_signal_diffs": sorted(diffs.items(), key=lambda x: x[1]),
            "stuck_signals": sorted(stuck),
            "cycles_compared": n,
            "inputs_replayed": in_sigs,
            "outputs": [o for o in outputs if o in sigs_cex],
        }
        out["ok"] = True
        out["analysis"] = analysis
        out["clk_sig"] = clk
        with open(os.path.join(sample_dir, "trace_analysis_replay.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception as e:
        out["error"] = "compare fail: %s" % repr(e)[:200]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="s33")
    ap.add_argument("--samples-dir", default="bugs", choices=["bugs", "deep"])
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args(argv)
    base = BUGS if args.samples_dir == "bugs" else DEEP
    samples = [s.strip() for s in args.samples.split(",") if s.strip()]
    os.makedirs(WORK_ROOT, exist_ok=True)
    done = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = []
        for sid in samples:
            sdir = os.path.join(base, sid)
            if not os.path.isdir(sdir):
                print("skip no dir %s" % sid, flush=True)
                continue
            futs.append(ex.submit(analyze_sample, sdir, sid, args.timeout))
        for fu in as_completed(futs):
            r = fu.result()
            done.append(r)
            a = r.get("analysis") or {}
            print("[%s] ok=%s first_anomaly=%s diffs=%d stuck=%d steps=%s err=%s" % (
                r["sample"], r["ok"], a.get("first_anomaly_cycle"),
                len(a.get("key_signal_diffs", [])), len(a.get("stuck_signals", [])),
                a.get("cex_steps"), (r.get("error") or "")[:90]), flush=True)
    ok = sum(1 for r in done if r["ok"])
    print("== done: ok=%d/%d ==" % (ok, len(done)), flush=True)
    return 0 if ok == len(done) else 1


if __name__ == "__main__":
    sys.exit(main())