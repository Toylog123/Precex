# -*- coding: utf-8 -*-
"""A vs A+structural on hardest state-transition samples (loc-only, no formal)."""
import sys, os, json, time, re, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = r"D:\BaiduSyncdisk\02_Precex"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "agents", "local_repairer"))
os.chdir(REPO)

from experiments.configs.prompt_templates import sanitize_design_text, build_prompt, SYSTEM_PROMPT
from scripts.run_experiments import _build_evidence_text
from structural_repairer import apply_structural_mode

OUT = os.path.join(REPO, "experiments", "runs", "exp_structural_ablation.json")
# 凭据从根 .env 读取（绝不硬编码入库）；DEEPSEEK_BASE_URL 缺省为官方 OpenAI 兼容端点
def _load_env():
    env = {}
    env_path = os.path.join(REPO, ".env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, _, v = ln.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'").strip('"')
    return env

_ENV = _load_env()
API_KEY = _ENV.get("DEEPSEEK_API_KEY", "")
API_URL = _ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions"
if not API_KEY:
    raise SystemExit("ERROR: DEEPSEEK_API_KEY 未在 .env 中配置")


TARGETS = ["s07", "s08", "s09", "s18", "s36", "s15"]


def load_done():
    if os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    return {"results": []}


def save_done(data):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def call_api(sample_id, mode):
    sd = os.path.join("samples", "bugs", sample_id)
    with open(os.path.join(sd, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    inject_line = meta.get("inject_line", -1)
    with open(os.path.join(sd, "buggy.v"), encoding="utf-8") as f:
        design = f.read()
    design_clean = sanitize_design_text(design)
    ev_text = _build_evidence_text("A", sd)
    prompt = build_prompt("A", design_clean, design, ev_text, meta)
    if mode == "structural":
        prompt = apply_structural_mode(prompt, meta.get("error_type", ""))
    prompt += chr(10) + "【重复试验】seed=0（独立抽样标识，请独立判断）" + chr(10)

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
        loc_match = re.search(r"###LOCATE###" + chr(10) + r"(.*?)" + chr(10) + r"###DIFF###", content, re.DOTALL)
        loc_line = None
        if loc_match:
            for ll in loc_match.group(1).split(chr(10)):
                digits = re.findall(r"\d+", ll)
                if digits:
                    loc_line = int(digits[0]); break
        return {"sample": sample_id, "mode": mode, "loc_top1": bool(loc_line == inject_line),
                "loc_line": loc_line, "inject_line": inject_line, "input_tokens": in_tok,
                "output_tokens": out_tok, "elapsed": round(elapsed, 1), "status": "ok"}
    except Exception as e:
        return {"sample": sample_id, "mode": mode, "loc_top1": False, "loc_line": None,
                "inject_line": inject_line, "input_tokens": 0, "output_tokens": 0,
                "elapsed": round(time.time() - t0, 1), "status": "error", "error": str(e)[:120]}


def main():
    data = load_done()
    done = {(r["sample"], r["mode"]) for r in data["results"]}
    tasks = [(s, m) for s in TARGETS for m in ["plain", "structural"] if (s, m) not in done]
    print("[structural] pending: %d" % len(tasks), flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(call_api, s, m): (s, m) for s, m in tasks}
        for fut in as_completed(futs):
            r = fut.result()
            data["results"].append(r)
            save_done(data)
            print("[done] %s/%s loc=%s inj=%s (%.0fs)" % (r["sample"], r["mode"], r["loc_line"], r["inject_line"], r["elapsed"]), flush=True)
    for m in ["plain", "structural"]:
        rs = [r for r in data["results"] if r["mode"] == m]
        hits = sum(1 for r in rs if r["loc_top1"])
        print("[summary] %s: %d/%d" % (m, hits, len(rs)), flush=True)


if __name__ == "__main__":
    main()
