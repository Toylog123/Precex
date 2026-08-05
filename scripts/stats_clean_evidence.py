#!/usr/bin/env python3
# PreCex - scripts/stats_clean_evidence.py  干净口径统计补全（论文 P1 统计方法项）
# 输出：McNemar 精确检验（含 Holm 校正）、Wilson 比例 CI、效应量（率差+CI）、seed 稳定性、成本重算
# 用法：python scripts/stats_clean_evidence.py [--json experiments/runs/clean_stats.json]
import json, glob, os, sys, math
from collections import defaultdict
from itertools import combinations

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO, 'experiments', 'runs')

def load_shards(pattern):
    rows = []
    for f in sorted(glob.glob(os.path.join(RUNS, pattern))):
        try:
            d = json.load(open(f, encoding='utf-8'))
            rows += d.get('results', []) if isinstance(d, dict) else d
        except Exception as e:
            print('skip', os.path.basename(f), repr(e)[:80])
    return rows

def dedupe(rows):
    seen = set(); out = []
    for r in rows:
        k = (r.get('sample'), r.get('setting'), r.get('seed'))
        if k in seen: continue
        seen.add(k); out.append(r)
    return out

def wilson_ci(k, n, z=1.959964):
    if n == 0: return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return p, max(0.0, center-half), min(1.0, center+half)

def mcnemar_exact(a, b, c, d):
    disc = b + c
    if disc == 0:
        return 1.0, (b, c)
    p = 0.0
    k_obs = b
    base = math.comb(disc, k_obs) * 0.5**disc
    for k in range(disc + 1):
        prob = math.comb(disc, k) * 0.5**disc
        if prob <= base + 1e-15:
            p += prob
    return p, (b, c)

def holm_adjust(ps):
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    out = [None]*m
    prev = 1.0
    for rank, idx in enumerate(order, 1):
        val = max(ps[idx]*(m - rank + 1), 0.0)
        val = min(val, prev)
        out[idx] = val
        prev = val
    return out

def main():
    out_path = None
    if '--json' in sys.argv:
        out_path = sys.argv[sys.argv.index('--json')+1]
    rows = dedupe(load_shards('leakfix_[0-9].json') + load_shards('leakfix_D.json'))
    rows = [r for r in rows if r.get('setting') in ('A','B','C','D')]
    by = defaultdict(list)
    for r in rows: by[r['setting']].append(r)
    settings = ['A','B','C','D']
    agg = {}
    for s in settings:
        rs = by[s]
        n = len(rs)
        loc = sum(1 for r in rs if r.get('loc_top1'))
        repair = sum(1 for r in rs if r.get('repair_pass'))
        cost = sum(r.get('cost') or 0 for r in rs)
        itok = sum(r.get('input_tokens') or 0 for r in rs)
        otok = sum(r.get('output_tokens') or 0 for r in rs)
        p, lo, hi = wilson_ci(loc, n)
        agg[s] = dict(n=n, loc=loc, loc_rate=100*loc/n, wilson_lo=100*lo, wilson_hi=100*hi,
                      repair=repair, repair_rate=100*repair/n, cost=cost,
                      in_tok=itok, out_tok=otok, per_seed={})
        sby = defaultdict(list)
        for r in rs: sby[r.get('seed')].append(r)
        for sd in sorted(sby):
            srs = sby[sd]
            sloc = sum(1 for x in srs if x.get('loc_top1'))
            sby[sd] = dict(n=len(srs), loc=sloc, rate=100*sloc/len(srs))
        agg[s]['per_seed'] = sby

    keyed = {}
    for r in rows:
        keyed.setdefault(r['setting'], {}).setdefault((r.get('sample'), r.get('seed')), r)
    pairs = list(combinations(settings, 2))
    mcn = []
    for sa, sb in pairs:
        ka, kb = keyed[sa], keyed[sb]
        common = set(ka) & set(kb)
        a = b = c = d = 0
        for k in common:
            va, vb = bool(ka[k].get('loc_top1')), bool(kb[k].get('loc_top1'))
            if va and vb: a += 1
            elif va and not vb: b += 1
            elif not va and vb: c += 1
            else: d += 1
        pv, disc = mcnemar_exact(a, b, c, d)
        pa, pb = agg[sa]['loc_rate']/100, agg[sb]['loc_rate']/100
        na, nb = agg[sa]['n'], agg[sb]['n']
        diff = pa - pb
        se = math.sqrt(pa*(1-pa)/na + pb*(1-pb)/nb)
        mcn.append(dict(pair=sa + ' vs ' + sb, a=a, b=b, c=c, d=d, n=len(common),
                        p=pv, loc_rate_a=100*pa, loc_rate_b=100*pb,
                        rate_diff=100*diff, rate_diff_ci_lo=100*(diff-1.96*se),
                        rate_diff_ci_hi=100*(diff+1.96*se), discordant=disc))
    ps = [x['p'] for x in mcn]
    holm = holm_adjust(ps)
    for x, hp in zip(mcn, holm): x['p_holm'] = hp

    lines = []
    lines.append('=== 干净口径四设置聚合（Wilson 95% CI）===')
    for s in settings:
        a = agg[s]
        lines.append(s + ': n=' + str(a['n']) + ' loc=' + str(a['loc']) + ' (' + format(a['loc_rate'], '.1f') + '%, 95%CI ' + format(a['wilson_lo'], '.1f') + '-' + format(a['wilson_hi'], '.1f') + ') repair=' + str(a['repair']) + '/' + str(a['n']) + ' (' + format(a['repair_rate'], '.1f') + '%) cost=$' + format(a['cost'], '.4f'))
    lines.append('')
    lines.append('=== 配对 McNemar（逐 sample x seed 对齐，Holm 校正）===')
    for x in mcn:
        lines.append(x['pair'] + ': a=' + str(x['a']) + ' b=' + str(x['b']) + ' c=' + str(x['c']) + ' d=' + str(x['d']) + ' n=' + str(x['n']) + ' p=' + format(x['p'], '.4f') + ' p_holm=' + format(x['p_holm'], '.4f') + ' | 率差=' + format(x['rate_diff'], '+.1f') + 'pp (95%CI ' + format(x['rate_diff_ci_lo'], '+.1f') + '~' + format(x['rate_diff_ci_hi'], '+.1f') + ')')
    lines.append('')
    lines.append('=== seed 稳定性（每设置每 seed 定位率）===')
    for s in settings:
        parts = ' '.join('seed' + str(sd) + ':' + format(v['rate'], '.1f') + '%' for sd, v in sorted(agg[s]['per_seed'].items()))
        rates = [v['rate'] for v in agg[s]['per_seed'].values()]
        lines.append(s + ': ' + parts + ' | min-max 跨度 ' + format(max(rates)-min(rates), '.1f') + 'pp')
    lines.append('')
    lines.append('总运行: ' + str(sum(a['n'] for a in agg.values())) + ' | 总成本: $' + format(sum(a['cost'] for a in agg.values()), '.4f'))

    if out_path:
        payload = dict(settings=agg, pairwise=mcn, total_n=sum(a['n'] for a in agg.values()),
                       total_cost=sum(a['cost'] for a in agg.values()))
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        lines.append('')
        lines.append('WROTE ' + out_path)
    print('\n'.join(lines))
    return 0

if __name__ == '__main__':
    sys.exit(main())
