#!/usr/bin/env python3
# PreCex - scripts/regen_summary_parallel.py 摘要重生成并行分片
# 作者：Toylog | 版本：v0.1 | 功能概述：把待重生成样本均分 N 片，每片一个子进程串行调用
#   regen_text_summary.py（--samples 单批），规避单进程挂起 + 提升吞吐。
"""PreCex 摘要重生成并行分片。"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "regen_text_summary.py")
PY = sys.executable


def expand(spec, dirname):
    ids = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            prefix = "".join(c for c in a if not c.isdigit())
            na, nb = int("".join(c for c in a if c.isdigit())), int("".join(c for c in b if c.isdigit()))
            ids += ["%s%02d" % (prefix, i) for i in range(na, nb + 1)]
        else:
            ids.append(part)
    return [x for x in ids if os.path.isdir(os.path.join(ROOT, "samples", dirname, x))]


def run_batch(batch, samples_dir, provider, window, budget):
    spec = ",".join(batch)
    cmd = [PY, SCRIPT, "--samples-dir", samples_dir, "--samples", spec,
           "--provider", provider, "--window", str(window), "--max-budget", str(budget)]
    print(">> %s" % " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    out = []
    try:
        for line in proc.stdout:
            out.append(line.rstrip())
        proc.wait(timeout=1200)
    except Exception as e:
        proc.kill()
        out.append("[kill] %r" % e)
    return "\n".join(out[-20:])


def main():
    samples_dir = sys.argv[1] if len(sys.argv) > 1 else "bugs"
    spec = sys.argv[2] if len(sys.argv) > 2 else ("s04-s37" if samples_dir == "bugs" else None)
    nprocs = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    provider = sys.argv[4] if len(sys.argv) > 4 else "deepseek"
    ids = expand(spec, samples_dir) if spec else [x for x in os.listdir(os.path.join(ROOT, "samples", samples_dir))]
    ids = sorted(set(ids))
    if not ids:
        raise SystemExit("no targets")
    print("total=%d procs=%d" % (len(ids), nprocs), flush=True)
    # 分片
    batches = [[] for _ in range(nprocs)]
    for i, sid in enumerate(ids):
        batches[i % nprocs].append(sid)
    with ThreadPoolExecutor(max_workers=nprocs) as ex:
        futs = [ex.submit(run_batch, b, samples_dir, provider, 8, 5.0) for b in batches if b]
        for f in futs:
            print(f.result(), flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
