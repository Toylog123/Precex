#!/usr/bin/env python3
# PreCex - scripts/analyze_deep_subset.py  深时序子集四设置分析（A/B 已有 + C/D 补跑）
import json, os, sys
from collections import defaultdict
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO, 'experiments', 'runs')

def load(path):
    p = os.path.join(RUNS, path)
    if not os.path.exists(p): return []
    d = json.load(open(p, encoding='utf-8'))
    return d.get('results', d) if isinstance(d, dict) else d

def load_partial(path):
    p = os.path.join(RUNS, path)
    if not os.path.exists(p): return []
    out = []
    for line in open(p, encoding='utf-8'):
        line = line.strip()
        if line:
            try: out.append(json.loads(line))
            except Exception: pass
    return out

def dedupe(rows):
    seen = set(); out = []
    for r in rows:
        k = (r.get('sample'), r.get('setting'), r.get('seed'))
        if k in seen: continue
        seen.add(k); out.append(r)
    return out

def main():
    rows = dedupe(load('deep_subset_ab.json') + load('deepcd_0.json') + load('deepcd_1.json') +
                  load('deepcd_2.json') + load_partial('deep_subset_cd.json.partial.jsonl'))
    # 仅保留 deep 样本 s38-s42
    rows = [r for r in rows if r.get('sample') in ('s38','s39','s40','s41','s42')]
    samples = ['s38','s39','s40','s41','s42']
    settings = ['A','B','C','D']
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r['sample']][r['setting']].append(r)
    print('=== 深时序子集四设置覆盖检查（期望每格 3 seeds）===')
    ok = True
    for s in samples:
        line = s + ': '
        for st in settings:
            n = len(by[s].get(st, []))
            line += st + '=' + str(n) + ' '
            if n != 3: ok = False
        print(line)
    print('覆盖完整:', ok)
    print()
    print('=== 每设置聚合（loc/repair/cost）===')
    agg = {}
    for st in settings:
        rs = [r for r in rows if r.get('setting') == st]
        n = len(rs)
        loc = sum(1 for r in rs if r.get('loc_top1'))
        rep = sum(1 for r in rs if r.get('repair_pass'))
        cost = sum(r.get('cost') or 0 for r in rs)
        agg[st] = dict(n=n, loc=loc, rep=rep, cost=cost)
        print('%s: n=%d loc=%d (%.1f%%) repair=%d (%.1f%%) cost=$%.4f' % (
            st, n, loc, 100*loc/max(1,n), rep, 100*rep/max(1,n), cost))
    print()
    print('=== 逐样本逐设置 loc_top1 矩阵（3 seeds 的 True 数）===')
    for s in samples:
        cells = []
        for st in settings:
            rs = by[s].get(st, [])
            cells.append('%s:%d/3' % (st, sum(1 for r in rs if r.get('loc_top1'))))
        print(s + ' | ' + ' '.join(cells))
    out = os.path.join(RUNS, 'deep_subset_4settings.json')
    json.dump({'samples': samples, 'settings': settings, 'results': rows, 'agg': agg},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print()
    print('WROTE', out, '| total rows', len(rows))
    return 0

if __name__ == '__main__':
    sys.exit(main())
