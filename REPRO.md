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

# 9) 论文数字终审（40 项断言，从 experiments/runs 读取并逐一核对）
python3 scripts/audit_paper_numbers.py

# 10) 论文图表重建（数据驱动，从 experiments/runs 读取）
python3 scripts/make_paper_figs.py

# 11) 组装投稿包并校验完整性（SHA256SUMS 由脚本自动生成）
python3 scripts/build_submission_package.py
cd submission_package && sha256sum -c verification/SHA256SUMS && cd ..
```

## 4. 数据位置（experiments/runs/ 不入库，按需保留）

| 数据 | 路径 | 说明 |
| --- | --- | --- |
| 主实验原始合并 | experiments/runs/experiments_results_parallel.json | 306 条（A/B/C×34×3，可由脚本重建） |
| D 设置结果（论文口径） | experiments/runs/experiments_results_D_clean.json | 102 条；已入库（原始分片 _d_*.json 可重建） |
| 主实验修正（BMC，论文口径） | experiments/runs/experiments_results_corrected.json | 306 条，repair_pass_bmc 全部 True；已入库 |
| 跨模型重跑（DeepSeek） | experiments/runs/experiments_results_ds.json + experiments_results_ds_full3.json | 102 条（seed0）+ 306 条（三-seed）；均已入库 |
| L2 假阳性率 | experiments/runs/experiments_results_l2.json | 72 条（A/B/C×24 L2 样本）；已入库 |
| token 账本 | experiments/runs/token_ledger.jsonl | 1519 条，全部调用强制记账；已入库 |
| 充分性 | experiments/runs/reverify_bmc_all.json / t2_audit_abc.json / t2_audit_D.json | 303/303、408/408；均已入库 |
| 验证计时 | experiments/runs/verify_timing.json | 重验逐样本 verify/golden 耗时；已入库 |
| C 压缩对比 | experiments/runs/slim_compression.json | 原始 vs slim 字符/比率；已入库 |
| BMC 深度抽查 | docs/bmc_depth_spotcheck_slim.json | axi 16→24、uart_rx 24→32，6 目标 5 PASS + 1 手工 apply；已入库 |
| LLM 评分 | experiments/runs/llm_scores/ | 多模型可解释性评分（summary/all/deepseek/minimax 已入库） |

## 5. 账本口径（成本核算）

- 公式：`cost = input_tokens × 输入单价/1M + output_tokens × 输出单价/1M`（USD）
- MiniMax M3：输入 $0.60/1M、输出 $2.40/1M；>512K 上下文翻倍（代码注释标注"占位，以平台账单为准待校准"）
- DeepSeek V4-Flash：输入 $0.14/1M（cache miss）、输出 $0.28/1M
- 完整账本（2026-08-05）：**1519 次调用，$18.48**；主实验 408 runs（A/B/C/D）**$11.22、avg $0.0275**；DeepSeek 跨模型 306 次 $1.02 + L2 72 次 $0.29 + 可解释性 40 次 $0.11
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
