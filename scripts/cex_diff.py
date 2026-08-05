#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/cex_diff.py 反例差分诊断 (WP6)
输入：旧 cex（原始 buggy 反例）与新 cex（修复后仍失败的反例）。
输出：fail_step 移动、信号变化集、状态卡死检测、<=120 token 诊断文本（注入下一轮 prompt）。
用法：
  python3 scripts/cex_diff.py --sample s17 --old samples/bugs/s17/cex.vcd \
      --old-log samples/bugs/s17/cex.log --new <repaired_cex.vcd> --new-log <repaired_cex.log>
  python3 scripts/cex_diff.py --sample s17 --old ... --new-pass   # 修复已通过，无需新 cex
"""
from __future__ import annotations
import argparse, json, os, re, sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))
from vcd_parser import VcdParser  # noqa: E402

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


def extract_fail_step(log_path):
    """sby cex.log -> (max_checked_step, assert_line)。"""
    steps, assert_line = [], ""
    if log_path and os.path.isfile(log_path):
        for line in open(log_path, encoding="utf-8", errors="replace"):
            m = re.search(r"Checking assertions in step (\d+)\.\.", line)
            if m:
                steps.append(int(m.group(1)))
            if "Assert failed" in line:
                assert_line = line.strip()
    return (max(steps) if steps else None), assert_line


def _row_map(trace):
    """state_trace 行列表 -> 以 smt_step 值（若有）或行号为 key 的 {step: {sig: val}}。"""
    out = {}
    for row in trace:
        step = row.get("smt_step")
        key = step if isinstance(step, int) else row["cycle"]
        out[key] = row
    return out


def analyze(old_vcd, new_vcd, clk_sig, old_fail, new_fail):
    op = VcdParser(old_vcd, clk_sig=clk_sig).parse()
    sigs = [s for s in KEY_SIGS if s in set(op.all_signals())] + ["smt_step"]
    ot = _row_map(op.state_trace(sigs))
    if new_vcd:
        np = VcdParser(new_vcd, clk_sig=clk_sig).parse()
        nt = _row_map(np.state_trace(sigs))
    else:
        nt = {}
    old_fail = old_fail if old_fail is not None else (max(ot) if ot else 0)
    new_fail = new_fail if new_fail is not None else (max(nt) if nt else None)
    old_row = ot.get(old_fail, {})
    new_row = nt.get(new_fail, {})
    changed = {}
    for s in sigs:
        if s == "smt_step":
            continue
        ov, nv = old_row.get(s), new_row.get(s)
        if nv is not None and ov != nv:
            changed[s] = {"old": ov, "new": nv}
    # 状态卡死：state/state_d/cnt 在失败前 6 拍不变（旧反例内）
    stuck = []
    for s in ("state", "state_d", "cnt", "step_cnt", "bit_cnt"):
        vals = [ot.get(k, {}).get(s) for k in sorted(ot.keys())]
        vals = [v for v in vals if v is not None]
        tail = vals[-6:] if len(vals) > 6 else vals
        if len(set(tail)) == 1 and len(tail) >= 4:
            stuck.append(s)
    move = None
    if new_fail is not None and old_fail is not None:
        move = new_fail - old_fail
    return {
        "old_fail_step": old_fail, "new_fail_step": new_fail,
        "fail_cycle_move": move,
        "changed_signals": changed, "stuck_signals": stuck,
    }


def diagnosis_text(sample, r, assert_line):
    """生成 <=120 token 的中文诊断文本。"""
    parts = []
    if r["new_fail_step"] is None:
        parts.append("修复后未产生反例（通过或超时），旧反例 step=%s 断言失败：%s"
                     % (r["old_fail_step"], assert_line or "?"))
    else:
        mv = r["fail_cycle_move"]
        if mv == 0:
            mv_s = "失败步数与旧反例相同"
        elif mv is not None and mv > 0:
            mv_s = "失败步数后移 %d 拍（部分修复/变深）" % mv
        elif mv is not None:
            mv_s = "失败步数前移 %d 拍（恶化）" % (-mv)
        else:
            mv_s = "步数不可比"
        parts.append("样本 %s：旧反例 step %s 失败，新反例 %s（%s）"
                     % (sample, r["old_fail_step"], mv_s, assert_line or "?"))
        cs = list(r["changed_signals"].keys())
        if cs:
            parts.append("新反例中值变化的信号：%s" % ",".join(cs[:8]))
        if r["stuck_signals"]:
            parts.append("状态疑似卡死：%s 在失败前连续不变" % ",".join(r["stuck_signals"]))
    txt = "；".join(parts) if parts else "无可用诊断"
    return txt[:240]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    ap.add_argument("--old", required=True, help="旧 cex.vcd 路径")
    ap.add_argument("--old-log", default=None)
    ap.add_argument("--new", default=None, help="新 cex.vcd 路径（修复后仍失败）")
    ap.add_argument("--new-log", default=None)
    ap.add_argument("--new-pass", action="store_true", help="修复已通过，无新反例")
    ap.add_argument("--clk", default=None)
    ap.add_argument("--out", default=None, help="诊断 JSON 输出路径")
    args = ap.parse_args(argv)
    meta = {}
    mp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "samples", "bugs", args.sample, "meta.json")
    if os.path.isfile(mp):
        meta = json.load(open(mp, encoding="utf-8"))
    clk = args.clk or MODULE_CLK.get(meta.get("module"), "clk")
    old_fail, old_assert = extract_fail_step(args.old_log)
    new_fail, new_assert = (None, "") if args.new_pass else extract_fail_step(args.new_log)
    r = analyze(args.old, None if args.new_pass else args.new, clk, old_fail, new_fail)
    r["sample"] = args.sample
    r["module"] = meta.get("module")
    r["assert_line"] = old_assert or new_assert
    r["diagnosis"] = diagnosis_text(args.sample, r, old_assert or new_assert)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())