# -*- coding: utf-8 -*-
"""PreCex 主实验并行调度（分离模式）：按样本拆组，每组独立 WSL 子进程跑 run_experiments（nohup 后台）。
用法: python3 scripts/run_experiments_parallel.py [--samples s04-s37] [--settings A,B,C] [--seeds 0,1,2] [--jobs 4]
      --detach 以 nohup 启动后立即返回；--merge 手动合并 exp_part_*.json 到 --out。
"""
import argparse, json, os, subprocess, sys, re, shutil, glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WSL_ROOT = "/mnt/d/BaiduSyncdisk/02_Precex"

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

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="s04-s37")
    ap.add_argument("--settings", default="A,B,C")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--out", default=None)
    ap.add_argument("--detach", action="store_true", help="nohup 启动后立即返回");
    ap.add_argument("--merge", action="store_true", help="只合并已有 exp_part_*.json 到 --out");
    args = ap.parse_args(argv)
    workdir = os.path.join(REPO_ROOT, "experiments", "runs")
    os.makedirs(workdir, exist_ok=True)
    out_path = args.out or os.path.join(workdir, "experiments_results_parallel.json")
    if args.merge:
        results = []; all_samples = []; settings = []; seeds = []
        for p in sorted(glob.glob(os.path.join(workdir, "exp_part_*.json"))):
            d = json.load(open(p, encoding="utf-8"))
            results.extend(d.get("results", [])); all_samples.extend(d.get("samples", []));
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
    jobs = max(1, min(args.jobs, len(samples)))
    chunks = [[] for _ in range(jobs)]
    for i, s in enumerate(samples):
        chunks[i % jobs].append(s)
    shdir = os.path.join(workdir, ".par_sh")
    os.makedirs(shdir, exist_ok=True)
    for i, chunk in enumerate(chunks):
        if not chunk: continue
        wsl_out = "%s/experiments/runs/exp_part_%d.json" % (WSL_ROOT, i)
        sh = os.path.join(shdir, "part_%d.sh" % i)
        wsl_sh = "%s/experiments/runs/.par_sh/part_%d.sh" % (WSL_ROOT, i)
        body = "#!/bin/bash\n"
        body += "export HOME=/home/toylog\n"
        body += "cd %s\n" % WSL_ROOT
        body += "export PATH=$HOME/.local/bin:$PATH\n"
        body += "export SMTBMC=$PWD/smoke/yosys-smtbmc-z3.sh\n"
        body += "nohup python3 scripts/run_experiments.py --samples %s --settings %s --seeds %s --retries %d --out %s > %s 2>&1 &\n" % (
            ",".join(chunk), args.settings, args.seeds, args.retries, wsl_out, wsl_out + ".log")
        with open(sh, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print("[spawn] part %d: %s" % (i, ",".join(chunk)), flush=True)
        if args.detach:
            subprocess.Popen(["wsl", "-e", "bash", wsl_sh], cwd=REPO_ROOT)
        else:
            subprocess.run(["wsl", "-e", "bash", wsl_sh], cwd=REPO_ROOT)
    print("[spawned] %d parts (detach=%s)" % (jobs, args.detach))

if __name__ == "__main__":
    sys.exit(main())
