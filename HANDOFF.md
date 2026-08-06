# PreCex 项目交接文档（HANDOFF）

> 作者：Toylog | 版本：v1.13（2026-08-06）
> 功能概述：给接手的智能体/会话的项目状态与待办说明。**新会话第一步：完整阅读本文件 + docs/ 下文档，再动手。**
> v1.12 更新（2026-08-05）：**critical：ground-truth 泄漏修复**——审计发现 prompt 把 inject_line/inject_desc 写进元数据与 B/BT/BH 证据段、且 buggy.v 头部注释含注入描述/行号（LLM 直接看到答案）；已修复（commit 3ba58bd/5f1ac02）：全部消费点剥离证据字段 + sanitize_design_text 消毒设计头部（保持行号）+ audit_ground_truth.py 回归审计 PASS；**旧 306/408 次主实验数字作废**，无泄漏重跑（leakfix_*，306 次 DeepSeek）进行中，完成后论文按无泄漏口径重写。
> v1.2 更新：M0.5 三例预研完成（Gate-0 通过，主叙事定案：反例语义化驱动 + 充分性闭环，见 docs/Gate-0-决策记录.md；v1.5 已修正为 B 主设置）；M1 数据集推进中（BugBench-PS 31 个 L3 样本 s04–s34，三通过 + golden 双对照全绿）；下一步为数据集补齐至 30–40 → Gate-2。
> v1.4 更新（2026-08-04）：**主实验 306 次真实评测完成并修正**——diff 应用器模糊匹配修复 + 39 条失败离线重放（10 转 PASS）+ 4 条网络失败补跑（s30/A2 PASS）；A/B/C 修复率收敛 73.5%，**B（结构化证据）loc_top1 61.8% 与成本全面占优，Gate-0 叙事由 C 主设置修正为 B 主设置**；3 条网络失败离线重放确认 FAIL（306 条全 verdict 无缺失）。下一步：Gate-2 逐样本校验 + 按 B 叙事定稿。
> v1.6 更新（2026-08-05）：**主实验判据修正为 BMC（306/306 全通过，100%）**；**跨模型重跑（DeepSeek v4-flash 306 次，三-seed）显示 B 定位优势模型依赖，主叙事修正为「证据表征 × 模型交互效应」**；**L2 假阳性率实验完成（24 样本 72 次，91.7%）**；论文加固与终审完成（8 页 PDF，账本 1519 次 $18.48）；Gate-2 已通过（2026-08-04 34/34 复验）。下一步：论文投稿前终审（人工可解释性评分可选补强）。
> v1.7 更新（2026-08-05）：**论文终审完成**（P0 终审：裸 % 修复 + 303 口径说明，重编 9 页 0 overfull/undefined/error）；**投稿准备全部落地**：多来源 LLM 可解释性评分（DeepSeek v4-flash + MiniMax M3，40 次，ICC 已写入论文）、BMC 深度抽查（axi 16→24、uart_rx 24→32）、中文期刊适配调研、投稿包 25 文件 + SHA256SUMS + zip 打包（--zip）、REPRO 命令链第 11 步、摘要中英一致性审计；**审计全绿**（数字 40 项 + 引用 8 项）；HEAD 1f50a31 已推送。下一步：仅剩 3 项用户决策（作者单位/目标期刊/真人评分者）→ 投稿包冻结重建 → 2026-10 投稿。
> v1.8 更新（2026-08-05）：**用户决策落地**：作者单位=国防科技大学（论文/投稿信已填）；真人评分者=无，采用多 LLM 交叉评分作为探索性结果投稿；目标期刊未定（保留首选软件学报/备选电子学报）。HEAD 6554c71 已推送。下一步：仅剩目标期刊确认 → 模板适配 + 中文文献 → 投稿包冻结重建 → 2026-10 投稿。
> v1.13 更新（2026-08-06）：**C 数字最终化 + 统计重生 + A vs C 显著性发现**——C 从 MM-era 59.8% 切换为 DS-summary 43.2%（95/102），clean_stats 配对 McNemar + Holm 完整重算，发现 A vs C 显著（p=0.0004，Holm p=0.0024），其余五对不显著；审计 56/56 PASS；英文摘要同步更新；HEAD 61fee2c 已推送。下一步：仅剩目标期刊确认 → 投稿包冻结重建 → 2026-10 投稿。
> v1.11 更新（2026-08-05）：**残余结构性问题论文修订**：摘要/结论统一改为“BMC 回归通过率 100%”（首次出现定义有限深度 BMC 无反例操作含义，中英摘要同步）；引言前置适用边界段（短反例可局部修正 L3 子集，长周期结构性重写属绕过留待未来）；内部效度补假阴性风险未量化声明（深度抽查为代表性非系统性证据，结论为当前深度操作口径相对比较）；方法节标注“系统版本口径”（完整系统增量机制未全量重跑，主实验为功能子集）；未来工作新增根因诊断引擎（轨迹切片/SAT 极小反例核心，试错式→诊断驱动）。论文 10 页 0 undefined ref，audit_paper_refs 0 fails。HEAD 6f9013c 已推送。
> v1.10 更新（2026-08-05）：**架构评审 5 项硬伤修复**：反馈循环历史注入（run_experiments retry_history，首次 prompt 口径不变）、自适应窗口（deep 5 样本 semantics w=17-24 落地，主集 34 保持 window=8）、故障锥算法明确（静态代码级扇入）、最小补丁 delta-debugging（minimize_patch.py，s40 真实 BMC 1-minimal 验证）、工具链兼容预检（check_rtl_compat.py --check-compat）；论文新增 3 方法小节+架构边界局限段，10 页 0 undefined ref；诚实边界：主实验 408/306 为旧固定 prompt 协议，报告数字不受影响。HEAD 8f47bc7 已推送。
> v1.9 更新（2026-08-05）：**深时序专项子集 s38-s42 落地**：samples/deep/ 独立目录（bugs=34 不变量恢复），natural tb 35-75 拍反例 DeepSeek A/B×3-seed 30/30 BMC 首次修复通过（$0.095）；**修复深样本链路 P1 + 并行脚本 P2**：run_experiments.py v0.2（--samples-dir deep + 跨目录解析 + 0 任务非零退出，根治静默空跑）、bug_injector.py --samples-dir deep（复现不再写回 samples/bugs）、run_experiments_parallel.py v0.3（spawn 前清理分片旧 partial）；样本分层定案（BugBench-PS 34 受控注入 + deep 子集 natural 跨周期专项），**叙事无需降级**，B 定位优势限定表述（MiniMax 主实验）在论文全文生效。HEAD 582edcc 已推送。

