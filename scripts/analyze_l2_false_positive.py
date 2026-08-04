#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/analyze_l2_false_positive.py：L2 假阳性率分析

输入：L2 样本主实验结果 JSON（--out 指定，结构同 experiments_results_corrected.json，
      含 sample/setting/repair_pass/repair_pass_bmc/verdict/attempts/cost）。
输出：按 setting 与样本维度的 L2 假阳性率统计 + JSON 报告。

判据（方案 A，docs/方案-授权-L2假阳性率与多模型主实验.md）：
  假阳性率 = 系统把 L2 当 L3 修好（误报）的比例 = 修复成功（BMC 判据）的 L2 样本 / 总 L2 样本。
  L2 样本弱 tb 可直接 FAIL（单周期可观测错误），系统将其当 L3 定位并修复
  说明该 L2 缺陷被系统以 L3 流程处理成功——即"伪 L3"误报。
  （若 L2 修复率显著低于 L3，说明系统对 L2 类单周期错误有鉴别力；
   若接近 L3，说明纯度门禁代价高、L2 与 L3 边界模糊。）
"""
import argparse, json, os, sys


def load_results(path):
    d = json.load(open(path, encoding="utf-8"))
    results = d.get("results", [])
    if not results and isinstance(d, list):
        results = d
    return results


def analyze(results):
    """统计 L2 假阳性率。返回 (per_setting, per_sample, total)。"""
    per_setting = {}
    per_sample = {}
    total = {"n": 0, "repair_pass": 0, "repair_pass_bmc": 0,
            "loc_top1": 0, "attempts_sum": 0, "cost": 0.0, "samples": 0}
    samples_seen = set()
    for r in results:
        s = r.get("sample")
        st = r.get("setting")
        if not s or not st:
            continue
        # 修复判据优先 BMC（真实验证），退化到 repair_pass
        pass_bmc = r.get("repair_pass_bmc", r.get("repair_pass", False))
        pass_any = r.get("repair_pass", False)
        loc1 = bool(r.get("loc_top1"))
        key_s = (s, st)
        per_setting.setdefault(st, {"n": 0, "repair_pass": 0, "repair_pass_bmc": 0,
                                   "loc_top1": 0, "cost": 0.0, "samples": 0})
        d = per_setting[st]
        d["n"] += 1
        d["repair_pass"] += 1 if pass_any else 0
        d["repair_pass_bmc"] += 1 if pass_bmc else 0
        d["loc_top1"] += 1 if loc1 else 0
        d["cost"] += r.get("cost", 0.0) or 0.0
        d["samples"] = len({x[0] for x in per_setting[st]["_seen"]}) if "_seen" in per_setting[st] else 0
        per_setting[st].setdefault("_seen", set()).add(s)
        per_setting[st]["samples"] = len(per_setting[st]["_seen"])

        per_sample.setdefault(s, {"n": 0, "repair_pass": 0, "repair_pass_bmc": 0,
                                  "loc_top1": 0, "cost": 0.0, "settings": set()})
        p = per_sample[s]
        p["n"] += 1
        p["repair_pass"] += 1 if pass_any else 0
        p["repair_pass_bmc"] += 1 if pass_bmc else 0
        p["loc_top1"] += 1 if loc1 else 0
        p["cost"] += r.get("cost", 0.0) or 0.0
        p["settings"].add(st)

        total["n"] += 1
        total["repair_pass"] += 1 if pass_any else 0
        total["repair_pass_bmc"] += 1 if pass_bmc else 0
        total["loc_top1"] += 1 if loc1 else 0
        total["attempts_sum"] += r.get("attempts", 0) or 0
        total["cost"] += r.get("cost", 0.0) or 0.0
        samples_seen.add(s)
    total["samples"] = len(samples_seen)

    # 清理内部辅助字段
    for st, d in per_setting.items():
        d.pop("_seen", None)
        d["rate_bmc"] = round(d["repair_pass_bmc"] / d["n"], 4) if d["n"] else None
        d["rate_pass"] = round(d["repair_pass"] / d["n"], 4) if d["n"] else None
        d["loc_top1_rate"] = round(d["loc_top1"] / d["n"], 4) if d["n"] else None
    for s, p in per_sample.items():
        p["settings"] = sorted(p["settings"])
        p["rate_bmc"] = round(p["repair_pass_bmc"] / p["n"], 4) if p["n"] else None
        p["rate_pass"] = round(p["repair_pass"] / p["n"], 4) if p["n"] else None
    total["rate_bmc"] = round(total["repair_pass_bmc"] / total["n"], 4) if total["n"] else None
    total["rate_pass"] = round(total["repair_pass"] / total["n"], 4) if total["n"] else None
    total["loc_top1_rate"] = round(total["loc_top1"] / total["n"], 4) if total["n"] else None
    total["avg_attempts"] = round(total["attempts_sum"] / total["n"], 2) if total["n"] else None
    return per_setting, per_sample, total


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    ap = argparse.ArgumentParser(description="L2 假阳性率分析（方案 A）")
    ap.add_argument("--results", required=True, help="L2 主实验结果 JSON 路径")
    ap.add_argument("--out", default=None, help="输出报告 JSON（默认 stdout + 控制台摘要）")
    ap.add_argument("--l3-baseline", default=None, help="可选：L3 主实验结果 JSON（对比 L3 修复率）")
    args = ap.parse_args(argv)

    results = load_results(args.results)
    per_setting, per_sample, total = analyze(results)
    print("== L2 假阳性率分析 ==")
    print("样本数: %d  调用数: %d  总成本: $%.4f" % (total["samples"], total["n"], total["cost"]))
    print("修复率(BMC判据): %s  (%d/%d)  <- 假阳性率口径" % (
        ("%.1f%%" % (total["rate_bmc"] * 100)) if total["rate_bmc"] is not None else "N/A",
        total["repair_pass_bmc"], total["n"]))
    print("修复率(普通判据): %s  (%d/%d)" % (
        ("%.1f%%" % (total["rate_pass"] * 100)) if total["rate_pass"] is not None else "N/A",
        total["repair_pass"], total["n"]))
    print("loc_top1: %s  (%d/%d)" % (
        ("%.1f%%" % (total["loc_top1_rate"] * 100)) if total["loc_top1_rate"] is not None else "N/A",
        total["loc_top1"], total["n"]))
    print("平均 attempts: %s" % total["avg_attempts"])

    print("\n-- 按 setting --")
    for st in sorted(per_setting):
        d = per_setting[st]
        print("  %s: n=%d 修复率(BMC)=%s 修复率(普通)=%s loc_top1=%s cost=$%.4f" % (
            st, d["n"],
            ("%.1f%%" % (d["rate_bmc"] * 100)) if d["rate_bmc"] is not None else "N/A",
            ("%.1f%%" % (d["rate_pass"] * 100)) if d["rate_pass"] is not None else "N/A",
            ("%.1f%%" % (d["loc_top1_rate"] * 100)) if d["loc_top1_rate"] is not None else "N/A",
            d["cost"]))

    print("\n-- 按样本 --")
    for s in sorted(per_sample):
        p = per_sample[s]
        print("  %s: n=%d 修复率(BMC)=%s settings=%s" % (
            s, p["n"],
            ("%.1f%%" % (p["rate_bmc"] * 100)) if p["rate_bmc"] is not None else "N/A",
            ",".join(p["settings"])))

    # L3 基线对比
    l3 = None
    if args.l3_baseline:
        l3_results = load_results(args.l3_baseline)
        _s, _p, l3 = analyze(l3_results)
        print("\n-- L3 基线对比（假阳性率语境）--")
        print("  L3 修复率(BMC): %s  (%d/%d)" % (
            ("%.1f%%" % (l3["rate_bmc"] * 100)) if l3["rate_bmc"] is not None else "N/A",
            l3["repair_pass_bmc"], l3["n"]))
        if total["rate_bmc"] is not None and l3["rate_bmc"] is not None:
            diff = total["rate_bmc"] - l3["rate_bmc"]
            print("  差异(L2 - L3): %+.1f 个百分点" % (diff * 100))

    report = {"per_setting": per_setting, "per_sample": per_sample, "total": total,
              "l3_baseline": l3, "note": "L2 假阳性率（方案 A 口径）"
              if l3 is None else "L2 假阳性率 + L3 基线（方案 A 口径）"}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("\n报告已写入: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())