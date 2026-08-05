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

# 1. Main experiment (clean: leakfix_merged_clean A/B/C 306 + leakfix_D 102)
abc = load("experiments/runs/leakfix_merged_clean.json")["results"]
d = load("experiments/runs/leakfix_D.json")["results"]
allrows = abc + d
agg = collections.defaultdict(lambda: {"n":0,"loc":0,"rep":0,"cost":0.0})
for r in allrows:
    a = agg[r["setting"]]
    a["n"] += 1
    if r.get("loc_top1"): a["loc"] += 1
    if r.get("repair_pass") or str(r.get("verdict","")).startswith("PASS"): a["rep"] += 1
    a["cost"] += float(r.get("cost") or 0)
expect = {"A":(64.7,100.0,0.60),"B":(55.9,100.0,0.40),"C":(59.8,100.0,0.57),"D":(56.9,100.0,0.37)}
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

# 3. L2 (clean protocol: leakfix_l2.json)
l2 = load("experiments/runs/leakfix_l2.json")
l2rows = l2["results"]
tot_n = len(l2rows)
tot_ok = sum(1 for r in l2rows if str(r.get("verdict","")).startswith("PASS"))
tot_loc = sum(1 for r in l2rows if r.get("loc_top1"))
tot_cost = sum(float(r.get("cost") or 0) for r in l2rows)
check("l2 n=72", tot_n == 72, "got %d" % tot_n)
check("l2 rate 91.7", abs(100*tot_ok/tot_n-91.7) < 0.1, "got %.2f" % (100*tot_ok/tot_n))
check("l2 loc 47.2", abs(100*tot_loc/tot_n-47.2) < 0.1, "got %.2f" % (100*tot_loc/tot_n))
check("l2 cost 0.48", abs(tot_cost-0.484) < 0.01, "got %.3f" % tot_cost)

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
rows = []
for _l in open(_ledger_path, encoding="utf-8"):
    _l = _l.strip()
    if not _l:
        continue
    try:
        rows.append(json.loads(_l))
    except Exception:
        continue  # 跳过损坏行（如 mock 截断），账本其余行正常
led_cost = sum(float(r.get("cost_usd", r.get("cost")) or 0) for r in rows)
check("ledger n=2572", len(rows) == 2572, "got %d" % len(rows))
check("ledger cost 22.16", abs(led_cost-22.16) < 0.02, "got %.3f" % led_cost)

# 7. verify timing golden max
vt = load("experiments/runs/verify_timing.json")
gmax = max(x["golden_s"] for x in vt["per_sample"].values())
check("golden max ~153", abs(gmax-152.6) < 2.0, "got %.1f" % gmax)

# 8. ICC
sm = load("experiments/runs/llm_scores/summary.json")
check("icc C causality 0.656", abs(sm["icc"]["C"]["causality"]-0.656) < 0.01, "got %.3f" % sm["icc"]["C"]["causality"])
check("icc C actionability 0.774", abs(sm["icc"]["C"]["actionability"]-0.774) < 0.01, "got %.3f" % sm["icc"]["C"]["actionability"])
check("icc D ~0", sm["icc"]["D"]["causality"] == 0 and sm["icc"]["D"]["actionability"] == 0)
check("interp cost 0.11", abs(sm["session_cost"]-0.114) < 0.01, "got %.4f" % sm["session_cost"])

print()
print("TOTAL FAILS:", len(fails))
sys.exit(1 if fails else 0)