## 1. 项目速览

- **项目**：PreCex（Pre-synthesis + Counterexample）——反例驱动的综合前 RTL 缺陷定位与修复智能体
- **目标**：2026-10 论文初稿 + BugBench-PS 数据集（30–40 个 L3 样本）+ 开源工具链
- **仓库**：`D:\BaiduSyncdisk\02_Precex`（GitHub: Toylog123/Precex，分支 main）
- **约束**：单人 + 智能体自动化管线｜3 个月硬时间线（2026-08 → 10）｜LLM 预算不限｜自动化优先
- **核心命题**：以形式反例为最高置信证据，构建"结构化证据 → 反例语义化 → 切片约束修复 → 形式再验证"闭环，修复综合前 RTL 的跨周期行为缺陷（L3）

## 2. 文档索引（按序阅读）

| 文件 | 内容 | 优先级 |
| --- | --- | --- |
| README.md | 项目总览、系统结构、实验设置、里程碑 | 必读 |
| docs/方案.md | **唯一方案文档**：背景/组件设计/数据集/评测/里程碑/风险/难度（v1.6） | 必读 |
| docs/文献调研与评估.md | 26 篇文献 + 2025–26 最新工作与差异化 | 参考 |
| docs/目录结构规范.md | 目录职责、7 件套定义、5 条关键规则 | 必读 |
| docs/进度.md | **进度周报**：每次推进必须倒序追加更新 | 必读+维护 |
| smoke/断言子集收敛.md | **Gate-1 实测收敛的断言安全子集**（iverilog 12 vs yosys 0.33 兼容矩阵） | 必读（写断言前） |

