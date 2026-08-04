# -*- coding: utf-8 -*-
"""Generate paper figures for PreCex from authoritative data."""
import os, json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import collections
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'paper', 'figures'))
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({'figure.dpi': 150, 'font.size': 10, 'axes.titlesize': 11, 'axes.labelsize': 10})

def load_json(rel):
    p = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', rel))
    with open(p, encoding='utf-8') as f:
        return json.load(f)

# ---- authoritative data loading (replaces hard-coded numbers) ----
abc = load_json('experiments/runs/experiments_results_corrected.json')
dset = load_json('experiments/runs/experiments_results_D_clean.json')
rows_abc = abc['results'] if isinstance(abc, dict) else abc
rows_d = dset['results'] if isinstance(dset, dict) else dset

def setting_stats(rows):
    agg = collections.defaultdict(lambda: {'n': 0, 'loc': 0, 'cost': 0.0})
    for r in rows:
        s = r.get('setting')
        a = agg[s]
        a['n'] += 1
        if r.get('loc_top1'):
            a['loc'] += 1
        a['cost'] += float(r.get('cost_usd') or r.get('cost') or 0)
    return agg

stats = setting_stats(rows_abc)
stats_d = setting_stats(rows_d)
for s in ('A', 'B', 'C'):
    stats.setdefault(s, {'n': 0, 'loc': 0, 'cost': 0.0})
if 'D' in stats_d:
    stats['D'] = stats_d['D']
for s in ('A', 'B', 'C', 'D'):
    stats[s]['loc_rate'] = 100.0 * stats[s]['loc'] / max(stats[s]['n'], 1)

settings = ['A', 'B', 'C', 'D']
loc = [stats[s]['loc_rate'] for s in settings]
cost = [round(stats[s]['cost'], 2) for s in settings]
labels = ['A\n(raw log)', 'B\n(structured)', 'C\n(semanticized)', 'D\n(causal graph)']

# ---- Figure 1: Four-setting localization + cost ----

fig, ax1 = plt.subplots(figsize=(7, 4.2))
bars = ax1.bar(labels, loc, color=['#8aa8c8', '#d1495b', '#f2a65a', '#6a8caf'], alpha=0.9, width=0.6)
ax1.set_ylabel('loc_top1 precision (%)')
ax1.set_ylim(0, 100)
for b, v in zip(bars, loc):
    ax1.text(b.get_x() + b.get_width()/2, v + 1.5, f'{v:.1f}%', ha='center', fontsize=9)
ax1.set_title('Localization precision by evidence setting (n=%d each)' % stats['A']['n'])
ax1.annotate('', xy=(1, 68), xytext=(0, 68), arrowprops=dict(arrowstyle='-', color='k', lw=1))
ax1.text(0.5, 70, 'p=0.0035', ha='center', fontsize=8)
ax1.annotate('', xy=(1, 55), xytext=(3, 55), arrowprops=dict(arrowstyle='-', color='k', lw=1))
ax1.text(2, 57, 'p=0.0164', ha='center', fontsize=8)
ax2 = ax1.twinx()
ax2.plot(labels, cost, '--o', linewidth=1.5, color='#333')
ax2.set_ylabel('LLM cost (USD)')
ax2.set_ylim(0, 6)
for x, v in zip(range(4), cost):
    ax2.text(x, v + 0.15, f'${v:.2f}', ha='center', fontsize=8)
plt.tight_layout()
plt.savefig(os.path.join(OUT, 'fig_setting_loc_cost.png'), bbox_inches='tight')
plt.close()

# ---- Figure 2: Error-type x setting heatmap ----
errs = ['state\ntrans', 'handshake', 'reset', 'fifo\nfull/empty', 'boundary\nwrap', 'width\ntrunc', 'edge']
err_order = ['状态跳转', '握手', '复位', 'FIFO 满空', '边界回绕', '位宽截断', '边沿']
mat = np.zeros((7, 4))
all_rows = rows_abc + rows_d
for i, e in enumerate(err_order):
    for j, s in enumerate(settings):
        sub = [r for r in all_rows if r.get('error_type') == e and r.get('setting') == s]
        n = len(sub)
        mat[i, j] = 100.0 * sum(1 for r in sub if r.get('loc_top1')) / max(n, 1)
fig, ax = plt.subplots(figsize=(6.5, 4.5))
im = ax.imshow(mat, cmap='YlGnBu', vmin=0, vmax=100, aspect='auto')
ax.set_xticks(range(4)); ax.set_xticklabels(labels, fontsize=9)
ax.set_yticks(range(7)); ax.set_yticklabels(errs, fontsize=9)
ax.set_xlabel('Evidence setting')
ax.set_title('loc_top1 precision by error class and setting (%)')
for i in range(7):
    for j in range(4):
        ax.text(j, i, f'{mat[i,j]:.0f}', ha='center', va='center', fontsize=9,
                color='white' if mat[i,j] > 55 else 'black')
fig.colorbar(im, label='loc_top1 (%)')
plt.tight_layout()
plt.savefig(os.path.join(OUT, 'fig_error_setting_heatmap.png'), bbox_inches='tight')
plt.close()

# ---- Figure 3: Pipeline architecture (schematic) ----
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.set_xlim(0, 10); ax.set_ylim(0, 5); ax.axis('off')
boxes = [
    (0.2, 3.4, 1.9, 1.2, 'Failing formal\ntrace (sby VCD)', '#dbe9f6'),
    (2.5, 3.4, 1.9, 1.2, 'EvidenceEngine\n(structured JSON, B)', '#cfe8cf'),
    (4.8, 3.4, 1.9, 1.2, 'CexSemantizer\n(cycle/state/fault cone,\nNL summary, C)', '#fde9d9'),
    (7.1, 3.4, 1.9, 1.2, 'LocalRepairer\n(LLM, slice-constrained\ndiff)', '#f9d5e5'),
    (3.65, 0.4, 2.7, 1.2, 'Verifier\n(compile + sim + BMC,\nT2 audit, mutation)', '#e6e0f8'),
]
for x, y, w, h, label, color in boxes:
    rect = plt.Rectangle((x, y), w, h, facecolor=color, edgecolor='#333', linewidth=1.2, zorder=2)
    ax.add_patch(rect)
    ax.text(x + w/2, y + h/2, label, ha='center', va='center', fontsize=8.5, zorder=3)
for i in range(len(boxes)-2):
    x0 = boxes[i][0] + boxes[i][2]; x1 = boxes[i+1][0]
    ax.annotate('', xy=(x1, boxes[i+1][1] + boxes[i+1][3]/2), xytext=(x0, boxes[i][1] + boxes[i][3]/2),
                arrowprops=dict(arrowstyle='->', color='#333', lw=1.5))
ax.annotate('', xy=(4.05, 1.6), xytext=(3.65, 1.6), arrowprops=dict(arrowstyle='-', color='#999', lw=1))
ax.annotate('', xy=(2.45, 3.4), xytext=(4.05, 1.0), arrowprops=dict(arrowstyle='->', color='#999', lw=1.2, linestyle='--'))
ax.text(4.5, 1.05, 'fail: re-run <=N (new evidence)', ha='center', fontsize=8, color='#555')
ax.text(4.9, 4.75, 'pass: patch + verification record', ha='center', fontsize=8.5, color='#2a7d2a')
ax.text(0.3, 4.75, 'PreCex pipeline', fontsize=12, fontweight='bold')
plt.tight_layout()
plt.savefig(os.path.join(OUT, 'fig_pipeline.png'), bbox_inches='tight')
plt.close()
print('figures written:', os.listdir(OUT))
