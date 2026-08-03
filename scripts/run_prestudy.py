#!/usr/bin/env python3
# PreCex - scripts/run_prestudy.py M0.5 预研评测一键化
# 作者：Toylog | 版本：v0.1 | 功能概述：3 样本 × A/B/C × 真实 MiniMax M3 LLM 定位+修复评测：
#   - 组装 prompt（prompt_templates，仅证据段替换）
#   - 真实 LLM 输出定位（line/signals/reason）与 unified diff
#   - 应用 diff → evaluator 三通过判定（compile/sim/formal）
#   - 指标：定位 Top-1（行==meta.inject_line）、修复三通过率、token/费用、轮数
#   - 输出 experiments/runs/prestudy_results.json + .csv（不入库）
# 用法：
#   python3 scripts/run_prestudy.py [--samples s01,s02,s03] [--settings A,B,C]
#            [--mock] [--retries 2] [--out experiments/runs/prestudy_results.json]

import csv
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from llm_client import LLMClient
from prompt_templates import SYSTEM_PROMPT, build_prompt, build_evidence_text
import evaluator

SAMPLES_DIR = os.path.join(REPO_ROOT, "samples", "prestudy")
DEFAULT_OUT = os.path.join(REPO_ROOT, "experiments", "runs", "prestudy_results.json")


def parse_llm_output(content):
    """解析 LLM 输出：###LOCATE###（line/signals/reason）与 ###DIFF###（unified diff）。"""
    # 剥离 MiniMax M3 原生 thinking 块（<think>...</think>），避免污染 diff 解析
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S)
    content = re.sub(r"<thought>.*?</thought>", "", content, flags=re.S)
    loc = {"line": None, "signals": "", "reason": ""}
    diff_text = None
    m = re.search(r"###LOCATE###\s*(.*?)(?:###DIFF###|$)", content, re.S)
    if m:
        block = m.group(1)
        ml = re.search(r"line\s*[:：]\s*(\d+)", block)
        if ml:
            loc["line"] = int(ml.group(1))
        ms = re.search(r"signals\s*[:：]\s*(.+)", block)
        if ms:
            loc["signals"] = ms.group(1).strip()
        mr = re.search(r"reason\s*[:：]\s*(.+)", block)
        if mr:
            loc["reason"] = mr.group(1).strip()
    m = re.search(r"###DIFF###\s*(.*?)$", content, re.S)
    if m:
        diff_text = m.group(1).strip()
    return loc, diff_text


def apply_unified_diff(original, diff_text):
    """把 unified diff 应用到原文，返回 (成功?, 新文本, 错误信息)。

    支持单 hunk/多 hunk：逐行操作（- 删除 / + 插入 / 上下文 对齐），
    从后往前应用 hunk 避免行号偏移；行号仅作提示，实际按内容匹配。
    """
    if not diff_text:
        return False, None, "no diff"
    # 行尾归一化：原始文件可能 CRLF，LLM 输出 diff 通常 LF，避免逐行匹配失败
    original = original.replace("\r\n", "\n").replace("\r", "\n")
    diff_text = diff_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = original.splitlines(keepends=True)
    # 提取 hunk：@@ -a,b +c,d @@
    hunks = []
    cur = None
    for ln in diff_text.splitlines(keepends=True):
        if re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", ln):
            cur = {"old_start": int(re.match(r"^@@\s+-(\d+)", ln).group(1)), "ops": []}
            hunks.append(cur)
        elif cur is not None:
            if ln.startswith("-") and not ln.startswith("---"):
                cur["ops"].append(("-", ln[1:]))
            elif ln.startswith("+"):
                cur["ops"].append(("+", ln[1:]))
            elif ln.startswith(" "):
                cur["ops"].append((" ", ln[1:]))
            # 其他行（think 残留等）：跳过，不当作上下文
    if not hunks:
        return False, None, "no @@ hunk in diff"
    # 从后往前应用 hunk 避免行号偏移
    for h in reversed(hunks):
        old_seq = [op[1] for op in h["ops"] if op[0] in ("-", " ")]
        new_seq = [op[1] for op in h["ops"] if op[0] in ("+", " ")]
        if not old_seq:
            continue
        # 行尾归一化比较（diff 最后一行可能因 strip 丢失换行符）
        def _norm(s):
            return s.rstrip("\r\n")
        old_norm = [_norm(x) for x in old_seq]
        # 在文件中定位 old_seq（优先 h.old_start-1 附近，失败则全文件搜）
        start = min(max(0, h["old_start"] - 1), max(0, len(lines) - len(old_seq)))
        idx = None
        for i in range(max(0, start - 10), min(len(lines) - len(old_seq) + 1, start + len(old_seq) + 10)):
            if [_norm(x) for x in lines[i:i + len(old_seq)]] == old_norm:
                idx = i
                break
        if idx is None:
            # 回退：全文件模糊搜索
            for i in range(len(lines) - len(old_seq) + 1):
                if [_norm(x) for x in lines[i:i + len(old_seq)]] == old_norm:
                    idx = i
                    break
        if idx is None:
            return False, None, "cannot locate hunk @%d (first old line %r)" % (
                h["old_start"], (old_seq[0] if old_seq else "?").rstrip("\n"))
        # 替换行：保留原文件行尾风格（CRLF/LF），diff 缺失行尾时补回
        eol = "\n" if not lines or not lines[0].endswith("\r\n") else "\r\n"
        patched_seq = []
        for ln in new_seq:
            if not ln.endswith(("\n", "\r")):
                ln += eol
            elif eol == "\r\n" and ln.endswith("\n") and not ln.endswith("\r\n"):
                ln = ln[:-1] + "\r\n"
            patched_seq.append(ln)
        lines[idx:idx + len(old_seq)] = patched_seq
    return True, "".join(lines), None


