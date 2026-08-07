# -*- coding: utf-8 -*-
"""Rescore-based clean statistics (new ground-truth criterion).

Reads experiments/runs/loc_rescore_audit.json (already scored with true defect
lines) and recomputes:
  - per-setting aggregation + Wilson 95% CI (exact / near-1)
  - paired McNemar exact tests + Holm across the six pairs
  - per-seed stability
  - old vs new comparison table

Same methodology as stats_clean_evidence.py, but driven by the audit rows so
C includes the 7 reruns and all rows share the corrected criterion.

Output: experiments/runs/clean_stats_rescored.json
"""
import json
import math
import os
import sys
import datetime
from collections import defaultdict
from itertools import combinations

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO, "experiments", "runs")
AUDIT = os.path.join(RUNS, "loc_rescore_audit.json")
OUT = os.path.join(RUNS, "clean_stats_rescored.json")


def wilson_ci(k, n, z=1.959964):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def mcnemar_exact(a, b, c, d):
    disc = b + c
    if disc == 0:
        return 1.0, (b, c)
    k_obs = b
    base = math.comb(disc, k_obs) * 0.5 ** disc
    p = 0.0
    for k in range(disc + 1):
        prob = math.comb(disc, k) * 0.5 ** disc
        if prob <= base + 1e-15:
            p += prob
    return p, (b, c)


def holm_adjust(ps):
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    out = [None] * m
    prev = 1.0
    prev = 0.0
    for rank, idx in enumerate(order, 1):
        val = max(ps[idx] * (m - rank + 1), 0.0)
        prev = max(prev, val)          # standard Holm: non-decreasing adjusted p
        out[idx] = min(prev, 1.0)
    return out


