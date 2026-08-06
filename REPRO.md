# PreCex 可复现性说明（REPRO）

> 作者：Toylog｜版本：v0.1（2026-08-04）｜性质：主实验与论文数字的可复现命令链、数据位置与账本口径。
> 目标：照本文从空环境出发，可复现 306 次主实验（A/B/C×34×3）与论文全部关键数字。

## 1. 环境与工具链（Gate-1 实测）

- WSL（Ubuntu），仓库挂载于 `/mnt/d/BaiduSyncdisk/02_Precex`（Windows 侧 `D:\BaiduSyncdisk\02_Precex`）
- iverilog 12.0 / verilator 5.020 / yosys 0.33 / SymbiYosys(sby) / python3 3.12.3
- sby 引擎链：smtbmc + z3（`pip3 install --user z3-solver`）；运行需注入
  `PATH=$HOME/.local/bin` 与 `SMTBMC=$PWD/smoke/yosys-smtbmc-z3.sh`
- 断言安全子集（Gate-1 收敛）：immediate assert / if 门控 / 打拍跨周期 / assume / initial；禁用 concurrent property（详见 smoke/断言子集收敛.md）

## 2. API Key（.env，gitignore 保护，不入库）

| Provider | 变量 | 模型 | 端点 |
| --- | --- | --- | --- |
| MiniMax | MINIMAX_API_KEY | MiniMax-M3 | https://api.minimaxi.com/v1 |
| DeepSeek | DEEPSEEK_API_KEY | deepseek-v4-flash | https://api.deepseek.com/v1 |

其他可选：OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY（多 LLM 可解释性评分用，缺 key 自动跳过）。

## 3. 完整命令链

```bash
cd /mnt/d/BaiduSyncdisk/02_Precex
export PATH=$HOME/.local/bin:$PATH
export SMTBMC=$PWD/smoke/yosys-smtbmc-z3.sh

# 1) 冒烟自检（Gate-1）
cd smoke && bash diag_assert.sh && bash run_sby.sh && cd ..

# 2) 生成证据链（B=evidence.json，C=semantics.json）
python3 scripts/build_evidence.py --samples s04-s37 --real --window 8

# 3) 主实验（A/B/C × 34 × 3 seeds = 306 次真实调用；token 记账强制）
python3 scripts/run_experiments_parallel.py --samples s04-s37 --settings A,B,C --seeds 0,1,2 --jobs 8 --detach
python3 scripts/run_experiments_parallel.py --merge --out experiments/runs/experiments_results_parallel.json

# 3a) ground-truth 隔离回归审计（2026-08-05 泄漏修复后强制；PASS 才能用实验数字）
python3 scripts/audit_ground_truth.py

# 3b) 深时序专项子集（samples/deep/s38-s42，可选；深样本生成需注入器 --samples-dir deep）
python3 scripts/run_experiments.py --samples s38-s42 --samples-dir deep --settings A,B --seeds 0,1,2 --provider deepseek

# 4) 充分性量化（mutation/非空洞 + T2 审计 + bmc 重验）
python3 scripts/verify_sufficiency.py --samples s04-s37
python3 scripts/t2_audit.py --out experiments/runs/t2_audit_abc.json
python3 scripts/reverify_bmc.py --out experiments/runs/reverify_bmc_all.json

# 5) 验证段计时聚合（从 gate2 日志恢复；未来 run 自动落盘 verify_elapsed）
python3 scripts/aggregate_verify_timing.py

# 6) 非 LLM 定位基线（assert/信号/随机行启发式，论文实验设置引用）
python3 scripts/nonllm_baselines.py

# 7) C 证据压缩对比（原始 vs slim，只读）
python3 scripts/measure_slim_compression.py

# 8) 多 LLM 可解释性评分（可选，需 provider key）
python3 scripts/llm_interpretability.py --providers deepseek,minimax --samples s04-s37 --n 10

# 8b) 干净口径统计补全（McNemar+Holm+Wilson CI+效应量+seed 稳定性；--json 落盘 clean_stats.json）
python3 scripts/stats_clean_evidence.py --json experiments/runs/clean_stats.json

# 9) 论文数字终审（40 项断言，从 experiments/runs 读取并逐一核对）
python3 scripts/audit_paper_numbers.py

# 10) 论文图表重建（数据驱动，从 experiments/runs 读取）
python3 scripts/make_paper_figs.py

# 11a) 最小补丁后验验证（可选，delta-debugging；需 WSL 工具链）
python3 scripts/minimize_patch.py --sample samples/deep/s40 --diff-file /tmp/patch.diff

# 11b) 工具链适配性预检（可选，SVA/不可综合结构 fail-fast）
python3 scripts/check_rtl_compat.py --dir samples/bugs/s04

# 12) 组装投稿包并校验完整性（SHA256SUMS 由脚本自动生成）
python3 scripts/build_submission_package.py
cd submission_package && sha256sum -c verification/SHA256SUMS && cd ..
# 同时生成 ZIP（可选）：python3 scripts/build_submission_package.py --zip
```

## 4. 数据位置（experiments/runs/ 不入库，按需保留）

