#!/usr/bin/env python3
# PreCex - scripts/check_rtl_compat.py 工具链适配性预检（报错重写层）
# 作者：Toylog | 版本：v0.1 | 功能概述：扫描设计/断言文件中 iverilog 12 / Yosys 0.33 不支持的
#   SystemVerilog 结构（并发 SVA、real、非可综合语法等），在进入 LLM 修复/形式验证前给出
#   可操作的改写提示——对应评审缺陷 5："系统没有设计工具链降级/报错重写层，解析失败导致崩溃"。
#   策略：预防优先（断言安全子集 Gate-1 收敛）＋ 前置检测 fail-fast（替代运行中才崩溃）。
# 用法：
#   python3 scripts/check_rtl_compat.py <design.sv> [assertions.sv ...]
#   python3 scripts/check_rtl_compat.py --dir samples/bugs/s04
# 返回：0=无问题；1=发现不兼容结构（列出文件:行:结构:建议）。

from __future__ import annotations

import argparse
import os
import re
import sys

# iverilog 12 / yosys 0.33（read -sv -formal）不兼容的并发 SVA 与时序算子
UNSUPPORTED_PATTERNS = [
    (r"\bassert\s+property\b", "assert property（并发 SVA），改为 immediate assert(expr);"),
    (r"\bassume\s+property\b", "assume property（并发 SVA），改为 immediate assume(expr);"),
    (r"\b\$past\b", "$past 时序算子（concurrent 语境），改打拍跨周期：sig_d <= sig; if (en_d) assert(...)"),
    (r"\b\$rose\b", "$rose 时序算子，改 posedge 沿检测打拍"),
    (r"\b\$fell\b", "$fell 时序算子，改 negedge 沿检测打拍"),
    (r"\b\$stable\b", "$stable 时序算子，改打拍比较"),
    (r"\|\s*->", "蕴含算子 |->（并发 SVA），改 if (cond) assert(...)"),
    (r"##\s*\d", "延迟算子 ##n（并发 SVA），改打拍/计数断言"),
    (r"\bwithin\b", "within 时序算子（并发 SVA）"),
    (r"\buntil(?:_with)?\b", "until 时序算子（并发 SVA）"),
    (r"\breal\b", "real 类型（不可综合，Yosys 不支持）"),
    (r"\btime\b", "time 类型（不可综合）"),
    (r"\brealtime\b", "realtime 类型（不可综合）"),
]


def check_text(text, filename):
    """扫描单个文件，返回 [(line_no, pattern, suggestion)]。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        # 跳过注释行/字符串（简单启发：注释内的关键字不报）
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        for pattern, suggestion in UNSUPPORTED_PATTERNS:
            if re.search(pattern, line):
                hits.append((lineno, pattern, suggestion))
    return hits


def check_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return [(0, "<read-error>", str(e))]
    return check_text(text, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="工具链适配性预检（SVA/不可综合结构）")
    ap.add_argument("files", nargs="*", help="设计/断言文件；或 --dir 扫描样本目录")
    ap.add_argument("--dir", default=None, help="样本目录（自动取 buggy.v/断言文件）")
    args = ap.parse_args(argv)

    files = list(args.files)
    if args.dir:
        for name in sorted(os.listdir(args.dir)):
            if name.endswith((".v", ".sv")) and not name.startswith(("tb_", "golden")):
                files.append(os.path.join(args.dir, name))
    if not files:
        ap.error("需要文件列表或 --dir")

    all_hits = []
    for path in files:
        hits = check_file(path)
        for lineno, pattern, suggestion in hits:
            print("%s:%d: [%s] %s" % (path, lineno, pattern, suggestion))
            all_hits.append((path, lineno, pattern, suggestion))
    if all_hits:
        print("\n共 %d 处不兼容结构。建议按 smoke/断言子集收敛.md 改为 immediate assert/assume，"
              "或移除非可综合语法；修复后再进入 LLM 修复/形式验证，避免运行中解析失败。" % len(all_hits))
        return 1
    print("OK：%d 个文件未发现不兼容结构（iverilog 12 / Yosys 0.33 可解析）" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
