# -*- coding: utf-8 -*-
"""Non-LLM localization baselines, aligned with main-experiment loc_top1 (exact match on buggy_inject_line).
Baselines: (1) assertion-line heuristics, (2) signal-mention line, (3) random line (exact expected value)."""
import json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = r'D:\BaiduSyncdisk\02_Precex'
SAMPLES = os.path.join(BASE, 'samples', 'bugs')

def buggy_line(meta):
    gl = meta.get('inject_line')
    return meta.get('buggy_inject_line') or (gl + 4 if gl else None)

rows = []
for s in sorted(os.listdir(SAMPLES)):
    if not s.startswith('s'): continue
    d = os.path.join(SAMPLES, s)
    if not os.path.exists(os.path.join(d, 'meta.json')): continue
    meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
    with open(os.path.join(d, 'buggy.v'), encoding='utf-8') as f:
        lines = f.read().splitlines()
    bl = buggy_line(meta)
    alines = [i+1 for i, ln in enumerate(lines) if 'assert' in ln or 'assume' in ln or 'property' in ln]
    sigs = []
    ep = os.path.join(d, 'evidence.json')
    if os.path.exists(ep):
        try:
            ev = json.load(open(ep, encoding='utf-8'))
            sg = ev.get('signals', {})
            sigs = list(sg.keys()) if isinstance(sg, dict) else (sg or [])
        except Exception: pass
    slines = []
    for i, ln in enumerate(lines, 1):
        if any(x in ln for x in sigs) and ('assign' in ln or 'always' in ln or '<=' in ln):
            slines.append(i)
    rows.append({'sample': s, 'module': meta.get('module',''), 'error_type': meta.get('error_type',''),
                 'buggy_line': bl, 'total_lines': len(lines), 'assert_lines': alines, 'signal_lines': slines})

n = len(rows)
def rate(fn):
    hits = sum(1 for r in rows if r['buggy_line'] and fn(r) == r['buggy_line'])
    return hits, n

h1, _ = rate(lambda r: r['assert_lines'][0] if r['assert_lines'] else None)
h1b, _ = rate(lambda r: r['buggy_line'] if r['buggy_line'] in r['assert_lines'] else None)
h2, _ = rate(lambda r: r['signal_lines'][0] if r['signal_lines'] else None)
ev_random = sum(1.0/r['total_lines'] for r in rows) / n

print('samples:', n)
print(f'assert-first-line:        {h1}/{n} = {h1/n*100:.1f}%')
print(f'any-assert-line:          {h1b}/{n} = {h1b/n*100:.1f}%')
print(f'signal-first-line:        {h2}/{n} = {h2/n*100:.1f}%')
print(f'random-line (EV, exact):  {ev_random*100:.2f}%')

with open(os.path.join(BASE, 'experiments', 'runs', 'nonllm_baselines.json'), 'w', encoding='utf-8') as f:
    json.dump({'n': n, 'assert_first_line': h1/n, 'any_assert_line': h1b/n,
               'signal_first_line': h2/n, 'random_ev': ev_random,
               'detail': rows}, f, ensure_ascii=False, indent=1)
print('saved nonllm_baselines.json')