| 数据 | 路径 | 说明 |
| --- | --- | --- |
| 主实验原始合并 | experiments/runs/experiments_results_parallel.json | 306 条（A/B/C×34×3，可由脚本重建） |
| D 设置结果（论文口径） | experiments/runs/experiments_results_D_clean.json | 102 条；已入库（原始分片 _d_*.json 可重建） |
| 主实验修正（BMC，论文口径） | experiments/runs/experiments_results_corrected.json | 306 条，repair_pass_bmc 全部 True；已入库 |
| 跨模型重跑（DeepSeek） | experiments/runs/experiments_results_ds.json + experiments_results_ds_full3.json | 102 条（seed0）+ 306 条（三-seed）；均已入库 |
| L2 假阳性率 | experiments/runs/experiments_results_l2.json | 72 条（A/B/C×24 L2 样本）；已入库 |
| token 账本 | experiments/runs/token_ledger.jsonl | 2578 条（截至 2026-08-06 深子集补跑完成；experiments/runs 不入库） |
| 深子集（DeepSeek A/B） | experiments/runs/deep_subset_ab.json | 30 条（5 深样本 × A/B × 3 seeds，BMC 判据；不入库，与账本约定一致） |
| 深子集（DeepSeek 四设置，最终） | experiments/runs/deep_subset_4settings.json | 60/60 全部运行完成（5 深样本 x A/B/C/D x 3 seeds），修复率 100%；s38 定位 0/3 但四设置修复均 PASS（此前 6 个 INCONCLUSIVE 已补跑证实为 API/工具噪声）；聚合分析见 scripts/analyze_deep_subset.py |
| 充分性 | experiments/runs/reverify_bmc_all.json / t2_audit_abc.json / t2_audit_D.json | 303/303、408/408；均已入库 |
| 验证计时 | experiments/runs/verify_timing.json | 重验逐样本 verify/golden 耗时；已入库 |
| C 压缩对比 | experiments/runs/slim_compression.json | 原始 vs slim 字符/比率；已入库 |
| 干净统计（论文 §V-B） | experiments/runs/clean_stats.json | 六对 McNemar/Holm/效应量 CI/seed 稳定性（stats_clean_evidence.py 生成）；已入库 |
| BMC 深度抽查 | docs/bmc_depth_spotcheck_slim.json | axi 16→24、uart_rx 24→32，6 目标 5 PASS + 1 手工 apply；已入库 |
| LLM 评分 | experiments/runs/llm_scores/ | 多模型可解释性评分（summary/all/deepseek/minimax 已入库） |

## 5. 账本口径（成本核算）

- 公式：`cost = input_tokens × 输入单价/1M + output_tokens × 输出单价/1M`（USD）
- MiniMax M3：输入 $0.60/1M、输出 $2.40/1M；>512K 上下文翻倍（代码注释标注"占位，以平台账单为准待校准"）
- DeepSeek V4-Flash：输入 $0.14/1M（cache miss）、输出 $0.28/1M
- 账本（2026-08-06 深子集补跑后）：**2578 次调用**；干净口径主实验 A/B/C 306 次 $1.57 + D 102 次 $0.37 + L2 72 次 $0.48 + 深子集 60 次 $0.25 + 可解释性 40 次 $0.11
- 历史泄漏版账本（2026-08-05 冻结口径）1519 次、$18.48 已作废；当前全部数字以干净口径重跑为准
- mock 模式记账为设计行为（mode=mock，HEAD 基线含 69 条）；验证用 mock 运行会追加 mock 行，注意清理
- 分设置：A $2.78 / B $2.72 / C $4.17 / D $1.56；tokens A 1.99M / B 1.76M / C 3.50M / D 1.07M
- 核对：token_ledger.jsonl 1519 条全部与公式一致（0 mismatch），上下文均 <512K

## 6. 论文关键数字锚点（全部与原始数据核对一致，2026-08-04 审计）

| 指标 | 值 |
| --- | --- |
| loc_top1（BMC 判据） | A 47.1% / B 61.8% / C 56.9% / D 49.0% |
| 修复率（BMC 判据） | 四设置全部 100%（A/B/C 306/306 + D 102/102 = 408/408） |
| McNemar p | B vs A 0.0035；B vs D 0.0164；B vs C 0.404 |
| 充分性（强变异） | 400 → 354（88.5%） |
| 充分性（常量变异） | 484 → 396（81.8%） |
| T2 审计 | 408/408（A/B/C 306 + D 102；接口/断言/证据 0 失败） |
| reverify | 303/303（prove 误判 78、假阳性 0；74.3%→100%） |
| 验证性能 | Gate-2 重验 202.6s（3.4min）/68 任务；axi golden ≈88s、uart_rx ≈153s（verify_timing.json 实测 87.5-88.0s / 150.6-152.6s，取上界约数） |
| 补丁规模 | 408 条 diff mean 2.1 / median 2 / max 6 行 |
| 反例长度 | 34 样本 VCD 时钟事件合计 295 拍、中位 6 拍、最长 41 拍（s24=37、s35=41）；窗口压缩收益有限，不另报压缩率 |
| C 证据压缩（slim） | 34 样本总体 -44.6%（1.81×），中位 -42.8% |

## 7. 已知边界

- 主实验历史数据未记录单任务验证段计时（旧版 evaluator 未落盘）；verify_timing.json 从 gate2 复验日志恢复，未来运行自动落盘 verify_elapsed
- 多 LLM 可解释性评分：当前仅 DeepSeek + MiniMax 2 模型；OpenAI/Gemini/Anthropic key 补齐后可扩至 4 模型重跑
- LLM 输出非确定性：temperature=0 但 token 抽样仍可能波动；多 seed 设计（3 seeds）缓解
