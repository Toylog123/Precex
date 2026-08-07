# -*- coding: utf-8 -*-
"""阶段 1b：StructuralRepairer 完整 formal 验证（compile→sim→BMC golden-first）。

6 个 hardest 状态迁移样本（s07/s08/s09/s18/s36/s15）x {plain, structural} x 3 seeds
= 36 次真实调用，输出 experiments/runs/exp_structural_formal.json。

统计：
- loc：exact / ±1 / ±2（ground_truth_lines 真值）
- 修复：evaluator 完整 verdict（compile→sim→BMC golden-first）
- 补丁规模：diff 中 +/- 行数
- 接口/断言变更检测：diff +/- 行含 assert/assume/module/端口 关键字

用法（WSL）：
  python3 scripts/run_structural_formal.py --out experiments/runs/exp_structural_formal.json
  python3 scripts/run_structural_formal.py --mock --limit 1   # 管线自检
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "harness"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "configs"))
sys.path.insert(0, os.path.join(REPO_ROOT, "agents", "local_repairer"))

from llm_client import LLMClient  # noqa: E402
from prompt_templates import SYSTEM_PROMPT, build_prompt, sanitize_design_text  # noqa: E402
from run_prestudy import parse_llm_output, apply_unified_diff  # noqa: E402
from run_hygiene_ablation import _load_json, _sanitize_diff_lines  # noqa: E402
import run_experiments as rex  # noqa: E402
import evaluator  # noqa: E402
from ground_truth import ground_truth_lines  # noqa: E402
from structural_repairer import apply_structural_mode  # noqa: E402

TARGETS = ["s07", "s08", "s09", "s18", "s36", "s15"]
MODES = ["plain", "structural"]
SEEDS = [0, 1, 2]

INTERFACE_RE = re.compile(r"\b(assert|assume|property|module|input|output|inout)\b")


def _load_done(path):
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"results": []}


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_structural_prompt(sample_dir, mode, seed):
    with open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8") as f:
        design = f.read()
    meta = _load_json(os.path.join(sample_dir, "meta.json"))
    design_clean = sanitize_design_text(design)
    ev_text = rex._build_evidence_text("A", sample_dir)
    prompt = build_prompt("A", design_clean, design, ev_text, meta)
    if mode == "structural":
        prompt = apply_structural_mode(prompt, meta.get("error_type", ""))
    prompt += "\n【重复试验】seed=%d（独立抽样标识，请独立判断）\n" % seed
    return prompt


def _diff_scale_and_interface(diff_text):
    scale = 0
    iface = []
    for ln in (diff_text or "").split("\n"):
        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")):
            scale += 1
            if INTERFACE_RE.search(ln):
                iface.append(ln.strip()[:120])
    return scale, iface


def run_one(sample_id, mode, seed, llm, out_dir, mock=False):
    sample_dir = os.path.join(REPO_ROOT, "samples", "bugs", sample_id)
    result = {"sample": sample_id, "mode": mode, "seed": seed,
              "loc_line": None, "loc_top1": False, "loc_dev": None,
              "verdict": None, "repair_pass": False,
              "diff_text": "", "diff_scale": 0, "interface_changes": [],
              "errors": [], "reason": ""}
    prompt = build_structural_prompt(sample_dir, mode, seed)
    try:
        res = llm.chat(
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": prompt}],
            tag="structural:%s:%s:%d" % (sample_id, mode, seed),
            max_tokens=65536,
        )
    except Exception as e:
        result["errors"].append("llm: %s" % repr(e)[:300])
        return result
    result["input_tokens"] = res.get("input_tokens", 0)
    result["output_tokens"] = res.get("output_tokens", 0)
    result["cost"] = res.get("cost", 0.0)
    content = res.get("content", "")
    result["llm_raw"] = content
    loc, diff_text = parse_llm_output(content)
    result["loc_line"] = loc.get("line")
    result["reason"] = loc.get("reason", "")
    result["signals"] = loc.get("signals", "")
    result["diff_text"] = (diff_text or "")[:8000]
    true_lines = ground_truth_lines(sample_dir).get("lines") or []
    loc_ln = loc.get("line")
    result["true_lines"] = true_lines
    result["loc_top1"] = loc_ln in true_lines if true_lines and loc_ln is not None else False
    if true_lines and loc_ln is not None:
        result["loc_dev"] = min(abs(loc_ln - x) for x in true_lines)
    result["diff_scale"], result["interface_changes"] = _diff_scale_and_interface(diff_text)
    if not diff_text:
        result["errors"].append("no diff")
        return result
    with open(os.path.join(sample_dir, "buggy.v"), encoding="utf-8") as f:
        design = f.read()
    design_clean = sanitize_design_text(design)
    ok, patched, err = apply_unified_diff(design_clean, _sanitize_diff_lines(diff_text))
    if not ok:
        result["errors"].append("diff apply: %s" % err[:200])
        return result
    work = os.path.join(out_dir, "%s_%s_seed%d" % (sample_id, mode, seed))
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "buggy.v"), "w", encoding="utf-8") as f:
        f.write(patched)
    for fname in ("tb_weak.sv", "verify.sby", "verify_repair.sby", "uart_tx.sv"):
        src = os.path.join(sample_dir, fname)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(work, fname))
    tb_top = None
    tb_path = os.path.join(work, "tb_weak.sv")
    if os.path.isfile(tb_path):
        m = re.search(r"module\s+(tb_\w+)", open(tb_path, encoding="utf-8").read())
        if m:
            tb_top = m.group(1)
    try:
        ev = evaluator.evaluate(work, {"run_formal": True, "verbose": False, "tb_top": tb_top})
        result["verdict"] = ev["verdict"]
        result["repair_pass"] = ev["verdict"] == "PASS"
    except Exception as e:
        result["errors"].append("evaluate: %s" % repr(e)[:200])
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "experiments", "runs", "exp_structural_formal.json"))
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="自检用：只跑前 N 个任务")
    ap.add_argument("--samples", default=",".join(TARGETS))
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--seeds", default=",".join(str(x) for x in SEEDS))
    args = ap.parse_args()

    samples = [s.strip() for s in args.samples.split(",") if s.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    llm = LLMClient(provider="deepseek", mock=args.mock)
    out_dir = os.path.join(REPO_ROOT, "experiments", "runs", "_structural_work")
    os.makedirs(out_dir, exist_ok=True)

    data = _load_done(args.out)
    done = {(r.get("sample"), r.get("mode"), r.get("seed")) for r in data.get("results", [])}
    tasks = [(s, m, sd) for s in samples for m in modes for sd in seeds if (s, m, sd) not in done]
    if args.limit:
        tasks = tasks[:args.limit]
    print("[structural-formal] pending=%d (mock=%s)" % (len(tasks), args.mock), flush=True)

    def _flush():
        try:
            _save(args.out, data)
        except Exception as e:  # noqa: BLE001
            print("[structural-formal] WARN flush failed: %r" % (e,), flush=True)

    for sid, mode, seed in tasks:
        print("[structural-formal] %s/%s/seed%d" % (sid, mode, seed), flush=True)
        t0 = time.time()
        try:
            r = run_one(sid, mode, seed, llm, out_dir, mock=args.mock)
        except Exception as e:  # noqa: BLE001
            print("[structural-formal] ERROR %s/%s/%d: %r" % (sid, mode, seed, e), flush=True)
            r = {"sample": sid, "mode": mode, "seed": seed,
                 "loc_line": None, "loc_top1": False, "loc_dev": None,
                 "verdict": None, "repair_pass": False, "diff_text": "",
                 "diff_scale": 0, "interface_changes": [],
                 "errors": ["run_one: %s" % repr(e)[:300]], "reason": ""}
        r["elapsed"] = round(time.time() - t0, 1)
        data.setdefault("results", []).append(r)
        _flush()
        print("   -> loc=%s top1=%s verdict=%s errs=%d (%.0fs)" % (
            r.get("loc_line"), r.get("loc_top1"), r.get("verdict"),
            len(r.get("errors", [])), r.get("elapsed")), flush=True)

    rs = data.get("results", [])
    for mode in ["plain", "structural"]:
        sub = [r for r in rs if r.get("mode") == mode]
        if not sub:
            continue
        loc1 = sum(1 for r in sub if r.get("loc_top1"))
        w1 = sum(1 for r in sub if r.get("loc_dev") is not None and r["loc_dev"] <= 1)
        w2 = sum(1 for r in sub if r.get("loc_dev") is not None and r["loc_dev"] <= 2)
        rep = sum(1 for r in sub if r.get("repair_pass"))
        print("[structural-formal][%s] n=%d loc1=%d w1=%d w2=%d repair=%d" % (
            mode, len(sub), loc1, w1, w2, rep), flush=True)
    _flush()
    print("[structural-formal] done", flush=True)


if __name__ == "__main__":
    main()
