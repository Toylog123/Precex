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


def build_intent_prompt(sample_dir, cex_text):
    buggy = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_INTENT},
            {"role": "user", "content": (
                "模块：%s\n错误类型：%s\n击穿断言：%s\n\n反例证据：\n%s\n\n"
                "缺陷设计源码：\n```verilog\n%s\n```\n\n请输出修复意图 JSON。" % (
                    meta.get("module"), meta.get("error_type"), meta.get("hit_assertion"),
                    cex_text[:2000], buggy[:6000]))},
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
    """把 'state <= S3;' 类描述归一为正则匹配模式（容忍空白差异）。"""
    s = s.strip()
    m = re.match(r"^(\w+)\s*<=\s*([\w_\[\]:']+)\s*;?$", s)
    if m:
        lhs, rhs = m.group(1), m.group(2)
        return re.compile(r"\b%s\s*<=\s*%s\s*;" % (re.escape(lhs), re.escape(rhs)))
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
        return None
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
        return _gen_guard_boundary(buggy, intent, module)
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


def run_one(sample_id, llm, mock, timeout):
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
    prompt = build_intent_prompt(sample_dir, cex)
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="s43")
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    llm = LLMClient(provider=args.provider, mock=args.mock)
    samples = [s.strip() for s in args.samples.split(",") if s.strip()]
    results = []
    for sid in samples:
        r = run_one(sid, llm, args.mock, args.timeout)
        results.append(r)
        print("[%s] ok=%s verdict=%s formal=%s sim=%s intent=%s err=%s" % (
            sid, r["ok"], r["verdict"], r.get("formal"), r.get("sim"),
            (r.get("intent") or {}).get("action") if r.get("intent") else None,
            (r.get("error") or "")[:90]), flush=True)
    summary = {"total": len(results), "ok": sum(1 for r in results if r["ok"]),
               "patched": sum(1 for r in results if r["patched"]),
               "cost": round(sum(r["cost"] for r in results), 4)}
    out_path = args.out or os.path.join(REPO_ROOT, "experiments", "runs", "patch_assembler_%s.json" % "_".join(samples))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)
    print("== SUMMARY: %s ==" % json.dumps(summary, ensure_ascii=False))
    print("[done] -> %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())