# -*- coding: utf-8 -*-
import json, collections, os, sys

import argparse
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_DATA = os.path.join(_SCRIPT_DIR, "data")
_DEFAULT_ROOT = _PKG_DATA if os.path.isdir(_PKG_DATA) else os.path.dirname(_SCRIPT_DIR)
_ap = argparse.ArgumentParser()
_ap.add_argument("--data-root", default=_DEFAULT_ROOT)
_args = _ap.parse_args()
os.chdir(_args.data_root)

def load(p):
    # p 形如 experiments/runs/xxx；兼容两种 data-root：
    #   仓库根（data-root/experiments/runs/xxx 存在）与投稿包 data 目录（data-root/xxx 存在）
    cands = [p]
    if p.startswith("experiments/runs/"):
        cands.insert(0, p[len("experiments/runs/"):])
    last = None
    for c in cands:
        if os.path.isfile(c):
            last = c
            break
    if last is None:
        raise FileNotFoundError(cands[0])
    with open(last, encoding="utf-8") as f:
        return json.load(f)

fails = []
def check(name, cond, detail=""):
    if not cond:
        fails.append(name + (" | " + detail if detail else ""))
        print("FAIL:", name, detail)
    else:
        print("PASS:", name)

# 1. Main experiment (corrected A/B/C 306 + D_clean 102)
abc = load("experiments/runs/experiments_results_corrected.json")["results"]
d = load("experiments/runs/experiments_results_D_clean.json")["results"]
allrows = abc + d
agg = collections.defaultdict(lambda: {"n":0,"loc":0,"rep":0,"cost":0.0})
for r in allrows:
    a = agg[r["setting"]]
    a["n"] += 1
    if r.get("loc_top1"): a["loc"] += 1
    if r.get("repair_pass_bmc") is not False and (r.get("repair_pass_bmc") or r.get("repair_pass")): a["rep"] += 1
    a["cost"] += float(r.get("cost_usd") or r.get("cost") or 0)
expect = {"A":(47.1,100.0,2.78),"B":(61.8,100.0,2.72),"C":(56.9,100.0,4.17),"D":(49.0,100.0,1.56)}
for s,(eloc,erep,ecost) in expect.items():
    a = agg[s]
    check("main %s loc %.1f" % (s, 100*a["loc"]/a["n"]), abs(100*a["loc"]/a["n"]-eloc) < 0.05, "got %s n=%d" % (100*a["loc"]/a["n"], a["n"]))
    check("main %s rep" % s, a["rep"] == a["n"] == 102, "got %d/%d" % (a["rep"], a["n"]))
    check("main %s cost" % s, abs(a["cost"]-ecost) < 0.01, "got %.2f" % a["cost"])
check("main total 408", len(allrows) == 408, "got %d" % len(allrows))

# 2. cross-model 3 seeds
cm = load("experiments/runs/cross_model_3seeds.json")
check("cm n=306", cm["base_agg"]["n"] == 306 and cm["other_agg"]["n"] == 306)
check("cm base loc 55.2", abs(cm["base_agg"]["loc_top1_rate"]*100-55.2) < 0.05, "got %.2f" % (cm["base_agg"]["loc_top1_rate"]*100))
check("cm other loc 56.2", abs(cm["other_agg"]["loc_top1_rate"]*100-56.2) < 0.05, "got %.2f" % (cm["other_agg"]["loc_top1_rate"]*100))
check("cm base cost 9.67", abs(cm["base_agg"]["cost"]-9.67) < 0.02, "got %.3f" % cm["base_agg"]["cost"])
check("cm other cost 1.02", abs(cm["other_agg"]["cost"]-1.02) < 0.01, "got %.3f" % cm["other_agg"]["cost"])
check("cm B MM 61.8", abs(cm["per_setting"]["B"]["base"]["loc_top1_rate"]*100-61.8) < 0.05)
check("cm B DS 54.9", abs(cm["per_setting"]["B"]["other"]["loc_top1_rate"]*100-54.9) < 0.05)
check("cm C DS 62.7", abs(cm["per_setting"]["C"]["other"]["loc_top1_rate"]*100-62.7) < 0.05)
check("cm A DS 51.0", abs(cm["per_setting"]["A"]["other"]["loc_top1_rate"]*100-51.0) < 0.05)

# 3. L2
l2 = load("experiments/runs/l2_false_positive_analysis.json")
tot_n = sum(v["n"] for v in l2["per_setting"].values())
tot_ok = sum(v["repair_pass_bmc"] for v in l2["per_setting"].values())
check("l2 n=72", tot_n == 72, "got %d" % tot_n)
check("l2 rate 91.7", abs(100*tot_ok/tot_n-91.7) < 0.1, "got %.2f" % (100*tot_ok/tot_n))
check("l2 cost 0.29", abs(sum(v["cost"] for v in l2["per_setting"].values())-0.29) < 0.01)

# 4. sufficiency
for p, etot, ekill in [("experiments/runs/sufficiency_all_strong_d16.json",400,354), ("experiments/runs/sufficiency_const_all.json",484,396)]:
    d = load(p)
    tot = sum(r["mutations"] for r in d["results"])
    killed = sum(r["killed"] for r in d["results"])
    check("suff %s total" % os.path.basename(p), tot == etot, "got %d" % tot)
    check("suff %s killed" % os.path.basename(p), killed == ekill, "got %d" % killed)

# 5. T2
t2a = load("experiments/runs/t2_audit_abc.json")
t2d = load("experiments/runs/t2_audit_D.json")
check("t2 abc 306 pass", t2a["n"] == 306 and t2a["t2_pass"] == 306 and t2a["t2_fail"] == 0)
check("t2 D pass", t2d["t2_pass"] == 102 and t2d["t2_fail"] == 0)

# 6. ledger
_ledger_path = "experiments/runs/token_ledger.jsonl"
if not os.path.isfile(_ledger_path):
    _ledger_path = "token_ledger.jsonl"
rows = [json.loads(l) for l in open(_ledger_path, encoding="utf-8") if l.strip()]
led_cost = sum(float(r.get("cost_usd", r.get("cost")) or 0) for r in rows)
check("ledger n=1519", len(rows) == 1519, "got %d" % len(rows))
check("ledger cost 18.48", abs(led_cost-18.48) < 0.01, "got %.3f" % led_cost)

# 7. verify timing golden max
vt = load("experiments/runs/verify_timing.json")
gmax = max(x["golden_s"] for x in vt["per_sample"].values())
check("golden max ~153", abs(gmax-152.6) < 2.0, "got %.1f" % gmax)

# 8. ICC
sm = load("experiments/runs/llm_scores/summary.json")
check("icc C causality 0.656", abs(sm["icc"]["C"]["causality"]-0.656) < 0.01, "got %.3f" % sm["icc"]["C"]["causality"])
check("icc C actionability 0.774", abs(sm["icc"]["C"]["actionability"]-0.774) < 0.01, "got %.3f" % sm["icc"]["C"]["actionability"])
check("icc D ~0", sm["icc"]["D"]["causality"] == 0 and sm["icc"]["D"]["actionability"] == 0)
check("interp cost 0.11", abs(sm["session_cost"]-0.11) < 0.01, "got %.4f" % sm["session_cost"])

print()
print("TOTAL FAILS:", len(fails))
sys.exit(1 if fails else 0)
