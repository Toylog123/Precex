# MM 只当裁判改造（用户决策 2026-08-06）

> 用户决策：可解释性评分用 MiniMax，其余（C 摘要生成、主实验定位/修复）全部用 DeepSeek。
> 目的：消除"评分者=生成者/修复者"的角色重叠，MM 成为完全独立的裁判。

## 已完成的改造

1. **C 摘要全部 DS 重生成（63/63）**
   - bugs 34 样本：MM 版摘要备份到 semantics_mm.json，semantics.json 换 DS 版（mode=real）
   - deep 5 样本：补齐原本为空的 text_summary（DS）
   - L2 24 样本：补齐缺失的 semantics.json 结构 + DS 摘要
   - 脚本：scripts/regen_text_summary.py（含断点续跑 skip 逻辑）+ scripts/regen_summary_parallel.py
   - 账本：regen:* 条目已入账（约 63 次 DS 调用）
2. **旧可解释性评分备份**：experiments/runs/llm_scores_bak_2models/（DS+MM 双模型 ICC 版留档）

## 进行中

3. **C 设置主实验重跑（DS 摘要版）**：exp_c_ds_*.json（34×3=102 次，8 分片 WSL nohup）
4. **C 设置 deep 重跑**：exp_cdeep_ds_*.json（5×3=15 次，5 分片）
5. **C 设置 L2 重跑**：exp_cl2_ds_*.json（24×3=72 次，8 分片，待主实验完成后再启动）

## 进度快照（2026-08-06 09:50）

- deep 15 次已全部完成，其中 **8 次 API read timeout 异常**（非能力问题），已用 exp_cdeep_retry.json 重跑（retries=3）
- 主实验 exp_c_ds_* 进行中（约 43/102，7 进程）
- 已确认：deep 成功修复 7/15、定位 2/7——但异常项重跑后数字会变，暂不下结论

## DeepSeek 失败率分析（用户提问：2026-08-06 10:30）

**结论：本次主实验 C 重跑真实失败率约 1%（102 次仅 1 个真实 FAIL），此前"23% 失败率"是统计污染。**

### 证据链

1. 合并 exp_c_ds_*.json 后表面看 29/102 失败——但 28 个失败条目的账本时间戳全部是 08-05 12:36~16:31（旧 partial 残留），仅 1 个（s14/C/seed1）是本次真实 FAIL。
2. 根因：本次手动生成的分片脚本未清理旧 .partial.jsonl（run_experiments_parallel.py 会清理，手写脚本不会），断点续跑 done_keys 把 8 月 5 日的失败记录当"已完成"读入，既污染统计又阻止了真实重跑。
3. 失败类型全部为 read operation timed out（25/25），无 429/401/JSON 错误；失败样本 token 均不大（摘要 323-534 字符），成功样本中 s27/s28/s34 input_tokens 高达 1.5-1.9 万——不是上下文限制。
4. 真实失败率低的旁证：本次 01:30+ 时段账本有 105 个成功 tag，失败仅 s14/C/seed1。

### 例外：s42（deep 深时序样本）

- s42 反例最长（75 拍），C 证据 token 大，DeepSeek 对其请求反复 read timeout（3 seeds 首轮+重试均失败）。
- 这是深时序大请求在高峰时段的 API 不稳定，不是能力问题；需在低峰时段单独重跑或降并发。

### 教训

- 分片重跑前必须清理旧 partial（复用 run_experiments_parallel.py 的清理逻辑）。
- 判断 API 失败要用账本时间戳而非结果文件里的 repair_pass。

## 待办

6. **MM 单裁判可解释性评分**：llm_interpretability.py --providers minimax --out experiments/runs/llm_scores_mm
   - 评 DS 版 C 证据 + D 证据（10 样本 × 2 设置 = 20 次 MM 调用，约 $0.1）
   - 单 provider 无 ICC，输出绝对评分（各维度均值/分布）+ loc_top1 行为代理
7. **论文改写**：
   - §V-I 可解释性小节：从"双模型 ICC"改为"MM 独立裁判绝对评分"
   - 摘要/结论同步（若有提及）
   - 明确披露：C 摘要由 DS 生成、修复由 DS 执行、可解释性由 MM 独立评分——三者无重叠
8. **审计脚本更新**：audit_paper_numbers.py 的 ICC 检查改为 MM 绝对评分检查
9. **数据合并**：新 C 结果并入 leakfix_merged_clean.json（或新文件），更新 clean_stats.json
10. **文档同步**：进度.md、REPRO.md、投稿包

## 关键口径

- 主实验（A/B/C/D 定位与修复）：DS 全链路
- C 证据生成（text_summary）：DS（已改）
- 可解释性评分：MM 唯一裁判（无角色重叠：MM 不生成 C、不修复、不定位）
- 核心指标（定位/修复/BMC）：确定性判据，无 LLM 裁判
