#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreCex - Verifier 断言充分性量化（mutation / 非空洞检测）

对每个样本的 golden.v（正确设计）做断言 mutation：
  将断言表达式中的比较运算符随机扰动（> < >= <= == != 互换），
  生成 mutated golden.v，跑 sby 验证：
    - mutation 后 sby 抓到反例（FAIL）  -> 该断言能区分好坏（非空洞、有效）
    - mutation 后仍 PASS               -> 断言可能空洞/冗余（对缺陷不敏感）
输出 per-sample mutation 通过率（样本越接近 100% 越健康）与失败清单。

用法 (Windows): python scripts/verify_sufficiency.py [--jobs 8] [--samples s04,s10] [--out experiments/runs/sufficiency.json]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（跨平台 WSL/Windows）
BUGS = os.path.join(REPO_ROOT, 'samples', 'bugs')
OUT_DIR = os.path.join(REPO_ROOT, 'experiments', 'runs')
WSL_PREFIX = ('export HOME=/home/toylog; export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin; '
              'export SMTBMC=/mnt/d/BaiduSyncdisk/02_Precex/smoke/yosys-smtbmc-z3.sh; ')
IN_WSL = bool(os.environ.get('WSL_DISTRO_NAME'))  # 是否已在 WSL 内（WSL 内不嵌套调 wsl）

# 比较运算符扰动映射：mutation 时把 op 换成不同的 op
OPS = ['>=', '<=', '>', '<', '==', '!=']
OP_REPLACEMENT = {
    '>=': ['>', '<', '==', '!='],
    '<=': ['<', '>', '==', '!='],
    '>': ['>=', '<', '==', '!='],
    '<': ['<=', '>', '==', '!='],
    '==': ['!=', '>=', '<='],
    '!=': ['==', '>=', '<='],
}
# 强变异：取反语义（弱化变异会虚报 killed=0%，--strong 使用此表）
STRONG_OP_REPLACEMENT = {
    '>=': ['<'],
    '<=': ['>'],
    '>': ['<='],
    '<': ['>='],
    '==': ['!='],
    '!=': ['=='],
}

# 高阶变异类型：delete = 删除断言行；const = 改常量（DATA_W/ADDR_W/DEPTH 等参数引用）
HIGHER_ORDER_MUTATIONS = ['delete', 'const']

def expand_samples(spec):
    if not spec:
        return sorted(d for d in os.listdir(BUGS)
                      if re.match(r'^s\d{2}$', d) and os.path.isdir(os.path.join(BUGS, d)))
    out = []
    for part in spec.split(','):
        m = re.match(r'^s(\d+)-s(\d+)$', part)
        if m:
            out += ['s%02d' % i for i in range(int(m.group(1)), int(m.group(2)) + 1)]
        else:
            out.append(part)
    return out


def find_assert_lines(src):
    """提取含 assert 的行号与行文本（排除注释/字符串内的）。"""
    out = []
    for i, ln in enumerate(src.split('\n'), 1):
        code = re.sub(r'//.*$', '', ln)
        if 'assert' in code and not code.strip().startswith('//'):
            out.append((i, ln))
    return out


def mutate_line(line, op_map):
    """对行内第一个比较运算符做一次扰动；返回 (mutated_line, old_op, new_op) 或 None。
    布尔断言变异：assert(!x) <-> assert(x)；assert(a && b) -> assert(a)（去一个条件）。
    """
    # 布尔取反变异（兼容 'assert (' 带空格风格）
    if 'assert' in line:
        m = re.search(r'assert\s*\(\s*!', line)
        if m:
            mutated = re.sub(r'assert\s*\(\s*!', 'assert(', line, count=1)
            return mutated, 'bool_neg', 'bool_pos'
        m = re.search(r'assert\s*\(', line)
        if m and '==' not in line and '<' not in line and '>' not in line and '!=' not in line:
            mutated = re.sub(r'assert\s*\(', 'assert(!', line, count=1)
            return mutated, 'bool_pos', 'bool_neg'
    for op in OPS:
        if op in line:
            repl = op_map[op]
            new_op = repl[len(line) % len(repl)]
            mutated = line.replace(op, new_op, 1)
            return mutated, op, new_op
    return None


