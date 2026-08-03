#!/usr/bin/env python3
# PreCex - agents/cex_semantizer/waveform_svg.py VCD → SVG 波形渲染器（T1 视觉通道）
# 作者：Toylog | 版本：v0.1 | 功能概述：基于 vcd_parser 的周期事件数据，把关键信号绘制为
#   SVG 时序波形图（标量阶梯线 + 向量取值标注 + clk 周期刻度），供 MiniMax M3 多模态摘要使用。
#   纯标准库实现，无第三方依赖。

"""VCD → SVG/PNG 波形渲染（T1 视觉通道）。

用法（库方式）：
    from waveform_svg import render_svg
    svg_text = render_svg("cex.vcd", sigs=[...], out_path="wave.svg")
    from waveform_svg import render_png
    render_png("cex.vcd", sigs=[...], out_path="wave.png")   # 需 Pillow
"""

import os
import math

from vcd_parser import VcdParser


def _fmt_val(val, width):
    """把 VCD 值格式化为可读文本（标量 0/1；向量按二进制显示 + 十进制括号）。"""
    if val in ("0", "1", "x", "z"):
        return val
    # 向量（二进制串，可能含 x/z）
    if len(val) <= 8 and set(val) <= {"0", "1"}:
        try:
            dec = int(val, 2)
        except ValueError:
            dec = None
        return "%s(%d)" % (val, dec) if dec is not None else val
    return val


def _per_cycle_value(sig_values, cycle_starts, n_cycles):
    """把信号 (time,val) 变化序列对齐到周期索引（取每周期内最后一次值）。"""
    vals = []
    for ci in range(n_cycles):
        t0 = cycle_starts[ci]
        t1 = cycle_starts[ci + 1] if ci + 1 < n_cycles else t0 + 1
        last = None
        for (t, v) in sig_values:
            if t0 <= t < t1:
                last = v
        vals.append(last if last is not None else "?")
    return vals


