#!/usr/bin/env python3
# PreCex - scripts/build_submission_package.py
# 组装投稿包：论文 PDF/tex + 图表 + REPRO + 投稿信 + 数据清单 -> 单目录
# 用法：python scripts/build_submission_package.py [--out <dir>]
# 说明：作者单位/目标期刊占位符随论文 tex；冻结前需用户确认这两项。
import argparse
import os
import shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ITEMS = [
    ('paper/precex_paper.pdf', 'manuscript/precex_paper.pdf'),
    ('paper/manuscript/precex_paper.tex', 'manuscript/precex_paper.tex'),
    ('paper/manuscript/abstract_en.tex', 'manuscript/abstract_en.tex'),
    ('paper/figures/fig_pipeline.pdf', 'figures/fig_pipeline.pdf'),
    ('paper/figures/fig_setting_loc_cost.pdf', 'figures/fig_setting_loc_cost.pdf'),
    ('paper/figures/fig_error_setting_heatmap.pdf', 'figures/fig_error_setting_heatmap.pdf'),
    ('REPRO.md', 'REPRO.md'),
    ('docs/cover_letter.md', 'cover_letter.md'),
    ('docs/投稿包清单.md', 'submission_checklist.md'),
    ('docs/评审风险预案.md', 'review_risk_response.md'),
    ('scripts/audit_paper_numbers.py', 'verification/audit_paper_numbers.py'),
    ('scripts/audit_paper_refs.py', 'verification/audit_paper_refs.py'),
    ('docs/bmc_depth_spotcheck_slim.json', 'verification/bmc_depth_spotcheck_slim.json'),
    ('experiments/runs/experiments_results_corrected.json', 'verification/data/experiments_results_corrected.json'),
    ('experiments/runs/experiments_results_D_clean.json', 'verification/data/experiments_results_D_clean.json'),
    ('experiments/runs/cross_model_3seeds.json', 'verification/data/cross_model_3seeds.json'),
    ('experiments/runs/l2_false_positive_analysis.json', 'verification/data/l2_false_positive_analysis.json'),
    ('experiments/runs/llm_scores/summary.json', 'verification/data/llm_scores/summary.json'),
    ('experiments/runs/sufficiency_all_strong_d16.json', 'verification/data/sufficiency_all_strong_d16.json'),
    ('experiments/runs/sufficiency_const_all.json', 'verification/data/sufficiency_const_all.json'),
    ('experiments/runs/t2_audit_abc.json', 'verification/data/t2_audit_abc.json'),
    ('experiments/runs/t2_audit_D.json', 'verification/data/t2_audit_D.json'),
    ('experiments/runs/token_ledger.jsonl', 'verification/data/token_ledger.jsonl'),
    ('experiments/runs/verify_timing.json', 'verification/data/verify_timing.json'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(REPO, 'submission_package'))
    ap.add_argument('--zip', action='store_true', help='同时生成 ZIP 压缩包（规范命名 Precex_Submission_YYYYMMDD.zip）')
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    copied = []
    for src_rel, dst_rel in ITEMS:
        src = os.path.join(REPO, src_rel)
        dst = os.path.join(out, dst_rel)
        if not os.path.isfile(src):
            print('MISSING:', src_rel)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst_rel)
    print('submission package: %s' % out)
    print('files: %d' % len(copied))

    for c in copied:
        print('  -', c)
    # 校验清单
    missing = [r for r, _ in ITEMS if not os.path.isfile(os.path.join(REPO, r))]
    if missing:
        print('MISSING FILES:', missing)
    else:
        print('ALL %d ITEMS PRESENT' % len(ITEMS))
        readme = os.path.join(out, 'README.md')
        with open(readme, 'w', encoding='utf-8') as f:
            f.write('# PreCex 投稿包\n\n')
            f.write('> 由 scripts/build_submission_package.py 自动组装（2026-08-05）。\n\n')
            f.write('## 内容索引\n\n| 文件 | 用途 |\n|---|---|\n')
            f.write('| manuscript/precex_paper.pdf | 论文全文（9 页，矢量图） |\n')
            f.write('| manuscript/precex_paper.tex | 论文 LaTeX 主稿（中文） |\n')
            f.write('| figures/*.pdf | 三张矢量图 |\n')
            f.write('| REPRO.md | 可复现性说明 |\n')
            f.write('| cover_letter.md | 投稿信草稿 |\n')
            f.write('| submission_checklist.md | 投稿包清单 |\n')
            f.write('| review_risk_response.md | 评审风险预案 |\n')
            f.write('| verification/ | 数字终审 + 引用审计 + BMC 深度抽查 + 数据 |\n')
            f.write('| verification/SHA256SUMS | 全部文件 SHA-256 校验和 |\n')
            f.write('\n')
            f.write('## 冻结前置条件（需用户确认）\n\n1. 作者单位\n2. 目标期刊\n3. 人工可解释性评分（可选）\n\n确认后运行重新生成即完成冻结。\n')
        print('README.md written')

    # R9: SHA256SUMS for package integrity
    sums_path = os.path.join(out, "verification", "SHA256SUMS")
    os.makedirs(os.path.dirname(sums_path), exist_ok=True)
    with open(sums_path, "w", encoding="utf-8") as f:
        for root_dir, _, files in os.walk(out):
            for fn in sorted(files):
                if fn == "SHA256SUMS":
                    continue
                fp = os.path.join(root_dir, fn)
                rel = os.path.relpath(fp, out).replace(os.sep, '/')
                import hashlib
                h = hashlib.sha256(open(fp, 'rb').read()).hexdigest()
                f.write('%s  %s\n' % (h, rel))
    print('SHA256SUMS written:', sums_path)

    if args.zip:
        import datetime, zipfile
        stamp = datetime.date.today().strftime('%Y%m%d')
        zip_path = os.path.join(REPO, 'Precex_Submission_' + stamp + '.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root_dir, _, files in os.walk(out):
                for fn in sorted(files):
                    fp = os.path.join(root_dir, fn)
                    rel = os.path.relpath(fp, out).replace(os.sep, '/')
                    zf.write(fp, os.path.join('submission_package', rel))
        print('ZIP written:', zip_path)
        zsum = hashlib.sha256(open(zip_path, 'rb').read()).hexdigest()
        print('ZIP sha256:', zsum)


if __name__ == '__main__':
    main()
