# -*- coding: utf-8 -*-
"""PreCex - scripts/analyze_cross_model_arbitration.py
2a: 跨模型仲裁分析——MiniMax-M3 + DeepSeek v4-flash 多候选（每模型 3 温度），
对比单模型 vs 多模型 any-pass 修复率。输出 experiments/runs/cross_model_arbitration.json。
用法（BT 消融完成后）：python3 scripts/analyze_cross_model_arbitration.py
"""
import json, io, os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MM = os.path.join(REPO, "experiments/runs/multi_candidate_real_hard.json")
DS = os.path.join(REPO, "experiments/runs/multi_candidate_ds_hard.json")
OUT = os.path.join(REPO, "experiments/runs/cross_model_arbitration.json")

def load(p):
    if not os.path.isfile(p):
        return None
    with io.open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def groups_by_sample(data):
    out = {}
    for g in data.get("groups", []):
        out[(g["sample"], g["setting"])] = g
    return out

def main():
    mm = load(MM)
    ds = load(DS)
    if mm is None or ds is None:
        print("MISSING: minimax=%s deepseek=%s" % (mm is not None, ds is not None))
        print("  需要先运行 multi_candidate.py（MiniMax 已有 multi_candidate_real_hard.json，DeepSeek 运行中）")
        return 1
    mmg = groups_by_sample(mm)
    dsg = groups_by_sample(ds)
    samples = sorted(set(mmg) | set(dsg))
    rows = []
    for key in samples:
        s, st = key
        g_mm = mmg.get(key)
        g_ds = dsg.get(key)
        mm_cands = (g_mm or {}).get("candidates", [])
        ds_cands = (g_ds or {}).get("candidates", [])
        def pass_temps(cands):
            return sorted(c["temp"] for c in cands if c.get("pass_ok"))
        mm_pass = pass_temps(mm_cands)
        ds_pass = pass_temps(ds_cands)
        all_cands = mm_cands + ds_cands
        any_pass = any(c.get("pass_ok") for c in all_cands)
        rows.append({
            "sample": s, "setting": st,
            "minimax_temps_pass": mm_pass, "deepseek_temps_pass": ds_pass,
            "single_model_max_temps": max(len(mm_pass), len(ds_pass)),
            "single_model_any_pass": bool(mm_pass) or bool(ds_pass),
            "multi_model_any_pass": any_pass,
            "n_candidates": len(all_cands),
        })
    n = len(rows)
    report = {
        "note": "2a 跨模型仲裁：MiniMax-M3 + DeepSeek v4-flash，每模型 3 温度（0.2/0.5/0.8），"
                "multi_candidate.py 同协议（golden-first BMC 验证，仲裁分排序）。",
        "minimax_file": "experiments/runs/multi_candidate_real_hard.json",
        "deepseek_file": "experiments/runs/multi_candidate_ds_hard.json",
        "rows": rows,
        "summary": {
            "n": n,
            "single_model_any_pass_groups": sum(1 for r in rows if r["single_model_any_pass"]),
            "multi_model_any_pass_groups": sum(1 for r in rows if r["multi_model_any_pass"]),
            "multi_model_gain": sum(1 for r in rows if r["multi_model_any_pass"] and not r["single_model_any_pass"]),
            "single_model_rate": sum(1 for r in rows if r["single_model_any_pass"]) / n if n else 0,
            "multi_model_rate": sum(1 for r in rows if r["multi_model_any_pass"]) / n if n else 0,
        },
    }
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("saved:", OUT)
    return 0

if __name__ == "__main__":
    sys.exit(main())