def sample_mutations(sample_dir, strong=False, higher=None):
    """Generate mutations: per assert line one operator perturbation (strong/weak),
    plus optional higher-order types: delete (comment out assert), const (replace
    parameter constant refs like DATA_W/ADDR_W/DEPTH/DIV/HALF)."""
    golden = os.path.join(sample_dir, 'golden.v')
    if not os.path.isfile(golden):
        return []
    src = open(golden, encoding='utf-8').read()
    op_map = STRONG_OP_REPLACEMENT if strong else OP_REPLACEMENT
    higher = higher or []
    variants = []
    for lineno, line in find_assert_lines(src):
        # higher-order mutations first (delete / const), one variant each
        if 'delete' in higher:
            lines = src.split('\n')
            lines[lineno - 1] = '// [mutation-delete] ' + line
            variants.append({
                'line': lineno, 'old': 'delete', 'new': 'comment_out',
                'original_line': line, 'mutated_line': lines[lineno - 1],
                'mutated_src': '\n'.join(lines),
            })
        if 'const' in higher:
            for pat in (r'\bDATA_W\b', r'\bADDR_W\b', r'\bDEPTH\b', r'\bDIV\b', r'\bHALF\b'):
                m = re.search(pat, line)
                if m:
                    repl_val = {'DATA_W': "1'b1", 'ADDR_W': "1'b1", 'DEPTH': "2'd2",
                                'DIV': "3'd4", 'HALF': "2'd2"}.get(m.group(0), '1')
                    mutated = re.sub(pat, repl_val, line, count=1)
                    lines = src.split('\n')
                    lines[lineno - 1] = mutated
                    variants.append({
                        'line': lineno, 'old': 'const:' + pat, 'new': repl_val,
                        'original_line': line, 'mutated_line': mutated,
                        'mutated_src': '\n'.join(lines),
                    })
                    break
        m = mutate_line(line, op_map)
        if not m:
            continue
        mutated, old_op, new_op = m
        lines = src.split('\n')
        lines[lineno - 1] = mutated
        variants.append({
            'line': lineno, 'old': old_op, 'new': new_op,
            'original_line': line, 'mutated_line': mutated,
            'mutated_src': '\n'.join(lines),
        })
    return variants