def render_svg(vcd_path, sigs=None, clk_sig="clk", out_path=None, width=960, max_cycles=None):
    """渲染 SVG 波形。sigs 为 None 时自动选择关键信号（数量受限）。"""
    vp = VcdParser(vcd_path, clk_sig=clk_sig).parse()
    all_sigs = vp.all_signals()
    if not sigs:
        # 自动选择：优先状态/计数/控制类信号，最多 12 条
        pref = ["clk", "rst_n", "state", "state_d", "cnt", "cnt_d", "count", "count_d",
                "step_cnt", "step_cnt_d", "head", "tail", "full", "empty", "half_full",
                "wr_en", "rd_en", "cnt_en", "en", "start", "valid", "ready", "done"]
        sigs = [s for s in pref if s in all_sigs]
        rest = [s for s in all_sigs if s not in sigs and not s.startswith(("any", "_", "$", "smt_", "mem"))]
        sigs += rest[: max(0, 12 - len(sigs))]
    sigs = [s for s in sigs if s in all_sigs][:12]

    cycles = vp.cycle_events
    if max_cycles:
        cycles = cycles[:max_cycles]
    n = len(cycles)
    if n < 2:
        n = 2
    cycle_starts = [c["time"] for c in cycles]
    if len(cycle_starts) < n:
        cycle_starts = list(range(n))

    row_h = 34
    label_w = 150
    plot_w = width - label_w - 20
    total_h = 30 + len(sigs) * row_h + 30

    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
                 'viewBox="0 0 %d %d" font-family="Consolas,monospace" font-size="12">' % (width, total_h, width, total_h))
    parts.append('<rect width="%d" height="%d" fill="#ffffff"/>' % (width, total_h))
    parts.append('<text x="10" y="18" font-size="14" font-weight="bold">VCD waveform: %s</text>' % os.path.basename(vcd_path))

    # 时间轴刻度
    t0, t1 = cycle_starts[0], cycle_starts[-1] + 1
    span = max(1, t1 - t0)
    for ci in range(n):
        x = label_w + plot_w * (cycle_starts[ci] - t0) / span
        parts.append('<line x1="%.1f" y1="26" x2="%.1f" y2="28" stroke="#888"/>' % (x, x))
        if ci % max(1, n // 12) == 0:
            parts.append('<text x="%.1f" y="42" fill="#666">c%d</text>' % (x + 2, ci))

    # 每信号一行
    for r, sig in enumerate(sigs):
        y = 52 + r * row_h
        parts.append('<text x="10" y="%.1f" fill="#222">%s</text>' % (y + 14, sig))
        changes = vp.values.get(_sig_id(vp, sig), [])
        vals = _per_cycle_value(changes, cycle_starts, n)
        prev_y = None
        for ci in range(n):
            x0 = label_w + plot_w * (cycle_starts[ci] - t0) / span
            x1 = label_w + plot_w * (cycle_starts[ci + 1] - t0) / span if ci + 1 < n else width - 10
            v = vals[ci]
            if v in ("0", "1"):
                yy = y + 20 if v == "1" else y + 4
                parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1a6fd4" stroke-width="2"/>' % (x0, yy, x1, yy))
                if prev_y is not None and abs(prev_y - yy) > 6:
                    mx = (x0 + x1) / 2
                    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1a6fd4" stroke-width="1.5"/>' % (mx, prev_y, mx, yy))
                prev_y = yy
            else:
                # 向量/x：显示取值
                parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#cc6600" stroke-width="2"/>' % (x0, y + 12, x1, y + 12))
                txt = _fmt_val(v, None)
                parts.append('<text x="%.1f" y="%.1f" fill="#cc6600">%s</text>' % (x0 + 2, y + 11, txt))
                prev_y = y + 12

    parts.append('</svg>')
    svg = "\n".join(parts)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(svg)
    return svg


def _sig_id(vp, name):
    for vid, nm in vp.id2sig.items():
        if nm == name:
            return vid
    return None


def render_png(vcd_path, sigs=None, clk_sig="clk", out_path=None, width=1100, max_cycles=None):
    """渲染 PNG 波形（Pillow 绘制，供 M3 多模态输入；布局与 render_svg 一致）。"""
    from PIL import Image, ImageDraw, ImageFont

    vp = VcdParser(vcd_path, clk_sig=clk_sig).parse()
    all_sigs = vp.all_signals()
    if not sigs:
        pref = ["clk", "rst_n", "state", "state_d", "cnt", "cnt_d", "count", "count_d",
                "step_cnt", "step_cnt_d", "head", "tail", "full", "empty", "half_full",
                "wr_en", "rd_en", "cnt_en", "en", "start", "valid", "ready", "done"]
        sigs = [s for s in pref if s in all_sigs]
        rest = [s for s in all_sigs if s not in sigs and not s.startswith(("any", "_", "$", "smt_", "mem"))]
        sigs += rest[: max(0, 12 - len(sigs))]
    sigs = [s for s in sigs if s in all_sigs][:12]

    cycles = vp.cycle_events
    if max_cycles:
        cycles = cycles[:max_cycles]
    n = max(2, len(cycles))
    cycle_starts = [c["time"] for c in cycles]
    if len(cycle_starts) < n:
        cycle_starts = list(range(n))

    row_h = 36
    label_w = 150
    plot_w = width - label_w - 20
    total_h = 40 + len(sigs) * row_h + 30
    t0, t1 = cycle_starts[0], cycle_starts[-1] + 1
    span = max(1, t1 - t0)

    img = Image.new("RGB", (width, total_h), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 13)
        font_b = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
        font_b = font

    d.text((10, 8), "VCD waveform: %s" % os.path.basename(vcd_path), fill="black", font=font_b)
    # 周期刻度
    for ci in range(n):
        x = label_w + plot_w * (cycle_starts[ci] - t0) / span
        d.line((x, 30, x, 34), fill="gray")
        if ci % max(1, n // 12) == 0:
            d.text((x + 2, 36), "c%d" % ci, fill="gray", font=font)

    for r, sig in enumerate(sigs):
        y = 58 + r * row_h
        d.text((10, y), sig, fill="black", font=font)
        changes = vp.values.get(_sig_id(vp, sig), [])
        vals = []
        for ci in range(n):
            x0 = cycle_starts[ci]
            x1 = cycle_starts[ci + 1] if ci + 1 < n else x0 + 1
            last = None
            for (tt, v) in changes:
                if x0 <= tt < x1:
                    last = v
            vals.append(last if last is not None else "?")
        prev_y = None
        for ci in range(n):
            x0 = label_w + plot_w * (cycle_starts[ci] - t0) / span
            x1 = label_w + plot_w * (cycle_starts[ci + 1] - t0) / span if ci + 1 < n else width - 10
            v = vals[ci]
            if v in ("0", "1"):
                yy = y + 22 if v == "1" else y + 6
                d.line((x0, yy, x1, yy), fill=(26, 111, 212), width=2)
                if prev_y is not None and abs(prev_y - yy) > 6:
                    mx = (x0 + x1) / 2
                    d.line((mx, prev_y, mx, yy), fill=(26, 111, 212), width=2)
                prev_y = yy
            else:
                yy = y + 14
                d.line((x0, yy, x1, yy), fill=(204, 102, 0), width=2)
                txt = _fmt_val(v, None)
                d.text((x0 + 2, yy - 10), txt, fill=(204, 102, 0), font=font)
                prev_y = yy

    if out_path:
        img.save(out_path)
    return img


def main(argv=None):
    import sys
    if len(sys.argv) < 2:
        print("usage: waveform_svg.py <file.vcd> [out.svg|out.png]")
        return 1
    out = sys.argv[2] if len(sys.argv) > 2 else None
    if out and out.endswith(".png"):
        render_png(sys.argv[1], out_path=out)
        print("png:", out)
    else:
        svg = render_svg(sys.argv[1], out_path=out)
        print("svg chars:", len(svg))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
