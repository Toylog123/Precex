#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/compare_cross_model.py：跨模型主实验对比（方案 B 分析）

输入：两份主实验结果 JSON（如 MiniMax 与 DeepSeek 各一份，--out 分开输出），
      结构同 experiments_results_corrected.json（含 sample/setting/seed/repair_pass/
      repair_pass_bmc/loc_top1/attempts/cost/input_tokens/output_tokens）。
输出：按 setting 与总体对比 loc_top1 / 修复率(BMC) / 修复率(普通) / 平均 attempts / 成本 / tokens；
      并对同一 (sample, setting, seed) 逐条对齐，输出 McNemar 式差异（B vs 基线）。
      注意：所有聚合与 McNemar 均只统计两模型严格配对（相同 sample/setting/seed）的重叠子集，
      避免把另一模型缺失的 (sample,setting,seed) 当成失败混入统计。

用法：python3 scripts/compare_cross_model.py --base <minimax.json> --other <deepseek.json> [--out <report.json>]
"""
import argparse, json, math, os, sys


def load_results(path):
    d = json.load(open(path, encoding="utf-8"))
    results = d.get("results", [])
    if not results and isinstance(d, list):
        results = d
    return results


def key(r):
    return (r.get("sample"), r.get("setting"), r.get("seed", 0))


def bmc_ok(r):
    """修复判据（BMC）：优先 repair_pass_bmc（修正版结果），缺失时回退 repair_pass。
    注意：experiments_results_corrected.json 的 repair_pass 是旧 prove 判据遗留值（228/306），
    repair_pass_bmc 才是论文口径（306/306）；experiments_results_ds.json 无 repair_pass_bmc，
    其 repair_pass 即 BMC 判据结果（102/102）。"""
    v = r.get("repair_pass_bmc")
    if v is None:
        v = r.get("repair_pass")
    return bool(v)


def aggregate(results):
    agg = {"n": 0, "loc_top1": 0, "repair_pass": 0, "repair_pass_bmc": 0,
           "attempts_sum": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}
    for r in results:
        agg["n"] += 1
        agg["loc_top1"] += 1 if r.get("loc_top1") else 0
        agg["repair_pass"] += 1 if bmc_ok(r) else 0
        agg["repair_pass_bmc"] += 1 if bmc_ok(r) else 0
        agg["attempts_sum"] += r.get("attempts", 0) or 0
        agg["cost"] += r.get("cost", 0.0) or 0.0
        agg["input_tokens"] += r.get("input_tokens", 0) or 0
        agg["output_tokens"] += r.get("output_tokens", 0) or 0
    n = agg["n"] or 1
    return {"n": agg["n"], "loc_top1_rate": agg["loc_top1"] / n,
            "repair_pass_rate": agg["repair_pass"] / n,
            "repair_pass_bmc_rate": agg["repair_pass_bmc"] / n,
            "avg_attempts": agg["attempts_sum"] / n,
            "cost": agg["cost"], "input_tokens": agg["input_tokens"], "output_tokens": agg["output_tokens"]}


def mcnemar(base_map, other_map, keys_all):
    """修复率(BMC)的 McNemar 配对检验：统计 b!=o 的 discordant 对，双边 p 值（精确二项）。"""
    b_ok = o_ok = 0
    b_only = o_only = 0
    for k in keys_all:
        b = bmc_ok(base_map.get(k, {}))
        o = bmc_ok(other_map.get(k, {}))
        b_ok += 1 if b else 0; o_ok += 1 if o else 0
        if b and not o: b_only += 1
        if o and not b: o_only += 1
    n_d = b_only + o_only
    if n_d == 0:
        p = 1.0
    else:
        # 精确二项双侧：P(X<=min(b_only,o_only)) * 2，上限 1
        k = min(b_only, o_only)
        import math
        p = 0.0
        for i in range(k + 1):
            p += math.comb(n_d, i) * (0.5 ** n_d)
        p = min(1.0, 2 * p)
    return {"discordant": n_d, "base_only": b_only, "other_only": o_only,
            "base_ok": b_ok, "other_ok": o_ok, "p_value": round(p, 4)}


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(description="跨模型主实验对比（方案 B）")
    ap.add_argument("--base", required=True, help="基线模型结果 JSON（如 MiniMax）")
    ap.add_argument("--other", required=True, help="对比模型结果 JSON（如 DeepSeek）")
    ap.add_argument("--out", default=None, help="输出报告 JSON")
    ap.add_argument("--base-label", default="base", help="基线标签（默认 base）")
    ap.add_argument("--other-label", default="other", help="对比标签（默认 other）")
    args = ap.parse_args(argv)

    base = load_results(args.base)
    other = load_results(args.other)
    b_map = {key(r): r for r in base}
    o_map = {key(r): r for r in other}
    keys_all = sorted(set(b_map) | set(o_map))
    overlap = sorted(set(b_map) & set(o_map))
    print("== 跨模型对比: %s (%s) vs %s (%s) ==" % (args.base_label, args.base, args.other_label, args.other))
    print("样本/调用数: base=%d other=%d 严格配对(seed/sample/setting 全对齐)=%d" % (len(b_map), len(o_map), len(overlap)))

    # 只统计严格配对子集（避免全量与单 seed 混比）
    b_aligned = [b_map[k] for k in overlap]
    o_aligned = [o_map[k] for k in overlap]
    ba = aggregate(b_aligned); oa = aggregate(o_aligned)
    print("聚合口径: 仅 %d 条严格配对（%s=%s vs %s=%s）" % (len(overlap), args.base_label, args.base, args.other_label, args.other))
    print("\n-- 总体指标 --")
    hdr = "%-14s %10s %10s %10s %10s %10s %10s" % ("指标", args.base_label, args.other_label, "差异", "", "", "")
    print(hdr)
    rows = [
        ("loc_top1", ba["loc_top1_rate"], oa["loc_top1_rate"], "pp", 100),
        ("修复率(BMC)", ba["repair_pass_bmc_rate"], oa["repair_pass_bmc_rate"], "pp", 100),
        ("修复率(普通)", ba["repair_pass_rate"], oa["repair_pass_rate"], "pp", 100),
        ("avg_attempts", ba["avg_attempts"], oa["avg_attempts"], "x", 1),
        ("cost($)", ba["cost"], oa["cost"], "$", 1),
        ("input_tokens", ba["input_tokens"], oa["input_tokens"], "", 1),
        ("output_tokens", ba["output_tokens"], oa["output_tokens"], "", 1),
    ]
    for name, bv, ov, unit, scale in rows:
        if scale == 100:
            diff = (ov - bv) * 100
            print("  %-13s %9.1f%% %9.1f%% %+9.1f%s" % (name, bv * 100, ov * 100, diff, unit))
        else:
            diff = ov - bv if name == "cost($)" else ov - bv
            print("  %-13s %10.3f %10.3f %+10.3f %s" % (name, bv, ov, diff, unit))

    # 按 setting
    print("\n-- 按 setting --")
    for st in sorted({k[1] for k in overlap}):
        b_s = [b_map[k] for k in overlap if k[1] == st]
        o_s = [o_map[k] for k in overlap if k[1] == st]
        if not b_s or not o_s: continue
        bsa = aggregate(b_s); osa = aggregate(o_s)
        print("  %s: loc_top1 %s→%s | 修复率(BMC) %s→%s | n=%d/%d" % (
            st,
            ("%.1f%%" % (bsa["loc_top1_rate"] * 100)), ("%.1f%%" % (osa["loc_top1_rate"] * 100)),
            ("%.1f%%" % (bsa["repair_pass_bmc_rate"] * 100)), ("%.1f%%" % (osa["repair_pass_bmc_rate"] * 100)),
            len(b_s), len(o_s)))

    # McNemar（配对修复率差异显著性）
    mn = mcnemar(b_map, o_map, overlap)
    print("\n-- McNemar（修复率 BMC，配对）--")
    print("  严格配对不一致对: %d  (%s 仅成功: %d, %s 仅成功: %d)" % (
        mn["discordant"], args.base_label, mn["base_only"], args.other_label, mn["other_only"]))
    print("  p 值: %.4f%s" % (mn["p_value"], "  <0.05 显著" if mn["p_value"] < 0.05 else ""))

    report = {"base_label": args.base_label, "other_label": args.other_label,
              "base_file": args.base, "other_file": args.other,
              "base_agg": ba, "other_agg": oa,
              "per_setting": {}, "mcnemar": mn,
              "note": "跨模型主实验对比（方案 B 口径）"}
    for st in sorted({k[1] for k in overlap}):
        b_s = [b_map[k] for k in overlap if k[1] == st]
        o_s = [o_map[k] for k in overlap if k[1] == st]
        if b_s and o_s:
            report["per_setting"][st] = {"base": aggregate(b_s), "other": aggregate(o_s)}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("\n报告已写入: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
