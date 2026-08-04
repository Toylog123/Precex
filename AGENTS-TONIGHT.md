# PreCex 今晚自主目标（2026-08-04 夜）

你是 PreCex 项目（D:\BaiduSyncdisk\02_Precex）的自主推进 agent。目标：**完成 Gate-2 收尾中的"修复率 0% 根因修正"，量化 prove 判据 bug 的影响，用 bmc 重验 + 必要时花新 token 重跑 LLM，产出可信的修正后主实验结果，更新记录并推送 GitHub。**

你有**自主决策权**：在下面定义的边界内，自己判断、自己执行、自己记录，不要停下来等确认。

## 0. 必读上下文（开工先读）
- `HANDOFF.md`（第 5 节 Gate-2 待办）
- `docs/进度.md`（今日已有：断言充分性翻案记录 + 纠错）
- `docs/方案.md`（唯一方案，Thesis：B 主设置 + 充分性闭环）
- `experiments/runs/sufficiency_all_strong_d16.json`（88.5% killed 权威数据）
- `experiments/runs/experiments_results_parallel.json`（306 条主实验原始结果，含 LLM raw + diff）

## 1. 核心任务

### 任务 A（最高优先）：bmc 判据批量重验
- 读主实验结果，对所有有 diff_text 的结果（约 276 条）应用保存的 diff，在 **bmc 模式**（verify.sby 语义）下用 evaluator 重验 verdict
- 输出 `experiments/runs/reverify_bmc_all.json`，记录 (sample, setting, seed) 的 bmc PASS/FAIL
- 对比 prove 判定与 bmc 判定，量化 prove 误判率
- **优先复用已保存 diff，不重跑 LLM**（省时间）；此步是基础

### 任务 B（花新 token）：对 bmc 仍 FAIL 的结果，自主重跑 LLM 修复
- 任务 A 之后，筛选 bmc 下仍 FAIL 的结果（真没修对的）
- 对这批结果重新调用 LLM 修复（A/B/C 各设置，1-3 轮/结果），用 bmc 判据验收
- **允许花新 token**：目标是把 9 个 0% 样本（s16/s17/s18/s25/s26/s27/s28/s33/s34）的真实修复率拉起来
- 成本记账：每批重跑前记录预计成本，跑完记录实际 token/费用，追加到 docs/进度.md
- 如果某样本多次重跑仍 FAIL，**停下分析原因**（证据问题？断言问题？模型能力？），不要无脑重试

### 任务 C：定位 prove 模式为什么误判（已有初步证据，扩展确认）
- golden.v 在 prove 模式下也 UNKNOWN（已证 s33），扩展验证 s17/s25/s27/s28/s34/s16/s18/s26
- 明确：k-induction 不收敛的断言类型（门控/时序）、哪些模块 prove 可用（fifo 等）、修复判据应改为 bmc 还是 bmc+prove 双判
- 产出结论：主实验判据的修正方案（可能涉及 run_experiments.py 的 verify 策略）

### 任务 D：修正文档与结论
- `docs/进度.md` 新增今日记录：prove 误判发现、bmc 重验结果、LLM 重跑结果、修复率修正前后对比
- `docs/方案.md` 如需同步（指标定义/验证判据）直接改
- 如 HANDOFF.md 第 5 节待办状态有变化，更新（保留用户可能正在编辑的内容）

### 任务 E：提交推送
- 分步 commit：脚本 → 数据/文档（experiments/runs/ 不入库，只提交脚本+docs+必要的说明）
- push 到 main，`git ls-remote origin -h refs/heads/main` 验证

## 2. 自主决策框架（重要）

你有权自主决定，以下**无需问用户**：
- 验证方式选择：bmc / prove / depth 调整、并发数、重跑范围
- 重跑 LLM 的样本、轮次（每结果 ≤3 轮）、设置组合（A/B/C 全跑或针对性）
- 数据清洗：对明显损坏/超时的结果重跑或标记，需记录原因
- 文档措辞、进度记录格式、commit 粒度与信息
- 常规 git 操作（commit/push/stage），用户已授权

**必须停下问用户**（这些会改变结论方向或外部状态）：
- 修改已定稿的共享 RTL 基线 / 重新生成整个数据集 / 删除样本
- 改变论文主叙事（Thesis）方向
- 单批 LLM 成本超过 **$30**（超出前先汇报预估与实际）
- 涉及项目外的操作

**决策记录**：每个自主决策（尤其重跑 LLM、改判据）在 docs/进度.md 里记一笔：决策内容、原因、结果、成本。

## 3. 预算与记账
- LLM token 预算：放开，但每批操作前预估、操作后记录实际（token/cost），总成本上限 **$30**（超出停止并汇报）
- 时间预算：今晚不限，但要持续推进；每完成一个大任务立即记录，不攒到最后
- 重跑策略：先重跑修复率 0% 的 9 样本（81 结果），若效果好再考虑扩展

## 4. 工作原则（强制）
- **并行**：批量重验与重跑用 8 并发；能并行不串行
- **记录**：关键发现即时写 docs/进度.md（倒序、带日期标题）
- **效果评估**：每步对照预期——修复率是否达到预期？没达到就找原因（证据质量/断言/模型），不糊弄
- **证据优先**：任何结论必须有命令输出/文件佐证；不猜
- **先验证再下结论**：所有"修复成功/失败"以 bmc 实际输出为准

## 5. 环境与教训（血泪）
- WSL：z3 在 `/home/toylog/.local/bin/z3`；必须 `export HOME=/home/toylog; export PATH=...:$HOME/.local/bin; export SMTBMC=/mnt/d/BaiduSyncdisk/02_Precex/smoke/yosys-smtbmc-z3.sh`
- **不要**在 PowerShell 手工调 wsl 跑 sby（破坏 $HOME/PATH）；用 Python subprocess 传完整字符串
- 中文路径（docs/进度.md）：用 PowerShell `[System.IO.File]::ReadAllLines/WriteAllLines` + UTF8 无 BOM；Python 直读写会 OSError
- 反引号：PowerShell 双引号 here-string 会吞反引号后的字符；用单引号 here-string 或 `[char]96` 拼接
- apply_patch 不可用，用 PowerShell .NET 文件 API 精确替换
- 中文乱码：git diff 显示 ? 正常，用 Python repr 验证
- `experiments/runs/` 不入库（.gitignore）

## 6. 停止条件（只有这些才停）
- 任务 A-E 全部完成且验证（重验数据落地、LLM 重跑完成、文档更新、推送成功）
- 或达到成本上限（$30）
- 或遇到第 2 节"必须问用户"的岔路
- 否则持续推进，包括自动续跑

## 7. 完成验收清单
- [ ] reverify_bmc_all.json 生成，无未解释 ERROR
- [ ] 9 个 0% 样本修复率已修正（bmc 重验 + LLM 重跑），有证据
- [ ] docs/进度.md 有今日完整记录（prove 误判、bmc 重验、LLM 重跑、成本）
- [ ] 所有改动 commit + push，工作区干净
- [ ] 最终总结：prove 误判率、修正前后修复率对比、LLM 重跑效果与成本、对论文的影响