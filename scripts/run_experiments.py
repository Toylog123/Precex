#!/usr/bin/env python3
# PreCex - scripts/run_experiments.py 主实验批量评测（M1 数据集 s04-s37 + 深时序子集 s38+）
# 作者：Toylog | 版本：v0.2 | 功能概述：对 samples/bugs 与 samples/deep 下 L3 样本批量跑 A/B/C × 3 随机种子评测：
#   - 证据链：A=cex 原始日志/VCD，B=evidence.json（结构化），C=semantics.json（反例语义化）
#   - LLM 定位+修复 → evaluator 三通过判定（compile/sim/formal，修复后期望 PASS）
#   - 指标：loc_top1 / repair_pass / verdict / tokens / cost / attempts
#   - 输出 experiments/runs/experiments_results.json + .csv（不入库），token 记账由 llm_client 强制
# 用法：
#   python3 scripts/run_experiments.py [--samples s04-s37] [--settings A,B,C,D]  # D=FVDebug 式因果图
#            [--provider minimax|deepseek|openai|gemini|anthropic]  # 默认 minimax；DeepSeek 跨模型重跑用
#            [--samples-dir bugs|l2|deep]  # 默认 bugs；L2 假阳性率实验用 l2，深时序子集用 deep
#            [--seeds 0,1,2] [--retries 2] [--mock] [--out ...]
"""
PreCex 主实验批量评测。
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from llm_client import LLMClient  # noqa: E402
from prompt_templates import SYSTEM_PROMPT, build_prompt, sanitize_design_text  # noqa: E402
from run_prestudy import parse_llm_output, apply_unified_diff  # noqa: E402
import cex_diff  # noqa: E402
import evaluator  # noqa: E402

SAMPLES_BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
SAMPLES_L2 = os.path.join(REPO_ROOT, "samples", "l2")
SAMPLES_DEEP = os.path.join(REPO_ROOT, "samples", "deep")
SAMPLES_DIRS = {"bugs": SAMPLES_BUGS, "l2": SAMPLES_L2, "deep": SAMPLES_DEEP}
DEFAULT_OUT = os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results.json")
BUGGY_HEADER_OFFSET = 4
_SLIM_C = True  # C 证据激进出采样压缩开关（--no-slim-c 关闭，走完整原文）  # buggy.v 头注释偏移（与 bug_injector 一致）：缺陷行号 = inject_line + 4





def _cex_diff_diagnosis(sample_dir, ev, meta):
    """WP6：用新反例（evaluator 保留的 sby 输出）与旧反例差分，返回诊断文本。"""
    tmp = ev.get("tmpdir")
    if not tmp:
        return ""
    new_vcd = os.path.join(tmp, "sby_out", "engine_0", "trace.vcd")
    new_log = os.path.join(tmp, "sby_out", "engine_0", "logfile.txt")
    old_vcd = os.path.join(sample_dir, "cex.vcd")
    old_log = os.path.join(sample_dir, "cex.log")
    if not os.path.isfile(new_vcd) or not os.path.isfile(old_vcd):
        return ""
    clk = cex_diff.MODULE_CLK.get(meta.get("module"), "clk")
    try:
        old_fail, old_assert = cex_diff.extract_fail_step(old_log)
        new_fail, _ = cex_diff.extract_fail_step(new_log)
        r = cex_diff.analyze(old_vcd, new_vcd, clk, old_fail, new_fail, module=meta.get("module"))
        return cex_diff.diagnosis_text(meta.get("sample_id", ""), r, old_assert)
    except Exception as e:
        return "（差分诊断失败：%s）" % repr(e)[:80]

def expand_samples(spec):
    ids = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^s(\d+)-s(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            ids += ["s%02d" % i for i in range(lo, hi + 1)]
        else:
            ids.append(part)
    seen = set()
    out = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extract_inline_assertions(design):
    """提取内联断言段（buggy.v 中『内联强断言』标记之后、endmodule 前）。"""
    m = re.search(r"//.*?内联强断言.*?\n(.*?)\n\s*endmodule\b", design, re.S)
    if m:
        return m.group(1).strip()
    # 回退：提取所有 assert 行（含上下文），供 LLM 了解断言约束
    lines = design.splitlines()
    out = []
    for i, ln in enumerate(lines, 1):
        if "assert" in ln and "//" not in ln.split("assert")[0]:
            out.append("%4d: %s" % (i, ln))
    return "\n".join(out) if out else "（未提取到独立断言段，断言已内联于设计）"


def run_one(sample_dir, sample_id, setting, seed, llm, out_dir, mock=False, retries=2,
            verify_cfg=None, feedback="v1"):
    """单个 (sample, setting, seed) 评测。返回结果 dict。"""
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    design = sanitize_design_text(open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read())
    assertions = _extract_inline_assertions(design)
    ev_text = _build_evidence_text(setting, sample_dir)
    prompt = build_prompt(setting, design, assertions, ev_text, meta)
    prompt += "\n【重复试验】seed=%d（独立抽样标识，请独立判断）\n" % seed
    # 反馈循环：每轮失败的 diff/原因进入下一轮 prompt（history 注入），
    # 避免"开环重试"（重复相同错误补丁）。首次 prompt 与旧版一致。
    retry_history = []

    def _record_retry(failure_desc, diff_snippet=None):
        """把一次失败尝试记入历史并重建下一轮 prompt（反馈循环）。"""
        nonlocal prompt
        retry_history.append({
            "attempt": attempt,
            "diff": (diff_snippet or "")[:1500],
            "failure": failure_desc,
        })
        prompt = build_prompt(setting, design, assertions, ev_text, meta,
                              history=retry_history)
        prompt += "\n【重复试验】seed=%d attempt=%d（反馈循环第 %d 次，请避免上次失败模式）\n" % (
            seed, attempt + 1, len(retry_history))

    result = {
        "sample": sample_id, "setting": setting, "seed": seed, "mock": mock,
        "inject_line": meta.get("inject_line"), "error_type": meta.get("error_type"),
        "loc_top1": False, "loc_line": None, "reason": "", "signals": "",
        "repair_pass": False, "verdict": None, "attempts": 0,
        "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
        "diff_text": "", "errors": [], "llm_raw": "",
    }
    llm_out_dir = os.path.join(os.path.dirname(DEFAULT_OUT), "llm_outputs")
    os.makedirs(llm_out_dir, exist_ok=True)
    for attempt in range(retries + 1):
        result["attempts"] = attempt + 1
        try:
            res = llm.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tag="exp:%s:%s:seed%d" % (sample_id, setting, seed),
                max_tokens=65536,
            )
        except Exception as e:
            result["errors"].append("attempt %d: llm call failed: %s" % (attempt, e))
            continue
        result["input_tokens"] += res["input_tokens"]
        result["output_tokens"] += res["output_tokens"]
        result["cost"] += res["cost"]
        content = res["content"]
        result["llm_raw"] = content
        with open(os.path.join(llm_out_dir, "%s_%s_seed%d_a%d.txt" % (sample_id, setting, seed, attempt)),
                  "w", encoding="utf-8") as f:
            f.write(content)
        loc, diff_text = parse_llm_output(content)
        result["loc_line"] = loc["line"]
        result["signals"] = loc["signals"]
        result["reason"] = loc["reason"]
        result["diff_text"] = (diff_text or "")[:4000]
        # loc_top1 判据：LLM 看到的是带头注释的 buggy.v，行号须对 buggy_inject_line；
        # 旧样本无该字段时回退 inject_line（golden 行号，仅近似）
        golden_line = meta.get("inject_line")
        buggy_line = meta.get("buggy_inject_line", (golden_line + BUGGY_HEADER_OFFSET) if golden_line else None)
        result["loc_top1"] = (loc["line"] == buggy_line)
        if not diff_text:
            result["errors"].append("attempt %d: no diff" % attempt)
            _record_retry("attempt %d: 未生成 diff（输出格式不符合 ###DIFF### 约定）" % attempt)
            continue
        ok, patched, err = apply_unified_diff(design, diff_text)
        if not ok:
            result["errors"].append("attempt %d: diff apply failed: %s" % (attempt, err))
            _record_retry("attempt %d: diff 无法应用：%s" % (attempt, err), diff_text)
            continue
        work = os.path.join(out_dir, "%s_%s_seed%d_a%d" % (sample_id, setting, seed, attempt))
        os.makedirs(work, exist_ok=True)
        with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
            f.write(patched)
        for fname in ("tb_weak.sv", "verify.sby"):
            src = os.path.join(sample_dir, fname)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(work, fname))
        # 修复验证主判据 = bmc（verify.sby），与 golden 对照 verify_golden.sby 一致；
        # prove/k-induction（verify_repair.sby）仅作附加充分性参考，不作为失败判据。
        # 2026-08-04 实测：prove 对 axi_lite_slave 等门控时序断言不收敛（golden 本身也 UNKNOWN），
        # 主实验 75 个正确修复被判 FAIL（96.2% 假阴性）。保留 verify.sby 避免误杀。
        rp_src = os.path.join(sample_dir, "verify_repair.sby")
        if os.path.isfile(rp_src):
            shutil.copy(rp_src, os.path.join(work, "verify_repair.sby"))
        # 不再删除 verify.sby：evaluator 按字母序选中 verify.sby（bmc）作主判据
        # uart_rx 回环依赖
        if meta.get("module") == "uart_rx":
            src = os.path.join(sample_dir, "uart_tx.sv")
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(work, "uart_tx.sv"))
        tb_top = None
        tb_path = os.path.join(work, "tb_weak.sv")
        if os.path.isfile(tb_path):
            m = re.search(r"module\s+(tb_\w+)", open(tb_path, encoding="utf-8").read())
            if m:
                tb_top = m.group(1)
        _ev_cfg = {"run_formal": True, "verbose": False, "tb_top": tb_top}
        if feedback == "v2":
            _ev_cfg["keep_tmp"] = True   # 保留 sby 临时目录以提取新反例做差分诊断
        if verify_cfg:
            _ev_cfg.update(verify_cfg)
        ev = evaluator.evaluate(work, _ev_cfg)
        result["verify_mode"] = "bmc"  # 主判据 bmc；prove 参考见 verify_repair.sby
        result["verdict"] = ev["verdict"]
        result["verify_elapsed"] = {
            "compile": ev["compile"].get("elapsed"),
            "sim": ev["sim"].get("elapsed"),
            "formal": ev["formal"].get("elapsed"),
        }
        if ev["verdict"] == "PASS":
            result["repair_pass"] = True
            break
        result["errors"].append("attempt %d: verdict=%s formal=%s" % (
            attempt, ev["verdict"], ev["formal"].get("result")))
        diag = ""
        if feedback == "v2":
            diag = _cex_diff_diagnosis(sample_dir, ev, meta)
        fail_desc = ("verdict=%s formal=%s（修复后仍存在形式反例或验证未通过）"
                     % (ev["verdict"], ev["formal"].get("result")))
        if diag:
            fail_desc += "；【反例差分诊断】" + diag
        _record_retry(fail_desc, diff_text)
    return result


def _build_evidence_text(setting, sample_dir):
    """按设置读取证据文本（A/B/C），与 prompt_templates.build_evidence_text 同协议。"""
    def _strip_gt(raw):
        """剥离 evidence.json 中的 ground-truth 标注（inject_line/inject_desc/diff）。"""
        try:
            obj = json.loads(raw)
        except Exception:
            return raw
        if isinstance(obj, dict):
            for k in ("inject_line", "inject_desc", "diff", "buggy_inject_line"):
                obj.pop(k, None)
            return json.dumps(obj, ensure_ascii=False, indent=2)
        return raw
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
            return _strip_gt(f.read())
    if setting == "BH":
        # B 证据全文 + 握手协议分析（1d 握手专项：首轮注入，非仅重试）
        p = os.path.join(sample_dir, "evidence.json")
        if not os.path.isfile(p):
            return "\uff08evidence.json \u7f3a\u5931\uff09"
        with open(p, "r", encoding="utf-8") as f:
            body_b = _strip_gt(f.read())
        try:
            meta_p = os.path.join(sample_dir, "meta.json")
            meta = {}
            if os.path.isfile(meta_p):
                with open(meta_p, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            old_vcd = os.path.join(sample_dir, "cex.vcd")
            old_log = os.path.join(sample_dir, "cex.log")
            clk = cex_diff.MODULE_CLK.get(meta.get("module"), "clk")
            old_fail, _ = cex_diff.extract_fail_step(old_log)
            r = cex_diff.analyze(old_vcd, None, clk, old_fail, None, module=meta.get("module"))
            hs_feat = r.get("handshake_old") or {}
            viols = cex_diff.module_handshake_violations(hs_feat, meta.get("module") or "")
            note = cex_diff.HANDSHAKE_NOTE.get(meta.get("module") or "")
            rows = []
            for pk, f in sorted(hs_feat.items()):
                rows.append("%s: %s" % (pk, json.dumps(f, ensure_ascii=False)))
            hs_text = chr(10).join(rows)
            if viols:
                hs_text += chr(10) + "\u534f\u8bae\u8fdd\u89c4\uff1a" + "\uff1b".join(viols)
            if note:
                hs_text += chr(10) + "\u534f\u8bae\u63d0\u793a\uff1a" + note
        except Exception as e:
            hs_text = "\uff08\u63e1\u624b\u5206\u6790\u5931\u8d25\uff1a%s\uff09" % repr(e)[:80]
        return body_b + chr(10) + chr(10) + "\u3010\u63e1\u624b\u534f\u8bae\u5206\u6790\uff08TraceAnalyzer \u52a8\u6001\u5207\u7247 + \u534f\u8bae\u68c0\u6d4b\uff09\u3011" + chr(10) + hs_text
    if setting == "BT":
        # B 证据全文 + TraceAnalyzer 动态切片摘要（T 增量；配对消融 B vs B+T）
        p = os.path.join(sample_dir, "evidence.json")
        if not os.path.isfile(p):
            return "（evidence.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            body_b = _strip_gt(f.read())
        ta_path = os.path.join(sample_dir, "trace_analysis_replay.json")
        if not os.path.isfile(ta_path):
            ta_path = os.path.join(sample_dir, "trace_analysis.json")
        ta_text = ""
        if os.path.isfile(ta_path):
            try:
                with open(ta_path, "r", encoding="utf-8") as f:
                    ta = json.load(f)
                an = ta.get("analysis") or {}
                rows = []
                if "first_anomaly_cycle" in an:
                    rows.append("first_anomaly_cycle=%s" % an["first_anomaly_cycle"])
                if "cycles_compared" in an:
                    rows.append("cycles_compared=%s" % an["cycles_compared"])
                ks = (an.get("key_signal_diffs") or [])[:20]
                rows.append("key_signal_diffs=%s" % json.dumps(ks, ensure_ascii=False))
                ss = (an.get("stuck_signals") or [])[:10]
                rows.append("stuck_signals=%s" % json.dumps(ss, ensure_ascii=False))
                ta_text = " | ".join(rows)
            except Exception as e:
                ta_text = "（trace_analysis 解析失败: %s）" % e
        return body_b + chr(10) + chr(10) + "【TraceAnalyzer 动态切片摘要】" + chr(10) + ta_text
    if setting == "C":
        p = os.path.join(sample_dir, "semantics.json")
        if not os.path.isfile(p):
            return "（semantics.json 缺失）"
        with open(p, "r", encoding="utf-8") as f:
            raw = f.read()
        if not _SLIM_C:
            return raw
        s = json.loads(raw)
        # 激进出采样压缩：关键窗口 fail_step±4 完整 + 之前每 8 拍采样 + text_summary 截 300 字，
        # 保留因果关键信号，砍掉冗余波形（实测 34 样本 2.18x 缩小、54% token 削减）
        fs = s.get("fail_step")

        def _ds(seq):
            if not seq:
                return seq
            out = []
            lo = max(0, (fs - 4) if fs is not None else 0)
            for i, item in enumerate(seq):
                cyc = item.get("cycle") if isinstance(item, dict) else i
                try:
                    cyc = int(cyc)
                except (TypeError, ValueError):
                    cyc = i
                if cyc >= lo or i % 8 == 0:
                    out.append(item)
            return out

        slim = {
            "module": s.get("module"),
            "error_type": s.get("error_type"),
            "fail_stage": s.get("fail_stage"),
            "fail_step": fs,
            "failed_line": s.get("failed_line"),
            "trigger_condition": s.get("trigger_condition"),
            "fault_cone": s.get("fault_cone"),
            "cycle_events": _ds(s.get("cycle_events") or []),
            "state_trace": _ds(s.get("state_trace") or []),
        }
        ts = (s.get("text_summary") or "").strip()
        if ts:
            slim["text_summary"] = ts[:300] + ("…" if len(ts) > 300 else "")
        return json.dumps(slim, ensure_ascii=False, indent=2)
    if setting == "D":
        # FVDebug 式因果图（确定性提取，无 LLM 生成）：失败断言 + fault_cone 根因节点 + 全周期可读 state_trace + 触发条件
        parts = []
        ev_path = os.path.join(sample_dir, "evidence.json")
        sem_path = os.path.join(sample_dir, "semantics.json")
        ev = {}
        sem = {}
        if os.path.isfile(ev_path):
            with open(ev_path, "r", encoding="utf-8") as f:
                ev = json.load(f)
        if os.path.isfile(sem_path):
            with open(sem_path, "r", encoding="utf-8") as f:
                sem = json.load(f)
        parts.append("## FVDebug 式因果图（D 设置：反例自动提取，无 LLM 生成）")
        parts.append("### 失败断言")
        parts.append("module=%s | error_type=%s | fail_stage=%s | fail_step=%s" % (
            ev.get("module"), ev.get("error_type"), ev.get("fail_stage"), ev.get("fail_step")))
        parts.append("### 根因节点（fault_cone，按影响排序）")
        cone = sem.get("fault_cone") or []
        for node in cone:
            parts.append("- %s" % (node if isinstance(node, str) else json.dumps(node, ensure_ascii=False)))
        parts.append("### 因果链状态轨迹（全周期可读信号名）")
        for row in (sem.get("state_trace") or []):
            parts.append("cyc%s: %s" % (row.get("cycle", "?"), json.dumps(row, ensure_ascii=False)))
        parts.append("### 触发条件")
        parts.append(str(sem.get("trigger_condition") or ev.get("trigger_condition") or "?"))
        return "\n".join(parts)
    raise ValueError("setting 必须是 A/B/C/BT/BH")


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    samples = ["s04-s37"]
    settings = ["A", "B", "C"]
    seeds = [0, 1, 2]
    mock = False
    retries = 2
    feedback = "v1"
    out_path = DEFAULT_OUT
    verbose = False
    check_compat = "--check-compat" in argv
    if "--samples" in argv:
        samples = argv[argv.index("--samples") + 1].split(",")
    if "--settings" in argv:
        settings = argv[argv.index("--settings") + 1].split(",")
    if "--seeds" in argv:
        seeds = [int(x) for x in argv[argv.index("--seeds") + 1].split(",")]
    tasks_arg = []
    if "--tasks" in argv:
        tasks_arg = argv[argv.index("--tasks") + 1].split(",")
    global _SLIM_C
    _SLIM_C = "--no-slim-c" not in argv

    if "--mock" in argv:
        mock = True
    if "--retries" in argv:
        retries = int(argv[argv.index("--retries") + 1])
    if "--feedback" in argv:
        feedback = argv[argv.index("--feedback") + 1]
        if feedback not in ("v1", "v2"):
            raise SystemExit("--feedback 必须是 v1|v2")
    if "--out" in argv:
        out_path = argv[argv.index("--out") + 1]
    provider = "minimax"
    if "--provider" in argv:
        provider = argv[argv.index("--provider") + 1]
    if "--verbose" in argv:
        verbose = True
    verify_cfg = {}
    if "--verify-timeout" in argv:
        verify_cfg["formal_timeout"] = float(argv[argv.index("--verify-timeout") + 1])
    if "--verify-depth" in argv:
        verify_cfg["depth_override"] = int(argv[argv.index("--verify-depth") + 1])

    sample_ids = expand_samples(",".join(samples))
    samples_dir = "bugs"
    if "--samples-dir" in argv:
        samples_dir = argv[argv.index("--samples-dir") + 1]
        if samples_dir not in SAMPLES_DIRS:
            raise SystemExit("--samples-dir 必须是 bugs|l2|deep 之一，收到 %r" % samples_dir)
    samples_base = SAMPLES_DIRS[samples_dir]

    def _resolve_sample(sid):
        """优先取 --samples-dir 目录；缺失时探测其它已知样本目录（深时序子集在 samples/deep）。"""
        if os.path.isdir(os.path.join(samples_base, sid)):
            return os.path.join(samples_base, sid)
        for d in (SAMPLES_DEEP, SAMPLES_BUGS, SAMPLES_L2):
            if d == samples_base:
                continue
            p = os.path.join(d, sid)
            if os.path.isdir(p):
                return p
        return None

    dirs = {}
    for sid in sample_ids:
        p = _resolve_sample(sid)
        if p is not None:
            if os.path.dirname(p) != samples_base:
                print("note: 样本 %s 位于 %s（--samples-dir=%s 之外，自动解析）"
                      % (sid, os.path.dirname(p), samples_dir))
            dirs[sid] = p
        else:
            print("warning: 跳过未找到样本 %s" % sid)

    task_filter = None
    if tasks_arg:
        task_filter = set()
        for t in tasks_arg:
            parts = t.strip().split("/")
            if len(parts) == 3:
                task_filter.add((parts[0], parts[1], int(parts[2])))
            else:
                raise SystemExit("--tasks needs sXX/S/seed format: %s" % t)
        keep_s = sorted({t[0] for t in task_filter})
        keep_st = sorted({t[1] for t in task_filter})
        keep_sd = sorted({t[2] for t in task_filter})
        # --tasks 只过滤不扩充 dirs：补充解析 --tasks 点名但初始 dirs 缺失的样本
        # （例如深样本 s38+ 位于 samples/deep，默认 --samples-dir bugs 解析不到）
        for sid in keep_s:
            if sid not in dirs:
                p = _resolve_sample(sid)
                if p is not None:
                    if os.path.dirname(p) != samples_base:
                        print("note: --tasks 样本 %s 位于 %s（自动解析）" % (sid, os.path.dirname(p)))
                    dirs[sid] = p
        dirs = {s: dirs[s] for s in keep_s if s in dirs}
        settings = keep_st
        seeds = keep_sd

    llm = LLMClient(mock=mock, temperature=0.2, provider=provider)
    out_dir = tempfile.mkdtemp(prefix="exp_work_")
    results = []
    total = len(dirs) * len(settings) * len(seeds)
    if total == 0:
        raise SystemExit("error: 0 任务可运行（请求样本=%s、设置=%s、seeds=%s）；"
                         "请检查 --samples/--tasks/--samples-dir（深样本用 --samples-dir deep）"
                         % (sample_ids, settings, seeds))
    if check_compat:
        # 工具链适配性预检（报错重写层）：LLM 调用前先扫不兼容 SVA/不可综合语法，
        # 避免运行中 sby/iverilog 解析失败才暴露（评审缺陷 5）。
        from check_rtl_compat import check_file
        bad = []
        for sid in sorted(dirs):
            for hit in check_file(os.path.join(dirs[sid], "buggy.v")):
                bad.append((sid,) + hit)
        if bad:
            msg = "\n".join("%s:%d: %s" % (b[0], b[2], b[4]) for b in bad)
            raise SystemExit("error: --check-compat 发现 %d 处不兼容结构：\n%s\n"
                             "请改写后再运行（见 scripts/check_rtl_compat.py 建议）" % (len(bad), msg))
        print("[compat] %d 样本工具链适配性预检通过" % len(dirs))
    idx = 0
    # 增量写入：每完成一条 append 一行到 <out>.partial.jsonl，中断不丢进度；启动时跳过已完成键（断点续跑）
    partial_path = out_path + ".partial.jsonl"
    done_keys = set()
    if os.path.isfile(partial_path):
        with open(partial_path, "r", encoding="utf-8") as pf:
            for ln in pf:
                ln = ln.strip()
                if not ln: continue
                try:
                    prev = json.loads(ln)
                    done_keys.add((prev["sample"], prev["setting"], prev["seed"]))
                    results.append(prev)
                except Exception:
                    pass
    for sid in sorted(dirs):
        for st in settings:
            for sd in seeds:
                idx += 1
                key = (sid, st, sd)
                if task_filter is not None and key not in task_filter:
                    continue
                if key in done_keys:
                    print("[skip %d/%d] %s/%s/seed%d (已存在，续跑跳过)" % (idx, total, sid, st, sd), flush=True)
                    continue
                print("[run %d/%d] sample=%s setting=%s seed=%d mock=%s" % (
                    idx, total, sid, st, sd, mock), flush=True)
                r = run_one(dirs[sid], sid, st, sd, llm, out_dir, mock=mock, retries=retries,
                            verify_cfg=verify_cfg, feedback=feedback)
                print("[result] %s/%s/seed%d loc_top1=%s repair=%s verdict=%s cost=%.4f tokens=%d" % (
                    sid, st, sd, r["loc_top1"], r["repair_pass"], r["verdict"],
                    r["cost"], r["input_tokens"] + r["output_tokens"]), flush=True)
                results.append(r)
                with open(partial_path, "a", encoding="utf-8") as pf:
                    pf.write(json.dumps(r, ensure_ascii=False) + chr(10))
    shutil.rmtree(out_dir, ignore_errors=True)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"samples": sorted(dirs), "settings": settings, "seeds": seeds,
                   "results": results}, f, ensure_ascii=False, indent=2)
    csv_path = os.path.splitext(out_path)[0] + ".csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "sample", "setting", "seed", "loc_top1", "loc_line", "inject_line",
            "repair_pass", "verdict", "attempts", "input_tokens", "output_tokens",
            "cost", "reason"])
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    _write_summary(out_path, results)
    print("[done] results -> %s" % out_path)
    print("[csv]   -> %s" % csv_path)
    return 0


def _write_summary(out_path, results):
    """按 (sample, setting) 聚合 3 种子：loc_top1 均值/修复率/verdict 分布，输出 *summary.csv。"""
    agg = {}
    for r in results:
        key = (r["sample"], r["setting"])
        agg.setdefault(key, []).append(r)
    sum_path = os.path.splitext(out_path)[0] + "_summary.csv"
    with open(sum_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["sample", "setting", "n", "loc_top1_mean", "repair_pass_mean",
                    "pass_verdict", "fail_verdict", "inconc_verdict", "avg_cost"])
        for key in sorted(agg):
            rs = agg[key]
            n = len(rs)
            w.writerow([
                key[0], key[1], n,
                "%.3f" % (sum(1 for x in rs if x["loc_top1"]) / n),
                "%.3f" % (sum(1 for x in rs if x["repair_pass"]) / n),
                sum(1 for x in rs if x["verdict"] == "PASS"),
                sum(1 for x in rs if x["verdict"] == "FAIL"),
                sum(1 for x in rs if x["verdict"] in ("INCONCLUSIVE", "BROKEN")),
                "%.4f" % (sum(x["cost"] for x in rs) / n),
            ])
    print("[summary] -> %s" % sum_path)


if __name__ == "__main__":
    sys.exit(main())
