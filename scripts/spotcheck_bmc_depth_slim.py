#!/usr/bin/env python3
# PreCex - scripts/spotcheck_bmc_depth_slim.py
# Slim BMC depth spotcheck: representative samples across axi_lite_slave / uart_rx.
# axi_lite_slave 16->24, uart_rx 24->32; reuses saved diffs, no LLM calls.
import json
import os
import re
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'harness'))
import evaluator  # noqa: E402
from run_prestudy import apply_unified_diff  # noqa: E402

BUGS = os.path.join(REPO_ROOT, 'samples', 'bugs')
WORK = os.path.join(REPO_ROOT, 'experiments', 'runs', '.spotcheck_depth_slim')
SPOT = {'axi_lite_slave': (16, 24), 'uart_rx': (24, 32)}
# (sample, setting, seed) representative set
TARGETS = [
    ('s17', 'B', 0), ('s17', 'C', 0),   # axi incl. earlier None
    ('s25', 'B', 0), ('s34', 'B', 0),   # axi
    ('s18', 'B', 0), ('s36', 'B', 0),   # uart_rx
]


def main():
    abc = json.load(open(os.path.join(REPO_ROOT, 'experiments/runs/experiments_results_corrected.json'), encoding='utf-8'))['results']
    d = json.load(open(os.path.join(REPO_ROOT, 'experiments/runs/experiments_results_D_clean.json'), encoding='utf-8'))['results']
    allrows = abc + d
    bykey = {}
    for r in allrows:
        bykey[(r['sample'], r['setting'], r['seed'])] = r
    todo = []
    for t in TARGETS:
        r = bykey.get(t)
        if not r or not (r.get('diff_text') or '').strip():
            print('skip missing diff for', t)
            continue
        meta = json.load(open(os.path.join(BUGS, t[0], 'meta.json'), encoding='utf-8'))
        mod = meta.get('module')
        if mod not in SPOT:
            print('skip non-spot module', t, mod)
            continue
        todo.append((r, mod))
    print('slim spotcheck targets: %d' % len(todo), flush=True)
    os.makedirs(WORK, exist_ok=True)
    out = []
    for r, mod in todo:
        old_depth, new_depth = SPOT[mod]
        s = r['sample']
        d = os.path.join(WORK, '%s_%s_%d' % (s, r['setting'], r['seed']))
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        buggy = open(os.path.join(BUGS, s, 'buggy.v'), encoding='utf-8').read()
        ok, patched, err = apply_unified_diff(buggy, r['diff_text'])
        if not ok:
            out.append({'sample': s, 'setting': r['setting'], 'seed': r['seed'], 'module': mod,
                        'apply': 'FAIL', 'error': (err or '')[:200]})
            continue
        open(os.path.join(d, 'buggy.v'), 'w', encoding='utf-8').write(patched)
        for fname in ('tb_weak.sv', 'verify.sby'):
            sp = os.path.join(BUGS, s, fname)
            if os.path.isfile(sp):
                shutil.copy(sp, os.path.join(d, fname))
        if mod == 'uart_rx':
            up = os.path.join(BUGS, s, 'uart_tx.sv')
            if os.path.isfile(up):
                shutil.copy(up, os.path.join(d, 'uart_tx.sv'))
        tb = os.path.join(d, 'tb_weak.sv')
        tb_top = None
        if os.path.isfile(tb):
            m = re.search(r'modules+(tb_w+)', open(tb, encoding='utf-8').read())
            if m:
                tb_top = m.group(1)
        ev = evaluator.evaluate(d, {'run_formal': True, 'verbose': False, 'tb_top': tb_top,
                                    'formal_timeout': 600.0, 'depth_override': new_depth})
        out.append({'sample': s, 'setting': r['setting'], 'seed': r['seed'], 'module': mod,
                    'old_depth': old_depth, 'new_depth': new_depth,
                    'verdict': ev['verdict'], 'formal': ev['formal'].get('result'),
                    'exit_code': ev['formal'].get('exit_code')})
        print('[%d] %s/%s/%d mod=%s verdict=%s formal=%s' % (
            len(out), s, r['setting'], r['seed'], mod, ev['verdict'], ev['formal'].get('result')), flush=True)
    passes = sum(1 for x in out if x.get('verdict') == 'PASS')
    print()
    print('=== SLIM SPOTCHECK SUMMARY ===')
    print('total: %d, PASS: %d, non-pass: %d' % (len(out), passes, len(out) - passes))
    for x in out:
        if x.get('verdict') != 'PASS':
            print('NON-PASS:', x)
    with open(os.path.join(REPO_ROOT, 'experiments/runs/bmc_depth_spotcheck_slim.json'), 'w', encoding='utf-8') as f:
        json.dump({'module_depths': SPOT, 'targets': TARGETS, 'total': len(out), 'pass': passes,
                   'results': out}, f, ensure_ascii=False, indent=2)
    print('written: experiments/runs/bmc_depth_spotcheck_slim.json')


if __name__ == '__main__':
    main()
