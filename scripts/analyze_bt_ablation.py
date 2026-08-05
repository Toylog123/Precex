# -*- coding: utf-8 -*-
"""PreCex - scripts/analyze_bt_ablation.py
1a: B vs B+T 配对消融分析（DeepSeek v4-flash，34 样本 x 3 种子）。
输出 experiments/runs/bt_vs_b_analysis.json + .csv。
度量：strict loc_top1（冻结口径）+ win4（|loc_line - buggy_inject_line|<=4，删除/插入锚点歧义修正）。
"""
import json, io, csv, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B_FILE = os.path.join(REPO, "experiments/runs/experiments_results_ds_full3.json")
BT_FILE = os.path.join(REPO, "experiments/runs/bt_ablation_ds_bt3.json")
OUT_JSON = os.path.join(REPO, "experiments/runs/bt_vs_b_analysis.json")
OUT_CSV = os.path.join(REPO, "experiments/runs/bt_vs_b_analysis.csv")

def load(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def buggy_line(sid):
    p = os.path.join(REPO, "samples/bugs/%s/meta.json" % sid)
    if not os.path.isfile(p):
        return None
    with io.open(p, "r", encoding="utf-8") as f:
        return json.load(f).get("buggy_inject_line")

def row_metrics(r):
    ll = r.get("loc_line")
    bl = r.get("_buggy_line")
    strict = bool(r.get("loc_top1"))
    win4 = False
    if ll is not None and bl is not None:
        try:
            win4 = abs(int(ll) - int(bl)) <= 4
        except (TypeError, ValueError):
            pass
    return strict, win4

def agg(rows):
    n = len(rows)
    if n == 0:
        return None
    strict = sum(1 for r in rows if r["strict"])
    win4 = sum(1 for r in rows if r["win4"])
    return {
        "n": n,
        "loc_top1": strict,
        "loc_top1_rate": strict / n,
        "loc_win4": win4,
        "loc_win4_rate": win4 / n,
        "repair_pass": sum(1 for r in rows if r.get("repair_pass")),
        "repair_pass_rate": sum(1 for r in rows if r.get("repair_pass")) / n,
        "cost": sum(r.get("cost") or 0 for r in rows),
        "attempts_avg": sum(r.get("attempts") or 0 for r in rows) / n,
    }

b_all = [x for x in load(B_FILE)["results"] if x.get("setting") == "B"]
bt_all = load(BT_FILE)["results"]
assert len(b_all) == 102 and len(bt_all) == 102, (len(b_all), len(bt_all))

samples = sorted({x["sample"] for x in b_all})
per_sample = []
for sid in samples:
    bl = buggy_line(sid)
    rb = []
    for x in b_all:
        if x["sample"] == sid:
            x = dict(x); x["_buggy_line"] = bl
            s, w = row_metrics(x)
            x["strict"], x["win4"] = s, w
            rb.append(x)
    rt = []
    for x in bt_all:
        if x["sample"] == sid:
            x = dict(x); x["_buggy_line"] = bl
            s, w = row_metrics(x)
            x["strict"], x["win4"] = s, w
            rt.append(x)
    ab, at = agg(rb), agg(rt)
    per_sample.append({
        "sample": sid,
        "error_type": rb[0].get("error_type") if rb else None,
        "B": ab, "BT": at,
        "delta_strict": at["loc_top1"] - ab["loc_top1"],
        "delta_win4": at["loc_win4"] - ab["loc_win4"],
    })

cats = ["状态跳转", "握手"]
by_cat = {}
for c in cats + ["ALL"]:
    rb = [x for x in b_all] if c == "ALL" else [x for x in b_all if x.get("error_type") == c]
    rt = [x for x in bt_all] if c == "ALL" else [x for x in bt_all if x.get("error_type") == c]
    for x in rb:
        x = dict(x); x["_buggy_line"] = buggy_line(x["sample"])
        x["strict"], x["win4"] = row_metrics(x)
    for x in rt:
        x = dict(x); x["_buggy_line"] = buggy_line(x["sample"])
        x["strict"], x["win4"] = row_metrics(x)
    by_cat[c] = {"B": agg(rb), "BT": agg(rt)}
others = [c for c in sorted({x.get("error_type") for x in b_all}) if c not in cats]
rb_o = []
rt_o = []
for x in b_all:
    if x.get("error_type") in others:
        x = dict(x); x["_buggy_line"] = buggy_line(x["sample"])
        x["strict"], x["win4"] = row_metrics(x)
        rb_o.append(x)
for x in bt_all:
    if x.get("error_type") in others:
        x = dict(x); x["_buggy_line"] = buggy_line(x["sample"])
        x["strict"], x["win4"] = row_metrics(x)
        rt_o.append(x)
by_cat["OTHER"] = {"B": agg(rb_o), "BT": agg(rt_o)}

report = {
    "note": "B vs BT 配对消融（DeepSeek v4-flash，34 样本 x 3 种子，retries=2，feedback=v1）。"
            "strict=精确行命中；win4=|loc_line-buggy_inject_line|<=4（删除/插入锚点歧义修正）。",
    "b_file": "experiments/runs/experiments_results_ds_full3.json",
    "bt_file": "experiments/runs/bt_ablation_ds_bt3.json",
    "per_sample": per_sample,
    "by_category": by_cat,
}
with io.open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
with io.open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["sample", "error_type", "B_strict3", "BT_strict3", "delta_strict",
                "B_win4_3", "BT_win4_3", "delta_win4", "B_cost", "BT_cost"])
    for ps in per_sample:
        w.writerow([ps["sample"], ps["error_type"],
                    ps["B"]["loc_top1"], ps["BT"]["loc_top1"], ps["delta_strict"],
                    ps["B"]["loc_win4"], ps["BT"]["loc_win4"], ps["delta_win4"],
                    "%.4f" % ps["B"]["cost"], "%.4f" % ps["BT"]["cost"]])
    w.writerow([])
    for c, v in by_cat.items():
        w.writerow(["CATEGORY_" + c, "",
                    v["B"]["loc_top1"], v["BT"]["loc_top1"], v["BT"]["loc_top1"] - v["B"]["loc_top1"],
                    v["B"]["loc_win4"], v["BT"]["loc_win4"], v["BT"]["loc_win4"] - v["B"]["loc_win4"],
                    "%.4f" % v["B"]["cost"], "%.4f" % v["BT"]["cost"]])
print(json.dumps(by_cat, ensure_ascii=False, indent=2))
print("saved:", OUT_JSON)
