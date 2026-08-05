#!/usr/bin/env python3
# PreCex - scripts/minimize_patch.py 最小补丁后验验证（delta-debugging）
# 作者：Toylog | 版本：v0.1 | 功能概述：对一条已通过三通过的修复 diff 做后验最小性验证——
#   迭代尝试移除 diff 中的每个改动单元（-/+ 连续块），若移除后仍通过 compile/sim/BMC 三通过
#   则删除该单元，直到无可移除单元（1-minimal）。回答评审缺陷 4："系统只信任 LLM 对'最小'
#   的理解，从未做 delta-debugging 后验验证"。
# 说明：最小性是**相对当前验证判据（BMC + 弱 tb + 编译）**的 1-minimal，不保证语义不可约
#   （一行 if(a&&b) -> if(a&&b&&c) 可能仍是 1-minimal）；用于审计"是否存在可删除的冗余改动"。
# 运行（需 WSL 工具链，与主实验一致）：
#   export PATH=$HOME/.local/bin:$PATH
#   export SMTBMC=$PWD/smoke/yosys-smtbmc-z3.sh
#   python3 scripts/minimize_patch.py --sample samples/deep/s40 --diff-text "<diff>"
#   python3 scripts/minimize_patch.py --sample samples/deep/s40 --diff-file /tmp/patch.diff

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import evaluator  # noqa: E402
from run_prestudy import apply_unified_diff  # noqa: E402


