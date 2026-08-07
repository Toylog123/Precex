# -*- coding: utf-8 -*-
"""
CexTracer v3：动态反例轨迹切片器
================================
改进：
  1. 自动检测 VCD 时钟信号名（ACLK/clk）
  2. 过滤 yosys/formal 内部信号（anyinit/anyseq/smt_）
  3. 修复 axi 全大写信号识别（S_AXI_* 不应被过滤）
  4. block 匹配容错（多块得分，取最优）
"""

import os, re, json
from collections import defaultdict
from agents.cex_semantizer.vcd_parser import VcdParser


# ── Helpers ──────────────────────────────────────────────

_VERILOG_KW = {
    'begin','end','if','else','always','posedge','negedge','or','and',
    'not','assert','assume','property','disable','iff','module','input',
    'output','wire','reg','assign','parameter','localparam','case',
    'endcase','default','for','while','repeat','forever','generate',
    'endgenerate','function','endfunction','task','endtask','specify',
    'endspecify','initial','final','edge','bit','logic','int','integer',
}

_INTERNAL_PREFIXES = ('anyinit_', 'anyseq_', 'smt_', '_auto_', '$', '\\')

def _is_real_signal(name):
    """过滤 yosys/formal 内部信号。"""
    for p in _INTERNAL_PREFIXES:
        if name.startswith(p) or p in name:
            return False
    if 'procdff' in name or 'execute_' in name or 'setundef' in name:
        return False
    return True

def _extract_ids(text):
    """从 Verilog 文本提取标识符，保留 AXI 风格的全大写信号。"""
    ids = set(re.findall(r'\b([a-zA-Z_]\w*)\b', text))
    result = set()
    for s in ids:
        if s in _VERILOG_KW:
            continue
        if s.isdigit():
            continue
        # Keep if: contains lowercase (normal signal), 
        #          or starts with known protocol prefix (S_AXI_, AXI_, etc.)
        #          or contains underscore (likely a signal, not a parameter)
        if any(c.islower() for c in s) or '_' in s:
            result.add(s)
        elif s.isupper() and len(s) <= 2:
            continue  # likely parameter like S1, IDLE
    return result


