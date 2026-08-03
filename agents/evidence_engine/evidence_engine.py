#!/usr/bin/env python3
# PreCex - agents/evidence_engine/evidence_engine.py EvidenceEngine（组件1）
# 作者：Toylog | 版本：v0.1 | 功能概述：解析编译/仿真/sby 失败证据与 VCD，输出统一 JSON schema：
#   error_type / module / file / line / code_slice / signals / trigger_condition / fail_stage /
#   x_state_warn / raw_trace_ref。设置 B（结构化 JSON 证据）生成器，供 A/B/C 预研评测使用。
#   纯标准库实现，设计在 WSL Python 3.10+ 内运行。

"""EvidenceEngine：失败证据 → 统一 JSON。

用法：
    python3 evidence_engine.py <sample_dir> [--out <evidence.json>] [--verbose]

输入（样本目录约定，samples/prestudy/sNN/）：
    cex.log      sby 引擎日志（含 Assert failed ... step N 与 $assert$file:line$id）
    cex.vcd      sby 反例波形（用于 X 态统计与信号抽取）
    meta.json    样本标注（error_type / inject_line / inject_desc / module / golden_source）
    buggy.sv     缺陷设计（用于 code_slice 与信号声明解析）
"""

import json
import os
import re
import sys

# schema 版本
SCHEMA_VER = "v1.0"


def _load_text(path):
    """读取文本文件（UTF-8，容错 GBK 回退），不存在返回空串。"""
    if not path or not os.path.isfile(path):
        return ""
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def _load_json(path):
    """读取 JSON 文件，失败返回 {}。"""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def parse_sby_log(log_text):
    """解析 sby 引擎日志 → {module, failed_line, failed_assert_id, fail_step, fail_stage}。

    特征行：Assert failed in <module>: <file>:<line>... ($assert$<file>:<line>$<id>)
           BMC failed! 或 Temporal induction successful / DONE (PASS
    """
    out = {"module": None, "failed_line": None, "failed_assert_id": None,
           "fail_step": None, "fail_stage": None, "result": None}
    m = re.search(r"Assert failed in (\w+):", log_text)
    if m:
        out["module"] = m.group(1)
    m = re.search(r"(\S+\.sv|\.v):(\d+)(?:\.\d+-\d+\.\d+)? \(\$assert\$\S+?:\d+\$(\d+)\)", log_text)
    if m:
        out["failed_line"] = int(m.group(2))
        out["failed_assert_id"] = m.group(3)
    # 优先取 summary 行 "failed assertion ... at ... step N"（精确失败拍号）
    m = re.search(r"failed assertion .*?step (\d+)", log_text)
    if m:
        out["fail_step"] = int(m.group(1))
    else:
        steps = [int(x) for x in re.findall(r"Checking assertions in step (\d+)", log_text)]
        if steps:
            out["fail_step"] = max(steps)
    if "BMC failed" in log_text or "DONE (FAIL" in log_text:
        out["result"] = "fail"
    elif "successful proof by k-induction" in log_text or "Temporal induction successful" in log_text:
        out["result"] = "prove"
    elif "DONE (PASS" in log_text:
        out["result"] = "pass"
    if out["result"] == "fail":
        out["fail_stage"] = "bmc_depth_%s" % (out["fail_step"] if out["fail_step"] is not None else "?")
    elif out["result"] == "prove":
        out["fail_stage"] = "k-induction_proof"
    else:
        out["fail_stage"] = "unknown"
    return out


def parse_design_ports(design_text, module):
    """粗略解析 SystemVerilog 模块端口（ANSI 风格 input/output 行）→ {sig: dir}。

    仅覆盖样本使用的写法（input/output + wire/reg + 位宽），供 evidence 的 signals 字段使用。
    """
    ports = {}
    if not design_text:
        return ports
    # 参数名（parameter NAME = ...）不算端口，需排除
    params = set(re.findall(r"parameter\s+(\w+)", design_text))
    # 抓取 input/output 声明：行内含 input/output 与信号名（去掉位宽与逗号）
    for line in design_text.splitlines():
        s = line.strip()
        if not s:
            continue
        mdir = re.match(r"^(input|output|inout)\b", s)
        if not mdir:
            continue
        direction = mdir.group(1)
        # 去注释
        s = re.sub(r"//.*$", "", s)
        # 跳过参数列表内的行（module #(...) 中一般无 input/output，防御性处理）
        if "(" in s and ")" not in s:
            continue
        # 提取所有标识符（排除 wire/reg/input/output/signed/位宽常量）
        toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s)
        for t in toks:
            if t in ("input", "output", "inout", "wire", "reg", "logic", "signed", "unsigned"):
                continue
            if t in params:
                continue
            if t not in ports:
                ports[t] = direction
    return ports


def find_code_slice(design_text, failed_line, radius=4):
    """以失败行为中心的代码片段（含行号），供 LLM 定位参考。"""
    if not failed_line:
        return None
    lines = design_text.splitlines()
    lo = max(1, failed_line - radius)
    hi = min(len(lines), failed_line + radius)
    return "\n".join("%4d: %s" % (i, lines[i - 1]) for i in range(lo, hi + 1))