def _norm(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_units(diff_text):
    """把 unified diff 拆成可移除单元。

    单元 = 每个 hunk 内连续的 -/+ 行块（上下文行分隔）。返回
    (hunks, units)：hunks 为原始结构，units 为 [(hunk_idx, [op,...])]。
    """
    hunks = []
    cur = None
    for ln in diff_text.splitlines():
        if ln.startswith("@@"):
            cur = {"header": ln, "ops": []}
            hunks.append(cur)
        elif cur is not None:
            if ln.startswith("-") and not ln.startswith("---"):
                cur["ops"].append(("-", ln[1:]))
            elif ln.startswith("+"):
                cur["ops"].append(("+", ln[1:]))
            elif ln.startswith(" "):
                cur["ops"].append((" ", ln[1:]))
    units = []
    for hi, h in enumerate(hunks):
        unit = []
        for op in h["ops"]:
            if op[0] in ("-", "+"):
                unit.append(op)
            elif unit:
                units.append((hi, unit))
                unit = []
        if unit:
            units.append((hi, unit))
    return hunks, units


def rebuild_diff(hunks, removed_unit_keys):
    """重建 diff：保留 hunk 头与未被移除的 -/+ 行（行号仅作提示，apply 按内容匹配）。

    removed_unit_keys 形如 {(hunk_idx, frozenset(op_indices))}：移除指定 hunk 中
    这些 op 序号对应的 -/+ 行（单元内所有行一起移除）。
    """
    lines = []
    for hi, h in enumerate(hunks):
        blocked = set()
        for khi, ops in removed_unit_keys:
            if khi == hi:
                blocked.update(ops)
        kept_ops = [op for ui, op in enumerate(h["ops"]) if ui not in blocked]
        if not any(op[0] in ("-", "+") for op in kept_ops):
            # 该 hunk 已无任何改动（只剩上下文）：整体丢弃，避免空 hunk 头
            continue
        lines.append(h["header"])
        for ui, op in enumerate(h["ops"]):
            if ui in blocked:
                continue
            if op[0] == "-":
                lines.append("-" + op[1])
            elif op[0] == "+":
                lines.append("+" + op[1])
            else:
                lines.append(" " + op[1])
    return "\n".join(lines) + "\n"


def _unit_keys(hunks, units):
    """返回 {unit_key: (hunk_idx, op_indices)}：unit_key 用 (hunk_idx, 起始 op 序号) 稳定标识。"""
    keys = []
    op_pos = []
    for hi, h in enumerate(hunks):
        cur = []
        for ui, op in enumerate(h["ops"]):
            if op[0] in ("-", "+"):
                cur.append(ui)
            elif cur:
                keys.append((hi, tuple(cur)))
                cur = []
        if cur:
            keys.append((hi, tuple(cur)))
    return keys


def verify_patch(sample_dir, design_text, diff_text, tb_top=None, keep_tmp=False):
    """把 diff 应用到设计并跑三通过（compile/sim/BMC）。返回 (verdict, formal_result)。"""
    ok, patched, err = apply_unified_diff(design_text, diff_text)
    if not ok:
        return None, "apply_failed:" + err
    work = tempfile.mkdtemp(prefix="minimize_")
    try:
        with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
            f.write(patched)
        for name in ("tb_weak.sv", "verify.sby", "verify_repair.sby", "uart_tx.sv"):
            src = os.path.join(sample_dir, name)
            if os.path.isfile(src):
                shutil.copy(src, os.path.join(work, name))
        if tb_top is None:
            tb_path = os.path.join(work, "tb_weak.sv")
            if os.path.isfile(tb_path):
                m = re.search(r"module\s+(tb_\w+)", open(tb_path, encoding="utf-8").read())
                tb_top = m.group(1) if m else None
        cfg = {"run_formal": True, "verbose": False, "tb_top": tb_top, "keep_tmp": keep_tmp}
        ev = evaluator.evaluate(work, cfg)
        return ev["verdict"], ev["formal"].get("result")
    finally:
        if not keep_tmp:
            shutil.rmtree(work, ignore_errors=True)


def minimize(sample_dir, diff_text, tb_top=None, max_verifications=40):
    """Delta-debugging：贪心移除可移除单元直到 1-minimal。返回报告 dict。"""
    design = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    design = _norm(design)
    diff_text = _norm(diff_text)
    baseline_verdict, baseline_formal = verify_patch(sample_dir, design, diff_text, tb_top)
    if baseline_verdict != "PASS":
        return {
            "ok": False,
            "error": "baseline patch 未通过三通过：verdict=%s formal=%s（最小性验证仅对有效修复有意义）"
                     % (baseline_verdict, baseline_formal),
        }
    hunks, units = parse_units(diff_text)
    unit_keys = _unit_keys(hunks, units)
    if not unit_keys:
        return {"ok": True, "error": None, "units": 0, "removed_units": [],
                "minimal": True, "verifications_run": 0,
                "minimal_diff": diff_text}
    removed = set()
    verifications = 1  # baseline
    changed = True
    while changed and verifications < max_verifications:
        changed = False
        for key in unit_keys:
            if key in removed:
                continue
            trial = removed | {key}
            reduced = rebuild_diff(hunks, trial)
            verdict, formal = verify_patch(sample_dir, design, reduced, tb_top)
            verifications += 1
            if verdict == "PASS":
                removed = trial
                changed = True
                break
    minimal_diff = rebuild_diff(hunks, removed)
    # 行级统计
    def _changed_lines(d):
        return [l for l in d.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
    return {
        "ok": True,
        "error": None,
        "units": len(unit_keys),
        "removed_units": [{"hunk": k[0], "ops": list(k[1])} for k in sorted(removed)],
        "minimal": len(removed) == 0,
        "verifications_run": verifications,
        "original_changed_lines": len(_changed_lines(diff_text)),
        "minimal_changed_lines": len(_changed_lines(minimal_diff)),
        "minimal_diff": minimal_diff,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="最小补丁后验验证（delta-debugging）")
    ap.add_argument("--sample", required=True, help="样本目录（含 buggy.v/tb_weak.sv/verify.sby）")
    ap.add_argument("--diff-file", help="diff 文本文件")
    ap.add_argument("--diff-text", help="diff 文本（命令行）")
    ap.add_argument("--tb-top", default=None)
    ap.add_argument("--out", default=None, help="结果 JSON 输出路径")
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args(argv)
    if args.diff_file:
        diff_text = open(args.diff_file, encoding="utf-8").read()
    elif args.diff_text:
        diff_text = args.diff_text
    else:
        ap.error("需要 --diff-file 或 --diff-text")
    report = minimize(args.sample, diff_text, tb_top=args.tb_top)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
