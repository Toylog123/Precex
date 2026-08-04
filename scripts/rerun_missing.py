#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex ???????? MiniMax ??????? 4 ????s16/A/0, s16/C/0, s17/B/2, s30/A/2??
?? run_experiments.run_one??????????? LLM ?????? experiments/runs/rerun_missing.json?
???WSL ???python3 scripts/rerun_missing.py
"""
import json, os, sys, tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))

from llm_client import LLMClient  # noqa: E402
from run_experiments import run_one, SAMPLES_BUGS  # noqa: E402

TARGETS = [("s16", "A", 0), ("s16", "C", 0), ("s17", "B", 2), ("s30", "A", 2)]
OUT = os.path.join(REPO_ROOT, "experiments", "runs", "rerun_missing.json")


def main():
    llm = LLMClient(mock=False, temperature=0.2)
    out_dir = tempfile.mkdtemp(prefix="rerun_work_")
    results = []
    for sid, st, sd in TARGETS:
        sample_dir = os.path.join(SAMPLES_BUGS, sid)
        print("== rerun %s %s seed%d" % (sid, st, sd), flush=True)
        r = run_one(sample_dir, sid, st, sd, llm, out_dir, mock=False, retries=2)
        print("   verdict=%s repair=%s loc=%s att=%d" % (
            r.get("verdict"), r.get("repair_pass"), r.get("loc_line"), r.get("attempts")), flush=True)
        results.append(r)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"samples": [t[0] for t in TARGETS], "settings": [t[1] for t in TARGETS],
                   "seeds": [t[2] for t in TARGETS], "results": results}, f, ensure_ascii=False, indent=2)
    print("[rerun done] -> %s" % OUT, flush=True)


if __name__ == "__main__":
    sys.exit(main())