## 3. 当前状态

- **已完成（W0）**：方案 v1.6、文献调研、系统结构定案（4+2）、仓库初始化
- **已完成（W1｜M0 → Gate-1 通过，2026-08-03）**：
  - 工具链版本验证（WSL）：iverilog 12.0 / verilator 5.020 / yosys 0.33 / sby / python3 3.12.3
  - **断言安全子集收敛**：immediate assert / if 门控 / 打拍跨周期 / immediate assume / initial 初始化（详见 smoke/断言子集收敛.md）
  - smoke 冒烟三步：弱 tb 过 + formal 败（sby smtbmc+z3 抓反例）+ golden 对照 k-induction 可证
  - harness/evaluator.py（compile→sim→formal 三通过判定，自检 verdict=FAIL 正确）
  - rtl/ 6 模块黄金基线（fifo_sync/uart_tx/uart_rx/axi_lite_slave/fsm_ctrl/counter_alu，均编译+仿真+yosys 通过）
- **已完成（M0.5 预研启动，2026-08-03）**：
  - harness/llm_client.py（MiniMax M3 封装 + token 记账强制 + mock 模式；API key 已写入根 `.env`，gitignore 保护）
  - scripts/bug_injector.py（7 类错误模板注入器 + L3 自动校验，`--list-types` 可查模板）
  - samples/prestudy/s01–s03 三例 L3 样本骨架（fifo_sync fifo_count / fsm_ctrl state_trans / counter_alu boundary_wrap；弱 tb 已验证 s01 过）
- **已完成（M0.5 预研主体，Gate-0 通过，2026-08-03）**：
  - EvidenceEngine / CexSemantizer（含轨迹压缩）/ A-B-C prompt 模板族 / T1 视觉快测 / run_prestudy 一键评测 全部落地；
    3 样本 × A/B/C × 真实 MiniMax M3 评测 9/9 修复三通过，主叙事定案（详见 docs/Gate-0-决策记录.md 与 docs/进度.md）
- **进行中（M1 数据集，W4–7）**：
  - BugBench-PS 当前 34 个 L3 样本（s04–s37 连续编号，6 模块 × 7 错误类型矩阵，11 件套 + golden 双对照 + prove 修复验证）；
    samples/README.md 为数据集规范；注入器 --variant 选择器与变体池见 scripts/bug_injector.py
  - **UART 参数化深时序机制（2026-08-04）**：注入器 --param 覆写 CLK_FREQ/BAUD（小 DIV），uart_rx 深时序反例
    BMC 深度 230+ → 176 可收敛，s35–s37 入库（uart_tx 3 / uart_rx 4）；黄金断言时序修复（A6 baud_tick_d、
    A1/A2 rxd_d）+ uart_rx 环境约束（START/STOP 期间 rxd 保持）
  - **主实验管线就绪（2026-08-04）**：A/B/C 证据链全量生成（evidence.json + semantics.json，
    axi 时钟自动识别）；scripts/run_experiments.py 批量评测（A/B/C × 3 种子，prove 修复验证，
    k-induction 充分性）；s04 端到端实测 buggy FAIL → 修复 PASS
  - **主实验完成并修正（2026-08-04→05）**：306 次真实评测（34×A/B/C×3 种子）→ BMC 判据重验 306/306 全通过（修复率 100%，旧 prove 判据 73.5% 为判据假象）；B loc_top1 61.8% 最优（详见 docs/进度.md）
  - **跨模型重跑完成（2026-08-05）**：DeepSeek v4-flash 306 次（A/B/C×34×3-seed，BMC 统一口径严格配对）——修复率两模型均 100%，但 **B 定位优势模型依赖（MiniMax 61.8% vs DeepSeek 54.9% 被 C 62.7% 反超）**，主叙事修正为「证据表征 × 模型交互效应」
  - **L2 假阳性率完成（2026-08-05）**：24 个 L2 样本 × A/B/C = 72 次 DeepSeek 评测，修复率 91.7%（弱 tb 门禁不构成能力分界），uart_tx 握手/状态类短板
  - **深时序专项子集（2026-08-05）**：samples/deep/s38-s42（natural tb + ≥20 拍门禁，35-75 拍），DeepSeek A/B×3-seed 30/30 BMC 首次修复通过——跨周期叙事实证；定位随语义深度下降（最深 uart_tx loc=0/6）但修复闭环兜底；B 优势不跨域（A 53.3% vs B 33.3%），强化「证据表征 × 模型」叙事
  - **论文加固与终审（2026-08-05）**：新增跨模型/L2 两小节，全文一致性修正（B 优势限定 MiniMax），账本更新 1519 次 $18.48，9 页 PDF 编译验证
  - 待办：仅剩目标期刊确认（作者单位/评分者已决，见第 5 节）；确认后即执行：期刊模板适配 + 中文文献 → 投稿包冻结重建 → 2026-10 投稿

