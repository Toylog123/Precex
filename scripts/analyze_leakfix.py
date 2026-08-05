#!/usr/bin/env python3
# PreCex - scripts/analyze_leakfix.py  泄漏版 vs 无泄漏版主实验对比分析
# 作者：Toylog | 版本：v0.1 | 功能概述：读取 leakfix_* 分片（无泄漏重跑）与旧 DS 全量
#   （泄漏版）结果，按 setting 聚合 loc_top1/repair_pass/成本，输出对比表与逐样本差异。
import json, glob, os, sys
from collections import Counter, defaultdict
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAK = os.path.join(REPO, 'experiments/runs/experiments_results_ds_full3.json')
def load_leakfix():
    rows = []
    for f in sorted(glob.glob(os.path.join(REPO, 'experiments/runs/leakfix_[0-9].json'))):
        try: rows += json.load(open(f, encoding='utf-8'))
        except Exception as e: print('skip', f, repr(e)[:60])
    return rows
def load_old():
    d = json.load(open(LEAK, encoding='utf-8'))
    return d.get('results', d) if isinstance(d, dict) else d
def agg(rows):
    out = defaultdict(lambda: {'n': 0, 'loc': 0, 'repair': 0, 'cost': 0.0})
    for r in rows:
        s = r.get('setting'); a = out[s]
        a['n'] += 1; a['loc'] += 1 if r.get('loc_top1') else 0
        a['repair'] += 1 if r.get('repair_pass') else 0
        a['cost'] += r.get('cost') or 0
    return out
def fmt(a):
    return 'n=%d loc=%d(%.1f%%) repair=%d(%.1f%%) cost=$%.3f' % (
        a['n'], a['loc'], 100*a['loc']/max(1,a['n']), a['repair'], 100*a['repair']/max(1,a['n']), a['cost'])
def main():
    new = load_leakfix()
    old = load_old()
    print('leakfix rows:', len(new), '| old rows:', len(old))
    print()
    print('=== 按设置对比（旧=泄漏版 DS / 新=无泄漏重跑）===')
    ag, ao = agg(new), agg(old)
    for s in sorted(set(ag) | set(ao)):
        print('%s:' % s)
        print('  旧:', fmt(ao.get(s, {'n':0,'loc':0,'repair':0,'cost':0})))
        print('  新:', fmt(ag.get(s, {'n':0,'loc':0,'repair':0,'cost':0})))
    print()
    print('=== 逐样本 loc_top1 翻转（旧True新False 或 旧False新True）===')
    oldm = {(r.get('sample'), r.get('setting'), r.get('seed')): r for r in old}
    flips = 0
    for r in new:
        o = oldm.get((r.get('sample'), r.get('setting'), r.get('seed')))
        if o and o.get('loc_top1') != r.get('loc_top1'):
            flips += 1
            print('  %s/%s/seed%s: %s -> %s' % (r.get('sample'), r.get('setting'), r.get('seed'), o.get('loc_top1'), r.get('loc_top1')))
    print('loc_top1 翻转总数:', flips)
    return 0
if __name__ == '__main__':
    sys.exit(main())
