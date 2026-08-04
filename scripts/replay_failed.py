#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex ?????????? repair_pass=False ?? diff apply failed ????
? llm_outputs/ ????????? attempt ??? diff???????????????
??? evaluator ??????? LLM ?????? sby ?????
???WSL ???
  python3 scripts/replay_failed.py --samples s14 --settings A,B,C --seeds 0,1,2
      --results experiments/runs/experiments_results_parallel.json
      --out experiments/runs/replay_results.json
"""
import argparse, glob, json, os, re, shutil, sys, tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from run_prestudy import parse_llm_output, apply_unified_diff  # noqa: E402
import evaluator  # noqa: E402


def expand_samples(spec):
    ids = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^s(\d+)-s(\d+)$", part)
        if m:
            ids += ["s%02d" % i for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            ids.append(part)
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="")
    ap.add_argument("--settings", default="A,B,C")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--results", default=os.path.join(REPO_ROOT, "experiments", "runs", "experiments_results_parallel.json"))
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "experiments", "runs", "replay_results.json"))
    ap.add_argument("--llm-outputs", default=os.path.join(REPO_ROOT, "experiments", "runs", "llm_outputs"))
    args = ap.parse_args(argv)

    results = json.load(open(args.results, encoding="utf-8"))["results"]
    samples = expand_samples(args.samples) or sorted({r["sample"] for r in results})
    settings = args.settings.split(",")
    seeds = [int(x) for x in args.seeds.split(",")]

    partial = args.out + ".partial.jsonl"
    done = set()
    if os.path.isfile(partial):
        with open(partial, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                    done.add((rec["sample"], rec["setting"], rec["seed"]))
                except Exception:
                    pass

    targets = []
    for r in results:
        if r["sample"] not in samples or r["setting"] not in settings or r["seed"] not in seeds:
            continue
        if r["repair_pass"]:
            continue
        errs = r.get("errors") or []
        if not any("diff apply failed" in e for e in errs):
            continue
        targets.append(r)
    print("replay targets: %d" % len(targets), flush=True)

    llm_out_dir = args.llm_outputs
    out_list = []
    for t in targets:
        key = (t["sample"], t["setting"], t["seed"])
        if key in done:
            continue
        sample_dir = os.path.join(REPO_ROOT, "samples", "bugs", t["sample"])
        design = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
        meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
        best = None
        for attempt in range(t.get("attempts", 3)):
            raw_path = os.path.join(llm_out_dir, "%s_%s_seed%d_a%d.txt" % (t["sample"], t["setting"], t["seed"], attempt))
            if not os.path.isfile(raw_path):
                continue
            content = open(raw_path, encoding="utf-8").read()
            loc, diff_text = parse_llm_output(content)
            if not diff_text:
                continue
            ok, patched, err = apply_unified_diff(design, diff_text)
            if not ok:
                continue
            work = tempfile.mkdtemp(prefix="replay_%s_%s_s%d_" % (t["sample"], t["setting"], t["seed"]))
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
                if ev["verdict"] == "PASS":
                    best = {"sample": t["sample"], "setting": t["setting"], "seed": t["seed"],
                            "replayed_attempt": attempt, "verdict": "PASS", "repair_pass": True,
                            "loc_line": loc["line"], "diff_text": diff_text[:4000]}
                    break
                best = {"sample": t["sample"], "setting": t["setting"], "seed": t["seed"],
                        "replayed_attempt": attempt, "verdict": ev["verdict"], "repair_pass": False,
                        "loc_line": loc["line"], "diff_text": diff_text[:4000],
                        "eval_error": ev.get("formal", {}).get("result")}
                print("[%s %s s%d] attempt%d verdict=%s" % (t["sample"], t["setting"], t["seed"], attempt, ev["verdict"]), flush=True)
            finally:
                shutil.rmtree(work, ignore_errors=True)
        rec = best or {"sample": t["sample"], "setting": t["setting"], "seed": t["seed"],
                       "verdict": None, "repair_pass": False, "replayed_attempt": None}
        with open(partial, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_list.append(rec)
        print("[done] %s %s s%d -> %s" % (t["sample"], t["setting"], t["seed"], rec.get("verdict")), flush=True)
    # 结束时把 partial（含此前各 chunk 已完成的记录）合并写回 --out JSON
    all_recs = []
    if os.path.isfile(partial):
        with open(partial, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        all_recs.append(json.loads(ln))
                    except Exception:
                        pass
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_recs, f, ensure_ascii=False, indent=2)
    print("[replay merged] total=%d new=%d -> %s" % (len(all_recs), len(out_list), args.out), flush=True)


if __name__ == "__main__":
    sys.exit(main())
