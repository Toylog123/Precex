# -*- coding: utf-8 -*-
"""Rescore all main experiments with corrected ground-truth line numbers.

Authoritative run files:
  A,B : experiments/runs/leakfix_merged_clean.json
  C   : experiments/runs/exp_c_ds_full.json        (102 runs, incl. 7 reruns)
  D   : experiments/runs/leakfix_D.json
  deep: experiments/runs/deep_subset_4settings.json (s38-s42, A/B/C/D)
Ablations (today, for completeness):
  exp_e_ablation.json / exp_e_v2_ablation.json / exp_structural_ablation.json

Output: experiments/runs/loc_rescore_audit.json
"""
import os
import sys
import json
import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
from ground_truth import ground_truth_lines

RUNS = os.path.join(REPO, "experiments", "runs")

MAIN_SOURCES = [
    ("A", "leakfix_merged_clean.json", {"A"}),
    ("B", "leakfix_merged_clean.json", {"B"}),
    ("C", "exp_c_ds_full.json", {"C"}),
    ("D", "leakfix_D.json", {"D"}),
]
DEEP_SOURCE = ("deep", "deep_subset_4settings.json", {"A", "B", "C", "D"})
ABLATION_SOURCES = [
    ("e_ablation", "exp_e_ablation.json", None),
    ("e_v2_ablation", "exp_e_v2_ablation.json", None),
    ("structural_ablation", "exp_structural_ablation.json", None),
]


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d["results"] if isinstance(d, dict) and "results" in d else d


def build_ground_truth():
    gt = {}
    for base in ["bugs", "deep"]:
        d = os.path.join(REPO, "samples", base)
        if not os.path.isdir(d):
            continue
        for sid in sorted(os.listdir(d)):
            sd = os.path.join(d, sid)
            if not os.path.isdir(sd):
                continue
            gt[sid] = ground_truth_lines(sd)
    return gt


def rescore_rows(rows, gt, setting_filter=None, skip_mock=True):
    out = []
    stats = {"n": 0, "old_hits": 0, "new_exact": 0, "new_near1": 0,
             "flips_to_hit": 0, "flips_to_miss": 0, "missing_gt": 0}
    per_sample = {}
    for r in rows:
        if skip_mock and r.get("mock") is True:
            continue
        if setting_filter and r.get("setting") not in setting_filter:
            continue
        sid = r.get("sample")
        stats["n"] += 1
        old = bool(r.get("loc_top1"))
        stats["old_hits"] += int(old)
        loc = r.get("loc_line")
        g = gt.get(sid)
        if g is None or not g.get("lines"):
            stats["missing_gt"] += 1
            new_exact, new_near1, dev_min = False, False, None
        elif loc is None:
            new_exact, new_near1, dev_min = False, False, None
        else:
            dev_min = min(abs(int(loc) - t) for t in g["lines"])
            new_exact = dev_min == 0
            new_near1 = dev_min <= 1
        stats["new_exact"] += int(new_exact)
        stats["new_near1"] += int(new_near1)
        if new_exact and not old:
            stats["flips_to_hit"] += 1
        if (not new_exact) and old:
            stats["flips_to_miss"] += 1
        key = (sid, r.get("setting"))
        ps = per_sample.setdefault(key, {"n": 0, "old": 0, "new_exact": 0,
                                         "new_near1": 0, "locs": []})
        ps["n"] += 1
        ps["old"] += int(old)
        ps["new_exact"] += int(new_exact)
        ps["new_near1"] += int(new_near1)
        ps["locs"].append(loc)
        out.append({
            "sample": sid, "setting": r.get("setting"), "seed": r.get("seed"),
            "loc_line": loc, "old_loc_top1": old,
            "new_exact": new_exact, "new_near1": new_near1,
            "loc_dev_min": dev_min,
        })
    return out, stats, per_sample


def fmt(st):
    n = max(st["n"], 1)
    return "n=%4d old=%3d(%5.1f%%) exact=%3d(%5.1f%%) near1=%3d(%5.1f%%) up=%d down=%d" % (
        st["n"], st["old_hits"], st["old_hits"] / n * 100,
        st["new_exact"], st["new_exact"] / n * 100,
        st["new_near1"], st["new_near1"] / n * 100,
        st["flips_to_hit"], st["flips_to_miss"])


def main():
    gt = build_ground_truth()
    audit = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "method": gt["s04"]["method"] if "s04" in gt else "difflib non-header",
        "criterion": "loc_line in ground-truth defect lines (exact); "
                     "loc_dev_min <= 1 for near",
        "samples": {sid: {"lines": g["lines"], "content_lines": g["content_lines"],
                          "regions": g["regions"]}
                    for sid, g in sorted(gt.items())},
        "main": {},
        "deep": {},
        "ablations": {},
    }

    # main A/B/C/D
    for label, fn, sf in MAIN_SOURCES:
        rows = load_rows(os.path.join(RUNS, fn))
        out, stats, per_sample = rescore_rows(rows, gt, sf)
        audit["main"][label] = {"file": fn, "stats": stats, "rows": out,
                                "per_sample": {f"{k[0]}/{k[1]}": v
                                               for k, v in sorted(per_sample.items())}}
        print(label, fmt(stats))

    # deep
    fn, sf = DEEP_SOURCE[1], DEEP_SOURCE[2]
    rows = load_rows(os.path.join(RUNS, fn))
    out, stats, per_sample = rescore_rows(rows, gt, sf)
    audit["deep"] = {"file": fn, "stats": stats, "rows": out,
                     "per_sample": {f"{k[0]}/{k[1]}": v
                                    for k, v in sorted(per_sample.items())}}
    print("deep", fmt(stats))

    # ablations
    for label, fn, sf in ABLATION_SOURCES:
        rows = load_rows(os.path.join(RUNS, fn))
        out, stats, per_sample = rescore_rows(rows, gt, sf, skip_mock=False)
        audit["ablations"][label] = {"file": fn, "stats": stats, "rows": out,
                                     "per_sample": {f"{k[0]}/{k[1]}": v
                                                    for k, v in sorted(per_sample.items())}}
        print(label, fmt(stats))

    out_path = os.path.join(RUNS, "loc_rescore_audit.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1)
    print("\nWROTE", out_path)

    # per-sample summary for main (new exact hits across seeds)
    print("\n=== per-sample (new exact, A/B/C/D main) ===")
    for label in ["A", "B", "C", "D"]:
        ps = audit["main"][label]["per_sample"]
        row = " ".join("%s:%d/%d" % (k.split("/")[0], v["new_exact"], v["n"])
                       for k, v in ps.items())
        print(label, row)


if __name__ == "__main__":
    main()
