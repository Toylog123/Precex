#!/usr/bin/env python3
# PreCex - scripts/measure_slim_compression.py C 证据压缩对比（Phase 1.5）
# 作者：Toylog | 版本：v0.1 | 功能概述：对 samples/bugs 下 34 样本的 semantics.json
#   量化"激进出采样压缩（_SLIM_C）"相对原始 JSON 的字符数压缩率；若存在 token 账本中
#   cex_semantize 调用的 in/out token，也给出 token/成本节省。只读，不改任何数据。
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUGS = os.path.join(REPO_ROOT, 'samples', 'bugs')
RUNS = os.path.join(REPO_ROOT, 'experiments', 'runs')

def slim_semantics_text(sample_dir):
    """与 run_experiments.py _SLIM_C 同协议。"""
    with open(os.path.join(sample_dir, 'semantics.json'), encoding='utf-8') as f:
        s = json.load(f)
    fs = s.get('fail_step')
    def _ds(seq):
        if not seq:
            return seq
        out = []
        lo = max(0, (fs - 4) if fs is not None else 0)
        for i, item in enumerate(seq):
            cyc = item.get('cycle') if isinstance(item, dict) else i
            try:
                cyc = int(cyc)
            except (TypeError, ValueError):
                cyc = i
            if cyc >= lo or i % 8 == 0:
                out.append(item)
        return out
    slim = {
        'module': s.get('module'), 'error_type': s.get('error_type'),
        'fail_stage': s.get('fail_stage'), 'fail_step': fs,
        'failed_line': s.get('failed_line'), 'trigger_condition': s.get('trigger_condition'),
        'fault_cone': s.get('fault_cone'),
        'cycle_events': _ds(s.get('cycle_events') or []),
        'state_trace': _ds(s.get('state_trace') or []),
    }
    ts = (s.get('text_summary') or '').strip()
    if ts:
        slim['text_summary'] = ts[:300] + ('…' if len(ts) > 300 else '')
    return json.dumps(slim, ensure_ascii=False, indent=2)

def main():
    rows = []
    total_raw = total_slim = 0
    for d in sorted(os.listdir(BUGS)):
        sdir = os.path.join(BUGS, d)
        p = os.path.join(sdir, 'semantics.json')
        if not os.path.isdir(sdir) or not os.path.isfile(p):
            continue
        with open(p, encoding='utf-8') as f:
            raw = f.read()
        slim = slim_semantics_text(sdir)
        raw_len = len(raw)
        slim_len = len(slim)
        total_raw += raw_len
        total_slim += slim_len
        rows.append({'sample': d, 'raw_chars': raw_len, 'slim_chars': slim_len,
                     'ratio': round(raw_len / max(1, slim_len), 3),
                     'saved_pct': round((1 - slim_len / max(1, raw_len)) * 100, 1)})
    rows.sort(key=lambda r: r['sample'])
    summary = {
        'n': len(rows),
        'total_raw_chars': total_raw,
        'total_slim_chars': total_slim,
        'overall_saved_pct': round((1 - total_slim / max(1, total_raw)) * 100, 1),
        'overall_ratio': round(total_raw / max(1, total_slim), 3),
        'median_saved_pct': round(sorted(r['saved_pct'] for r in rows)[len(rows)//2], 1),
        'per_sample': rows,
    }
    out = os.path.join(RUNS, 'slim_compression.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:2200])

if __name__ == '__main__':
    main()
