# -*- coding: utf-8 -*-
"""PreCex 设置对比（A/B/C/D 全量）：loc_top1 / repair_bmc / verdict / tokens / cost 聚合表。
用法: python3 scripts/analyze_settings.py --results experiments/runs/experiments_results_corrected.json [--d experiments/runs/experiments_results_D.json]
"""
import argparse, json, os, sys, collections, csv

def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return d.get("results", [])

def agg(rs):
    st = {}
    for r in rs:
        s = r.get("setting", "?")
        a = st.setdefault(s, {"n":0, "loc":0, "repair_bmc":0, "pass":0, "fail":0, "tokens":0, "cost":0.0, "attempts":0})
        a["n"] += 1
        a["loc"] += 1 if r.get("loc_top1") else 0
        a["repair_bmc"] += 1 if (r.get("repair_pass_bmc") or r.get("repair_pass")) else 0
        v = r.get("verdict")
        if v == "PASS": a["pass"] += 1
        elif v == "FAIL": a["fail"] += 1
        a["tokens"] += (r.get("input_tokens",0) or 0) + (r.get("output_tokens",0) or 0)
        a["cost"] += r.get("cost",0) or 0
        a["attempts"] += r.get("attempts",0) or 0
    return st

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--abc", default=r"experiments/runs/experiments_results_corrected.json")
    ap.add_argument("--d", default=r"experiments/runs/experiments_results_D.json")
    args = ap.parse_args()
    rs = load(args.abc)
    if os.path.exists(args.d):
        rs += load(args.d)
    st = agg(rs)
    print("%-3s %5s %10s %12s %8s %8s %12s %10s %10s" % ("S","n","loc_top1","repair_bmc","PASS","FAIL","tokens","cost","avg_att"))
    for s in sorted(st):
        a = st[s]
        print("%-3s %5d %9.1f%% %11.1f%% %8d %8d %12d %10.4f %10.2f" % (
            s, a["n"], 100.0*a["loc"]/a["n"], 100.0*a["repair_bmc"]/a["n"],
            a["pass"], a["fail"], a["tokens"], a["cost"], a["attempts"]*1.0/a["n"]))
    # per-sample D vs B
    print("\n=== D vs B 逐样本 ===")
    by = collections.defaultdict(dict)
    for r in rs:
        by[r["sample"]][r["setting"]] = r
    print("%-5s %10s %10s %10s %10s" % ("sample","B_loc","D_loc","B_repair","D_repair"))
    for s in sorted(by):
        b = by[s].get("B"); dd = by[s].get("D")
        if not b or not dd: continue
        print("%-5s %10s %10s %10s %10s" % (s,
            "%.0f%%" % (100*sum(1 for x in [b] if x.get("loc_top1"))/1) if b else "-",
            "%.0f%%" % (100*sum(1 for x in [dd] if x.get("loc_top1"))/1) if dd else "-",
            "%.0f%%" % (100*sum(1 for x in [b] if x.get("repair_pass_bmc"))/1) if b else "-",
            "%.0f%%" % (100*sum(1 for x in [dd] if x.get("repair_pass_bmc"))/1) if dd else "-"))
    # csv
    csv_path = os.path.join(os.path.dirname(args.d), "settings_compare.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["setting","n","loc_top1_rate","repair_bmc_rate","PASS","FAIL","tokens","cost"])
        for s in sorted(st):
            a = st[s]
            w.writerow([s, a["n"], "%.3f"%(a["loc"]/a["n"]), "%.3f"%(a["repair_bmc"]/a["n"]),
                        a["pass"], a["fail"], a["tokens"], "%.4f"%a["cost"]])
    print("[csv] ->", csv_path)

if __name__ == "__main__":
    sys.exit(main())
