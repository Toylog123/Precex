#!/usr/bin/env python3
# PreCex - scripts/reverify_bmc.py
# 批量重验主实验 patch：用 bmc 判据（verify.sby 语义）评估所有有 diff 的结果
# 背景：主实验修复判定用 verify_repair.sby（prove/k-induction），对 axi_lite_slave 不收敛
#       （golden.v 本身在 prove 下也 UNKNOWN），正确修复被误判 FAIL
# 本脚本复用主实验结果中已保存的 diff_text，只重验、不重跑 LLM
# 运行方式（在 WSL 内）：export HOME=/home/toylog; export PATH=...:$HOME/.local/bin;
#   export SMTBMC=/mnt/d/BaiduSyncdisk/02_Precex/smoke/yosys-smtbmc-z3.sh;
#   cd /mnt/d/BaiduSyncdisk/02_Precex; python3 scripts/reverify_bmc.py [--jobs 8]
# 输出：experiments/runs/reverify_bmc_all.json（不入库）
import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, 'scripts'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'harness'))
from run_prestudy import apply_unified_diff  # noqa: E402
import evaluator  # noqa: E402

BUGS = os.path.join(REPO_ROOT, 'samples', 'bugs')
RESULT_JSON = os.path.join(REPO_ROOT, 'experiments', 'runs', 'experiments_results_parallel.json')
OUT_JSON = os.path.join(REPO_ROOT, 'experiments', 'runs', 'reverify_bmc_all.json')
WORK_ROOT = os.path.join(REPO_ROOT, 'experiments', 'runs', '.reverify_bmc')


def verify_bmc(sample, patched_src, tag, formal_timeout=900.0):
    """在 WSL 内用 evaluator（verify.sby=bmc 语义）验证 patch。返回 (verdict, formal_result, exit_code)。"""
    d = os.path.join(WORK_ROOT, tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'buggy.v'), 'w', encoding='utf-8') as f:
        f.write(patched_src)
    sdir = os.path.join(BUGS, sample)
    for fname in ('tb_weak.sv', 'verify.sby'):
        sp = os.path.join(sdir, fname)
        if os.path.isfile(sp):
            shutil.copy(sp, os.path.join(d, fname))
    meta_p = os.path.join(sdir, 'meta.json')
    meta = {}
    if os.path.isfile(meta_p):
        try:
            meta = json.load(open(meta_p, encoding='utf-8'))
        except Exception:
            meta = {}
        if meta.get('module') == 'uart_rx':
            up = os.path.join(sdir, 'uart_tx.sv')
            if os.path.isfile(up):
                shutil.copy(up, os.path.join(d, 'uart_tx.sv'))
    tb_top = None
    tb = os.path.join(d, 'tb_weak.sv')
    if os.path.isfile(tb):
        m = re.search(r'module\s+(tb_\w+)', open(tb, encoding='utf-8').read())
        if m:
            tb_top = m.group(1)
    ev = evaluator.evaluate(d, {'run_formal': True, 'verbose': False, 'tb_top': tb_top,
                                'formal_timeout': formal_timeout})
    return ev['verdict'], ev['formal'].get('result'), ev['formal'].get('exit_code'), meta.get('module')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--formal-timeout', type=float, default=900.0)
    args = ap.parse_args(argv)

    data = json.load(open(RESULT_JSON, encoding='utf-8'))
    results = data['results']
    todo = [r for r in results if (r.get('diff_text') or '').strip()]
    print('total results %d, with diff %d, jobs %d' % (len(results), len(todo), args.jobs), flush=True)
    os.makedirs(WORK_ROOT, exist_ok=True)

    lock = threading.Lock()
    out = []

    def run(r):
        s = r['sample']
        row = {
            'sample': s, 'setting': r['setting'], 'seed': r['seed'],
            'old_repair_pass': r.get('repair_pass'), 'attempts': r.get('attempts'),
        }
        buggy = open(os.path.join(BUGS, s, 'buggy.v'), encoding='utf-8').read()
        ok, patched, err = apply_unified_diff(buggy, r['diff_text'])
        if not ok:
            row.update({'apply': 'FAIL', 'verdict': None, 'formal': None, 'error': (err or '')[:200]})
            return row
        tag = '%s_%s_%d' % (s, r['setting'], r['seed'])
        try:
            verdict, formal, exit_code, module = verify_bmc(s, patched, tag, args.formal_timeout)
            row.update({'apply': 'OK', 'verdict': verdict, 'formal': formal,
                        'exit_code': exit_code, 'module': module})
        except Exception as ex:  # noqa: BLE001
            row.update({'apply': 'OK', 'verdict': 'ERROR', 'formal': repr(ex)[:200], 'module': None})
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(run, r) for r in todo]
        for fu in as_completed(futs):
            row = fu.result()
            with lock:
                out.append(row)
                print('[%d] %s/%s/%d apply=%s verdict=%s formal=%s' % (
                    len(out), row['sample'], row['setting'], row['seed'],
                    row['apply'], row['verdict'], row['formal']), flush=True)

    # 汇总
    def rate(rows, key):
        n = len(rows)
        k = sum(1 for x in rows if x.get(key))
        return (k, n, round(100.0 * k / n, 1) if n else 0.0)

    old_pass = sum(1 for x in out if x.get('old_repair_pass'))
    new_pass = sum(1 for x in out if x.get('verdict') == 'PASS')
    n_ok = sum(1 for x in out if x.get('verdict') in ('PASS', 'FAIL', 'INCONCLUSIVE'))
    # prove 误判（负例）：旧 FAIL -> bmc PASS（正确修复被 prove 误杀）
    false_neg = [x for x in out if not x.get('old_repair_pass') and x.get('verdict') == 'PASS']
    # prove 假阳：旧 PASS -> bmc 非 PASS
    false_pos = [x for x in out if x.get('old_repair_pass') and x.get('verdict') != 'PASS']
    summary = {
        'total_reverified': len(out),
        'old_repair_pass': old_pass,
        'new_bmc_pass': new_pass,
        'old_rate': round(100.0 * old_pass / len(out), 1),
        'new_rate': round(100.0 * new_pass / len(out), 1),
        'prove_false_negative': len(false_neg),
        'prove_false_positive': len(false_pos),
        'prove_false_negative_rate': round(100.0 * len(false_neg) / max(1, len(out) - old_pass), 1),
    }
    print('\n=== SUMMARY ===', flush=True)
    for k, v in summary.items():
        print('%s: %s' % (k, v), flush=True)
    print('--- per sample (bmc pass / total, old vs new) ---', flush=True)
    per_sample = {}
    for x in out:
        per_sample.setdefault(x['sample'], [0, 0, 0])
        ps = per_sample[x['sample']]
        ps[1] += 1
        if x.get('old_repair_pass'):
            ps[2] += 1
        if x.get('verdict') == 'PASS':
            ps[0] += 1
    for s in sorted(per_sample):
        p = per_sample[s]
        print('%s bmc=%d/%d old=%d/%d' % (s, p[0], p[1], p[2], p[1]), flush=True)
    print('--- prove false negatives (old FAIL -> bmc PASS) ---', flush=True)
    for x in false_neg:
        print('%s/%s/%d' % (x['sample'], x['setting'], x['seed']), flush=True)
    print('--- prove false positives (old PASS -> bmc not PASS) ---', flush=True)
    for x in false_pos:
        print('%s/%s/%d old=%s new=%s' % (x['sample'], x['setting'], x['seed'], x['old_repair_pass'], x['verdict']), flush=True)

    json.dump({'summary': summary, 'results': out},
              open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('[done] -> %s' % OUT_JSON, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())