class CexTracer:
    """动态反例轨迹切片器 v3。"""

    def __init__(self, sample_dir, clk_sig=None):
        self.sample_dir = sample_dir
        self.clk_sig = clk_sig  # None = auto-detect
        self.vcd_path = None
        self.buggy_path = None
        self.evidence_path = os.path.join(sample_dir, "evidence.json")

        for f in os.listdir(sample_dir):
            if f.endswith(".vcd"):
                self.vcd_path = os.path.join(sample_dir, f)
            elif f == "buggy.v":
                self.buggy_path = os.path.join(sample_dir, f)

        self.vp = None
        self.real_signals = set()
        self.assert_signals = set()
        self.fail_step = 0

    # ── VCD ────────────────────────────────────────────────

    def _detect_clock(self):
        """从 buggy.v 的 always @(posedge X) 检测时钟信号名。"""
        candidates = ['clk', 'ACLK', 'CLK', 'clock', 'aclk']
        if self.buggy_path and os.path.exists(self.buggy_path):
            with open(self.buggy_path, encoding='utf-8') as f:
                code = f.read()
            m = re.findall(r'always\s*@\s*\(\s*posedge\s+(\w+)', code)
            if m:
                candidates = [m[0]] + candidates
        return candidates

    def parse_vcd(self):
        if not self.vcd_path:
            raise FileNotFoundError("No VCD in %s" % self.sample_dir)
        clocks = self._detect_clock()
        for clk in clocks:
            try:
                vp = VcdParser(self.vcd_path, clk_sig=clk)
                vp.parse()
                sigs = vp.all_signals()
                if sigs:
                    self.vp = vp
                    self.real_signals = {s for s in sigs if _is_real_signal(s)}
                    return
            except Exception:
                continue
        raise RuntimeError("Cannot parse VCD with any clock: %s" % clocks)

    def flipped_in_window(self, window=8):
        trace = self.vp.state_trace(list(self.real_signals))
        flipped = set()
        prev = {}
        for t in trace:
            c = t.get("cycle", 0)
            if abs(c - self.fail_step) > window:
                continue
            for sig, val in t.items():
                if sig == "cycle":
                    continue
                if sig not in self.real_signals:
                    continue
                if sig in prev and val is not None and prev[sig] != val:
                    flipped.add(sig)
                if val is not None:
                    prev[sig] = val
        return flipped

    # ── Evidence ────────────────────────────────────────────

    def _load_evidence(self):
        if os.path.exists(self.evidence_path):
            with open(self.evidence_path, encoding="utf-8") as f:
                ev = json.load(f)
            tc = ev.get("trigger_condition", "")
            ids = _extract_ids(tc)
            self.assert_signals = ids & self.real_signals if self.real_signals else ids
            self.fail_step = ev.get("fail_step", 0)

    # ── Verilog blocks ──────────────────────────────────────

    def _extract_blocks(self):
        if not self.buggy_path:
            return []
        with open(self.buggy_path, encoding="utf-8") as f:
            lines = f.readlines()

        blocks = []
        in_block = False
        start = 0
        depth = 0

        for i, raw in enumerate(lines):
            line = raw.strip()
            if not in_block:
                if re.match(r'(always\s*@|assign\s)', line):
                    in_block = True
                    start = i
                    depth = 0
                    # Count begin/end on this line
                    opens = len(re.findall(r'\bbegin\b', line))
                    closes = len(re.findall(r'\bend\b', line))
                    depth = opens - closes
                    if depth == 0 and 'begin' in line:
                        depth = 1
                    if depth <= 0:
                        blocks.append((start, i))
                        in_block = False
                continue

            opens = len(re.findall(r'\bbegin\b', line))
            closes = len(re.findall(r'\bend\b', line))
            depth += opens - closes
            if depth <= 0:
                blocks.append((start, i))
                in_block = False

        return blocks

    def _signals_in_range(self, lines, start, end):
        text = '\n'.join(lines[start:end+1])
        text = re.sub(r'//.*', '', text)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        all_ids = _extract_ids(text)
        return all_ids & self.real_signals if self.real_signals else all_ids

    def best_block(self):
        """找到包含断言上下文的最相关 block。"""
        if not self.buggy_path:
            return None

        with open(self.buggy_path, encoding="utf-8") as f:
            lines = f.readlines()

        blocks = self._extract_blocks()
        ev_line = 0
        if os.path.exists(self.evidence_path):
            with open(self.evidence_path, encoding="utf-8") as f:
                ev_line = json.load(f).get("line", 0)

        best = None
        best_score = -1
        for start, end in blocks:
            block_text = '\n'.join(lines[start:end+1])
            sigs = self._signals_in_range(lines, start, end)

            score = 0
            # Ev line inside block = strong signal
            if start <= ev_line - 1 <= end:
                score += 20
            # Overlap with assert signals
            score += len(sigs & self.assert_signals) * 5
            # Contains assert keyword
            if 'assert' in block_text.lower():
                score += 3
            # Larger blocks (more context) get slight preference
            score += min(len(sigs) * 0.1, 5)

            if score > best_score:
                best_score = score
                best = (start, end)

        if best:
            return self._signals_in_range(lines, best[0], best[1])
        return set()

    # ── Main ─────────────────────────────────────────────────

    def build(self, fail_step=None):
        self._load_evidence()
        if fail_step is not None:
            self.fail_step = fail_step

        self.parse_vcd()
        flipped = self.flipped_in_window()
        block_sigs = self.best_block()

        # Dynamic cone = block signals that actually flipped
        dynamic = sorted(block_sigs & flipped)
        silent = sorted(self.assert_signals - flipped)

        static_path = os.path.join(self.sample_dir, "semantics.json")
        static_size = 0
        if os.path.exists(static_path):
            with open(static_path, encoding="utf-8") as f:
                static_size = len(json.load(f).get("fault_cone", []))

        result = {
            "algorithm": "block_clustering_v3",
            "fail_step": self.fail_step,
            "assert_signals": sorted(self.assert_signals),
            "static_cone_size": static_size,
            "dynamic_cone": dynamic,
            "dynamic_cone_size": len(dynamic),
            "silent_signals": silent,
            "reduction_ratio": round(len(dynamic) / max(static_size, 1), 2),
        }

        out_path = os.path.join(self.sample_dir, "dynamic_cone.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result


def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 cex_tracer.py <sample_dir>")
        sys.exit(1)
    t = CexTracer(sys.argv[1])
    r = t.build()
    print("static=%d → dynamic=%d (%.0f%%)" % (
        r["static_cone_size"], r["dynamic_cone_size"],
        r["reduction_ratio"] * 100))
    print("silent:", r["silent_signals"])
    for s in r["dynamic_cone"][:15]:
        print("  ", s)


if __name__ == "__main__":
    main()
