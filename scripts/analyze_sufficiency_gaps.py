#!/usr/bin/env python3
# PreCex - scripts/analyze_sufficiency_gaps.py 充分性缺口清单（Phase 3，v0.2）
# 作者：Toylog | 版本：v0.2 | 功能概述：从 sufficiency_all_strong_d16.json（强变异，论文锚点 88.5%）
#   与 sufficiency_const_all.json（常量变异 81.8%）聚合每样本/每断言行未 kill 的变异，
#   归类模块×错误类型，输出 experiments/runs/sufficiency_gaps.json（不入库）。
#   修正：v0.2 使用正确的强变异文件（--strong --depth 16）。
import json, os, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
base = os.path.join(REPO, 'experiments', 'runs')
BUGS = os.path.join(REPO, 'samples', 'bugs')

def load(fn):
    with open(os.path.join(base, fn), encoding='utf-8') as f:
        return json.load(f)

def meta_of(sid):
    try:
        with open(os.path.join(BUGS, sid, 'meta.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

strong = load('sufficiency_all_strong_d16.json')['results']
const = load('sufficiency_const_all.json')['results']

gaps = []
for fn, rows, kind in (('sufficiency_all_strong_d16.json', strong, 'strong'),
                       ('sufficiency_const_all.json', const, 'const')):
    for r in rows:
        sid = r.get('sample')
        m = meta_of(sid)
        for w in r.get('weak', []):
            gaps.append({
                'kind': kind, 'sample': sid, 'module': m.get('module', '?'),
                'error_type': m.get('error_type', '?'),
                'line': w.get('line'), 'variant': w.get('variant'),
                'mutation': w.get('old_op') or w.get('old') or w.get('new_op') or w.get('new') or '',
                'done': w.get('done', ''),
            })

by_sample = defaultdict(list)
for g in gaps:
    by_sample[g['sample']].append(g)
sample_gaps = []
for sid in sorted(by_sample):
    gg = by_sample[sid]
    m = meta_of(sid)
    sample_gaps.append({
        'sample': sid, 'module': m.get('module', '?'), 'error_type': m.get('error_type', '?'),
        'strong_uncovered': sum(1 for x in gg if x['kind'] == 'strong'),
        'const_uncovered': sum(1 for x in gg if x['kind'] == 'const'),
        'total_uncovered': len(gg),
        'lines': sorted({x['line'] for x in gg if x['line'] is not None}),
    })

by_mod = defaultdict(lambda: {'strong': 0, 'const': 0})
for g in gaps:
    by_mod[g['module']]['strong' if g['kind'] == 'strong' else 'const'] += 1
mod_summary = {m: {'strong_uncovered': v['strong'], 'const_uncovered': v['const']}
               for m, v in sorted(by_mod.items())}

strong_total = sum(r.get('mutations', 0) for r in strong)
strong_killed = sum(r.get('killed', 0) for r in strong)
const_total = sum(r.get('mutations', 0) for r in const)
const_killed = sum(r.get('killed', 0) for r in const)

summary = {
    'generated': __import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'),
    'coverage': {
        'strong_d16': {'mutations': strong_total, 'killed': strong_killed,
                       'rate_pct': round(strong_killed / strong_total * 100, 1) if strong_total else 0},
        'const': {'mutations': const_total, 'killed': const_killed,
                  'rate_pct': round(const_killed / const_total * 100, 1) if const_total else 0},
    },
    'by_module': mod_summary,
    'by_sample': sample_gaps,
    'n_uncovered_strong': sum(1 for g in gaps if g['kind'] == 'strong'),
    'n_uncovered_const': sum(1 for g in gaps if g['kind'] == 'const'),
    'gap_classification': {
        '可补（新变异/加深）': '对未 kill 的断言行可尝试更激进的变异算子或更大 BMC depth',
        '需新样本': '若某模块×错误类型的全部断言均未 kill，说明该组合断言充分性存疑，需补充样本验证',
    },
}
with open(os.path.join(base, 'sufficiency_gaps.json'), 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print('coverage:', summary['coverage'])
print('n_uncovered strong=%d const=%d' % (summary['n_uncovered_strong'], summary['n_uncovered_const']))
print('--- by module ---')
for m, v in mod_summary.items():
    print('%s: strong_unc=%d const_unc=%d' % (m, v['strong_uncovered'], v['const_uncovered']))
print('--- samples with most gaps ---')
for s in sorted(sample_gaps, key=lambda x: -x['total_uncovered'])[:12]:
    print('%s/%s/%s: strong=%d const=%d lines=%s' % (s['sample'], s['module'], s['error_type'],
          s['strong_uncovered'], s['const_uncovered'], s['lines']))
