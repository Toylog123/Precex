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

# WP6 v2.1: 握手信号对（valid/ready 或协议交互），用于动态差分中的握手特征分析（1d 握手专项）
HANDSHAKE_PAIRS = {
    "axi_lite_slave": [
        ("S_AXI_AWVALID", "S_AXI_AWREADY"),
        ("S_AXI_WVALID", "S_AXI_WREADY"),
        ("S_AXI_BVALID", "S_AXI_BREADY"),
        ("S_AXI_ARVALID", "S_AXI_ARREADY"),
        ("S_AXI_RVALID", "S_AXI_RREADY"),
    ],
    "uart_tx": [
        ("tx_start", "tx_busy"),
        ("tx_busy", "txd"),
    ],
    "uart_rx": [
        ("rx_valid", "rx_ready"),
        ("rxd", "rx_busy"),
    ],
}

# 1d 握手专项：模块级协议语义提示（注入诊断文本，指导 LLM 定位握手缺陷）
HANDSHAKE_NOTE = {
    "axi_lite_slave": "AXI-Lite 写通道：AWVALID&AWREADY、WVALID&WREADY 均完成握手后，BVALID 才可置位；BVALID 保持到 BREADY 有效后释放（不允许重复/持续响应）。读通道同理：AR 握手完成后才可置 RVALID，RVALID 保持到 RREADY 后释放。",
    "uart_tx": "UART TX 起始位握手：tx_start 有效后 tx_busy 拉高，同时 txd 必须立即输出低电平起始位并保持一个位周期（A1 断言）；busy 期间 txd 按位输出，帧结束后恢复高电平。",
    "uart_rx": "UART RX：检测到 rxd 下降沿后 rx_busy 拉高并采样起始位；rx_valid 表示一帧接收完成，保持到 rx_ready 拉高后释放。",
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


def _sig01(val):
    """VCD 值 -> 0/1/None（非 0/1 位串/高阻视为 None）。"""
    if val is None:
        return None
    v = str(val).strip()
    if v == "0":
        return 0
    if v == "1":
        return 1
    try:
        iv = int(v, 2)
    except (TypeError, ValueError):
        return None
    if iv in (0, 1):
        return iv
    return None


def handshake_features(trace, pairs, fail_step):
    """对每对握手信号计算时序特征（last-value 保持语义）。

    trace: {step: {sig: val}}（_row_map 输出，只有变化周期有值）。
    返回 {pair_key: {first_valid_rise, first_ready_rise, wait_cycles,
                      hold_after_ready, deassert_seen, valid_at_fail, ready_at_fail,
                      ready_at_valid_rise}}。
    """
    out = {}
    keys = sorted(trace.keys(), key=lambda k: (int(k) if isinstance(k, int) else k))
    for v_sig, r_sig in pairs:
        # last-value 保持：未变化周期继承前一值，解决 VcdParser 无保持语义问题
        held = []
        lv = lr = None
        for k in keys:
            row = trace.get(k, {})
            vv = _sig01(row.get(v_sig))
            rr = _sig01(row.get(r_sig))
            if vv is not None:
                lv = vv
            if rr is not None:
                lr = rr
            held.append((k, lv, lr))
        if not any(x[1] is not None for x in held) and not any(x[2] is not None for x in held):
            continue
        fv = fr = None
        wait = 0
        hold = 0
        deassert = False
        prev_v = 0
        ready_at_valid_rise = None
        for k, vv, rr in held:
            if vv is None and rr is None:
                continue
            if fv is None and vv == 1 and prev_v == 0:
                fv = k
                ready_at_valid_rise = rr
            if fr is None and rr == 1:
                fr = k
            if vv == 1 and rr == 0 and (fr is None or k < fr):
                wait += 1
            if fr is not None and k >= fr and vv == 1:
                hold += 1
            if vv == 0 and fv is not None:
                deassert = True
            if vv is not None:
                prev_v = vv
        vf = None
        rf = None
        if fail_step is not None:
            for k, vv, rr in held:
                if k == fail_step:
                    vf, rf = vv, rr
                    break
        out["%s/%s" % (v_sig, r_sig)] = {
            "first_valid_rise": fv,
            "first_ready_rise": fr,
            "wait_cycles": wait,
            "hold_after_ready": hold,
            "deassert_seen": deassert,
            "valid_at_fail": vf,
            "ready_at_fail": rf,
            "ready_at_valid_rise": ready_at_valid_rise,
        }
    return out


def module_handshake_violations(feat, module):
    """基于特征的模块级协议违规检测，返回中文列表。"""
    viol = []
    if module == "axi_lite_slave":
        bp = feat.get("S_AXI_BVALID/S_AXI_BREADY") or {}
        aw = (feat.get("S_AXI_AWVALID/S_AXI_AWREADY") or {}).get("first_ready_rise")
        w = (feat.get("S_AXI_WVALID/S_AXI_WREADY") or {}).get("first_ready_rise")
        b_rise = bp.get("first_valid_rise")
        if b_rise is not None and bp.get("deassert_seen") is False:
            viol.append("BVALID 持续有效未释放（重复响应/响应卡住）")
        if b_rise is not None and bp.get("first_ready_rise") is None:
            viol.append("BVALID 置位但 BREADY 从未拉起")
        if b_rise is not None and aw is not None and w is not None and b_rise < max(aw, w):
            viol.append("BVALID 在写通道（AW/W）握手完成前提前置位")
        rp = feat.get("S_AXI_RVALID/S_AXI_RREADY") or {}
        ar = (feat.get("S_AXI_ARVALID/S_AXI_ARREADY") or {}).get("first_ready_rise")
        r_rise = rp.get("first_valid_rise")
        if r_rise is not None and rp.get("deassert_seen") is False:
            viol.append("RVALID 持续有效未释放（读响应卡住）")
        if r_rise is not None and ar is not None and r_rise < ar:
            viol.append("RVALID 在 AR 握手完成前提前置位")
    elif module == "uart_tx":
        tp = feat.get("tx_busy/txd") or {}
        if tp.get("first_valid_rise") is not None and tp.get("ready_at_valid_rise") == 1:
            viol.append("tx_busy 拉高时 txd=1（起始位未拉低，击穿 A1）")
    elif module == "uart_rx":
        rp = feat.get("rx_valid/rx_ready") or {}
        if rp.get("first_valid_rise") is not None and rp.get("deassert_seen") is False:
            viol.append("rx_valid 持续有效未释放（接收完成信号卡住）")
    return viol


def handshake_delta_text(old_feat, new_feat, module):
    """输出握手特征差异（<=400 字符中文）。"""
    parts = []
    all_pairs = sorted(set(old_feat) | set(new_feat))
    for pk in all_pairs:
        o = old_feat.get(pk) or {}
        n = new_feat.get(pk) or {}
        # 只报告变化或明显违规
        changed = any(o.get(k) != n.get(k) for k in
                      ("first_valid_rise", "first_ready_rise", "wait_cycles", "hold_after_ready", "deassert_seen"))
        viol = []
        if n.get("hold_after_ready") and n.get("deassert_seen") is False:
            viol.append("valid 在 ready 后未释放")
        if n.get("first_ready_rise") is None and n.get("first_valid_rise") is not None:
            viol.append("ready 从未拉起")
        if not changed and not viol:
            continue
        line = pk + ":"
        if changed:
            line += " 旧(valid_rise=%s,ready_rise=%s,wait=%s,hold=%s,deassert=%s) -> 新(valid_rise=%s,ready_rise=%s,wait=%s,hold=%s,deassert=%s)" % (
                o.get("first_valid_rise"), o.get("first_ready_rise"), o.get("wait_cycles"), o.get("hold_after_ready"), o.get("deassert_seen"),
                n.get("first_valid_rise"), n.get("first_ready_rise"), n.get("wait_cycles"), n.get("hold_after_ready"), n.get("deassert_seen"))
        if viol:
            line += " [违规] " + ",".join(viol)
        parts.append(line)
    return "；".join(parts)


def analyze(old_vcd, new_vcd, clk_sig, old_fail, new_fail, module=None):
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
    # WP6 v2.1 握手特征（1d 握手专项）：按 module 选择握手对，计算旧/新特征与差异
    pairs = HANDSHAKE_PAIRS.get(module or "", [])
    hs_old = handshake_features(ot, pairs, old_fail) if pairs else {}
    hs_new = handshake_features(nt, pairs, new_fail) if pairs else {}
    hs_delta = handshake_delta_text(hs_old, hs_new, module or "")
    result = {
        "old_fail_step": old_fail, "new_fail_step": new_fail,
        "fail_cycle_move": move,
        "changed_signals": changed, "stuck_signals": stuck,
        "handshake_old": hs_old, "handshake_new": hs_new, "handshake_delta": hs_delta,
        "module": module or "",
    }
    return result
    # handshake fields filled above (backward compat)
    # old return replaced


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
    hs_feat = r.get("handshake_new") or r.get("handshake_old") or {}
    viols = module_handshake_violations(hs_feat, r.get("module") or "")
    if viols:
        parts.append("协议违规检测：" + "；".join(viols))
    if r.get("handshake_delta") and r.get("new_fail_step") is not None:
        parts.append("握手分析：" + r["handshake_delta"][:260])
    module_note = HANDSHAKE_NOTE.get(r.get("module") or "")
    if module_note:
        parts.append("协议提示：" + module_note)
    txt = "；".join(parts) if parts else "无可用诊断"
    return txt[:900]


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
    r = analyze(args.old, None if args.new_pass else args.new, clk, old_fail, new_fail, module=meta.get("module"))
    r["sample"] = args.sample
    r["module"] = meta.get("module")
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