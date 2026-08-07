# -*- coding: utf-8 -*-
"""E v2 (value trace) vs A retest on hardest samples."""
import sys, os, json, time, re, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"D:\BaiduSyncdisk\02_Precex"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "agents", "local_repairer"))
os.chdir(REPO)

from experiments.configs.prompt_templates import sanitize_design_text, build_prompt, SYSTEM_PROMPT
from scripts.run_experiments import _build_evidence_text

OUT = os.path.join(REPO, "experiments", "runs", "exp_e_v2_ablation.json")
API_KEY = "sk-4a3c3804e6954f1c98b04a059e2b40ba"
API_URL = "https://api.deepseek.com/v1/chat/completions"

TARGETS = ["s07", "s08", "s15", "s18", "s35"]


def load_done():
    if os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    return {"results": []}


def save_done(data):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def call_api(sample_id):
    sd = os.path.join("samples", "bugs", sample_id)
    with open(os.path.join(sd, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    inject_line = meta.get("inject_line", -1)
    with open(os.path.join(sd, "buggy.v"), encoding="utf-8") as f:
        design = f.read()
    design_clean = sanitize_design_text(design)
    ev_text = _build_evidence_text("E", sd)
    prompt = build_prompt("E", design_clean, design, ev_text, meta)
    prompt += "\n【重复试验】seed=0\n"
    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        "temperature": 0.2, "max_tokens": 65536,
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
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
                    loc_line = int(digits[0]); break
        return {"sample": sample_id, "setting": "E", "loc_top1": bool(loc_line == inject_line),
                "loc_line": loc_line, "inject_line": inject_line, "input_tokens": in_tok,
                "output_tokens": out_tok, "elapsed": round(elapsed, 1), "status": "ok"}
    except Exception as e:
        return {"sample": sample_id, "setting": "E", "loc_top1": False, "loc_line": None,
                "inject_line": inject_line, "input_tokens": 0, "output_tokens": 0,
                "elapsed": round(time.time() - t0, 1), "status": "error", "error": str(e)[:150]}


def main():
    data = load_done()
    done = {r["sample"] for r in data["results"]}
    tasks = [s for s in TARGETS if s not in done]
    print("[e-v2] pending: %d" % len(tasks), flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(call_api, s): s for s in tasks}
        for fut in as_completed(futs):
            r = fut.result()
            data["results"].append(r)
            save_done(data)
            print("[done] %s loc=%s inj=%s (%.0fs)" % (r["sample"], r["loc_line"], r["inject_line"], r["elapsed"]), flush=True)
    hits = sum(1 for r in data["results"] if r["loc_top1"])
    print("[summary] E-v2: %d/%d" % (hits, len(data["results"])), flush=True)


if __name__ == "__main__":
    main()
