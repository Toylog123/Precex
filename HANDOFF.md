# PreCex 项目交接文档（HANDOFF）

> 作者：Toylog | 版本：v1.1（2026-08-03）
> 功能概述：给接手的智能体/会话的项目状态与待办说明。**新会话第一步：完整阅读本文件 + docs/ 下文档，再动手。**
> v1.2 更新：M0.5 三例预研完成（Gate-0 通过，主叙事定案：反例语义化驱动 + 充分性闭环，见 docs/Gate-0-决策记录.md）；M1 数据集推进中（BugBench-PS 31 个 L3 样本 s04–s34，三通过 + golden 双对照全绿）；下一步为数据集补齐至 30–40 → Gate-2。

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
  - BugBench-PS 当前 31 个 L3 样本（s04–s34 连续编号，6 模块 × 7 错误类型矩阵，10 件套 + golden 双对照）；
    samples/README.md 为数据集规范；注入器 --variant 选择器与变体池见 scripts/bug_injector.py
  - 待办：按矩阵缺口（uart_tx/uart_rx/handshake/edge）补齐至 30–40 → **Gate-2 逐样本校验**

### Gate 状态表
| Gate | 内容 | 状态 |
| --- | --- | --- |
| Gate-1 | 工具链自检 + 断言子集双工具实测 | **通过（2026-08-03）** |
| Gate-0 | 3 例预研：C vs B 增益 + A 基线难度 + T1 快测（**决定论文主叙事**） | **通过（2026-08-03）：反例语义化驱动 + 充分性闭环** |
| Gate-2 | 数据集 30–40 样本逐样本校验 | 待执行（W4–7） |

## 4. 关键技术定案（不要推翻，除非有强证据）

- **LLM**：MiniMax M3 API（OpenAI 兼容端点 `https://api.minimaxi.com/v1`，模型 `MiniMax-M3`，1M 上下文、原生多模态、thinking）。Key 存根 `.env`（MINIMAX_API_KEY，已配置）。统一封装在 `harness/llm_client.py`，**token 记账强制**（账本 experiments/runs/token_ledger.jsonl，不入库）。
- **工具链**：WSL 内 iverilog 12 / verilator 5.020 / yosys 0.33 / SymbiYosys(sby)。**sby 引擎链定案：smtbmc + z3**（`pip3 install --user z3-solver`；运行需注入 env：`PATH=$HOME/.local/bin` + `SMTBMC=smoke/yosys-smtbmc-z3.sh`，见 smoke/run_sby.sh）。`.sby` 一律显式 `read -sv -formal`。
- **断言安全子集（Gate-1 实测收敛，写断言必须遵守）**：
  - ✅ 可用：`always @(posedge clk) assert(expr);` / `if (cond) assert(expr);`（门控）/ 打拍跨周期（`en_d<=en; cnt_d<=cnt; if(en_d) assert(cnt==cnt_d+1);`）/ `assume(expr);` / `initial` 初始化寄存器
  - ❌ 禁用：`assert/assume property`（一切形式）、`@(posedge clk)` 事件、`|->`、`##n`、`$past/$rose/$fell`（concurrent 语境）——iverilog 12 与 yosys 0.33 均不兼容
  - 仿真侧 `$fatal(1,"msg")` 首个参数必须为数字
- **系统结构**：核心 4 组件（EvidenceEngine → CexSemantizer → LocalRepairer → Verifier）+ 2 支撑（Controller=消融实验变量、BugBench-PS=评测资产）
- **实验设置**：A 原始日志 / B 结构化 / C 反例语义化（主）/ D FVDebug 式因果图（对照）/ T1 视觉通道（探索）
- **自动化原则**：数据注入器无人值守、评测一键化、失败重试内置（≤N 轮防死循环）、Gate 决策点才暂停确认

## 5. 下一步执行清单（M1 数据集 → Gate-2）

1. 按 samples/README.md 矩阵缺口扩展样本：重点 uart_tx/uart_rx/handshake/edge 新变体（uart_rx 深时序可参数化小 DIV；counter 满值回绕可接受长 BMC）
2. 新增样本逐一过注入器三通过校验 + golden 双对照（verify_golden.sby）
3. 唯一性 + 结构审计：模块×类型矩阵、件套完整、sample_id 一致、cex.vcd/cex.log 存在
4. 主实验 n≥20：A/B/C × 样本 × 种子批量评测（scripts/run_experiments.py + run_prestudy.py 管线）
5. Verifier 充分性量化：mutation/非空洞/假阳性率 + T2 验证 agent
6. **Gate-2 数据集定案**（30–40 样本逐样本校验）→ **更新 docs/进度.md** → git commit + push

## 6. 协作规则（强制）

- **进度必更**：每个里程碑/周/Gate 完成，按周报模板（倒序）更新 docs/进度.md
- **代码规范**：中文注释；每文件头注释注明 作者 Toylog + 版本号 + 功能概述；避免不必要复制、提前返回、控制并发
- **文档唯一性**：docs/方案.md 是唯一方案文档，改方案只改它；不新建重复文档
- **git**：分步提交，push 到 main（用户已授权常规提交推送流程）；.env 与 experiments/runs/ 绝不入库
- **遇到不确定性**：先查方案.md 的对应章节与风险表，再决定是否询问用户

## 7. 交接话术（新会话开场可直接使用）

> 请先完整阅读 D:\BaiduSyncdisk\02_Precex\HANDOFF.md（项目交接文档）与 docs/ 下的 方案.md、目录结构规范.md、进度.md、文献调研与评估.md，以及 README.md 与 smoke/断言子集收敛.md，然后告诉我你已掌握的项目要点。这是 PreCex 项目：反例驱动的综合前 RTL 缺陷定位与修复智能体。当前状态：W1（Gate-1）已完成并推送；M0.5 三例预研进行中（llm_client/bug_injector/3 例样本骨架就绪，MiniMax M3 key 已配置在 .env）；下一步按 HANDOFF.md 第 5 节执行 M0.5 预研 → Gate-0（决定论文主叙事）。完成后更新 docs/进度.md 并推送 GitHub。工作区根目录是 D:\BaiduSyncdisk\02_Precex。
