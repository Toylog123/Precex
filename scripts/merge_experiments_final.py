#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex ??????????? partial + ?????????????????? A/B/C ???
???python3 scripts/merge_experiments_final.py
"""
import json, os, sys, collections

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO_ROOT, "experiments", "runs")
MAIN = os.path.join(RUNS, "experiments_results_parallel.json")
REPLAY_PARTIAL = os.path.join(RUNS, "replay_results.json.partial.jsonl")
REPLAY_JSON = os.path.join(RUNS, "replay_results.json")
RERUN = os.path.join(RUNS, "rerun_missing.json")


def load_jsonl(p):
    out = []
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    return out


def main():
    d = json.load(open(MAIN, encoding="utf-8"))
    rs = d["results"]
    by_key = {(r["sample"], r["setting"], r["seed"]): r for r in rs}
    print("main results:", len(rs))

    # ?????partial ?????? chunk?
    replays = load_jsonl(REPLAY_PARTIAL)
    if not replays:
        replays = load_jsonl(REPLAY_JSON)
    print("replay records:", len(replays))
    n_replay_pass = 0
    for rec in replays:
        k = (rec["sample"], rec["setting"], rec["seed"])
        if k not in by_key:
            continue
        old = by_key[k]
        if rec.get("repair_pass"):
            n_replay_pass += 1
        old["repair_pass"] = bool(rec.get("repair_pass"))
        old["verdict"] = rec.get("verdict")
        old["replayed"] = True
        old["replayed_attempt"] = rec.get("replayed_attempt")
        if rec.get("eval_error"):
            old["replay_eval_error"] = rec["eval_error"]

    # ????????????
    if os.path.isfile(RERUN):
        rd = json.load(open(RERUN, encoding="utf-8"))
        for rec in rd.get("results", []):
            k = (rec["sample"], rec["setting"], rec["seed"])
            if k in by_key:
                by_key[k].update(rec)
                by_key[k]["rerun"] = True
        print("rerun records:", len(rd.get("results", [])))

    # ??
    with open(MAIN, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("merged -> %s" % MAIN)
    print("replay ? PASS ?:", n_replay_pass)

    # ??
    agg = collections.defaultdict(lambda: {"n": 0, "loc": 0, "rep": 0, "pass": 0, "tok": 0, "cost": 0.0})
    for r in by_key.values():
        st = r["setting"]
        a = agg[st]
        a["n"] += 1
        a["loc"] += 1 if r.get("loc_top1") else 0
        a["rep"] += 1 if r.get("repair_pass") else 0
        a["pass"] += 1 if r.get("verdict") == "PASS" else 0
        a["tok"] += r.get("input_tokens", 0) + r.get("output_tokens", 0)
        a["cost"] += r.get("cost", 0.0)
    print("\n=== ??? A/B/C ===")
    for st in sorted(agg):
        a = agg[st]
        print("%s n=%d loc_top1=%.1f%% repair=%.1f%% pass=%d tok=%d cost=%.3f" % (
            st, a["n"], 100.0 * a["loc"] / a["n"], 100.0 * a["rep"] / a["n"],
            a["pass"], a["tok"], a["cost"]))


if __name__ == "__main__":
    sys.exit(main())
