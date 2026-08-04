# -*- coding: utf-8 -*-
"""PreCex 主实验结果分析：合并 partial/完整 json，输出 A/B/C 对比指标表。
用法: python3 scripts/analyze_experiments.py [--out experiments/runs/experiments_results_parallel.json]
"""
import argparse, json, os, sys, glob, csv, io

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_results(out_path):
    """优先完整 json；否则合并 exp_part_*.json + partial。"""
    if os.path.isfile(out_path):
        d = json.load(open(out_path, encoding="utf-8"))
        rs = d.get("results", [])
        if rs: return rs
    # 合并 exp_part_*.json 或 partial
    workdir = os.path.join(REPO_ROOT, "experiments", "runs")
    rs = []; seen = set()
    for p in sorted(glob.glob(os.path.join(workdir, "exp_part_*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
            for r in d.get("results", []):
                k = (r["sample"], r["setting"], r["seed"])
                if k not in seen: seen.add(k); rs.append(r)
        except Exception: pass
    for p in sorted(glob.glob(os.path.join(workdir, "exp_part_*.json.partial.jsonl"))):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln: continue
                try:
                    r = json.loads(ln)
                    k = (r["sample"], r["setting"], r["seed"])
                    if k not in seen: seen.add(k); rs.append(r)
                except Exception: pass
    rs.sort(key=lambda r: (r["sample"], r["setting"], r["seed"]))
    return rs

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results_parallel.json"))
    args = ap.parse_args(argv)
    rs = load_results(args.out)
    print("total results:", len(rs))
    # 按 setting 聚合
    agg = {}
    for r in rs:
        st = r["setting"]
        a = agg.setdefault(st, {"n": 0, "loc_top1": 0, "repair_pass": 0, "pass": 0, "fail": 0, "inconc": 0, "tokens": 0, "cost": 0.0, "attempts": 0})
        a["n"] += 1
        a["loc_top1"] += 1 if r.get("loc_top1") else 0
        a["repair_pass"] += 1 if r.get("repair_pass") else 0
        v = r.get("verdict")
        if v == "PASS": a["pass"] += 1
        elif v == "FAIL": a["fail"] += 1
        else: a["inconc"] += 1
        a["tokens"] += r.get("input_tokens", 0) + r.get("output_tokens", 0)
        a["cost"] += r.get("cost", 0.0)
        a["attempts"] += r.get("attempts", 0)
    print("\n=== A/B/C 对比（3 种子聚合） ===")
    print("%-3s %5s %10s %12s %8s %8s %10s %10s %8s" % ("S", "n", "loc_top1", "repair_pass", "PASS", "FAIL", "tokens", "cost", "avg_att"));
    for st in sorted(agg):
        a = agg[st]
        print("%-3s %5d %10.1f%% %12.1f%% %8d %8d %10d %10.4f %8.2f" % (
            st, a["n"], 100.0*a["loc_top1"]/a["n"], 100.0*a["repair_pass"]/a["n"],
            a["pass"], a["fail"], a["tokens"], a["cost"], a["attempts"]*1.0/a["n"]))
    # 按样本×setting 输出 CSV
    workdir = os.path.dirname(args.out)
    csv_path = os.path.join(workdir, "analysis_by_sample.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["sample", "setting", "n", "loc_top1_rate", "repair_rate", "pass_count", "avg_cost"])
        by = {}
        for r in rs:
            k = (r["sample"], r["setting"]); by.setdefault(k, []).append(r)
        for k in sorted(by):
            xs = by[k]; n = len(xs)
            w.writerow([k[0], k[1], n, "%.3f" % (sum(1 for x in xs if x.get("loc_top1"))/n),
                        "%.3f" % (sum(1 for x in xs if x.get("repair_pass"))/n),
                        sum(1 for x in xs if x.get("verdict") == "PASS"),
                        "%.4f" % (sum(x.get("cost", 0) for x in xs)/n)])
    print("\n[csv] ->", csv_path)
    # 打印各样本修复率（方便发现难样本）
    print("\n=== 按样本（3 setting × 3 seed） ===")
    bys = {}
    for r in rs: bys.setdefault(r["sample"], []).append(r)
    for s in sorted(bys):
        xs = bys[s]; n = len(xs)
        print("%-5s n=%-2d loc_top1=%.2f repair=%.2f pass=%d/%d" % (s, n,
              sum(1 for x in xs if x.get("loc_top1"))/n, sum(1 for x in xs if x.get("repair_pass"))/n,
              sum(1 for x in xs if x.get("verdict") == "PASS"), n))

if __name__ == "__main__":
    sys.exit(main())
