#!/usr/bin/env python3
# PreCex - agents/cex_semantizer/cex_semantizer.py CexSemantizer 文本通道（组件2 核心）
# 作者：Toylog | 版本：v0.1 | 功能概述：基于 EvidenceEngine 的结构化 JSON + VCD，
#   生成反例语义化证据（设置 C）：
#   - 周期事件表（cycle event table）
#   - 状态轨迹（state trace，仅关键控制/状态信号）
#   - 故障锥（fault cone，静态近似：断言违例信号 + 代码切片引用的信号）
#   - M3 NL 摘要（附录 A 模板，经 harness/llm_client.py 调用，token 记账强制）
#   输出 samples/prestudy/sNN/semantics.json（含 text_summary），供 A/B/C 评测设置 C 使用。

"""CexSemantizer：反例 → 周期事件/状态轨迹/故障锥 + NL 摘要。

用法：
    python3 cex_semantizer.py <sample_dir> [--out <semantics.json>] [--mock|--real]
      --mock  用 llm_client mock 模式生成摘要（离线调试，默认）
      --real  真实调用 MiniMax M3（需 .env 配置 key）
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "harness"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from llm_client import LLMClient
from vcd_parser import VcdParser

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 状态轨迹关注信号（按模块类型通用：控制/状态/计数/指针/标志）
KEY_SIGS = [
    "rst_n", "wr_en", "rd_en", "cnt_en", "en", "start", "valid", "ready",
    "state", "state_d", "cnt", "cnt_d", "count", "count_d", "step_cnt", "step_cnt_d",
    "head", "tail", "full", "empty", "half_full", "full_d", "empty_d",
    "done", "timeout_irq", "op", "op_d", "a", "b", "a_d", "b_d", "alu_out", "alu_out_d",
    "data_in", "din", "dout",
]


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _extract_sig_names(text):
    """从代码片段/断言表达式提取信号名（标识符，排除关键字/常量）。"""
    if not text:
        return set()
    kw = {
        "if", "else", "begin", "end", "assert", "assume", "input", "output", "wire", "reg",
        "logic", "signed", "unsigned", "posedge", "negedge", "or", "and", "not", "module",
        "endmodule", "parameter", "localparam", "function", "endfunction", "case", "endcase",
        "default", "for", "while", "return", "assign", "always", "initial", "integer",
    }
    names = set()
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", text):
        t = m.group(1)
        if t not in kw and not t.startswith(("OP_", "A", "S_", "IDLE", "BUSY", "DONE")):
            names.add(t)
    return names


class CexSemantizer:
    """反例语义化主类。"""

    def __init__(self, sample_dir, clk_sig="clk", llm=None):
        self.sample_dir = os.path.abspath(sample_dir)
        self.clk_sig = clk_sig
        self.llm = llm
        self.evidence = _load_json(os.path.join(self.sample_dir, "evidence.json"))
        cex_path = os.path.join(self.sample_dir, "cex.vcd")
        self.vp = VcdParser(cex_path, clk_sig=clk_sig).parse() if os.path.isfile(cex_path) else None
        self.semantics = {}

    def build(self, max_cycles=None):
        """生成语义化证据（不含 NL 摘要，摘要由 summarize() 生成）。"""
        ev = self.evidence
        cycles = self.vp.cycle_events if self.vp else []
        if max_cycles:
            cycles = cycles[:max_cycles]
        # 周期事件表：只保留信号变化行（值在相邻周期不同的信号）
        event_table = []
        prev = {}
        for ce in cycles:
            cur = {e["sig"]: e["val"] for e in ce["events"]}
            changed = {k: v for k, v in cur.items() if prev.get(k) != v}
            event_table.append({
                "cycle": ce["cycle"],
                "time": ce["time"],
                "changes": [{"sig": k, "val": v} for k, v in sorted(changed.items())],
            })
            prev = cur
        # 状态轨迹：关键信号
        sigs = [s for s in KEY_SIGS if self.vp and s in set(self.vp.all_signals())]
        state_trace = self.vp.state_trace(sigs) if self.vp else []
        # 故障锥（静态近似）：断言触发信号 + 代码切片引用的信号
        cone = set()
        cone |= _extract_sig_names(ev.get("trigger_condition"))
        cone |= _extract_sig_names(ev.get("code_slice"))
        cone |= set(sigs)
        cone = sorted(cone)
        self.semantics = {
            "schema_ver": "v1.0",
            "sample_id": ev.get("sample_id"),
            "module": ev.get("module"),
            "error_type": ev.get("error_type"),
            "fail_stage": ev.get("fail_stage"),
            "fail_step": ev.get("fail_step"),
            "failed_line": ev.get("line"),
            "trigger_condition": ev.get("trigger_condition"),
            "cycle_events": event_table,
            "state_trace": state_trace,
            "fault_cone": cone,
            "key_signals": sigs,
            "text_summary": None,
        }
        return self.semantics

    def summarize(self, mock=True, tag="cex_semantize"):
        """生成 NL 摘要（附录 A 模板）：周期事件表 + 状态轨迹 + 故障锥 → M3 3-5 句。"""
        s = self.semantics
        # 压缩状态轨迹：超过 24 周期只保留前后各 8 + 触发周期附近
        trace = s.get("state_trace", [])
        if len(trace) > 24:
            head, tail = trace[:8], trace[-8:]
            trace_view = head + [{"cycle": "... 省略 ..."}] + tail
        else:
            trace_view = trace
        prompt = (
            "你是资深 RTL 验证工程师。基于给定的周期事件表、状态轨迹与故障锥信号，\n"
            "用 3–5 句描述：缺陷发生在哪个周期、哪些信号先异常、与断言违例的因果链。\n"
            "要求：不猜测证据之外的原因；指出最可疑的代码位置（模块+信号+周期）。\n\n"
            "【故障信息】\n"
            "module=%s error_type=%s fail_stage=%s fail_step=%s\n"
            "trigger_condition=%s failed_line=%s\n"
            "fault_cone=%s\n\n"
            "【周期事件表】（cycle: 本周期有变化的信号=新值）\n%s\n\n"
            "【状态轨迹】（cycle: 关键信号值）\n%s\n"
            % (
                s.get("module"), s.get("error_type"), s.get("fail_stage"), s.get("fail_step"),
                s.get("trigger_condition"), s.get("failed_line"),
                ", ".join(s.get("fault_cone", [])),
                json.dumps([{ "cycle": ce["cycle"], "changes": ce["changes"] } for ce in s.get("cycle_events", [])], ensure_ascii=False),
                json.dumps(trace_view, ensure_ascii=False),
            )
        )
        client = self.llm or LLMClient(mock=mock)
        res = client.text_generate(prompt, system="你是 PreCex 的 CexSemantizer：反例语义化引擎。", tag=tag)
        s["text_summary"] = res["content"]
        s["summary_meta"] = {
            "mode": res["mode"], "input_tokens": res["input_tokens"],
            "output_tokens": res["output_tokens"], "cost": res["cost"],
        }
        return s


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__)
        return 1
    sample_dir = argv[0]
    out_path = None
    mock = True
    if "--out" in argv:
        i = argv.index("--out")
        out_path = argv[i + 1] if i + 1 < len(argv) else None
    if "--real" in argv:
        mock = False
    cs = CexSemantizer(sample_dir)
    cs.build()
    cs.summarize(mock=mock)
    text = json.dumps(cs.semantics, ensure_ascii=False, indent=2)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print("summary:", (cs.semantics.get("text_summary") or "")[:500])
    print("tokens:", cs.semantics.get("summary_meta"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
