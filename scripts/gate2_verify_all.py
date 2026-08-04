#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate-2 full reverify: for each sample, verify.sby must FAIL (cex) and
verify_golden.sby must PASS (non-vacuous). Runs with --jobs concurrency and
writes experiments/runs/gate2_reverify.json.

Usage (Windows): python scripts/gate2_verify_all.py [--jobs 8] [--samples s04,s10]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = r'D:/BaiduSyncdisk/02_Precex'
BUGS = os.path.join(REPO_ROOT, 'samples', 'bugs')
OUT_DIR = os.path.join(REPO_ROOT, 'experiments', 'runs')
WSL_PREFIX = ('export HOME=/home/toylog; export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin; '
              'export SMTBMC=/mnt/d/BaiduSyncdisk/02_Precex/smoke/yosys-smtbmc-z3.sh; ')


def expand_samples(spec):
    if not spec:
        return sorted(d for d in os.listdir(BUGS)
                      if re.match(r'^s\d{2}$', d) and os.path.isdir(os.path.join(BUGS, d)))
    out = []
    for part in spec.split(','):
        m = re.match(r'^s(\d+)-s(\d+)$', part)
        if m:
            out += ['s%02d' % i for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            out.append(part)
    return out


def run_sby(sample, kind, timeout=600):
    """kind: 'verify' -> expect FAIL, 'golden' -> expect PASS.
    Returns (done_line_or_tail, elapsed, rc)."""
    cfg = 'verify.sby' if kind == 'verify' else 'verify_golden.sby'
    cmd = (WSL_PREFIX + 'cd /mnt/d/BaiduSyncdisk/02_Precex/samples/bugs/%s; '
           'sby -f %s -d /tmp/g2x_%s_%s > /tmp/g2x_%s_%s.out 2>&1; echo RC=$? >> /tmp/g2x_%s_%s.out'
           % (sample, cfg, sample, kind, sample, kind, sample, kind))
    t0 = time.time()
    try:
        p = subprocess.Popen(['wsl', '-e', 'bash', '-c', cmd])
        rc = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        return 'TIMEOUT', time.time() - t0, -1
    elapsed = time.time() - t0
    out_path = '/tmp/g2x_%s_%s.out' % (sample, kind)
    done = ''
    try:
        r = subprocess.run(['wsl', '-e', 'bash', '-c', 'cat %s' % out_path],
                           capture_output=True, text=True, timeout=30)
        content = r.stdout + r.stderr
        m = re.search(r'(DONE \([A-Z]+[^)]*\))', content)
        done = m.group(1) if m else (content[-200:] if content else '')
    except Exception as e:
        done = 'read-fail:%s' % e
    return done, elapsed, rc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--samples', default='')
    ap.add_argument('--out', default=os.path.join(OUT_DIR, 'gate2_reverify.json'))
    args = ap.parse_args(argv)
    samples = expand_samples(args.samples)
    tasks = [(s, k) for s in samples for k in ('verify', 'golden')]
    print('samples: %d, tasks: %d, jobs=%d' % (len(samples), len(tasks), args.jobs), flush=True)

    results = {}
    lock = __import__('threading').Lock()
    t_start = time.time()

    def _run(task):
        s, k = task
        done, elapsed, rc = run_sby(s, k)
        with lock:
            results[(s, k)] = {'done': done, 'elapsed': round(elapsed, 1), 'rc': rc}
            print('[%d/%d] %s %s: %s (%.1fs)' % (len(results), len(tasks), s, k, done, elapsed), flush=True)
        return task

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(_run, t) for t in tasks]
        for _ in as_completed(futs):
            pass

    total = time.time() - t_start
    print('total: %.1fs (%.1f min), avg %.1fs' % (total, total / 60, total / len(tasks)), flush=True)

    summary = []
    for s in samples:
        v = results.get((s, 'verify'), {})
        g = results.get((s, 'golden'), {})
        v_ok = 'FAIL' in v.get('done', '')
        g_ok = 'PASS' in g.get('done', '')
        summary.append({'sample': s, 'verify': v.get('done'), 'verify_ok': v_ok,
                        'golden': g.get('done'), 'golden_ok': g_ok,
                        'pass': v_ok and g_ok})
    n_pass = sum(1 for x in summary if x['pass'])
    print('PASS: %d/%d' % (n_pass, len(summary)), flush=True)
    for x in summary:
        if not x['pass']:
            print('  FAIL: %s verify=%s golden=%s' % (x['sample'], x['verify'], x['golden']), flush=True)

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'total_time': total, 'results': summary}, f, ensure_ascii=False, indent=2)
    print('[done] -> %s' % args.out, flush=True)
    return 0 if n_pass == len(summary) else 1


if __name__ == '__main__':
    sys.exit(main())