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

def strip_ground_truth(text):
    """剥离证据文本中的 ground-truth 标注（inject_line/inject_desc/diff）。

    ground-truth 隔离：证据段只允许包含 LLM 可独立获得的信息，
    禁止把数据集标注（注入行号/缺陷描述）混入生成上下文（Layer3 防火墙）。
    """
    import json as _json
    try:
        obj = _json.loads(text)
    except Exception:
        return text
    if isinstance(obj, dict):
        for k in ("inject_line", "inject_desc", "diff", "buggy_inject_line"):
            obj.pop(k, None)
        return _json.dumps(obj, ensure_ascii=False, indent=2)
    return text


def sanitize_design_text(design):
    """消毒 buggy.v 头部注释中的数据集标注（缺陷描述/注入行号），保持行数不变。

    buggy.v 头部注释由 bug_injector 写入，含"注入『类型』类缺陷——描述（击穿断言）"
    与"单点注入（行 N）"等 ground-truth 信息；喂给 LLM 前必须替换为中性注释，
    否则 LLM 直接看到缺陷描述与行号（A 设置同样受影响）。
    保持行数不变：loc_top1 判据依赖 buggy_inject_line 与设计文本行号对应。
    """
    import re as _re
    # 只处理注释行；保留行尾符（\n 或 \r\n），保证行数/行号不变。
    # 第一处（功能概述行）→ 中性概述；其余（来源/击穿行）→ 中性来源。
    first = [True]
    def _rep(m):
        indent = m.group(1)
        ending = m.group(2) or ""
        if first[0]:
            first[0] = False
            return indent + " 功能概述：L3 跨周期行为缺陷样本（弱 tb 通过但形式验证失败）" + ending
        return indent + " 来源：buggy 版本（L3 跨周期行为缺陷样本）" + ending
    pattern = _re.compile(r'^(\s*//)[^\r\n]*(?:注入|击穿|单点注入)[^\r\n]*(\r?\n?)$', _re.M)
    out = pattern.sub(_rep, design)
    return out if out != design else design


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
    elif setting == "BT":
        ev_label = "【证据段 B+T：结构化证据 + TraceAnalyzer 动态切片】"
    elif setting == "BH":
        ev_label = "【证据段 B+H：结构化证据 + 握手协议分析（动态切片 + 违规检测 + 协议提示）】"
    elif setting == "D":
        ev_label = "【证据段 D：FVDebug 式因果图（失败断言 + 根因节点 + 因果链状态轨迹，确定性提取）】"
    elif setting == "E":
        ev_label = "\u3010\u8bc1\u636e\u6bb5 E\uff1a\u52a8\u6001\u8f68\u8ff9\u5207\u7247\uff08CexTracer\u2014\u2014\u53cd\u4f8b\u7a97\u53e3\u5185\u7ffb\u8f6c\u4fe1\u53f7 + \u9759\u9ed8\u53ef\u7591\u4fe1\u53f7 + \u65ad\u8a00\u4e0a\u4e0b\u6587\uff09\u3011"
    elif setting == "C":
        ev_label = "【证据段 C：反例语义化（周期事件表+状态轨迹+故障锥+NL 摘要）】"
    else:
        raise ValueError("setting 必须是 A/B/C/D/E/BT/BH")
    prompt = (
        head + ev_label + chr(10) + "[证据内容开始]" + chr(10)
        + evidence_text + chr(10) + "[证据内容结束]" + chr(10) + chr(10)
    )
    prompt += "【元数据】error_type=%s module=%s" % (
        meta.get("error_type", "?"), meta.get("module", "?")) + chr(10)
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
            return strip_ground_truth(f.read())
    if setting == "BH":
        p = os.path.join(sample_dir, "evidence.json")
        if not os.path.isfile(p):
            return "\uff08evidence.json \u7f3a\u5931\uff09"
        with open(p, "r", encoding="utf-8") as f:
            body_b = strip_ground_truth(f.read())
        try:
            import json as _json
            import os as _os
            import cex_diff as _cd
            meta_p = _os.path.join(sample_dir, "meta.json")
            meta = {}
            if _os.path.isfile(meta_p):
                with open(meta_p, "r", encoding="utf-8") as f:
                    meta = _json.load(f)
            old_vcd = _os.path.join(sample_dir, "cex.vcd")
            old_log = _os.path.join(sample_dir, "cex.log")
            clk = _cd.MODULE_CLK.get(meta.get("module"), "clk")
            old_fail, _ = _cd.extract_fail_step(old_log)
            r = _cd.analyze(old_vcd, None, clk, old_fail, None, module=meta.get("module"))
            hs_feat = r.get("handshake_old") or {}
            viols = _cd.module_handshake_violations(hs_feat, meta.get("module") or "")
            note = _cd.HANDSHAKE_NOTE.get(meta.get("module") or "")
            rows = []
            for pk, f in sorted(hs_feat.items()):
                rows.append("%s: %s" % (pk, _json.dumps(f, ensure_ascii=False)))
            hs_text = chr(10).join(rows)
            if viols:
                hs_text += chr(10) + "\u534f\u8bae\u8fdd\u89c4\uff1a" + "\uff1b".join(viols)
            if note:
                hs_text += chr(10) + "\u534f\u8bae\u63d0\u793a\uff1a" + note
        except Exception as e:
            hs_text = "\uff08\u63e1\u624b\u5206\u6790\u5931\u8d25\uff1a%s\uff09" % repr(e)[:80]
        return body_b + chr(10) + chr(10) + "\u3010\u63e1\u624b\u534f\u8bae\u5206\u6790\uff08TraceAnalyzer \u52a8\u6001\u5207\u7247 + \u534f\u8bae\u68c0\u6d4b\uff09\u3011" + chr(10) + hs_text
    if setting == "BT":
        p = os.path.join(sample_dir, "evidence.json")
        if not os.path.isfile(p):
            return "（evidence.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            body_b = f.read()
        ta_path = os.path.join(sample_dir, "trace_analysis_replay.json")
        if not os.path.isfile(ta_path):
            ta_path = os.path.join(sample_dir, "trace_analysis.json")
        ta_text = ""
        if os.path.isfile(ta_path):
            try:
                import json as _json
                with open(ta_path, "r", encoding="utf-8") as f:
                    ta = _json.load(f)
                an = ta.get("analysis") or {}
                rows = []
                if "first_anomaly_cycle" in an:
                    rows.append("first_anomaly_cycle=%s" % an["first_anomaly_cycle"])
                if "cycles_compared" in an:
                    rows.append("cycles_compared=%s" % an["cycles_compared"])
                ks = (an.get("key_signal_diffs") or [])[:20]
                rows.append("key_signal_diffs=%s" % _json.dumps(ks, ensure_ascii=False))
                ss = (an.get("stuck_signals") or [])[:10]
                rows.append("stuck_signals=%s" % _json.dumps(ss, ensure_ascii=False))
                ta_text = " | ".join(rows)
            except Exception as e:
                ta_text = "（trace_analysis 解析失败: %s）" % e
        return body_b + chr(10) + chr(10) + "【TraceAnalyzer 动态切片摘要】" + chr(10) + ta_text
    if setting == "C":
        p = os.path.join(sample_dir, "semantics.json")
        if not os.path.isfile(p):
            return "（semantics.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    if setting == "E":
        p = os.path.join(sample_dir, "dynamic_cone.json")
        if not os.path.isfile(p):
            return "\uff08dynamic_cone.json \u7f3a\u5931\uff0c\u8bf7\u5148\u8fd0\u884c CexTracer\uff09"
        with open(p, "r", encoding="utf-8") as fh:
            import json as _json2
            cone = _json2.loads(fh.read())
        evp = os.path.join(sample_dir, "evidence.json")
        ev = {}
        if os.path.isfile(evp):
            with open(evp, "r", encoding="utf-8") as fh:
                ev = _json2.loads(fh.read())
        parts = ["\u3010\u53cd\u4f8b\u52a8\u6001\u8f68\u8ff9\u5207\u7247\uff08CexTracer\uff09\u3011"]
        parts.append("\u5931\u8d25\u6b65\uff1a%s  \u65ad\u8a00\u4fe1\u53f7\uff1a%s" % (cone.get("fail_step"), ", ".join(cone.get("assert_signals", []))))
        parts.append("")
        dc = cone.get("dynamic_cone", [])
        parts.append("\u3010\u52a8\u6001\u6545\u969c\u9525\uff08\u5b9e\u9645\u7ffb\u8f6c\u7684\u5173\u952e\u4fe1\u53f7\uff0c\u5171 %d \u4e2a\uff09\u3011" % len(dc))
        for sig in dc[:20]:
            parts.append("  - %s" % sig)
        parts.append("")
        sl = cone.get("silent_signals", [])
        if sl:
            parts.append("\u3010\u9759\u9ed8\u53ef\u7591\u4fe1\u53f7\uff08\u65ad\u8a00\u5f15\u7528\u4f46\u4ece\u672a\u7ffb\u8f6c\uff0c\u5171 %d \u4e2a\uff09\u3011" % len(sl))
            for sig in sl[:10]:
                parts.append("  - %s\uff08\u8be5\u4fe1\u53f7\u5728\u65ad\u8a00\u4e2d\u5f15\u7528\u4f46\u53cd\u4f8b\u7a97\u53e3\u5185\u672a\u7ffb\u8f6c\uff0c\u53ef\u80fd\u662f\u72b6\u6001\u673a\u5361\u6b7b\u7684\u6839\u56e0\uff09" % sig)
            parts.append("")
        parts.append("\u538b\u7f29\u7387\uff1a\u9759\u6001\u9525 %d -> \u52a8\u6001\u9525 %d\uff08%.0f%%\uff09" % (
            cone.get("static_cone_size", 0), cone.get("dynamic_cone_size", 0),
            cone.get("reduction_ratio", 0) * 100))
        parts.append("\u89e6\u53d1\u6761\u4ef6\uff1a%s" % ev.get("trigger_condition", "\uff08\u672a\u63d0\u53d6\uff09"))
        parts.append("\u9519\u8bef\u7c7b\u578b\uff1a%s" % ev.get("error_type", "?"))
        return chr(10).join(parts)
    raise ValueError("setting 必须是 A/B/C/D/E/BT/BH")