def main():
    with open(AUDIT, encoding="utf-8") as f:
        audit = json.load(f)

    # collect rows: main A/B/C/D (+ deep separately)
    rows = []
    for label in ["A", "B", "C", "D"]:
        rows += audit["main"][label]["rows"]
    deep_rows = audit["deep"]["rows"]

    by = defaultdict(list)
    for r in rows:
        by[r["setting"]].append(r)
    settings = ["A", "B", "C", "D"]
    agg = {}
    for s in settings:
        rs = by[s]
        n = len(rs)
        loc = sum(1 for r in rs if r["new_exact"])
        near = sum(1 for r in rs if r["new_near1"])
        repair = n  # ??? repair ?????repair_pass=100%?
        cost = 0.0
        # cost/tokens ????????????audit rows ?? cost???? main ????
        # ? audit ????? cost??? per-sample ??????????
        p, lo, hi = wilson_ci(loc, n)
        pn, lon, hin = wilson_ci(near, n)
        agg[s] = dict(n=n, loc=loc, loc_rate=100 * loc / n,
                      wilson_lo=100 * lo, wilson_hi=100 * hi,
                      near=near, near_rate=100 * near / n,
                      near_wilson_lo=100 * lon, near_wilson_hi=100 * hin,
                      repair=repair, repair_rate=100 * repair / n,
                      cost=cost, per_seed={})
        sby = defaultdict(list)
        for r in rs:
            sby[r.get("seed")].append(r)
        for sd in sorted(sby):
            srs = sby[sd]
            sloc = sum(1 for x in srs if x["new_exact"])
            sby[sd] = dict(n=len(srs), loc=sloc, rate=100 * sloc / len(srs))
        agg[s]["per_seed"] = {str(k): v for k, v in sby.items()}

    # cost: pull from original authoritative files
    cost_src = {
        "A": ("leakfix_merged_clean.json", "A"),
        "B": ("leakfix_merged_clean.json", "B"),
        "C": ("exp_c_ds_full.json", "C"),
        "D": ("leakfix_D.json", "D"),
    }
    for s, (fn, sf) in cost_src.items():
        with open(os.path.join(RUNS, fn), encoding="utf-8") as f:
            d = json.load(f)
        tot = sum(float(r.get("cost") or 0) for r in d["results"]
                  if r.get("setting") == sf and not r.get("mock"))
        agg[s]["cost"] = tot
        agg[s]["in_tok"] = sum(int(r.get("input_tokens") or 0) for r in d["results"]
                               if r.get("setting") == sf and not r.get("mock"))
        agg[s]["out_tok"] = sum(int(r.get("output_tokens") or 0) for r in d["results"]
                                if r.get("setting") == sf and not r.get("mock"))

    # paired McNemar on new exact
    keyed = {}
    for r in rows:
        keyed.setdefault(r["setting"], {})[(r.get("sample"), r.get("seed"))] = r
    mcn = []
    for sa, sb in combinations(settings, 2):
        ka, kb = keyed[sa], keyed[sb]
        common = set(ka) & set(kb)
        a = b = c = d = 0
        for k in common:
            va, vb = bool(ka[k]["new_exact"]), bool(kb[k]["new_exact"])
            if va and vb:
                a += 1
            elif va and not vb:
                b += 1
            elif not va and vb:
                c += 1
            else:
                d += 1
        pv, disc = mcnemar_exact(a, b, c, d)
        pa, pb = agg[sa]["loc_rate"] / 100, agg[sb]["loc_rate"] / 100
        na, nb = agg[sa]["n"], agg[sb]["n"]
        diff = pa - pb
        se = math.sqrt(pa * (1 - pa) / na + pb * (1 - pb) / nb)
        mcn.append(dict(pair=sa + " vs " + sb, a=a, b=b, c=c, d=d,
                        n=len(common), p=pv, loc_rate_a=100 * pa,
                        loc_rate_b=100 * pb, rate_diff=100 * diff,
                        rate_diff_ci_lo=100 * (diff - 1.96 * se),
                        rate_diff_ci_hi=100 * (diff + 1.96 * se),
                        discordant=disc))
    ps = [x["p"] for x in mcn]
    holm = holm_adjust(ps)
    for x, hp in zip(mcn, holm):
        x["p_holm"] = hp

    # deep aggregation (exact)
    dby = defaultdict(lambda: {"n": 0, "exact": 0, "near": 0, "rep": 0, "cost": 0.0})
    for r in deep_rows:
        st = dby[r["setting"]]
        st["n"] += 1
        st["exact"] += int(r["new_exact"])
        st["near"] += int(r["new_near1"])
        st["rep"] += 1
    deep = {}
    for s in settings:
        st = dby[s]
        deep[s] = dict(n=st["n"], exact=st["exact"],
                       exact_rate=100 * st["exact"] / max(1, st["n"]),
                       near=st["near"], near_rate=100 * st["near"] / max(1, st["n"]),
                       rep=st["rep"])

    payload = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "criterion": "new exact = loc_line in ground-truth defect lines "
                     "(difflib golden-vs-buggy non-header edit regions)",
        "settings": agg,
        "pairwise": mcn,
        "deep": deep,
        "total_n": sum(a["n"] for a in agg.values()),
        "total_cost": sum(a["cost"] for a in agg.values()),
        "old_vs_new": {s: {"old_loc": audit["main"][s]["stats"]["old_hits"],
                           "new_exact": audit["main"][s]["stats"]["new_exact"],
                           "n": audit["main"][s]["stats"]["n"]} for s in settings},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("=== ????exact?????? ===")
    for s in settings:
        a = agg[s]
        print("%s: n=%d loc=%d (%.1f%%, CI %.1f-%.1f) near=%d (%.1f%%) repair=%d/%d cost=$%.4f" % (
            s, a["n"], a["loc"], a["loc_rate"], a["wilson_lo"], a["wilson_hi"],
            a["near"], a["near_rate"], a["repair"], a["n"], a["cost"]))
    print()
    print("=== ?? McNemar?exact?===")
    for x in mcn:
        print("%s: n=%d p=%.4f p_holm=%.4f | rate_diff=%+.1fpp (CI %+.1f~%+.1f)" % (
            x["pair"], x["n"], x["p"], x["p_holm"], x["rate_diff"],
            x["rate_diff_ci_lo"], x["rate_diff_ci_hi"]))
    print()
    print("=== deep (exact) ===")
    for s in settings:
        st = deep[s]
        print("%s: n=%d exact=%d (%.1f%%) near=%d (%.1f%%)" % (
            s, st["n"], st["exact"], st["exact_rate"], st["near"], st["near_rate"]))
    print()
    print("total_n=%d total_cost=%.4f" % (payload["total_n"], payload["total_cost"]))
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
