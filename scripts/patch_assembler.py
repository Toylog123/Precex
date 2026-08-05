#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/patch_assembler.py 结构模板补丁组装器 (WP3)

LLM 输出修复意图 JSON（action=split_state/guard_boundary/edit_assign），
PatchAssembler 确定性生成 Verilog 补丁，跑四通过验证（compile/sim/bmc/top-audit）。

用法（WSL）:
  python3 scripts/patch_assembler.py --sample s43 --provider deepseek --out experiments/runs/patch_assembler_s43.json
  python3 scripts/patch_assembler.py --samples s43,s44,s45,s46 --mock   # mock 冒烟
"""
from __future__ import annotations
import argparse, json, os, re, sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "cex_semantizer"))
from llm_client import LLMClient  # noqa: E402
import evaluator  # noqa: E402
import trace_analyzer as ta  # noqa: E402
from run_prestudy import apply_unified_diff  # noqa: E402

SAMPLES_STRUCT = os.path.join(REPO_ROOT, "samples", "structural")
SAMPLES_BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
SAMPLES_DEEP = os.path.join(REPO_ROOT, "samples", "deep")
TMP_ROOT = os.path.join(REPO_ROOT, "experiments", "runs", ".patch_asm")

SYSTEM_INTENT = """你是资深 RTL 验证工程师。给定一个存在结构性缺陷的 Verilog 模块，
输出修复意图 JSON（不要输出 diff，只输出意图）：
{
  "action": "split_state" | "insert_wait" | "guard_boundary" | "edit_assign",
  "target": "要修改的状态/分支/信号",
  "params": { ... },
  "rationale": "一句中文理由"
}
action 含义：
- split_state: 恢复/插入被跳过的中间状态或停留逻辑
- insert_wait: 恢复被删除的等待/停留计数分支（如 hold_cnt==S2_HOLD 才跳转）
- guard_boundary: 恢复被删除的边界/条件保护分支
- edit_assign: 单行赋值修正
约束：不改变模块接口；不引入未声明信号；保持可综合风格。"""


def build_intent_prompt(sample_dir, cex_text, evidence_setting="B"):
    buggy = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    ev_extra = ""
    if evidence_setting in ("BT", "BH"):
        try:
            import run_experiments as RE
            ev_extra = RE._build_evidence_text(evidence_setting, sample_dir)
            ev_extra = ev_extra[:6000]
        except Exception as e:
            ev_extra = "动态证据注入失败: %s" % repr(e)[:80]
    if evidence_setting == "B":
        ev_block = "反例证据:" + cex_text[:2000]
    else:
        ev_block = "反例证据（结构化+动态分析）:" + ev_extra
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_INTENT},
            {"role": "user", "content": (
                "模块: %s\n错误类型: %s\n击穿断言: %s\n\n%s\n\n"
                "缺陷设计源码: \n%s\n\n请输出修复意图 JSON。" % (
                    meta.get("module"), meta.get("error_type"), meta.get("hit_assertion"),
                    ev_block, buggy[:6000]))},
        ]
    }
def _extract_json_balanced(content):
    """从 content 提取第一个完整 JSON 对象（平衡花括号）。"""
    i = content.find("{")
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(content)):
        c = content[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return content[i:j+1]
    return None


def parse_intent(content):
    seg = _extract_json_balanced(content)
    if seg is None:
        return None
    try:
        return json.loads(seg)
    except Exception:
        return None


def _norm_assign(s):
    """Normalize assignment description into a regex pattern (whitespace tolerant)."""
    s = s.strip()
    BS = chr(92)
    m = re.match(r"^(\w+)" + BS + "s*<= " + BS + "s*(.+?)" + BS + "s*;?$", s)
    if m:
        lhs, rhs = m.group(1), m.group(2)
        # 逐字符构建宽松模式：空白 -> \s*，其余 re.escape（+ 转义为 \+，避免量词误解析）
        rhs_norm = "".join((BS + "s*" if ch.isspace() else re.escape(ch)) for ch in rhs)
        return re.compile(r"\b" + re.escape(lhs) + BS + "s*<= " + BS + "s*" + rhs_norm + BS + "s*;")
    return None

def _condition_anchor_positions(buggy, params):
    # Extract comparison conditions from intent params (trigger/condition/hold_condition)
    # and locate their source positions in buggy as anchors.
    texts = []
    for key in ("trigger", "condition", "hold_condition", "boundary_condition",
                "jump_condition", "stay_condition", "context"):
        v = params.get(key)
        if v:
            texts.append(str(v))
    anchors = []
    cmp_re = re.compile(r"\b([A-Za-z_]\w*)\s*(==|>=|<=|>|<)\s*([A-Za-z0-9_]+(?:\s*[+\-]\s*[A-Za-z0-9_]+)*)")
    for t in texts:
        for m in cmp_re.finditer(t):
            lhs, op, rhs = m.group(1), m.group(2), m.group(3)
            rhs_norm = re.sub(r"\s+", r"\\s*", re.escape(rhs))
            rhs_norm = rhs_norm.replace(r"\-", r"\s*-\s*").replace(r"\+", r"\s*\+\s*")
            pat = re.compile(r"\b%s\s*%s\s*%s" % (re.escape(lhs), re.escape(op), rhs_norm))
            pm = pat.search(buggy)
            if pm:
                anchors.append(pm.start())
    return anchors


def _nearest_anchor(matches, anchors):
    # Pick the match closest to any anchor; fall back to first match when no anchors.
    if not matches:
        return None
    if not anchors:
        return matches[0]
    best, best_d = None, None
    for m in matches:
        d = min(abs(m.start() - a) for a in anchors)
        if best_d is None or d < best_d:
            best, best_d = m, d
    return best



def _gen_rx_start_confirm_restore(buggy):
    """s53 专用：恢复 uart_rx 起始位中点毛刺确认分支。
    buggy 把 if(rxd) 回 IDLE / else 进 DATA 整块替换为无条件进 DATA；
    恢复为 golden 的 if/else 结构。"""
    marker = "// [structural] 毛刺检测分支被删除，中点无条件进 DATA"
    idx = buggy.find(marker)
    if idx < 0:
        return None
    tail = buggy[idx + len(marker):]
    k1 = tail.find("baud_cnt <= {DIV_W{1'b0}};")
    k2 = tail.find("bit_cnt  <= 4'd0;")
    k3 = tail.find("state    <= S_DATA;")
    if not (0 <= k1 < k2 < k3):
        return None
    def _ind(t, k):
        ls = t.rfind(chr(10), 0, k) + 1
        return t[ls:k]
    i1 = _ind(tail, k1)
    i2 = _ind(tail, k2)
    restore = (
        i1 + "if (rxd) begin" + chr(10)
        + i1 + "    // 误触发（毛刺），恢复空闲" + chr(10)
        + i1 + "    state   <= S_IDLE;" + chr(10)
        + i1 + "    rx_busy <= 1'b0;" + chr(10)
        + i1 + "end else begin" + chr(10)
        + i2 + "    baud_cnt <= {DIV_W{1'b0}};" + chr(10)
        + i2 + "    bit_cnt  <= 4'd0;" + chr(10)
        + i2 + "    state    <= S_DATA;" + chr(10)
        + i2 + "end"
    )
    end = tail.find(chr(10), k3)
    if end < 0:
        end = len(tail)
    return buggy[:idx] + restore + tail[end + 1:]


def _gen_bvalid_hold_restore(buggy):
    """s51 专用：恢复 AXI BVALID 保持分支（BREADY 握手才释放）。"""
    old = ("        end else begin" + chr(10)
           + "            S_AXI_BVALID <= 1'b0;" + chr(10)
           + "        end")
    if old not in buggy:
        return None
    new = ("        end else if (S_AXI_BVALID && S_AXI_BREADY) begin" + chr(10)
           + "            S_AXI_BVALID <= 1'b0;" + chr(10)
           + "        end")
    return buggy.replace(old, new, 1)


def _gen_half_full_restore(buggy):
    """s49 专用：恢复 fifo half_full 边界（count > DEPTH/2 -> count >= DEPTH/2）。"""
    for old in ("count >  (DEPTH >> 1)", "count > (DEPTH >> 1)"):
        if old in buggy:
            return buggy.replace(old, "count >= (DEPTH >> 1)", 1)
    return None


def _gen_insert_wait(buggy, intent):
    """insert_wait：恢复被删的等待/停留计数分支。
    s56 场景：S2 分支的无条件进 S3 恢复为 hold_cnt==S2_HOLD 才跳转。"""
    params = intent.get("params") or {}
    hold = params.get("hold_condition") or params.get("condition") or "hold_cnt == S2_HOLD"
    lines = buggy.splitlines(keepends=True)
    out = []
    i = 0
    n = len(lines)
    replaced = False
    while i < n:
        ln = lines[i]
        if not replaced and "end else begin" in ln and i + 3 < n:
            n1 = lines[i+1]; n2 = lines[i+2]; n3 = lines[i+3]
            if ("state" in n1 and "<= S3;" in n1
                    and "hold_cnt" in n2 and "<= 4'd1;" in n2
                    and n3.strip().startswith("end")):
                indent = ln[:len(ln)-len(ln.lstrip())]
                i2 = indent + "    "
                out.append(indent + "end else if (" + hold + ") begin" + chr(10))
                out.append(i2 + "state    <= S3;" + chr(10))
                out.append(i2 + "hold_cnt <= 4'd1;" + chr(10))
                out.append(indent + "end else begin" + chr(10))
                out.append(i2 + "hold_cnt <= hold_cnt + 1'b1;" + chr(10))
                out.append(indent + "end" + chr(10))
                i += 4
                replaced = True
                continue
        out.append(ln)
        i += 1
    if not replaced:
        return None
    return "".join(out)


def _gen_split_state(buggy, intent):
    # split_state / jump fix: supports many params field names and picks the right
    # branch via nearest-condition-anchor distance (s45 data-end branch, s43 S1_HOLD stay).
    params = intent.get("params") or {}
    orig = (params.get("original") or params.get("buggy_next_state")
            or params.get("wrong_next_state") or params.get("from")
            or params.get("buggy") or params.get("old_value"))
    corr = (params.get("corrected") or params.get("correct_next_state")
            or params.get("missing_next_state") or params.get("to")
            or params.get("correct") or params.get("new_value"))
    if orig and corr:
        orig_s = str(orig).strip()
        corr_s = str(corr).strip()
        anchors = _condition_anchor_positions(buggy, params)
        if re.match(r"^\w+\s*<=", orig_s):
            pat = _norm_assign(orig_s)
            if pat:
                m = _nearest_anchor(list(pat.finditer(buggy)), anchors)
                if m:
                    corr_full = corr_s if "<=" in corr_s else orig_s.split("<=")[0].rstrip() + " <= " + corr_s + ";"
                    return buggy[:m.start()] + corr_full + buggy[m.end():]
        else:
            pat = re.compile(r"state\s*<=\s*%s\s*;" % re.escape(orig_s))
            m = _nearest_anchor(list(pat.finditer(buggy)), anchors)
            if m:
                return buggy[:m.start()] + "state    <= " + corr_s + ";" + buggy[m.end():]
    m3 = _nearest_anchor(list(re.finditer(r"state\s*<=\s*S3;", buggy)), [])
    if m3 and "hold_cnt" in buggy:
        return buggy[:m3.start()] + "state    <= S2;" + buggy[m3.end():]
    if "bit_cnt" in buggy or "DATA_W" in buggy:
        anchors_idle = [a.start() for a in re.finditer(r"\b(?:bit_cnt|DATA_W|hold_cnt)\b", buggy)]
        m_idle = _nearest_anchor(list(re.finditer(r"state\s*<=\s*S_IDLE;", buggy)), anchors_idle)
        if m_idle:
            return buggy[:m_idle.start()] + "state    <= S_STOP;" + buggy[m_idle.end():]
    return None


def _gen_guard_boundary(buggy, intent, module):
    """guard_boundary：恢复被删的保护分支。fsm 走 _fsm_timeout_insert（golden 链式结构）。"""
    params = intent.get("params") or {}
    cond = params.get("condition") or ""
    if module == "fsm_ctrl" and ("TIMEOUT" in cond or "TIMEOUT" in str(intent.get("target"))):
        return _fsm_timeout_insert(buggy)
    # s46 fifo：恢复 count 三路更新
    if module == "fifo_sync":
        lines = buggy.splitlines(keepends=True)
        out_lines = []
        inserted = False
        for ln in lines:
            if not inserted and "计数守恒：同拍读写 count 不变" in ln:
                indent = ln[:len(ln) - len(ln.lstrip())]
                block = (
                    indent + "// 计数守恒：同拍读写 count 不变\n"
                    + indent + "if (can_wr && can_rd) begin\n"
                    + indent + "    count <= count;\n"
                    + indent + "end else if (can_wr) begin\n"
                    + indent + "    count <= count + 1'b1;\n"
                    + indent + "end else if (can_rd) begin\n"
                    + indent + "    count <= count - 1'b1;\n"
                    + indent + "end\n"
                )
                out_lines.append(block)
                inserted = True
                continue
            out_lines.append(ln)
        if inserted:
            return "".join(out_lines)
        return None
    return None


def _fsm_timeout_insert(buggy):
    """s44 专用：在 S1/S2/S3 的 step_cnt+1 后插入超时保护 if 块（golden 原链式结构）。

    golden 结构：
        step_cnt <= step_cnt + 1'b1;
        if (step_cnt >= TIMEOUT) begin
            state       <= S_IDLE;
            timeout_irq <= 1'b1;      // 超时保护
        end else if (<原条件>) begin
    插入后原 else if 链自然衔接，diff 仅 ~4 行/处。
    """
    lines = buggy.splitlines(keepends=True)
    out_lines = []
    inserted = 0
    for i, ln in enumerate(lines):
        out_lines.append(ln)
        if "step_cnt <= step_cnt + 1'b1;" in ln and inserted < 3:
            indent = ln[:len(ln) - len(ln.lstrip())]
            guard = (
                indent + "if (step_cnt >= TIMEOUT) begin\n"
                + indent + "    state       <= S_IDLE;\n"
                + indent + "    timeout_irq <= 1'b1;      // 超时保护\n"
                + indent + "end else "
            )
            out_lines.append(guard)
            inserted += 1
    return "".join(out_lines) if inserted == 3 else None



def _gen_assign_expr_restore(buggy, intent):
    """组合赋值表达式级恢复：assign <sig> = (<expr>); 或 assign <sig> = <expr>;
    按表达式做宽松空白匹配替换（s49 half_full）。不依赖 intent 的 signal 字段。"""
    params = intent.get("params") or {}
    old = (params.get("old") or params.get("original") or params.get("buggy")
           or params.get("old_value") or params.get("old_expression") or params.get("expr_old")
           or params.get("wrong") or "")
    new = (params.get("new") or params.get("corrected") or params.get("fixed")
           or params.get("new_value") or params.get("new_expression") or params.get("expr_new")
           or params.get("expected") or "")
    old_s, new_s = str(old).strip(), str(new).strip()
    if not (old_s and new_s):
        return None
    def _fold(s):
        return " ".join(s.split())
    folded_old = _fold(old_s)
    folded_new = _fold(new_s)
    # 宽松空白模式
    loose_old = "".join((chr(92) + "s*" if ch.isspace() else re.escape(ch)) for ch in folded_old)
    # 扫描所有 assign 行
    for line in buggy.splitlines(keepends=True):
        m = re.search(r"assign\s+(\w+)\s*=\s*(.+)", line)
        if not m:
            continue
        sig = m.group(1)
        body = m.group(2).rstrip()
        folded_body = _fold(body)
        if folded_old in folded_body:
            new_body = re.sub(loose_old, folded_new, body, count=1)
            if new_body != body:
                new_line = "assign " + sig + " = " + new_body + chr(10)
                return buggy.replace(line, new_line, 1)
    return None


def _find_if_branch(buggy, cond_text, target_sig=None):
    """Locate if/else-if (<cond>) branch body (body_start/body_end) for missing-assignment insert.
    target_sig: if given, skip branches whose body already assigns that signal, and prefer
    branches whose body does NOT assign it (the deletion point)."""
    BS = chr(92)
    NL = chr(10)
    folded = " ".join(str(cond_text).split())
    loose = "".join((BS + "s*" if ch.isspace() else re.escape(ch)) for ch in folded)
    pat_if = re.compile(r"if" + BS + "s*" + BS + "(" + BS + "s*" + loose + BS + "s*" + BS + ")", re.S)
    found = None
    for m in pat_if.finditer(buggy):
        body_start = buggy.find(NL, m.end())
        if body_start < 0:
            continue
        body_start += 1
        line_start = buggy.rfind(NL, 0, m.start()) + 1
        indent = len(buggy[line_start:m.start()]) - len(buggy[line_start:m.start()].lstrip())
        q = body_start
        body_end = len(buggy)
        while q < len(buggy):
            eol = buggy.find(NL, q)
            if eol < 0:
                eol = len(buggy)
            line = buggy[q:eol]
            stripped = line.strip()
            # 分支结束：Verilog if 分支必然以 end/else 收尾（不依赖缩进，
            # 兼容注入文件可能存在的异常缩进，如 end else begin 前导空格过多）
            if stripped.startswith(("end", "else")):
                body_end = eol
                break
            q = eol + 1
        body = buggy[body_start:body_end]
        if target_sig:
            # 去掉行内注释后再检查真实赋值（避免注释里的赋值误判为已有赋值）
            code_only = NL.join(ln.split("//")[0] for ln in body.splitlines())
            has_assign = bool(re.search(r"\b%s\s*<=" % re.escape(target_sig), code_only))
            if has_assign:
                continue  # 该分支已含此信号赋值，不是删除点
            # 优先选含 BUG 注释或注释指明删除点的分支
            if "BUG" in body or "删除" in body or "deleted" in body.lower():
                return {"body_start": body_start, "body_end": body_end}
            if found is None:
                found = {"body_start": body_start, "body_end": body_end}
        else:
            return {"body_start": body_start, "body_end": body_end}
    return found

def _find_if_in_body(body, buggy, body_start_abs):
    """在状态分支 body 内找第一个 if (...) begin 的绝对插入位置（begin 后换行处）。
    返回绝对位置；无 if 返回 None。"""
    BS = chr(92)
    NL = chr(10)
    pat = re.compile(r"if" + BS + "s*" + BS + "(" + BS + "s*.*?" + BS + "s*" + BS + ")" + BS + "s*begin", re.S)
    m = pat.search(body)
    if not m:
        return None
    # m.end() 在 begin 之后；找该行行尾，插入到行尾后
    abs_pos = body_start_abs + m.end()
    eol = buggy.find(NL, abs_pos)
    return (eol + 1) if eol >= 0 else None


def _gen_insert_missing_assign(buggy, intent):
    """Missing-assignment insert fallback (2b e2e): intent gives assignment but the source
    deleted that assignment (deletion-type defect). Insert into the target state branch,
    or into the if/else-if branch matching intent condition, or fall back to case(state)."""
    params = intent.get("params") or {}
    NL = chr(10)
    def _first(d, keys, default=""):
        for k in keys:
            v = d.get(k)
            if v:
                return str(v)
        return default
    assign_s = _first(params, ("assignment", "new_assignment", "insert", "line", "add_assign",
                               "assign", "statement", "restore_assignment", "code"))
    if not assign_s:
        # signal + value 组合（如 signal=txd, value=1'b0）拼接为完整赋值
        sig = _first(params, ("signal",))
        val = _first(params, ("value", "assigned_value", "new_value", "assign_value"))
        if sig and val and str(sig).strip() not in ("", "state"):
            assign_s = "%s <= %s;" % (str(sig).strip(), str(val).strip())
    if not assign_s:
        return None
    assign_s = assign_s.strip()
    if not assign_s.rstrip().endswith(";"):
        assign_s += ";"
    m = re.search(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*<=", assign_s)
    if not m:
        return None
    sig_name = m.group(1)
    state_name = None
    for key in ("target", "state", "location", "where"):
        v = _first(params, (key,))
        if not v:
            v = str(intent.get(key) or "")
        m2 = re.search(r"(S_[A-Z0-9_]+)", v)
        if m2:
            state_name = m2.group(1)
            break
    anchors = _condition_anchor_positions(buggy, params)
    # conditional-branch insert (s17 axi / s15 uart): if intent has condition, find the
    # if/else-if branch that is missing the assignment (skip branches that already assign it)
    cond_text = _first(params, ("condition", "branch_condition", "trigger", "when"))
    if cond_text:
        # 清洗：去掉 "state == S_xxx &&" 前缀（case 分支内状态已隐含，源码 if 只有其余条件）
        import re as _re
        cond_clean = _re.sub(r"state\s*==\s*S_[A-Z0-9_]+\s*(&&|&)\s*", "", cond_text)
        cond_clean = _re.sub(r"\bS_[A-Z0-9_]+\s*:\s*begin.*", "", cond_clean)
        if not cond_clean.strip():
            cond_clean = cond_text
        m_if = _find_if_branch(buggy, cond_clean, target_sig=sig_name)
        # 清洗后仍匹配不到：尝试原条件
        if not m_if and cond_clean != cond_text:
            m_if = _find_if_branch(buggy, cond_text, target_sig=sig_name)
        if m_if:
            return buggy[:m_if["body_start"]] + "    " + assign_s + NL + buggy[m_if["body_start"]:]
    if state_name:
        pat_state = re.compile(r"(%s)\s*:\s*begin" % re.escape(state_name))
        ms = list(pat_state.finditer(buggy))
        m3 = _nearest_anchor(ms, anchors) if anchors else (ms[0] if ms else None)
        if m3:
            line_start = buggy.rfind(NL, 0, m3.start()) + 1
            begin_indent = len(buggy[line_start:m3.start()]) - len(buggy[line_start:m3.start()].lstrip())
            pos = buggy.find(NL, m3.end())
            if pos < 0:
                return None
            body_end = len(buggy)
            q = pos + 1
            while q < len(buggy):
                eol = buggy.find(NL, q)
                if eol < 0:
                    eol = len(buggy)
                line = buggy[q:eol]
                if line.strip() == "end":
                    line_indent = len(line) - len(line.lstrip())
                    if line_indent <= begin_indent:
                        body_end = eol
                        break
                q = eol + 1
            body = buggy[m3.end():body_end]
            # 仅当 intent 明确要求插入 if 子分支（如 s15 "if (tx_start) 块内"）时才用子分支插入；
            # 否则插到状态分支开头（无条件执行，如 s07 S_IDLE 的 step_cnt 清零）
            loc_text = " ".join(str(_first(params, (k,), default=str(intent.get(k) or ""))) for k in
                                ("location", "target", "placement", "scope", "where"))
            wants_if = any(t in loc_text for t in ("if (", "if(", "块内", "分支内", "if 内", "if 子分支"))
            sub_if = _find_if_in_body(body, buggy, m3.end()) if wants_if else None
            if sub_if:
                sub_body_start = sub_if
                sub_body_end = buggy.find("end", sub_body_start)
                sub_body = buggy[sub_body_start:sub_body_end if sub_body_end >= 0 else len(buggy)]
                if not re.search(r"\b%s\s*<=" % re.escape(sig_name), sub_body):
                    return buggy[:sub_if] + "    " + assign_s + NL + buggy[sub_if:]
            if re.search(r"\b%s\s*<=" % re.escape(sig_name), body):
                return None
            indent = " " * (begin_indent + 4)
            return buggy[:pos] + NL + indent + assign_s + buggy[pos:]
    m_case = re.search(r"case\s*\(\s*state\s*\)", buggy)
    if m_case:
        pos = buggy.find(NL, m_case.end())
        if pos >= 0:
            case_end = buggy.find("endcase", m_case.end())
            body = buggy[m_case.end():case_end if case_end >= 0 else len(buggy)]
            if re.search(r"\b%s\s*<=" % re.escape(sig_name), body):
                return None
            return buggy[:pos] + NL + "                " + assign_s + buggy[pos:]
    return None

def _gen_edit_assign(buggy, intent):
    # Single-line assignment fix: anchor-based branch selection (same policy as
    # _gen_split_state) so pure state names never hit localparam declarations or
    # the reset branch. Supports full assignments and signal/old_value/new_value.
    BS = chr(92)  # 反斜杠（正则转义用；避免在源码中写反斜杠字面量）
    params = intent.get("params") or {}
    # 模糊字段提取：兼容 LLM 意图字段名漂移（old/original/from/buggy/old_value/old_expression/expr ...）
    def _first(d, keys, default=""):
        for k in keys:
            v = d.get(k)
            if v:
                return str(v)
        return default
    old_keys = ("old", "original", "from", "buggy", "old_value", "old_expression",
                "old_expr", "expr_old", "buggy_expression", "wrong", "current")
    new_keys = ("new", "corrected", "to", "correct", "new_value", "fixed",
                "new_expression", "new_expr", "expr_new", "fixed_expression", "expected")
    old = _first(params, old_keys)
    new = _first(params, new_keys)
    if not (old and new):
        return _gen_insert_missing_assign(buggy, intent)
    old_s, new_s = str(old).strip(), str(new).strip()
    anchors = _condition_anchor_positions(buggy, params)
    if "<=" in old_s:
        # Full assignment form: 'state <= S_IDLE;' or 'count <= count + 1;'
        pat = _norm_assign(old_s)
        if pat:
            m = _nearest_anchor(list(pat.finditer(buggy)), anchors)
        else:
            m = None
            idx = buggy.find(old_s)
            if idx >= 0:
                end = buggy.find(";", idx)
                m = _pos_match(idx, end + 1 if end >= 0 else idx + len(old_s))
        if m:
            corr_full = new_s if "<=" in new_s else old_s.split("<=")[0].rstrip() + " <= " + new_s + ";"
            return buggy[:m.start()] + corr_full + buggy[m.end():]
    else:
        # Bare state name / value: only rewrite state <= old; (never localparam).
        pat = re.compile(r"state\s*<=\s*%s\s*;" % re.escape(old_s))
        m = _nearest_anchor(list(pat.finditer(buggy)), anchors)
        if m:
            return buggy[:m.start()] + "state    <= " + new_s + ";" + buggy[m.end():]
        # Non-state signal provided explicitly (e.g. signal=count, old_value=...).
        sig = params.get("signal")
        if sig and str(sig).strip() not in ("", "state"):
            sig_s = str(sig).strip()
            pat2 = re.compile(r"\b%s\s*<=\s*%s\s*;" % (re.escape(sig_s), re.escape(old_s)))
            m2 = _nearest_anchor(list(pat2.finditer(buggy)), anchors)
            if m2:
                corr_full = new_s if "<=" in new_s else "%s <= %s;" % (sig_s, new_s)
                return buggy[:m2.start()] + corr_full + buggy[m2.end():]
            # 组合赋值形式：assign <sig> = (<expr>); ——纯字符串替换（s49 half_full）
            # 直接在原始 buggy 中定位 "assign <sig> = ("，再对表达式做宽松空白正则替换；
            # LLM 意图可能缺 signal 字段，此时扫描所有 assign 行按表达式匹配
            def _fold(s):
                return " ".join(s.split())
            folded_old = _fold(old_s)
            folded_new = _fold(new_s)
            # 宽松空白模式：把 folded_old 中每个空白块替换为 \s*（生成模式串，无转义问题）
            def _loose(expr):
                return "".join((BS + "s*" if ch.isspace() else re.escape(ch)) for ch in expr)
            loose_old = _loose(folded_old)
            sigs = [sig_s] if sig_s else []
            if not sigs:
                # 无 signal：扫描所有 assign 行，按表达式匹配
                for line in buggy.splitlines():
                    m = re.match(r"assign\s+(\w+)\s*=", line)
                    if m:
                        sigs.append(m.group(1))
            for cand in sigs:
                idx = buggy.find("assign " + cand + " = (")
                if idx >= 0:
                    end = buggy.find(");", idx)
                    if end >= 0:
                        expr_raw = buggy[idx:end + 2]
                        new_expr_raw = re.sub(loose_old, folded_new, expr_raw, count=1)
                        if new_expr_raw != expr_raw:
                            return buggy[:idx] + new_expr_raw + buggy[end + 2:]
                idx2 = buggy.find("assign " + cand + " = ")
                if idx2 >= 0:
                    end2 = buggy.find(";", idx2)
                    if end2 >= 0:
                        expr_raw2 = buggy[idx2:end2 + 1]
                        new_expr_raw2 = re.sub(loose_old, folded_new, expr_raw2, count=1)
                        if new_expr_raw2 != expr_raw2:
                            return buggy[:idx2] + new_expr_raw2 + buggy[end2 + 1:]
    return None


def _pos_match(start, end):
    # Minimal stand-in for a regex match when only a plain string index is known.
    class _PM:
        pass
    pm = _PM()
    pm.start = lambda: start
    pm.end = lambda: end
    return pm



def assemble(buggy, intent, module):
    action = intent.get("action")
    if action == "split_state":
        if module == "uart_rx":
            return _gen_rx_start_confirm_restore(buggy)
        if module == "axi_lite_slave":
            p = _gen_bvalid_hold_restore(buggy)
            if p:
                return p
        return _gen_split_state(buggy, intent)
    if action == "insert_wait":
        return _gen_insert_wait(buggy, intent)
    if action == "guard_boundary":
        if module == "fifo_sync":
            p = _gen_half_full_restore(buggy)
            if p:
                return p
        p = _gen_guard_boundary(buggy, intent, module)
        if p:
            return p
        # guard_boundary 兜底：恢复缺失赋值（如 s07 S_IDLE 的 step_cnt 清零，
        # LLM 用 guard_boundary 表达"恢复被删的保护分支"）
        return _gen_insert_missing_assign(buggy, intent)
    if action == "edit_assign":
        p = _gen_assign_expr_restore(buggy, intent)
        if p:
            return p
        return _gen_edit_assign(buggy, intent)
    return None


def _find_sample_dir(sid):
    for base in (SAMPLES_STRUCT, SAMPLES_BUGS, SAMPLES_DEEP):
        p = os.path.join(base, sid)
        if os.path.isdir(p):
            return p
    return None


def run_one(sample_id, llm, mock, timeout, evidence="BH"):
    sample_dir = _find_sample_dir(sample_id)
    out = {"sample": sample_id, "ok": False, "error": "", "intent": None,
           "patched": False, "verdict": None, "cost": 0.0, "tokens": 0}
    if sample_dir is None:
        out["error"] = "no sample dir"
        return out
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    module = meta.get("module")
    cex = ""
    cxp = os.path.join(sample_dir, "cex.log")
    if os.path.isfile(cxp):
        cex = open(cxp, encoding="utf-8", errors="replace").read()
    prompt = build_intent_prompt(sample_dir, cex, evidence_setting=evidence)
    try:
        res = llm.chat(messages=prompt["messages"], temperature=0.2)
    except Exception as e:
        out["error"] = "llm fail: %s" % repr(e)[:120]
        return out
    out["cost"] = res.get("cost", 0.0)
    out["tokens"] = (res.get("input_tokens", 0) or 0) + (res.get("output_tokens", 0) or 0)
    content = res.get("content", "") or ""
    os.makedirs(os.path.join(REPO_ROOT, "experiments", "runs", ".patch_asm"), exist_ok=True)
    with open(os.path.join(REPO_ROOT, "experiments", "runs", ".patch_asm", sample_id + "_llm.txt"), "w", encoding="utf-8") as f:
        f.write(content)
    out["llm_content"] = content[:500]
    intent = parse_intent(content)
    out["intent"] = intent
    if not intent:
        out["error"] = "intent parse fail"
        return out
    buggy = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    patched = assemble(buggy, intent, module)
    if patched is None or patched == buggy:
        out["error"] = "assemble fail (no change)"
        return out
    out["patched"] = True
    # 写临时样本目录并四通过验证
    work = os.path.join(TMP_ROOT, sample_id)
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
        f.write(patched)
    for fn in ("tb_weak.sv", "verify.sby", "verify_golden.sby", "uart_tx.sv"):
        sp = os.path.join(sample_dir, fn)
        if os.path.isfile(sp):
            shutil.copy(sp, os.path.join(work, fn))
    tb_src = open(os.path.join(work, "tb_weak.sv"), encoding="utf-8").read()
    m = re.search(r"module\s+(tb_\w+)", tb_src)
    tb_top = m.group(1) if m else None
    ev = evaluator.evaluate(work, {"run_formal": True, "formal_timeout": timeout, "tb_top": tb_top})
    out["verdict"] = ev["verdict"]
    out["formal"] = ev["formal"].get("result")
    out["sim"] = ev["sim"].get("ok")
    out["compile"] = ev["compile"].get("ok")
    out["ok"] = ev["verdict"] == "PASS"
    return out


def run_e2e(sample_id, llm, mock, timeout, evidence="BH", max_rounds=3,
            temps=(0.2, 0.5, 0.8)):
    """2b end-to-end loop: intent (BH evidence) -> PatchAssembler -> 4-pass verify;
    on failure, cex_diff diagnosis feeds next round; 3-temperature multi-candidate per round."""
    sample_dir = _find_sample_dir(sample_id)
    NL = chr(10)
    out = {"sample": sample_id, "ok": False, "rounds": 0, "attempts": 0,
           "cost": 0.0, "tokens": 0, "rounds_detail": [], "errors": [],
           "verdict": None, "patched": False}
    if sample_dir is None:
        out["errors"].append("no sample dir")
        return out
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    module = meta.get("module")
    buggy = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    cex = ""
    cxp = os.path.join(sample_dir, "cex.log")
    if os.path.isfile(cxp):
        cex = open(cxp, encoding="utf-8", errors="replace").read()
    history = []
    for rnd in range(1, max_rounds + 1):
        out["rounds"] = rnd
        round_rec = {"round": rnd, "candidates": [], "ok": False, "diag": ""}
        any_patch = False
        for temp in temps:
            out["attempts"] += 1
            rec = {"temp": temp, "ok": False, "intent": None, "error": "",
                   "cost": 0.0, "tokens": 0}
            prompt = build_intent_prompt(sample_dir, cex, evidence_setting=evidence)
            if history:
                hist_lines = ["【上次修复历史（反馈循环）】"]
                for h in history:
                    line = "- 第 %d 轮 %s：%s" % (h["round"], h.get("temp"), h.get("failure", ""))
                    if h.get("diag"):
                        line += "  诊断：" + h["diag"]
                    hist_lines.append(line)
                hist_lines.append("要求：先分析上次为何失败，给出不同的修复意图，不要重复该模式。")
                prompt["messages"][1]["content"] += NL + NL.join(hist_lines)
            prompt["messages"][1]["content"] += NL + "【多候选】temperature=%.1f 独立生成意图，请勿重复其他候选方案。" % temp
            try:
                res = llm.chat(messages=prompt["messages"], temperature=temp)
            except Exception as e:
                rec["error"] = "llm fail: %s" % repr(e)[:100]
                round_rec["candidates"].append(rec)
                continue
            rec["cost"] = res.get("cost", 0.0)
            rec["tokens"] = (res.get("input_tokens", 0) or 0) + (res.get("output_tokens", 0) or 0)
            out["cost"] += rec["cost"]
            out["tokens"] += rec["tokens"]
            content = res.get("content", "") or ""
            intent = parse_intent(content)
            rec["intent"] = intent
            if not intent:
                rec["error"] = "intent parse fail"
                round_rec["candidates"].append(rec)
                continue
            patched = assemble(buggy, intent, module)
            if patched is None or patched == buggy:
                rec["error"] = "assemble fail (no change)"
                round_rec["candidates"].append(rec)
                continue
            any_patch = True
            import shutil
            work = os.path.join(TMP_ROOT, sample_id + "_e2e")
            shutil.rmtree(work, ignore_errors=True)
            os.makedirs(work, exist_ok=True)
            with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
                f.write(patched)
            for fname in ("tb_weak.sv", "verify.sby", "verify_golden.sby", "uart_tx.sv"):
                sp = os.path.join(sample_dir, fname)
                if os.path.isfile(sp):
                    shutil.copy(sp, os.path.join(work, fname))
            tb_src = open(os.path.join(work, "tb_weak.sv"), encoding="utf-8").read()
            m = re.search(r"module\s+(tb_\w+)", tb_src)
            tb_top = m.group(1) if m else None
            ev = evaluator.evaluate(work, {"run_formal": True, "formal_timeout": timeout,
                                           "tb_top": tb_top, "keep_tmp": True})
            rec["verdict"] = ev["verdict"]
            rec["formal"] = ev["formal"].get("result")
            rec["sim"] = ev["sim"].get("ok")
            rec["compile"] = ev["compile"].get("ok")
            rec["ok"] = ev["verdict"] == "PASS"
            round_rec["candidates"].append(rec)
            if rec["ok"]:
                out["ok"] = True
                out["verdict"] = "PASS"
                out["patched"] = True
                out["rounds_detail"].append(round_rec)
                return out
        if any_patch:
            try:
                tmp = ev.get("tmpdir")
                if tmp:
                    new_vcd = os.path.join(tmp, "sby_out", "engine_0", "trace.vcd")
                    new_log = os.path.join(tmp, "sby_out", "engine_0", "logfile.txt")
                    if os.path.isfile(new_vcd):
                        import cex_diff
                        clk = cex_diff.MODULE_CLK.get(module, "clk")
                        old_fail, old_assert = cex_diff.extract_fail_step(cxp)
                        new_fail, _ = cex_diff.extract_fail_step(new_log)
                        r = cex_diff.analyze(new_vcd, new_vcd, clk, old_fail, new_fail, module=module)
                        round_rec["diag"] = cex_diff.diagnosis_text(sample_id, r, old_assert)
            except Exception as e:
                round_rec["diag"] = "（差分诊断失败：%s）" % repr(e)[:80]
        for cand in round_rec["candidates"]:
            if cand.get("error"):
                history.append({"round": rnd, "temp": cand.get("temp"),
                                "failure": cand["error"][:200],
                                "diag": round_rec.get("diag", "")})
        out["rounds_detail"].append(round_rec)
        if not any_patch:
            history.append({"round": rnd, "temp": "all", "failure": "所有候选意图均未组装出有效补丁",
                            "diag": round_rec.get("diag", "")})
    return out

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="s43")
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--evidence", default="BH", choices=["B", "BT", "BH"])
    ap.add_argument("--e2e", action="store_true", help="2b end-to-end loop (multi-round feedback + multi-candidate)")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    llm = LLMClient(provider=args.provider, mock=args.mock)
    samples = [s.strip() for s in args.samples.split(",") if s.strip()]
    results = []
    for sid in samples:
        if args.e2e:
            r = run_e2e(sid, llm, args.mock, args.timeout, evidence=args.evidence,
                        max_rounds=args.max_rounds)
        else:
            r = run_one(sid, llm, args.mock, args.timeout, evidence=args.evidence)
        results.append(r)
        if args.e2e:
            print("[%s] e2e ok=%s rounds=%d attempts=%d verdict=%s cost=%.4f" % (
                sid, r["ok"], r.get("rounds", 0), r.get("attempts", 0), r.get("verdict"), r.get("cost", 0.0)), flush=True)
        else:
            print("[%s] ok=%s verdict=%s formal=%s sim=%s intent=%s err=%s" % (
                sid, r["ok"], r["verdict"], r.get("formal"), r.get("sim"),
                (r.get("intent") or {}).get("action") if r.get("intent") else None,
                (r.get("error") or "")[:90]), flush=True)
    summary = {"total": len(results), "ok": sum(1 for r in results if r["ok"]),
               "patched": sum(1 for r in results if r["patched"]),
               "rounds": sum(r.get("rounds", 0) for r in results),
               "attempts": sum(r.get("attempts", 0) for r in results),
               "cost": round(sum(r["cost"] for r in results), 4)}
    out_path = args.out or os.path.join(REPO_ROOT, "experiments", "runs", "patch_assembler_%s.json" % "_".join(samples))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)
    print("== SUMMARY: %s ==" % json.dumps(summary, ensure_ascii=False))
    print("[done] -> %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())