### Gate 状态表
| Gate | 内容 | 状态 |
| --- | --- | --- |
| Gate-1 | 工具链自检 + 断言子集双工具实测 | **通过（2026-08-03）** |
| Gate-0 | 3 例预研：C vs B 增益 + A 基线难度 + T1 视觉快测（决定主叙事） | **通过（2026-08-03）但 2026-08-04 主实验修正为 B 主设置，2026-08-05 跨模型实验修正为「证据表征 × 模型交互效应」** |
| Gate-2 | 数据集 30–40 样本逐样本校验 | **通过（2026-08-04：34/34 复验 + 缺口负结果归档）** |

## 4. 关键技术定案（不要推翻，除非有强证据）

- **LLM**：MiniMax M3 API（OpenAI 兼容端点 `https://api.minimaxi.com/v1`，模型 `MiniMax-M3`，1M 上下文、原生多模态、thinking）。Key 存根 `.env`（MINIMAX_API_KEY，已配置）。统一封装在 `harness/llm_client.py`，**token 记账强制**（账本 experiments/runs/token_ledger.jsonl，不入库）。
- **工具链**：WSL 内 iverilog 12 / verilator 5.020 / yosys 0.33 / SymbiYosys(sby)。**sby 引擎链定案：smtbmc + z3**（`pip3 install --user z3-solver`；运行需注入 env：`PATH=$HOME/.local/bin` + `SMTBMC=smoke/yosys-smtbmc-z3.sh`，见 smoke/run_sby.sh）。`.sby` 一律显式 `read -sv -formal`。
- **断言安全子集（Gate-1 实测收敛，写断言必须遵守）**：
  - ✅ 可用：`always @(posedge clk) assert(expr);` / `if (cond) assert(expr);`（门控）/ 打拍跨周期（`en_d<=en; cnt_d<=cnt; if(en_d) assert(cnt==cnt_d+1);`）/ `assume(expr);` / `initial` 初始化寄存器
  - ❌ 禁用：`assert/assume property`（一切形式）、`@(posedge clk)` 事件、`|->`、`##n`、`$past/$rose/$fell`（concurrent 语境）——iverilog 12 与 yosys 0.33 均不兼容
  - 仿真侧 `$fatal(1,"msg")` 首个参数必须为数字
