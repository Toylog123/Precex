#!/usr/bin/env python3
# PreCex - scripts/spotcheck_bmc_depth.py
# BMC depth sensitivity spotcheck: axi_lite_slave 16->24, uart_rx 24->32
# Run inside WSL with SMTBMC env set.
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'harness'))
import evaluator  # noqa: E402
from run_prestudy import apply_unified_diff  # noqa: E402

BUGS = os.path.join(REPO_ROOT, 'samples', 'bugs')
WORK = os.path.join(REPO_ROOT, 'experiments', 'runs', '.spotcheck_depth')
SPOT = {'axi_lite_slave': (16, 24), 'uart_rx': (24, 32)}


def main():
    abc = json.load(open(os.path.join(REPO_ROOT, 'experiments/runs/experiments_results_corrected.json'), encoding='utf-8'))['results']
    d = json.load(open(os.path.join(REPO_ROOT, 'experiments/runs/experiments_results_D_clean.json'), encoding='utf-8'))['results']
    allrows = abc + d
    todo = []
    for r in allrows:
        s = r['sample']
        meta_p = os.path.join(BUGS, s, 'meta.json')
        if not os.path.isfile(meta_p):
            continue
        mod = json.load(open(meta_p, encoding='utf-8')).get('module')
        if mod not in SPOT:
            continue
        if not (r.get('diff_text') or '').strip():
            continue
        todo.append((r, mod))
    print('spotcheck targets: %d (axi 16->24, uart_rx 24->32)' % len(todo), flush=True)
    os.makedirs(WORK, exist_ok=True)
    out = []

    def run(item):
        r, mod = item
        old_depth, new_depth = SPOT[mod]
        s = r['sample']
        d = os.path.join(WORK, '%s_%s_%d' % (s, r['setting'], r['seed']))
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        buggy = open(os.path.join(BUGS, s, 'buggy.v'), encoding='utf-8').read()
        ok, patched, err = apply_unified_diff(buggy, r['diff_text'])
        if not ok:
            return {'sample': s, 'setting': r['setting'], 'seed': r['seed'], 'module': mod,
                    'apply': 'FAIL', 'error': (err or '')[:200]}
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
                                    'formal_timeout': 900.0, 'depth_override': new_depth})
        return {'sample': s, 'setting': r['setting'], 'seed': r['seed'], 'module': mod,
                'old_depth': old_depth, 'new_depth': new_depth,
                'verdict': ev['verdict'], 'formal': ev['formal'].get('result'),
                'exit_code': ev['formal'].get('exit_code')}

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(run, item) for item in todo]
        for fu in as_completed(futs):
            row = fu.result()
            out.append(row)
            print('[%d] %s/%s/%d mod=%s verdict=%s formal=%s' % (
                len(out), row['sample'], row['setting'], row['seed'],
                row.get('module'), row.get('verdict'), row.get('formal')), flush=True)

    passes = sum(1 for x in out if x.get('verdict') == 'PASS')
    print()
    print('=== SPOTCHECK SUMMARY ===')
    print('total: %d, PASS: %d, non-pass: %d' % (len(out), passes, len(out) - passes))
    for x in out:
        if x.get('verdict') != 'PASS':
            print('NON-PASS:', x)
    with open(os.path.join(REPO_ROOT, 'experiments/runs/bmc_depth_spotcheck.json'), 'w', encoding='utf-8') as f:
        json.dump({'module_depths': SPOT, 'total': len(out), 'pass': passes, 'results': out}, f,
                  ensure_ascii=False, indent=2)
    print('written: experiments/runs/bmc_depth_spotcheck.json')


if __name__ == '__main__':
    main()
