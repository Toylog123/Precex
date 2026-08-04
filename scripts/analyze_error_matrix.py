# -*- coding: utf-8 -*-
import json, sys, io, os
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
base = r'D:\BaiduSyncdisk\02_Precex\experiments\runs'
def load(fn):
    with open(os.path.join(base, fn), encoding='utf-8') as f:
        return json.load(f)
abc = load('experiments_results_corrected.json')['results']
d = load('experiments_results_D_clean.json')['results']
print('ABC n =', len(abc), ' D n =', len(d))
print('ABC repair_pass_bmc sum:', sum(1 for x in abc if x.get('repair_pass_bmc')))
print('ABC repair_pass old sum:', sum(1 for x in abc if x.get('repair_pass')))

def agg_loc(rows):
    m = defaultdict(lambda: [0, 0])
    for x in rows:
        m[x['error_type']][0] += 1
        if x.get('loc_top1'):
            m[x['error_type']][1] += 1
    return m

def agg_rep(rows):
    m = defaultdict(lambda: [0, 0])
    for x in rows:
        m[x['error_type']][0] += 1
        if x.get('repair_pass_bmc') is not False:  # include True/None? use truthy
            m[x['error_type']][1] += 1
    return m

def show(label, m, rate_idx=1):
    print('---', label, '---')
    for err in sorted(m, key=lambda k: -m[k][0]):
        n, hits = m[err]
        print(f'{err}\t{n}\t{hits}\t{hits/n*100:.1f}%')

show('LOC ABC (corrected)', agg_loc(abc))
show('LOC D', agg_loc(d))
all_rows = abc + d
show('LOC ALL', agg_loc(all_rows))
for setting in ['A','B','C','D']:
    rows = [x for x in all_rows if x['setting']==setting]
    show('LOC setting '+setting, agg_loc(rows))
print('--- REPAIR by BMC (ABC) ---')
m = agg_rep(abc)
for err in sorted(m, key=lambda k: -m[k][0]):
    n, hits = m[err]
    print(f'{err}\t{n}\t{hits}\t{hits/n*100:.1f}%')
