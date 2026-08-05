#!/usr/bin/env python3
# PreCex - experiments/configs/prompt_templates.py A/B/C prompt 模板族
# 作者：Toylog | 版本：v0.1 | 功能概述：LocalRepairer 定位+修复 prompt 模板族（设置 A/B/C），
#   同模板族仅"证据段"替换（实验协议第 ① 条：防偏）。
#   A = 原始日志/反例原文；B = 结构化 JSON（evidence.json）；C = 反例语义化（semantics.json）。
#   输出格式约定（供 scripts/run_prestudy.py 解析）：
#     ###LOCATE###  line: <int>  signals: <a,b>  reason: <一句话>
#     ###DIFF###    <unified diff，仅修改切片内代码>

"""A/B/C prompt 模板族（版本 v0.1）。

用法（库方式）：
    from prompt_templates import build_prompt, SYSTEM_PROMPT
    prompt = build_prompt(setting="C", design=..., assertions=..., evidence_text=..., meta=...)
"""

SYSTEM_PROMPT = """你是 PreCex 的 LocalRepairer：反例驱动的综合前 RTL 缺陷定位与修复智能体。
你的任务：
1. 定位：基于给定证据找出最可能的缺陷位置（模块+信号+行号），给出 Top-1 候选。
2. 修复：只允许修改故障锥/切片约束内的代码（故障锥信号所在 always 块 + 直接赋值链），
   禁止改接口、禁止无关重构；输出最小 unified diff。
修复成功判据（Verifier 三通过）：
  ① iverilog -g2012 编译 0 error；
  ② 弱 testbench 回归全绿（PASS: ... + $finish）；
  ③ sby bmc 无形式反例（或 k-induction 可证）。
注意：这是"弱 tb 通过但形式验证失败"的跨周期缺陷（L3），仿真通过不代表正确——
  必须以形式反例消失为准。若证据不足，宁可不改，也不要乱猜。
"""

# 输出格式说明（追加在证据段之后）
OUTPUT_FORMAT = """
【输出格式】（严格按以下标记输出，不要输出多余文字）：
###LOCATE###
line: <最可疑行号（整数）>
signals: <信号1,信号2,...>
reason: <一句话说明定位依据>

###DIFF###
--- a/buggy.sv
+++ b/buggy.sv
@@ -<起行>,<行数> +<起行>,<行数> @@
- <被删/被改的旧行>
+ <新增/修正后的新行>
"""


def build_prompt(setting, design, assertions, evidence_text, meta=None, history=None):
    """组装 user prompt：任务说明 + 设计 + 断言 + 证据段 + 输出格式。

    history（可选）：list[dict]，每次修复尝试失败后追加一条：
      {"attempt": int, "diff": str, "failure": str}
    重试时注入【上次修复历史】，明确告诉 LLM 上一次生成的 diff 与失败原因，
    并要求避免重复该模式——这是反馈循环（闭环承诺）在 prompt 层的兑现，
    避免"开环重试"（第二轮只把相同 prompt 再发一次、LLM 重复相同错误补丁）。
    首次调用不传 history 时输出与旧版逐字节一致（不改变已定案实验口径）。
    """
    meta = meta or {}
    history = history or []
    head = (
        "请定位并修复以下 RTL 设计中的跨周期行为缺陷（L3：弱 tb 通过但形式验证失败）。"
        + chr(10) + chr(10)
        + "【设计文件 buggy.sv】"
        + chr(10) + "[systemverilog 代码开始]" + chr(10) + design + chr(10) + "[systemverilog 代码结束]"
        + chr(10) + chr(10)
        + "【强断言（失效断言即形式失败点）】"
        + chr(10) + "[systemverilog 代码开始]" + chr(10) + assertions + chr(10) + "[systemverilog 代码结束]"
        + chr(10) + chr(10)
    )
    if setting == "A":
        ev_label = "【证据段 A：原始反例日志/反例原文（未结构化处理）】"
    elif setting == "B":
        ev_label = "【证据段 B：结构化证据 JSON（EvidenceEngine 输出）】"
    elif setting == "D":
        ev_label = "【证据段 D：FVDebug 式因果图（失败断言 + 根因节点 + 因果链状态轨迹，确定性提取）】"
    elif setting == "C":
        ev_label = "【证据段 C：反例语义化（周期事件表+状态轨迹+故障锥+NL 摘要）】"
    else:
        raise ValueError("setting 必须是 A/B/C")
    prompt = (
        head + ev_label + chr(10) + "[证据内容开始]" + chr(10)
        + evidence_text + chr(10) + "[证据内容结束]" + chr(10) + chr(10)
    )
    prompt += "【元数据】error_type=%s inject_line=%s（仅作参考，不代表答案）" % (
        meta.get("error_type", "?"), meta.get("inject_line", "?")) + chr(10)
    if history:
        prompt += chr(10) + "【上次修复历史（反馈循环）】" + chr(10)
        for h in history:
            prompt += (
                "- 第 %d 次尝试：你上次生成的 diff 未通过验证。%s%s"
                % (h.get("attempt", "?"),
                   chr(10) + "  上次 diff：" + h.get("diff", "") + chr(10) if h.get("diff") else "",
                   chr(10) + "  失败原因：" + h.get("failure", "?") + chr(10))
            )
        prompt += (
            "要求：请先分析上次修复为何失败（它引入了什么新反例/为何未消除原反例），"
            "然后给出**不同**的修复方案，不要重复该模式；若上次思路本身正确但实现有误，"
            "请修正实现而非原样重发。" + chr(10)
        )
    prompt += OUTPUT_FORMAT
    return prompt


def build_evidence_text(setting, sample_dir):
    """按设置读取证据文本（A/B/C）。返回 str。"""
    import os
    if setting == "A":
        parts = []
        log = os.path.join(sample_dir, "cex.log")
        vcd = os.path.join(sample_dir, "cex.vcd")
        if os.path.isfile(log):
            with open(log, "r", encoding="utf-8", errors="replace") as f:
                parts.append("[cex.log]" + chr(10) + f.read())
        if os.path.isfile(vcd):
            with open(vcd, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
                if len(lines) > 160:
                    body = (chr(10).join(lines[:120]) + chr(10) + "...（中段省略）..."
                            + chr(10) + chr(10).join(lines[-40:]))
                else:
                    body = chr(10).join(lines)
                parts.append("[cex.vcd 原始波形]" + chr(10) + body)
        return chr(10).join(parts)
    if setting == "B":
        p = os.path.join(sample_dir, "evidence.json")
        if not os.path.isfile(p):
            return "（evidence.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    if setting == "C":
        p = os.path.join(sample_dir, "semantics.json")
        if not os.path.isfile(p):
            return "（semantics.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    raise ValueError("setting 必须是 A/B/C")
