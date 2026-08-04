#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex ?????????????? llm_outputs/ ???? LLM ??????????? LLM??
?????? + evaluator ?????? sby ??????? 3 ?????/?????????
???WSL ???python3 scripts/replay_saved_outputs.py --samples s16:A:0,s16:C:0,s17:B:2
"""
import argparse, json, os, re, shutil, sys, tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from run_prestudy import parse_llm_output, apply_unified_diff  # noqa: E402
import evaluator  # noqa: E402

LLM_OUT_DIR = os.path.join(REPO_ROOT, "experiments", "runs", "llm_outputs")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True, help="???? sample:setting:seed")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "experiments", "runs", "replay_saved.json"))
    ap.add_argument("--attempts", type=int, default=4, help="???????? attempt ??")
    args = ap.parse_args(argv)

    targets = []
    for tok in args.samples.split(","):
        s, st, sd = tok.split(":")
        targets.append((s, st, int(sd)))

    results = []
    for sid, st, sd in targets:
        sample_dir = os.path.join(REPO_ROOT, "samples", "bugs", sid)
        design = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
        meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
        best = None
        print("== replay %s %s seed%d" % (sid, st, sd), flush=True)
        for attempt in range(args.attempts):
            raw_path = os.path.join(LLM_OUT_DIR, "%s_%s_seed%d_a%d.txt" % (sid, st, sd, attempt))
            if not os.path.isfile(raw_path):
                print("   attempt %d: no saved output" % attempt, flush=True)
                continue
            content = open(raw_path, encoding="utf-8").read()
            loc, diff_text = parse_llm_output(content)
            if not diff_text:
                print("   attempt %d: no diff in saved output" % attempt, flush=True)
                continue
            ok, patched, err = apply_unified_diff(design, diff_text)
            if not ok:
                print("   attempt %d: diff apply failed: %s" % (attempt, err[:120]), flush=True)
                continue
            work = tempfile.mkdtemp(prefix="replay_saved_%s_%s_s%d_" % (sid, st, sd))
            try:
                with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
                    f.write(patched)
                for fname in ("tb_weak.sv", "verify.sby"):
                    src = os.path.join(sample_dir, fname)
                    if os.path.isfile(src):
                        shutil.copy(src, os.path.join(work, fname))
                rp_src = os.path.join(sample_dir, "verify_repair.sby")
                if os.path.isfile(rp_src):
                    shutil.copy(rp_src, os.path.join(work, "verify_repair.sby"))
                    if os.path.isfile(os.path.join(work, "verify.sby")):
                        os.remove(os.path.join(work, "verify.sby"))
                if meta.get("module") == "uart_rx":
                    src = os.path.join(sample_dir, "uart_tx.sv")
                    if os.path.isfile(src):
                        shutil.copy(src, os.path.join(work, "uart_tx.sv"))
                tb_top = None
                tb_path = os.path.join(work, "tb_weak.sv")
                if os.path.isfile(tb_path):
                    m = re.search(r"module\s+(tb_\w+)", open(tb_path, encoding="utf-8").read())
                    if m:
                        tb_top = m.group(1)
                ev = evaluator.evaluate(work, {"run_formal": True, "verbose": False, "tb_top": tb_top})
                print("   attempt %d: verdict=%s" % (attempt, ev["verdict"]), flush=True)
                if ev["verdict"] == "PASS":
                    best = {"sample": sid, "setting": st, "seed": sd, "replayed_attempt": attempt,
                            "verdict": "PASS", "repair_pass": True, "loc_line": loc["line"]}
                    break
                best = {"sample": sid, "setting": st, "seed": sd, "replayed_attempt": attempt,
                        "verdict": ev["verdict"], "repair_pass": False, "loc_line": loc["line"],
                        "eval_error": ev.get("formal", {}).get("result")}
            finally:
                shutil.rmtree(work, ignore_errors=True)
        rec = best or {"sample": sid, "setting": st, "seed": sd, "verdict": None, "repair_pass": False}
        results.append(rec)
        print("[done] %s %s seed%d -> %s" % (sid, st, sd, rec.get("verdict")), flush=True)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("[saved replay complete] -> %s" % args.out, flush=True)


if __name__ == "__main__":
    sys.exit(main())
