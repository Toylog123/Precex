#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - scripts/multi_candidate.py multi-candidate repair arbitration (WP5)
Author: Toylog | Version: v0.1 | Purpose: for a given (sample, setting), call LLM
at 3 temperatures (0.2/0.5/0.8) to generate independent patch candidates, verify
each via golden-first BMC at base depth (reuse adaptive_bmc helpers), and rank
by arbitration score = 0.5*depth_ratio + 0.3*(1-lines/max_lines) + 0.2*top_pass.
Output experiments/runs/multi_candidate_report.json.
Usage (in WSL): python3 scripts/multi_candidate.py --samples s04 --settings B
      [--provider deepseek] [--mock] [--jobs 4] [--out <json>]
"""
from __future__ import annotations
import argparse, json, os, re, shutil, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))
from llm_client import LLMClient  # noqa: E402
from prompt_templates import SYSTEM_PROMPT, build_prompt  # noqa: E402
from run_prestudy import parse_llm_output, apply_unified_diff  # noqa: E402
from adaptive_bmc import _find_sample_dir, _read_depth, _make_workdir, _formal_at_depth, _tb_top  # noqa: E402
import evaluator  # noqa: E402

BUGS = os.path.join(REPO_ROOT, "samples", "bugs")
DEEP = os.path.join(REPO_ROOT, "samples", "deep")
DEFAULT_OUT = os.path.join(REPO_ROOT, "experiments", "runs", "multi_candidate_report.json")
TEMPERATURES = [0.2, 0.5, 0.8]
BUGGY_HEADER_OFFSET = 4


def _extract_assertions(design):
    m = re.search(r"//.*?内联强断言.*?\n(.*?)\n\s*endmodule\b", design, re.S)
    if m:
        return m.group(1).strip()
    lines = design.splitlines()
    out = []
    for i, ln in enumerate(lines, 1):
        if "assert" in ln and "//" not in ln.split("assert")[0]:
            out.append("%4d: %s" % (i, ln))
    return "\n".join(out) if out else "（未提取到独立断言段，断言已内联于设计）"


def _evidence_text(setting, sample_dir):
    if setting == "A":
        parts = []
        log = os.path.join(sample_dir, "cex.log")
        vcd = os.path.join(sample_dir, "cex.vcd")
        if os.path.isfile(log):
            parts.append("[cex.log]" + chr(10) + open(log, encoding="utf-8", errors="replace").read())
        if os.path.isfile(vcd):
            lines = open(vcd, encoding="utf-8", errors="replace").read().splitlines()
            parts.append("[cex.vcd]" + chr(10) + chr(10).join(lines[:80]))
        return chr(10).join(parts)
    if setting == "B":
        p = os.path.join(sample_dir, "evidence.json")
        return open(p, encoding="utf-8").read() if os.path.isfile(p) else "（evidence.json 缺失）"
    if setting == "C":
        p = os.path.join(sample_dir, "semantics.json")
        return open(p, encoding="utf-8").read() if os.path.isfile(p) else "（semantics.json 缺失）"
    raise ValueError("setting must be A/B/C")


def _patch_lines(diff_text):
    add = sum(1 for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    rem = sum(1 for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return add + rem


def _verify_patch(sample_dir, patched_src, base_depth, timeout):
    workdir = _make_workdir(sample_dir, "mc_tmp", patched_src)
    try:
        tb_top = _tb_top(workdir)
        files = [os.path.join(workdir, "buggy.v")]
        if tb_top:
            files.append(os.path.join(workdir, "tb_weak.sv"))
        sim = evaluator.sim_check(files, top=tb_top, out_bin=os.path.join(workdir, "sim.out"), cwd=workdir)
        sim_ok = sim["ok"]
        repaired = _formal_at_depth(workdir, "verify.sby", base_depth, timeout)
        golden = _formal_at_depth(workdir, "verify_golden.sby", base_depth, timeout)
        pass_ok = (
            repaired.get("result") in ("pass", "prove")
            and golden.get("result") in ("pass", "prove")
            and sim_ok
        )
        return {
            "sim_ok": sim_ok,
            "repaired": repaired.get("result"),
            "golden": golden.get("result"),
            "pass_ok": pass_ok,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _generate_candidate(sample_dir, sample_id, setting, temp, llm, timeout, base_depth):
    meta = json.load(open(os.path.join(sample_dir, "meta.json"), encoding="utf-8"))
    design = open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8").read()
    assertions = _extract_assertions(design)
    ev_text = _evidence_text(setting, sample_dir)
    prompt = build_prompt(setting, design, assertions, ev_text, meta)
    prompt += "\n【多候选】temperature=%.1f 独立生成补丁候选，请勿重复其他候选方案。\n" % temp
    row = {"temp": temp, "loc_top1": False, "pass_ok": False, "lines": 0,
           "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "diff": "", "error": ""}
    try:
        res = llm.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=temp,
            tag="wp5:%s:%s:t%.1f" % (sample_id, setting, temp),
        )
    except Exception as e:
        row["error"] = "llm: %s" % e
        return row
    row["input_tokens"] = res["input_tokens"]
    row["output_tokens"] = res["output_tokens"]
    row["cost"] = res["cost"]
    loc, diff_text = parse_llm_output(res["content"])
    row["loc_line"] = loc.get("line")
    golden_line = meta.get("inject_line")
    buggy_line = meta.get("buggy_inject_line", (golden_line + BUGGY_HEADER_OFFSET) if golden_line else None)
    row["loc_top1"] = (loc.get("line") == buggy_line)
    if not diff_text:
        row["error"] = "no_diff"
        return row
    ok, patched, err = apply_unified_diff(design, diff_text)
    if not ok:
        row["error"] = "apply: %s" % (err or "")[:120]
        return row
    row["diff"] = diff_text[:4000]
    row["lines"] = _patch_lines(diff_text)
    v = _verify_patch(sample_dir, patched, base_depth, timeout)
    row.update(v)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="s04")
    ap.add_argument("--settings", default="B")
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--temps", default="0.2,0.5,0.8")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=150.0)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    temps = [float(x) for x in args.temps.split(",") if x.strip()]
    samples = [s.strip() for s in args.samples.split(",") if s.strip()]
    settings = [s.strip() for s in args.settings.split(",") if s.strip()]
    llm = LLMClient(mock=args.mock, temperature=0.2, provider=args.provider)
    results = []
    total = len(samples) * len(settings) * len(temps)
    print("tasks: %d samples x %d settings x %d temps" % (len(samples), len(settings), len(temps)), flush=True)

    def _run(args2):
        sid, st, temp = args2
        sample_dir = _find_sample_dir(sid)
        if sample_dir is None:
            return {"sample": sid, "setting": st, "temp": temp, "error": "no_sample"}
        base = _read_depth(os.path.join(sample_dir, "verify.sby"))
        if not base:
            return {"sample": sid, "setting": st, "temp": temp, "error": "no_depth"}
        c = _generate_candidate(sample_dir, sid, st, temp, llm, args.timeout, base)
        c.update({"sample": sid, "setting": st, "temp": temp, "base_depth": base})
        return c

    tasks = [(s, st, t) for s in samples for st in settings for t in temps]
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(_run, t) for t in tasks]
        for fu in as_completed(futs):
            r = fu.result()
            results.append(r)
            print("[%d] %s/%s/t%.1f pass=%s loc=%s lines=%d" % (
                len(results), r.get("sample"), r.get("setting"), r.get("temp"),
                r.get("pass_ok"), r.get("loc_top1"), r.get("lines", 0)), flush=True)

    # arbitration: group by (sample, setting)
    groups = {}
    for r in results:
        groups.setdefault((r.get("sample"), r.get("setting")), []).append(r)
    ranked = []
    for key, cands in sorted(groups.items()):
        max_lines = max([c.get("lines", 0) for c in cands] or [1])
        for c in cands:
            depth_ratio = 1.0 if c.get("pass_ok") else 0.0
            lines_term = 1.0 - (c.get("lines", 0) / max(max_lines, 1))
            top_term = 1.0 if c.get("pass_ok") else 0.0
            c["score"] = round(0.5 * depth_ratio + 0.3 * lines_term + 0.2 * top_term, 3)
        cands.sort(key=lambda x: -x.get("score", 0))
        ranked.append({"sample": key[0], "setting": key[1], "candidates": cands,
                       "best": cands[0], "any_pass": any(c.get("pass_ok") for c in cands)})
    n_any = sum(1 for g in ranked if g["any_pass"])
    summary = {
        "groups": len(ranked),
        "any_pass_groups": n_any,
        "any_pass_rate": round(100.0 * n_any / max(1, len(ranked)), 1),
        "best_temp_dist": {},
    }
    for g in ranked:
        bt = g["best"].get("temp")
        summary["best_temp_dist"][str(bt)] = summary["best_temp_dist"].get(str(bt), 0) + 1
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "groups": ranked}, f, ensure_ascii=False, indent=2)
    print("=== SUMMARY ===", flush=True)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print("[done] -> %s" % args.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