def run_sby_on_src(sample, mutated_src, variant_idx, timeout=600, depth=None, workroot='.suff'):
    """把 mutated golden 写入临时样本目录跑 sby，返回 (done, elapsed, rc)。"""
    sample_dir = os.path.join(BUGS, sample)
    work = os.path.join(OUT_DIR, workroot, '%s_m%d' % (sample, variant_idx))
    os.makedirs(work, exist_ok=True)
    # 复制样本必需文件（verify.sby 也复制，稍后内容替换 buggy.v -> golden.v）
    for fname in os.listdir(sample_dir):
        src_p = os.path.join(sample_dir, fname)
        if os.path.isfile(src_p) and fname in ('verify_golden.sby',):
            continue
        dst = os.path.join(work, fname)
        if not os.path.exists(dst):
            try:
                import shutil
                shutil.copy(src_p, dst)
            except Exception:
                pass
    with open(os.path.join(work, 'golden.v'), 'w', encoding='utf-8') as f:
        f.write(mutated_src)
    # 复用 verify.sby（其 read 的是 buggy.v？改为直接生成一个 sby 指向 golden.v）
    sby = os.path.join(work, 'verify.sby')
    if not os.path.isfile(sby):
        return 'NO_SBY', 0, -1
    sby_src = open(sby, encoding='utf-8').read()
    # verify.sby 若 read buggy.v，替换成 golden.v；若已 golden 则不改
    sby_src = sby_src.replace('buggy.v', 'golden.v')
    if depth is not None:
        sby_src = re.sub(r'depth \d+', 'depth %d' % depth, sby_src)
    with open(sby, 'w', encoding='utf-8') as f:
        f.write(sby_src)
    work_path = os.path.join(REPO_ROOT, 'experiments', 'runs', workroot)
    cmd = (WSL_PREFIX + 'cd %s/%s_m%d; '
           'sby -f verify.sby -d /tmp/%s_%s_m%d > /tmp/%s_%s_m%d.out 2>&1; echo RC=$? >> /tmp/%s_%s_m%d.out'
           % (work_path, sample, variant_idx, workroot, sample, variant_idx, workroot, sample, variant_idx, workroot, sample, variant_idx))
    t0 = time.time()
    try:
        if IN_WSL:
            p = subprocess.Popen(['bash', '-c', cmd])
        else:
            p = subprocess.Popen(['wsl', '-e', 'bash', '-c', cmd])
        rc = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        return 'TIMEOUT', time.time() - t0, -1
    elapsed = time.time() - t0
    done = ''
    try:
        if IN_WSL:
            r = subprocess.run(['bash', '-c', 'cat /tmp/%s_%s_m%d.out' % (workroot, sample, variant_idx)],
                               capture_output=True, text=True, timeout=30)
        else:
            r = subprocess.run(['wsl', '-e', 'bash', '-c', 'cat /tmp/%s_%s_m%d.out' % (workroot, sample, variant_idx)],
                               capture_output=True, text=True, timeout=30)
        content = r.stdout + r.stderr
        m = re.search(r'(DONE \([A-Z]+[^)]*\))', content)
        done = m.group(1) if m else (content[-120:] if content else '')
    except Exception as e:
        done = 'read-fail:%s' % e
    return done, elapsed, rc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--timeout', type=int, default=300, help='single sby run timeout seconds')
    ap.add_argument('--samples', default='')
    ap.add_argument('--out', default=os.path.join(OUT_DIR, 'sufficiency.json'))
    ap.add_argument('--strong', action='store_true', help='强变异：取反语义（==<->!= 等），避免弱化变异虚报 0-killed')
    ap.add_argument('--depth', type=int, default=None, help='覆盖 verify.sby 的 BMC depth')
    args = ap.parse_args(argv)
    samples = expand_samples(args.samples)
    print('samples: %d, jobs=%d' % (len(samples), args.jobs), flush=True)

    workroot = '.suff_strong' if args.strong else '.suff'
    os.makedirs(os.path.join(OUT_DIR, workroot), exist_ok=True)
    results = {}
    lock = __import__('threading').Lock()
    t_start = time.time()

    # 先为每个样本生成 mutations
    plan = []
    for s in samples:
        variants = sample_mutations(os.path.join(BUGS, s), strong=args.strong)
        plan.append((s, variants))

    tasks = [(s, i) for s, variants in plan for i in range(len(variants))]
    print('total mutations: %d' % len(tasks), flush=True)

    def _run(task):
        s, vi = task
        sidx = next(idx for idx, (ss, _vs) in enumerate(plan) if ss == s)
        var = plan[sidx][1][vi]
        done, elapsed, rc = run_sby_on_src(s, var['mutated_src'], vi, timeout=args.timeout,
                                           depth=args.depth, workroot=workroot)
        # mutation 有效性：sby FAIL = 抓到反例 = 断言有效；PASS = 可能空洞
        killed = 'FAIL' in done
        with lock:
            results.setdefault(s, []).append({
                'variant': vi, 'line': var['line'], 'old_op': var['old'], 'new_op': var['new'],
                'done': done, 'elapsed': round(elapsed, 1), 'killed': killed,
            })
            print('[%d/%d] %s m%d line%d %s->%s: %s killed=%s' % (
                len(results[s]), len(tasks), s, vi, var['line'], var['old'], var['new'], done, killed), flush=True)

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(_run, t) for t in tasks]
        for _ in as_completed(futs):
            pass

    total = time.time() - t_start
    summary = []
    for s in samples:
        rs = results.get(s, [])
        n = len(rs)
        killed = sum(1 for r in rs if r['killed'])
        rate = (killed / n * 100) if n else 0.0
        summary.append({'sample': s, 'mutations': n, 'killed': killed,
                        'killed_rate': round(rate, 1),
                        'weak': [r for r in rs if not r['killed']][:5]})
    print('\ntotal: %.1fs' % total, flush=True)
    print('%-5s %5s %6s %7s' % ('sample', 'mut', 'killed', 'rate%'))
    for x in summary:
        print('%-5s %5d %6d %6.1f%%' % (x['sample'], x['mutations'], x['killed'], x['killed_rate']), flush=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'total_time': total, 'results': summary}, f, ensure_ascii=False, indent=2)
    print('[done] -> %s' % args.out, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