def find_trigger_condition(design_text, failed_line):
    """提取失败断言所在语句的 assert 表达式，作为 trigger_condition。"""
    if not failed_line:
        return None
    lines = design_text.splitlines()
    # 优先从失败行起向后 3 行内找 assert（yosys 行号常落在 if 行）
    for i in range(failed_line - 1, min(len(lines), failed_line + 2)):
        m = re.search(r"assert\s*\((.*)\)\s*;", lines[i])
        if m:
            return m.group(1).strip()
    # 回退：向上找最近含 assert 的行
    for i in range(max(0, failed_line - 8), failed_line - 1):
        m = re.search(r"assert\s*\((.*)\)\s*;", lines[i])
        if m:
            return m.group(1).strip()
    return None


def scan_vcd_xstate(vcd_text):
    """扫描 VCD 中的 x/z 值 → {count, signals}（X 态归一化告警）。

    解析 $var 映射 id→信号名，排除 yosys 内部信号（anyseq/auto_setundef/_witness_ 等），
    只报告设计可见信号的 x/z 出现。仅扫描值变化区（$dumpvars 之后），避免把
    $var 声明行中的 "execute" 等信号名误判为 x 值。
    """
    count = 0
    signals = set()
    # id → 信号名 映射（$var <w> <width> <id> <name> [<range>] $end）
    id2name = {}
    for m in re.finditer(r"\$var\s+\w+\s+\d+\s+(\S+)\s+(\S+)", vcd_text):
        id2name[m.group(1)] = m.group(2)
    # 值变化区：从 $dumpvars 之后开始逐行扫描
    idx = vcd_text.find("$dumpvars")
    body = vcd_text[idx:] if idx >= 0 else vcd_text
    for line in body.splitlines():
        s = line.strip()
        # 向量：b<value> <id>；标量：<value><id>（无空格）
        m = re.match(r"^b([01xzXZ]+)\s+(\S+)", s)
        if m:
            val, sig_id = m.group(1), m.group(2)
        else:
            m = re.match(r"^([01xzXZ])(\S+)", s)
            if not m:
                continue
            val, sig_id = m.group(1), m.group(2)
        if "x" in val.lower() or "z" in val.lower():
            name = id2name.get(sig_id, sig_id)
            # 过滤 yosys 内部信号
            if re.search(r"anyseq|setundef|_witness_|auto\$|\\_", name):
                continue
            count += 1
            signals.add(name)
    return {"count": count, "signals": sorted(signals)[:20]}


def build_evidence(sample_dir, verbose=False):
    """对样本目录生成结构化证据 JSON（设置 B）。"""
    sample_dir = os.path.abspath(sample_dir)
    sample_id = os.path.basename(sample_dir)
    cex_log = _load_text(os.path.join(sample_dir, "cex.log"))
    cex_vcd = _load_text(os.path.join(sample_dir, "cex.vcd"))
    meta = _load_json(os.path.join(sample_dir, "meta.json"))
    # 设计文件：buggy.sv 优先（预研样本约定），否则取非 tb/golden/assertions 的 .sv
    design_file = os.path.join(sample_dir, "buggy.sv")
    if not os.path.isfile(design_file):
        for f in sorted(os.listdir(sample_dir)):
            if f.endswith(".sv") and not f.startswith(("tb_", "golden")) and f != "assertions.sv":
                design_file = os.path.join(sample_dir, f)
                break
    design_text = _load_text(design_file)

    sby = parse_sby_log(cex_log)
    ports = parse_design_ports(design_text, sby["module"])
    code_slice = find_code_slice(design_text, sby["failed_line"])
    trigger = find_trigger_condition(design_text, sby["failed_line"])
    xstate = scan_vcd_xstate(cex_vcd)

    ev = {
        "schema_ver": SCHEMA_VER,
        "evidence_source": "sby_bmc",
        "sample_id": sample_id,
        "error_type": meta.get("error_type"),
        "inject_line": meta.get("inject_line"),
        "inject_desc": meta.get("inject_desc"),
        "module": sby["module"] or meta.get("module"),
        "file": os.path.relpath(design_file, os.path.dirname(sample_dir)),
        "line": sby["failed_line"],
        "code_slice": code_slice,
        "signals": ports,
        "trigger_condition": trigger,
        "fail_stage": sby["fail_stage"],
        "fail_step": sby["fail_step"],
        "failed_assert_id": sby["failed_assert_id"],
        "x_state_warn": xstate["count"] > 0,
        "x_state": xstate,
        "raw_trace_ref": os.path.join("samples", "prestudy", sample_id, "cex.vcd"),
    }
    if verbose:
        print("[evidence:%s] module=%s line=%s step=%s result=%s x_warn=%s" % (
            sample_id, ev["module"], ev["line"], ev["fail_step"], sby["result"], ev["x_state_warn"]))
    return ev


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        print(__doc__)
        return 1
    sample_dir = argv[0]
    out_path = None
    verbose = False
    if "--out" in argv:
        i = argv.index("--out")
        out_path = argv[i + 1] if i + 1 < len(argv) else None
    if "--verbose" in argv:
        verbose = True
    ev = build_evidence(sample_dir, verbose=verbose)
    text = json.dumps(ev, ensure_ascii=False, indent=2)
    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