- **系统结构**：核心 4 组件（EvidenceEngine → CexSemantizer → LocalRepairer → Verifier）+ 2 支撑（Controller=消融实验变量、BugBench-PS=评测资产）
- **实验设置**：A 原始日志 / B 结构化证据（MiniMax 上定位最优，主设置）/ C 反例语义化 / D FVDebug 式因果图（成本最低）/ 跨模型重跑（DeepSeek v4-flash）/ L2 门禁对照（假阳性率）
- **自动化原则**：数据注入器无人值守、评测一键化、失败重试内置（≤N 轮防死循环）、Gate 决策点才暂停确认

## 5. 当前状态与下一步（论文初稿 → 2026-10 投稿）

已完成：M0.5 预研（Gate-0/1）→ M1 数据集 34 样本定案（Gate-2 通过）→ 主实验 408 次（BMC 100%）→ 跨模型重跑 306 次（DeepSeek 三-seed）→ L2 假阳性率 72 次（91.7%）→ 深时序专项子集 30 次（s38-s42，30/30 BMC 首次修复通过）→ 论文加固 + 终审（9 页 PDF，账本 1519 次 $18.48）；多来源 LLM 可解释性评分（DeepSeek v4-flash + MiniMax M3，40 次，ICC 已写入论文）、BMC 深度敏感性抽查（axi 16→24、uart_rx 24→32）、中文期刊适配调研、投稿包 SHA256SUMS 校验和均已完成；全部已推送（main 最新 582edcc）

已决（2026-08-05）：作者单位=国防科技大学（论文/投稿信已填）；真人评分者=无，采用多 LLM 交叉评分（DeepSeek v4-flash + MiniMax M3，40 次，ICC 已写入论文）作为探索性结果投稿

待办（仅剩用户决策项）：
1. **目标期刊**：首选《软件学报》（CCF T1，需 Word 排版 + 补 3-5 条中文文献），备选《电子学报》（更贴 RTL/EDA）；见 docs/期刊适配调研.md。用户确认后执行：期刊模板适配 + 中文文献（prepare_zh_refs.py 就绪）→ 投稿包冻结重建 → 2026-10 投稿

## 6. 协作规则（强制）

- **进度必更**：每个里程碑/周/Gate 完成，按周报模板（倒序）更新 docs/进度.md
- **代码规范**：中文注释；每文件头注释注明 作者 Toylog + 版本号 + 功能概述；避免不必要复制、提前返回、控制并发
- **文档唯一性**：docs/方案.md 是唯一方案文档，改方案只改它；不新建重复文档
- **git**：分步提交，push 到 main（用户已授权常规提交推送流程）；.env 与 experiments/runs/ 绝不入库
- **遇到不确定性**：先查方案.md 的对应章节与风险表，再决定是否询问用户

## 7. 交接话术（新会话开场可直接使用）

> 请先完整阅读 D:\BaiduSyncdisk\02_Precex\HANDOFF.md（项目交接文档）与 docs/ 下的 方案.md、目录结构规范.md、进度.md、文献调研与评估.md，以及 README.md 与 smoke/断言子集收敛.md，然后告诉我你已掌握的项目要点。这是 PreCex 项目：反例驱动的综合前 RTL 缺陷定位与修复智能体。当前状态：M0.5 预研（Gate-0/1）、M1 数据集 34 样本定案（Gate-2 通过）、主实验 408 次（BMC 判据修复率 100%，B 在 MiniMax 上定位最优 61.8%）、跨模型重跑 306 次（DeepSeek 三-seed，B 优势模型依赖，主叙事：证据表征 × 模型交互效应）、L2 假阳性率 72 次（91.7%）均已完成并推送；论文 9 页 PDF 加固终审完成（账本 1519 次 $18.48）。所有可自决项已完成：多模型评分、BMC 深度抽查、期刊调研、投稿包 SHA256SUMS、REPRO 命令链、摘要一致性审计均已落地并推送；作者单位（国防科技大学）与真人评分者（无，LLM 交叉评分替代）已决；仅剩目标期刊确认 → 确认后执行链：期刊模板 + 中文文献 → 投稿包冻结 → 2026-10 投稿。工作区根目录是 D:\BaiduSyncdisk\02_Precex。
