#!/usr/bin/env python3
# PreCex - scripts/aggregate_verify_timing.py 验证段计时聚合（Phase 1）
# 作者：Toylog | 版本：v0.1 | 功能概述：从 gate2_verify_all.log（逐样本 sby 验证日志）聚合
#   每个样本 verify/golden 的验证墙钟耗时，写 experiments/runs/verify_timing.json（不入库）。
#   主实验历史数据未记录验证段计时（旧版 evaluator 未落盘），本脚本从 gate2 复验日志恢复
#   可复现的验证耗时统计；未来 run_experiments 输出已含 verify_elapsed 字段。
import json, os, re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO_ROOT, 'experiments', 'runs')

def extract_timing(log_text):
    """从 gate2 日志提取：'[1/68] s06 verify: DONE (FAIL, rc=2) (8.3s)' → s06.verify=8.3"""
    out = {}
    # 每任务行：[n/N] sXX <kind>: DONE (<verdict>, rc=<rc>) (<sec>s)
    for m in re.finditer(r'\[\d+/\d+\]\s+(s\d{2,})\s+(verify|golden):\s+DONE\s+\([^)]*\)\s+\(([\d.]+)s\)', log_text):
        sid = m.group(1)
        kind = m.group(2)
        sec = float(m.group(3))
        key = '%s.%s' % (sid, kind)
        out[key] = out.get(key, 0) + sec
    return out

def main():
    results = {}
    sources = []
    for pat in ('gate2_verify_all.log', 'gate2_reverify.json'):
        p = os.path.join(RUNS, pat)
        if os.path.isfile(p):
            with open(p, encoding='utf-8', errors='replace') as f:
                txt = f.read()
            sources.append(pat)
            if pat.endswith('.json'):
                try:
                    d = json.loads(txt)
                    rows = d if isinstance(d, list) else d.get('results', d.get('samples', []))
                    for r in rows:
                        sid = r.get('sample') or r.get('id')
                        if sid and r.get('elapsed'):
                            results.setdefault(sid + '.verify', 0)
                            results[sid + '.verify'] = max(results.get(sid + '.verify', 0), float(r['elapsed']))
                except Exception as e:
                    print('json parse skip', pat, e)
            else:
                results.update(extract_timing(txt))
    samples = sorted(set(k.split('.')[0] for k in results))
    # 每样本 verify + golden 合计
    per_sample = {}
    for s in samples:
        v = results.get(s + '.verify')
        g = results.get(s + '.golden')
        per_sample[s] = {'verify_s': round(v, 1) if v is not None else None,
                         'golden_s': round(g, 1) if g is not None else None}
    verify_vals = [x['verify_s'] for x in per_sample.values() if x['verify_s'] is not None]
    golden_vals = [x['golden_s'] for x in per_sample.values() if x['golden_s'] is not None]
    summary = {
        'sources': sources,
        'generated': __import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'),
        'n_samples': len(samples),
        'verify_total_s': round(sum(verify_vals), 1),
        'verify_median_s': round(sorted(verify_vals)[len(verify_vals)//2], 1) if verify_vals else 0,
        'verify_max_s': round(max(verify_vals), 1) if verify_vals else 0,
        'golden_total_s': round(sum(golden_vals), 1),
        'golden_median_s': round(sorted(golden_vals)[len(golden_vals)//2], 1) if golden_vals else 0,
        'golden_max_s': round(max(golden_vals), 1) if golden_vals else 0,
        'per_sample': per_sample,
    }
    out = os.path.join(RUNS, 'verify_timing.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
