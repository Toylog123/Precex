# -*- coding: utf-8 -*-
import json, glob, os, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "paper", "figures"))
VEC = os.path.join(OUT, "vector")
os.makedirs(OUT, exist_ok=True)
os.makedirs(VEC, exist_ok=True)

def save_fig(fig, name):
    fig.savefig(os.path.join(OUT, name + ".png"), bbox_inches="tight")
    fig.savefig(os.path.join(OUT, name + ".pdf"), bbox_inches="tight", format="pdf")
    fig.savefig(os.path.join(VEC, name + ".pdf"), bbox_inches="tight", format="pdf")
    fig.savefig(os.path.join(VEC, name + ".svg"), bbox_inches="tight", format="svg")
    print("saved:", name)
    plt.close(fig)

plt.rcParams.update({"figure.dpi": 150, "font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10})

RUNS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "experiments", "runs"))

def load_parts(pattern, settings):
    rows = []
    for f in sorted(glob.glob(os.path.join(RUNS, pattern))):
        d = json.load(open(f, encoding="utf-8"))
        rows.extend(d.get("results", []) if isinstance(d, dict) else d)
    seen, uniq = set(), []
    for r in rows:
        k = (r.get("sample"), r.get("setting"), r.get("seed"))
        if k in seen or r.get("setting") not in settings:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq

etype_map = {"状态跳转": "状态迁移", "状态迁移": "状态迁移", "握手": "握手", "复位": "复位",
             "FIFO 满空": "FIFO 满空", "边界回绕": "边界回绕", "位宽截断": "位宽截断", "边沿": "边沿"}
def etype(r):
    e = r.get("error_type", "")
    if e in etype_map:
        return etype_map[e]
    for k in etype_map:
        if k and k in e:
            return etype_map[k]
    return e or "?"

abc = load_parts("leakfix_[0-7].json", ("A", "B", "C"))
drows = load_parts("leakfix_D_[0-7].json", ("D",))
settings = ["A", "B", "C"]
if drows:
    settings.append("D")

def setting_stats(rows):
    agg = collections.defaultdict(lambda: {"n": 0, "loc": 0, "cost": 0.0})
    for r in rows:
        a = agg[r["setting"]]
        a["n"] += 1
        if r.get("loc_top1"):
            a["loc"] += 1
        a["cost"] += float(r.get("cost") or r.get("cost_usd") or 0)
    return agg

stats = setting_stats(abc + drows)
labels = {"A": "A\n(raw log)", "B": "B\n(structured)", "C": "C\n(semanticized)", "D": "D\n(causal graph)"}

# ---- Figure 1: setting localization + cost ----
fig, ax1 = plt.subplots(figsize=(7, 4.2))
loc = [100.0 * stats[s]["loc"] / max(stats[s]["n"], 1) for s in settings]
cost = [round(stats[s]["cost"], 2) for s in settings]
cols = {"A": "#8aa8c8", "B": "#d1495b", "C": "#f2a65a", "D": "#6a8caf"}
bars = ax1.bar([labels[s] for s in settings], loc, color=[cols[s] for s in settings], alpha=0.9, width=0.6)
ax1.set_ylabel("loc_top1 precision (%)")
ax1.set_ylim(0, 100)
for b, v in zip(bars, loc):
    ax1.text(b.get_x() + b.get_width() / 2, v + 1.5, "%.1f%%" % v, ha="center", fontsize=9)
n0 = stats["A"]["n"] if "A" in stats else 0
ax1.set_title("Localization precision by evidence setting (clean, n=%d each)" % n0)
ax1.text(0.5, 94, "paired diffs all n.s.\n(McNemar exact)", ha="center", fontsize=8, color="#555")
ax2 = ax1.twinx()
ax2.plot([labels[s] for s in settings], cost, "--o", linewidth=1.5, color="#333")
ax2.set_ylabel("LLM cost (USD)")
ax2.set_ylim(0, max(1.2, max(cost) * 1.4))
for x, v in zip(range(len(settings)), cost):
    ax2.text(x, v + 0.06, "$%.2f" % v, ha="center", fontsize=8)
