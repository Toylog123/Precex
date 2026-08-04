#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex ?????????????? LLM ???????
???python3 scripts/rerun_single.py --samples s16,A,0 s16,C,0 s17,B,2 s30,A,2 --timeout 360
"""
import argparse, json, os, signal, sys, tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))

from llm_client import LLMClient
from run_experiments import run_one, SAMPLES_BUGS

OUT = os.path.join(REPO_ROOT, "experiments", "runs", "rerun_missing.json")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True, help="???? sample,setting,seed")
    ap.add_argument("--timeout", type=int, default=360)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    targets = []
    for tok in args.samples.split(","):
        s, st, sd = tok.split(":")
        targets.append((s, st, int(sd)))

    def _alarm(sig, frm):
        raise TimeoutError("????? %ds" % args.timeout)
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(args.timeout)

    llm = LLMClient(mock=False, temperature=0.2)
    out_dir = tempfile.mkdtemp(prefix="rerun_single_")
    results = []
    for sid, st, sd in targets:
        print("== rerun %s %s seed%d" % (sid, st, sd), flush=True)
        try:
            r = run_one(os.path.join(SAMPLES_BUGS, sid), sid, st, sd, llm, out_dir, mock=False, retries=2)
        except Exception as e:
            r = {"sample": sid, "setting": st, "seed": sd, "verdict": None, "repair_pass": False,
                 "attempts": 0, "errors": ["external timeout/err: %s" % e]}
        print("   verdict=%s repair=%s loc=%s att=%d" % (r.get("verdict"), r.get("repair_pass"), r.get("loc_line"), r.get("attempts")), flush=True)
        results.append(r)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"samples": [t[0] for t in targets], "settings": [t[1] for t in targets],
                   "seeds": [t[2] for t in targets], "results": results}, f, ensure_ascii=False, indent=2)
    print("[done] -> %s" % OUT, flush=True)


if __name__ == "__main__":
    sys.exit(main())
