#!/usr/bin/env python3
# PreCex - agents/cex_semantizer/vcd_parser.py VCD 解析器
# 作者：Toylog | 版本：v0.1 | 功能概述：轻量 VCD 解析（纯标准库）：
#   - 建立 id → 信号名/位宽映射（$var 段）
#   - 逐时间戳解码值变化（标量/向量/x/z）
#   - 以 clk 上升沿切分为周期事件表（cycle event table）
#   - 输出 state_trace：每周期关键信号取值（供 CexSemantizer 文本通道使用）

"""VCD 解析器。

用法（库方式）：
    from vcd_parser import VcdParser
    vp = VcdParser("cex.vcd", clk_sig="clk")
    vp.parse()
    cycles = vp.cycle_events       # [{cycle, time, events:[{sig, val}]}]
    trace  = vp.state_trace(sigs)  # [{cycle, **{sig: val}}]
"""

import re


class VcdParser:
    """轻量 VCD 解析器：支持 $var/标量/向量值变化、时间戳、x/z 值。"""

    def __init__(self, path, clk_sig="clk"):
        self.path = path
        self.clk_sig = clk_sig
        self.id2sig = {}        # vcd_id -> 信号名
        self.id2width = {}      # vcd_id -> 位宽
        self.times = []         # 时间戳列表（升序）
        self.values = {}        # vcd_id -> [(time, value_str), ...]
        self.time_index = {}    # time -> index
        self.cycle_events = []
        self._clk_id = None

    def parse(self):
        """解析整个 VCD 文件。"""
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        lines = text.splitlines()
        i = 0
        cur_time = 0
        # 第一遍：$var 声明段
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("$var"):
                m = re.match(r"\$var\s+(\w+)\s+(\d+)\s+(\S+)\s+(\S+)", line)
                if m:
                    vtype, width, vid, name = m.group(1), int(m.group(2)), m.group(3), m.group(4)
                    self.id2sig[vid] = name
                    self.id2width[vid] = width
            i += 1
        # 第二遍：值变化与时间戳
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("#"):
                cur_time = int(line[1:].strip())
                if not self.times or self.times[-1] != cur_time:
                    self.times.append(cur_time)
            elif line.startswith("$"):
                # 忽略 $dumpvars/$end 等区块标记
                pass
            else:
                self._decode_value_line(line, cur_time)
            i += 1
        # 定位 clk id
        for vid, name in self.id2sig.items():
            if name == self.clk_sig:
                self._clk_id = vid
                break
        self._build_cycle_events()
        return self

    def _decode_value_line(self, line, cur_time):
        """解码一行值变化：b<bin> <id>（向量）或 <0/1/x/z><id>（标量）。"""
        m = re.match(r"^b([01xzXZ]+)\s+(\S+)", line)
        if m:
            val, vid = m.group(1), m.group(2)
        else:
            m = re.match(r"^([01xzXZ])(\S+)", line)
            if not m:
                return
            val, vid = m.group(1), m.group(2)
        self.values.setdefault(vid, []).append((cur_time, val))

    def _build_cycle_events(self):
        """以 clk 上升沿切分周期：每个上升沿后到下一上升沿前为一个 cycle。

        cycle 0 = 初始段（复位/初值）；cycle N = 第 N 个上升沿后的周期。
        """
        if not self._clk_id:
            # 无 clk：退化为时间戳分桶（每时间戳一周期）
            self._clk_id = None
        edges = []
        for (t, v) in self.values.get(self._clk_id or "", []):
            if v in ("1", "01", "001"):
                edges.append(t)
        # 每周期事件：取 [edge_t, next_edge_t) 内该信号最后一次值
        cycle_starts = [0] + edges
        self.cycle_events = []
        for ci, t0 in enumerate(cycle_starts):
            t1 = cycle_starts[ci + 1] if ci + 1 < len(cycle_starts) else None
            events = []
            for vid, changes in self.values.items():
                last = None
                for (t, v) in changes:
                    if t >= t0 and (t1 is None or t < t1):
                        last = v
                if last is not None:
                    events.append({"sig": self.id2sig.get(vid, vid), "val": last})
            self.cycle_events.append({"cycle": ci, "time": t0, "events": events})

    def state_trace(self, sigs):
        """按周期提取指定信号轨迹：返回 [{cycle, **{sig: val}}]。"""
        rows = []
        for ce in self.cycle_events:
            row = {"cycle": ce["cycle"], "time": ce["time"]}
            vals = {e["sig"]: e["val"] for e in ce["events"]}
            for s in sigs:
                row[s] = vals.get(s)
            rows.append(row)
        return rows

    def all_signals(self):
        """返回全部信号名（去重，保序）。"""
        return list(dict.fromkeys(self.id2sig.values()))


def main(argv=None):
    import sys
    if len(sys.argv) < 2:
        print("usage: vcd_parser.py <file.vcd> [clk_sig]")
        return 1
    clk = sys.argv[2] if len(sys.argv) > 2 else "clk"
    vp = VcdParser(sys.argv[1], clk_sig=clk).parse()
    print("signals:", vp.all_signals())
    print("clk_id:", vp._clk_id)
    print("cycles:", len(vp.cycle_events))
    for ce in vp.cycle_events[:6]:
        print("cycle", ce["cycle"], "time", ce["time"], "events", len(ce["events"]))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
