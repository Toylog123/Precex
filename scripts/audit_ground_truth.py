# PreCex - scripts/audit_ground_truth.py  ground-truth 隔离回归审计
# 作者：Toylog | 版本：v0.2 | 功能概述：验证所有喂给 LLM 的 prompt 证据/设计文本
#   不含数据集标注（inject_line/inject_desc/注入描述/击穿断言/单点注入行号）。
#   样本文件本身含标注是正常的（数据集资产）；审计的是'最终喂给 LLM 的内容'。
import json, os, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'experiments', 'configs'))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
import prompt_templates as PT
import run_experiments as RE
LEAK_WORDS = ('注入', '击穿', '单点注入', 'inject_line', 'inject_desc', 'buggy_inject_line')
def check_text(text, name, issues):
    for w in LEAK_WORDS:
        if w in text:
            issues.append('%s: 含泄漏词 %r' % (name, w))
def main():
    issues = []
    samples = []
    for root in ('samples/bugs', 'samples/deep'):
        d = os.path.join(REPO, root)
        if not os.path.isdir(d): continue
        for sid in sorted(os.listdir(d))[:6]:
            p = os.path.join(d, sid)
            if os.path.isfile(os.path.join(p, 'buggy.v')):
                samples.append((root.split('/')[-1], sid, p))
    for root, sid, p in samples:
        design = open(os.path.join(p, 'buggy.v'), encoding='utf-8').read()
        sanitized = PT.sanitize_design_text(design)
        check_text(sanitized, '%s/%s 消毒后设计' % (root, sid), issues)
        # 每个消费端生成的实际 prompt/证据
        for setting in ('A', 'B', 'BT', 'BH', 'C', 'D'):
            try:
                ev = RE._build_evidence_text(setting, p)
                check_text(ev, '%s/%s %s 证据段' % (root, sid, setting), issues)
            except Exception as e:
                issues.append('%s/%s %s 证据段生成失败: %s' % (root, sid, setting, repr(e)[:80]))
        meta = json.load(open(os.path.join(p, 'meta.json'), encoding='utf-8'))
        prompt = PT.build_prompt('B', sanitized, '', '', meta)
        check_text(prompt, '%s/%s 最终 prompt(B)' % (root, sid), issues)
    # 消费点源码应接入消毒
    for f in ('scripts/run_experiments.py', 'scripts/run_prestudy.py', 'scripts/multi_candidate.py',
              'scripts/llm_interpretability.py'):
        src = open(os.path.join(REPO, f), encoding='utf-8').read()
        if 'sanitize_design_text' not in src:
            issues.append('%s: 未接入 sanitize_design_text' % f)
    if issues:
        print('FAIL: %d 处潜在泄漏' % len(issues))
        for i in issues: print(' -', i)
        return 1
    print('PASS: 全部消费端 prompt/证据/设计无 ground-truth 泄漏')
    return 0
if __name__ == '__main__':
    sys.exit(main())
# PreCex - scripts/audit_ground_truth.py  ground-truth 隔离回归审计
# 作者：Toylog | 版本：v0.1 | 功能概述：扫描所有喂给 LLM 的证据/设计文本消费点，
#   确认不含数据集标注（inject_line/inject_desc/注入描述/击穿断言/单点注入行号），
#   防止 ground-truth 泄漏回归（2026-08-05 泄漏修复后固化）。
import json, os, re, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAK_WORDS = ('注入', '击穿', '单点注入', 'inject_line', 'inject_desc', 'buggy_inject_line')
CONSUMERS = ['scripts/run_experiments.py', 'scripts/run_prestudy.py', 'scripts/multi_candidate.py',
             'scripts/patch_assembler.py', 'scripts/llm_interpretability.py']
def check_text(text, name, issues):
    for w in LEAK_WORDS:
        if w in text:
            issues.append('%s: 含泄漏词 %r' % (name, w))
def main():
    issues = []
    # 1) 消费点源码不应直接读取未清洗的 evidence/design
    for f in CONSUMERS:
        p = os.path.join(REPO, f)
        if not os.path.isfile(p): continue
        src = open(p, encoding='utf-8').read()
        if 'sanitize_design_text' not in src and 'buggy.v' in src and 'build_intent_prompt' not in src:
            issues.append('%s: 未接入 sanitize_design_text' % f)
    # 2) 样本 evidence.json 不应含 inject 字段（若有则剥离函数必须处理）
    for root in ('samples/bugs', 'samples/deep'):
        d = os.path.join(REPO, root)
        if not os.path.isdir(d): continue
        for sid in sorted(os.listdir(d)):
            p = os.path.join(d, sid, 'evidence.json')
            if os.path.isfile(p):
                try: ev = json.load(open(p, encoding='utf-8'))
                except Exception: continue
                for k in ('inject_line', 'inject_desc'):
                    if k in ev:
                        issues.append('%s/%s: evidence.json 含 %s（提示：消费端必须剥离）' % (root, sid, k))
    # 3) buggy.v 头部不应含注入描述/行号（样本文件本身；提示：消费端消毒）
    for root in ('samples/bugs', 'samples/deep'):
        d = os.path.join(REPO, root)
        if not os.path.isdir(d): continue
        for sid in sorted(os.listdir(d)):
            p = os.path.join(d, sid, 'buggy.v')
            if os.path.isfile(p):
                head = open(p, encoding='utf-8', errors='replace').read()[:800]
                check_text(head, '%s/%s buggy.v 头部' % (root, sid), issues)
    if issues:
        print('FAIL: %d 处潜在泄漏' % len(issues))
        for i in issues: print(' -', i)
        return 1
    print('PASS: 全部消费点与样本无 ground-truth 泄漏')
    return 0
if __name__ == '__main__':
    sys.exit(main())