def run_one(sample_id, setting, llm, out_dir, mock=False, retries=2, verbose=False):
    """单个 (sample, setting) 评测：LLM 定位+修复 → 三通过 → 指标。返回结果 dict。"""
    sample_dir = os.path.join(SAMPLES_DIR, sample_id)
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    design = open(os.path.join(sample_dir, "buggy.sv"), encoding="utf-8").read()
    assertions = open(os.path.join(sample_dir, "assertions.sv"), encoding="utf-8").read()
    ev_text = build_evidence_text(setting, sample_dir)
    prompt = build_prompt(setting, design, assertions, ev_text, meta)

    result = {
        "sample": sample_id, "setting": setting, "mock": mock,
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
                tag="prestudy:%s:%s" % (sample_id, setting),
            )
        except Exception as e:
            result["errors"].append("attempt %d: llm call failed: %s" % (attempt, e))
            continue
        result["input_tokens"] += res["input_tokens"]
        result["output_tokens"] += res["output_tokens"]
        result["cost"] += res["cost"]
        content = res["content"]
        result["llm_raw"] = content
        with open(os.path.join(llm_out_dir, "%s_%s_a%d.txt" % (sample_id, setting, attempt)),
                  "w", encoding="utf-8") as f:
            f.write(content)
        loc, diff_text = parse_llm_output(content)
        result["loc_line"] = loc["line"]
        result["signals"] = loc["signals"]
        result["reason"] = loc["reason"]
        result["diff_text"] = (diff_text or "")[:4000]
        result["loc_top1"] = (loc["line"] == meta.get("inject_line"))
        if not diff_text:
            result["errors"].append("attempt %d: no diff" % attempt)
            continue
        # 应用 diff 到临时目录
        ok, patched, err = apply_unified_diff(design, diff_text)
        if not ok:
            result["errors"].append("attempt %d: diff apply failed: %s" % (attempt, err))
            continue
        work = os.path.join(out_dir, "%s_%s_a%d" % (sample_id, setting, attempt))
        os.makedirs(work, exist_ok=True)
        with open(os.path.join(work, "buggy.sv"), "w", encoding="utf-8") as f:
            f.write(patched)
        for fname in ("assertions.sv", "tb_weak.sv"):
            src = os.path.join(sample_dir, fname)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(work, fname))
        # 修复验证优先用 prove 模式（k-induction，快且充分），无则回退 bmc
        sby_src = os.path.join(sample_dir, "verify_repair.sby")
        if not os.path.isfile(sby_src):
            sby_src = os.path.join(sample_dir, "verify.sby")
        if os.path.isfile(sby_src):
            shutil.copy(sby_src, os.path.join(work, "verify.sby"))
        # 从 tb 文件提取模块名（文件名可能 ≠ 模块名，evaluator 默认用文件名当顶层）
        tb_top = None
        tb_path = os.path.join(work, "tb_weak.sv")
        if os.path.isfile(tb_path):
            with open(tb_path, "r", encoding="utf-8", errors="replace") as f:
                m = re.search(r"module\s+(\w+)", f.read())
                if m:
                    tb_top = m.group(1)
        ev = evaluator.evaluate(work, {"run_formal": True, "verbose": False,
                                       "tb_top": tb_top})
        result["verdict"] = ev["verdict"]
        if ev["verdict"] == "PASS":
            result["repair_pass"] = True
            break
        result["errors"].append("attempt %d: verdict=%s formal=%s" % (
            attempt, ev["verdict"], ev["formal"].get("result")))
    return result


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    samples = ["s01", "s02", "s03"]
    settings = ["A", "B", "C"]
    mock = False
    retries = 2
    out_path = DEFAULT_OUT
    verbose = False
    if "--samples" in argv:
        samples = argv[argv.index("--samples") + 1].split(",")
    if "--settings" in argv:
        settings = argv[argv.index("--settings") + 1].split(",")
    if "--mock" in argv:
        mock = True
    if "--retries" in argv:
        retries = int(argv[argv.index("--retries") + 1])
    if "--out" in argv:
        out_path = argv[argv.index("--out") + 1]
    if "--verbose" in argv:
        verbose = True

    llm = LLMClient(mock=mock, temperature=0.2)
    out_dir = tempfile.mkdtemp(prefix="prestudy_work_")
    results = []
    for s in samples:
        for st in settings:
            print("[run] sample=%s setting=%s mock=%s" % (s, st, mock), flush=True)
            r = run_one(s, st, llm, out_dir, mock=mock, retries=retries, verbose=verbose)
            print("[result] %s/%s loc_top1=%s repair=%s verdict=%s cost=%.4f tokens=%d" % (
                s, st, r["loc_top1"], r["repair_pass"], r["verdict"], r["cost"],
                r["input_tokens"] + r["output_tokens"]), flush=True)
            results.append(r)
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, ensure_ascii=False, indent=2)
    csv_path = os.path.splitext(out_path)[0] + ".csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "sample", "setting", "loc_top1", "loc_line", "inject_line", "repair_pass",
            "verdict", "attempts", "input_tokens", "output_tokens", "cost", "reason"])
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    print("[done] results -> %s" % out_path)
    print("[csv]   -> %s" % csv_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
