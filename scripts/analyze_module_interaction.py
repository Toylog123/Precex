#!/usr/bin/env python3
# PreCex - scripts/analyze_module_interaction.py 模块×错误类型×设置交互效应（Phase 3）
# 作者：Toylog | 版本：v0.1 | 功能概述：从 corrected（A/B/C）+ D_clean（D）聚合
#   模块×错误类型×设置 三维 loc_top1 与修复率（BMC 判据），落盘
#   experiments/runs/module_interaction.json（不入库）。只读，不改主实验结果。
import json, os, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
base = os.path.join(REPO, 'experiments', 'runs')
BUGS = os.path.join(REPO, 'samples', 'bugs')

def load(fn):
    with open(os.path.join(base, fn), encoding='utf-8') as f:
        return json.load(f)

abc = load('experiments_results_corrected.json')['results']
d = load('experiments_results_D_clean.json')['results']
rows = abc + d
print('ABC n=%d D n=%d total=%d' % (len(abc), len(d), len(rows)))

def module_of(sid):
    p = os.path.join(BUGS, sid, 'meta.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f).get('module', '?')
    except Exception:
        return '?'

grid = defaultdict(lambda: {'n': 0, 'loc': 0, 'rep': 0})
for x in rows:
    sid = x.get('sample')
    mod = module_of(sid)
    err = x.get('error_type', '?')
    st = x.get('setting', '?')
    key = (mod, err, st)
    grid[key]['n'] += 1
    if x.get('loc_top1'):
        grid[key]['loc'] += 1
    if x.get('repair_pass_bmc') or x.get('repair_pass') or x.get('verdict') == 'PASS':
        grid[key]['rep'] += 1

out_rows = []
for mod in sorted({k[0] for k in grid}):
    for err in sorted({k[1] for k in grid if k[0] == mod}):
        row = {'module': mod, 'error_type': err}
        for st in ('A', 'B', 'C', 'D'):
            g = grid.get((mod, err, st))
            row[st] = {
                'n': g['n'] if g else 0,
                'loc_top1': round(g['loc'] / g['n'] * 100, 1) if g and g['n'] else None,
                'repair': round(g['rep'] / g['n'] * 100, 1) if g and g['n'] else None,
            }
        out_rows.append(row)
out_rows.sort(key=lambda r: (r['module'], r['error_type']))
summary = {
    'generated': __import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'),
    'n_rows': len(out_rows),
    'n_modules': len({r['module'] for r in out_rows}),
    'n_errors': len({r['error_type'] for r in out_rows}),
    'settings': ['A', 'B', 'C', 'D'],
    'rows': out_rows,
}
with open(os.path.join(base, 'module_interaction.json'), 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
# 打印紧凑表
for r in out_rows:
    for st in ('A', 'B', 'C', 'D'):
        g = r[st]
        print('%s|%s|%s|n=%d loc=%s rep=%s' % (r['module'], r['error_type'], st, g['n'], g['loc_top1'], g['repair']))
