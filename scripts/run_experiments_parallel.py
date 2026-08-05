# -*- coding: utf-8 -*-
"""PreCex 主实验并行调度（分离模式，v0.3 均衡分片 + 分片旧产物清理）：
   v0.2（2026-08-04）按样本验证耗时权重做贪心均衡分片（慢样本 s36/s37/s33/s25/s28/s27/s17/s34 分散），
   替代 v0.1 的简单轮询；同一样本的全部 (setting,seed) 任务作为一组不拆散；新增 --dry-run。
   v0.3（2026-08-05）spawn 前清理该分片旧产物（含 .partial.jsonl 断点续跑文件），
   避免复用旧 partial 导致新任务被跳过（审查发现缺陷）。
用法: python3 scripts/run_experiments_parallel.py [--samples s04-s37] [--settings A,B,C] [--seeds 0,1,2] [--jobs 4]
      --dry-run 只打印分片规划不启动；--detach nohup 后台；--merge 合并 exp_part_*.json。
"""
import argparse, json, os, subprocess, sys, re, glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WSL_ROOT = "/mnt/d/BaiduSyncdisk/02_Precex"

DEFAULT_WEIGHTS = {
    "s36": 154.1, "s37": 151.5, "s33": 89.2, "s25": 88.8, "s28": 88.7,
    "s27": 88.5, "s17": 88.3, "s34": 87.7, "s35": 35.9, "s24": 14.9,
    "s05": 17.3, "s06": 16.7, "s04": 16.8, "s07": 18.5, "s30": 7.7,
}
DEFAULT_WEIGHT = 5.0

def expand_samples(spec):
    ids = []
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"^s(\d+)-s(\d+)$", part)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            ids += ["s%02d" % i for i in range(lo, hi + 1)]
        else:
            ids.append(part)
    seen = set(); out = []
    for x in ids:
        if x not in seen: seen.add(x); out.append(x)
    return out

def sample_weight(sid, weights):
    return weights.get(sid, DEFAULT_WEIGHT)

def balance_groups(groups, jobs, weights):
    """按样本组贪心均衡：组权重 = 样本验证耗时；每次把最重组放入累计负载最小分片。"""
    ordered = sorted(groups.items(), key=lambda kv: -sample_weight(kv[0], weights))
    chunks = [[] for _ in range(jobs)]
    loads = [0.0] * jobs
    for sid, tasks in ordered:
        w = sample_weight(sid, weights)
        min_j = min(range(jobs), key=lambda j: loads[j])
        chunks[min_j].extend(tasks)
        loads[min_j] += w
    return chunks, loads

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="s04-s37")
    ap.add_argument("--settings", default="A,B,C")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--prefix", default="exp_part_", help="分片输出前缀（默认 exp_part_）")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--out", default=None)
    ap.add_argument("--detach", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--provider", default="minimax", help="LLM provider（minimax/deepseek/openai/gemini/anthropic）")
    ap.add_argument("--merge", action="store_true")
    args = ap.parse_args(argv)
    workdir = os.path.join(REPO_ROOT, "experiments", "runs")
    os.makedirs(workdir, exist_ok=True)
    out_path = args.out or os.path.join(workdir, "experiments_results_parallel.json")
    weights = dict(DEFAULT_WEIGHTS)
    try:
        vt = json.load(open(os.path.join(workdir, "verify_timing.json"), encoding="utf-8"))
        for s, v in vt.get("per_sample", {}).items():
            weights[s] = (v.get("verify_s") or 0) + (v.get("golden_s") or 0)
    except Exception:
        pass
    if args.merge:
        results = []; all_samples = []; settings = []; seeds = []
        for p in sorted(glob.glob(os.path.join(workdir, "%s*.json" % args.prefix))):
            d = json.load(open(p, encoding="utf-8"))
            results.extend(d.get("results", [])); all_samples.extend(d.get("samples", []))
            settings = d.get("settings", settings); seeds = d.get("seeds", seeds)
        results.sort(key=lambda r: (r.get("sample"), r.get("setting"), r.get("seed")))
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"samples": all_samples, "settings": settings, "seeds": seeds, "results": results}, f, ensure_ascii=False, indent=2)
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        from run_experiments import _write_summary
        _write_summary(out_path, results)
        print("[merge] total=%d -> %s" % (len(results), out_path))
        return 0
    samples = expand_samples(args.samples)
    settings = [x.strip() for x in args.settings.split(",") if x.strip()]
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    # 按样本分组
    groups = {}
    for s in samples:
        groups[s] = [(s, st, sd) for st in settings for sd in seeds]
    jobs = max(1, min(args.jobs, len(groups)))
    chunks, loads = balance_groups(groups, jobs, weights)
    print("[plan] samples=%d settings=%s seeds=%s jobs=%d provider=%s" % (len(samples), ",".join(settings), ",".join(map(str, seeds)), jobs, args.provider))
    print("[plan] 分片（样本组）分布：")
    for j, chunk in enumerate(chunks):
        sids = sorted({t[0] for t in chunk})
        slow_in = [s for s in sids if sample_weight(s, weights) > 20]
        print("  part %d: %d samples / %d tasks, est_load=%.1fs, slow=%s" % (j, len(sids), len(chunk), loads[j], slow_in))
    print("[plan] 负载 max=%.1fs min=%.1fs ratio=%.2f (理想=1.0)" % (max(loads), min(loads), max(loads)/max(1, min(loads))))
    if args.dry_run:
        print("[dry-run] 未启动任何进程")
        return 0
    shdir = os.path.join(workdir, ".par_sh")
    os.makedirs(shdir, exist_ok=True)
    for i, chunk in enumerate(chunks):
        if not chunk: continue
        # 清理该分片旧产物（含 partial 断点续跑文件），避免复用旧 partial 导致新任务被跳过
        for suffix in (".json", ".json.partial.jsonl", ".csv", ".log"):
            stale = os.path.join(workdir, "%s%d%s" % (args.prefix, i, suffix))
            if os.path.isfile(stale):
                os.remove(stale)
        wsl_out = "%s/experiments/runs/%s%d.json" % (WSL_ROOT, args.prefix, i)
        sh = os.path.join(shdir, "part_%d.sh" % i)
        wsl_sh = "%s/experiments/runs/.par_sh/part_%d.sh" % (WSL_ROOT, i)
        body = "#!/bin/bash\n"
        body += "export HOME=/home/toylog\n"
        body += "cd %s\n" % WSL_ROOT
        body += "export PATH=$HOME/.local/bin:$PATH\n"
        body += "export SMTBMC=$PWD/smoke/yosys-smtbmc-z3.sh\n"
        task_ids = ",".join("%s/%s/%d" % (t[0], t[1], t[2]) for t in chunk)
        body += "nohup python3 scripts/run_experiments.py --tasks %s --retries %d --provider %s --out %s > %s 2>&1 &\n" % (
            task_ids, args.retries, args.provider, wsl_out, wsl_out + ".log")
        with open(sh, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print("[spawn] part %d: %d tasks" % (i, len(chunk)), flush=True)
        if args.detach:
            subprocess.Popen(["wsl", "-e", "bash", wsl_sh], cwd=REPO_ROOT)
        else:
            subprocess.run(["wsl", "-e", "bash", wsl_sh], cwd=REPO_ROOT)
    print("[spawned] %d parts (detach=%s)" % (jobs, args.detach))

if __name__ == "__main__":
    sys.exit(main())
