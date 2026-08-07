# -*- coding: utf-8 -*-
"""E vs A 定位消融实验（后台批处理 + 增量保存 + 并行 4 路）。"""
import sys, os, json, time, re, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"D:\BaiduSyncdisk\02_Precex"
sys.path.insert(0, REPO)
os.chdir(REPO)

from experiments.configs.prompt_templates import sanitize_design_text, build_prompt, SYSTEM_PROMPT
from scripts.run_experiments import _build_evidence_text

OUT = os.path.join(REPO, "experiments", "runs", "exp_e_ablation.json")
API_KEY = "sk-4a3c3804e6954f1c98b04a059e2b40ba"
API_URL = "https://api.deepseek.com/v1/chat/completions"

TARGETS = [
    ("s08", "bugs"), ("s09", "bugs"), ("s15", "bugs"), ("s17", "bugs"),
    ("s18", "bugs"), ("s19", "bugs"), ("s20", "bugs"), ("s29", "bugs"),
    ("s35", "bugs"), ("s36", "bugs"),
]
SETTINGS = ["A", "E"]


def load_done():
    if os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    return {"results": []}


def save_done(data):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def call_api(sample_id, base, setting):
    sd = os.path.join("samples", base, sample_id)
    with open(os.path.join(sd, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    inject_line = meta.get("inject_line", -1)
    with open(os.path.join(sd, "buggy.v"), encoding="utf-8") as f:
        design = f.read()
    design_clean = sanitize_design_text(design)

    ev_text = _build_evidence_text(setting, sd)
    prompt = build_prompt(setting, design_clean, design, ev_text, meta)
    prompt += "\n【重复试验】seed=0\n"

    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 65536,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL, data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY},
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - t0
        content = body["choices"][0]["message"]["content"]
        in_tok = body.get("usage", {}).get("prompt_tokens", 0)
        out_tok = body.get("usage", {}).get("completion_tokens", 0)

        loc_match = re.search(r"###LOCATE###\n(.*?)\n###DIFF###", content, re.DOTALL)
        loc_line = None
        if loc_match:
            for ll in loc_match.group(1).split("\n"):
                digits = re.findall(r"\d+", ll)
                if digits:
                    loc_line = int(digits[0])
                    break

        hit = bool(loc_line == inject_line)
        cost = in_tok * 0.14 / 1e6 + out_tok * 0.28 / 1e6
        return {
            "sample": sample_id, "base": base, "setting": setting,
            "loc_top1": hit, "loc_line": loc_line, "inject_line": inject_line,
            "input_tokens": in_tok, "output_tokens": out_tok,
            "cost": round(cost, 6), "elapsed": round(elapsed, 1),
            "evidence_chars": len(ev_text),
            "error_type": meta.get("error_type", "?"),
            "module": meta.get("module", "?"),
            "status": "ok",
        }
    except Exception as e:
        return {
            "sample": sample_id, "base": base, "setting": setting,
            "loc_top1": False, "loc_line": None, "inject_line": inject_line,
            "input_tokens": 0, "output_tokens": 0, "cost": 0,
            "elapsed": round(time.time() - t0, 1), "evidence_chars": 0,
            "error_type": "?", "module": "?",
            "status": "error", "error": str(e)[:200],
        }


def main():
    data = load_done()
    done = set()
    for r in data["results"]:
        done.add((r["sample"], r["setting"]))

    tasks = []
    for sid, base in TARGETS:
        for setting in SETTINGS:
            if (sid, setting) not in done:
                tasks.append((sid, base, setting))

    print("[e-ablation] pending tasks: %d" % len(tasks), flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(call_api, sid, base, setting): (sid, base, setting)
            for sid, base, setting in tasks
        }
        for fut in as_completed(futs):
            r = fut.result()
            data["results"].append(r)
            save_done(data)
            print("[done] %s/%s %s loc=%s inj=%s (%.0fs)" % (
                r["sample"], r["setting"], r["status"],
                r["loc_line"], r["inject_line"], r["elapsed"],
            ), flush=True)

    a_hits = sum(1 for r in data["results"] if r["setting"] == "A" and r["loc_top1"])
    e_hits = sum(1 for r in data["results"] if r["setting"] == "E" and r["loc_top1"])
    a_n = sum(1 for r in data["results"] if r["setting"] == "A")
    e_n = sum(1 for r in data["results"] if r["setting"] == "E")
    a_tok = sum(r["input_tokens"] + r["output_tokens"] for r in data["results"] if r["setting"] == "A")
    e_tok = sum(r["input_tokens"] + r["output_tokens"] for r in data["results"] if r["setting"] == "E")
    print("\n[summary] A: %d/%d=%.0f%% tok=%d | E: %d/%d=%.0f%% tok=%d" % (
        a_hits, a_n, a_hits / max(a_n, 1) * 100, a_tok,
        e_hits, e_n, e_hits / max(e_n, 1) * 100, e_tok,
    ), flush=True)


if __name__ == "__main__":
    main()