plt.tight_layout()
save_fig(fig, "fig_setting_loc_cost")

# ---- Figure 2: error-type x setting heatmap ----
errs = ["state\ntrans", "handshake", "reset", "fifo\nfull/empty", "boundary\nwrap", "width\ntrunc", "edge"]
err_order = ["状态迁移", "握手", "复位", "FIFO 满空", "边界回绕", "位宽截断", "边沿"]
all_rows = abc + drows
mat = np.zeros((len(err_order), len(settings)))
for i, e in enumerate(err_order):
    for j, s in enumerate(settings):
        sub = [r for r in all_rows if etype(r) == e and r.get("setting") == s]
        n = len(sub)
        mat[i, j] = 100.0 * sum(1 for r in sub if r.get("loc_top1")) / max(n, 1)
fig, ax = plt.subplots(figsize=(6.5, 4.5))
im = ax.imshow(mat, cmap="YlGnBu", vmin=0, vmax=100, aspect="auto")
ax.set_xticks(range(len(settings)))
ax.set_xticklabels([labels[s] for s in settings], fontsize=9)
ax.set_yticks(range(len(err_order)))
ax.set_yticklabels(errs, fontsize=9)
ax.set_xlabel("Evidence setting")
ax.set_title("loc_top1 precision by error class and setting (%)")
for i in range(len(err_order)):
    for j in range(len(settings)):
        ax.text(j, i, "%.0f" % mat[i, j], ha="center", va="center", fontsize=9,
                color="white" if mat[i, j] > 55 else "black")
fig.colorbar(im, label="loc_top1 (%)")
plt.tight_layout()
save_fig(fig, "fig_error_setting_heatmap")

# ---- Figure 3: pipeline architecture (schematic, unchanged) ----
fig, ax = plt.subplots(figsize=(9, 4.5))
ax.set_xlim(0, 10); ax.set_ylim(0, 5); ax.axis("off")
boxes = [
    (0.2, 3.4, 1.9, 1.2, "Failing formal\ntrace (sby VCD)", "#dbe9f6"),
    (2.5, 3.4, 1.9, 1.2, "EvidenceEngine\n(structured JSON, B)", "#cfe8cf"),
    (4.8, 3.4, 1.9, 1.2, "CexSemantizer\n(cycle/state/fault cone,\nNL summary, C)", "#fde9d9"),
    (7.1, 3.4, 1.9, 1.2, "LocalRepairer\n(LLM, slice-constrained\ndiff)", "#f9d5e5"),
    (3.65, 0.4, 2.7, 1.2, "Verifier\n(compile + sim + BMC,\nT2 audit, mutation)", "#e6e0f8"),
]
for x, y, w, h, label, color in boxes:
    rect = plt.Rectangle((x, y), w, h, facecolor=color, edgecolor="#333", linewidth=1.2, zorder=2)
    ax.add_patch(rect)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=8.5, zorder=3)
for i in range(len(boxes) - 2):
    x0 = boxes[i][0] + boxes[i][2]; x1 = boxes[i + 1][0]
    ax.annotate("", xy=(x1, boxes[i + 1][1] + boxes[i + 1][3] / 2), xytext=(x0, boxes[i][1] + boxes[i][3] / 2),
                arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))
ax.annotate("", xy=(4.05, 1.6), xytext=(3.65, 1.6), arrowprops=dict(arrowstyle="-", color="#999", lw=1))
ax.annotate("", xy=(2.45, 3.4), xytext=(4.05, 1.0), arrowprops=dict(arrowstyle="->", color="#999", lw=1.2, linestyle="--"))
ax.text(4.5, 1.05, "fail: re-run <=N (new evidence)", ha="center", fontsize=8, color="#555")
ax.text(4.9, 4.75, "pass: patch + verification record", ha="center", fontsize=8.5, color="#2a7d2a")
ax.text(0.3, 4.75, "PreCex pipeline", fontsize=12, fontweight="bold")
plt.tight_layout()
save_fig(fig, "fig_pipeline")
print("figures written:", os.listdir(OUT))
