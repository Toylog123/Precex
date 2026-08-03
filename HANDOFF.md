# PreCex 项目交接文档（HANDOFF）

> 作者：Toylog | 版本：v1.0（2026-08-03）
> 功能概述：给接手的智能体/会话的项目状态与待办说明。**新会话第一步：完整阅读本文件 + docs/ 下文档，再动手。**

## 1. 项目速览

- **项目**：PreCex（Pre-synthesis + Counterexample）——反例驱动的综合前 RTL 缺陷定位与修复智能体
- **目标**：2026-10 论文初稿 + BugBench-PS 数据集（30–40 个 L3 样本）+ 开源工具链
- **仓库**：`D:\BaiduSyncdisk\02_Precex`（GitHub: Toylog123/Precex，分支 main，已推送）
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

## 3. 当前状态

- **已完成（W0）**：方案 v1.6 迭代、文献调研、可行度/价值/难度评估、AI 结合点定案（T1/T2/T4）、系统结构定案（核心 4 组件 + 2 支撑）、仓库初始化与文档体系重构
- **当前阶段**：待启动 **W1（M0 工具链验证）**，下一个 Gate 为 **Gate-1**
- **未完成**：一切代码/数据/实验（仓库仅 docs/ 与目录骨架有内容）

### Gate 状态表
| Gate | 内容 | 状态 |
| --- | --- | --- |
| Gate-1 | 工具链自检 + 断言子集双工具实测 | 待执行（W1） |
| Gate-0 | 3 例预研：C vs B 增益 + A 基线 + T1 快测（**决定论文主叙事**） | 待执行（W2–3） |
| Gate-2 | 数据集 30–40 样本逐样本校验 | 待执行（W4–7） |

## 4. 关键技术定案（不要推翻，除非有强证据）

- **LLM**：MiniMax M3 API（OpenAI 兼容端点，原生多模态、1M 上下文、thinking）；统一封装在 `harness/llm_client.py`，**token 记账强制**
- **工具链**：WSL 内 iverilog 12 / verilator / yosys 0.33 / SymbiYosys(sby)；Python 环境在 **WSL**（用户已确认）；版本锁定 manifest
- **系统结构**：核心 4 组件（EvidenceEngine → CexSemantizer → LocalRepairer → Verifier）+ 2 支撑（Controller=消融实验变量、BugBench-PS=评测资产）
- **实验设置**：A 原始日志 / B 结构化 / C 反例语义化（主）/ D FVDebug 式因果图（对照）/ T1 视觉通道（探索）
- **断言子集**：iverilog 与 yosys -formal 双工具兼容的简单子集（Gate-1 实测收敛），仿真侧 `$fatal` 双实现
- **自动化原则**：数据注入器无人值守、评测一键化、失败重试内置（≤N 轮防死循环）、Gate 决策点才暂停确认

## 5. 下一步执行清单（W1｜M0 → Gate-1）

1. WSL 内验证工具链版本（`iverilog -V` / `verilator --version` / `yosys -V` / `sby --version`）
2. `smoke/` 冒烟：counter.sv + tb_counter.sv + counter.sby 跑通 **"弱 tb 过 + formal 败"** 的 L3 原型
3. **断言子集双工具实测**：候选清单逐条验证 iverilog 12 vs yosys -formal 兼容性，收敛为安全子集
4. `harness/` 骨架：evaluator.py（compile→sim→formal 三通过判定）
5. `rtl/` 6 模块黄金基线（fifo_sync/uart_tx/uart_rx/axi_lite_slave/fsm_ctrl/counter_alu）
6. Gate-1 通过 → **更新 docs/进度.md** → git commit + push

## 6. 协作规则（强制）

- **进度必更**：每个里程碑/周/Gate 完成，按周报模板（倒序）更新 docs/进度.md
- **代码规范**：中文注释；每文件头注释注明 作者 Toylog + 版本号 + 功能概述；避免不必要复制、提前返回、控制并发
- **文档唯一性**：docs/方案.md 是唯一方案文档，改方案只改它；不新建重复文档
- **git**：分步提交，push 到 main（用户已授权常规提交推送流程）
- **遇到不确定性**：先查方案.md 的对应章节与风险表，再决定是否询问用户

## 7. 交接话术（新会话开场可直接使用）

> 请先完整阅读 D:\BaiduSyncdisk\02_Precex\HANDOFF.md（项目交接文档）与 docs/ 下的 方案.md、目录结构规范.md、进度.md、文献调研与评估.md，以及 README.md，然后告诉我你已掌握的项目要点。这是 PreCex 项目：反例驱动的综合前 RTL 缺陷定位与修复智能体，当前 W0 完成、待启动 W1（M0 工具链验证 → Gate-1）。确认理解后按 HANDOFF.md 第 5 节执行，完成后更新 docs/进度.md 并推送 GitHub。工作区根目录是 D:\BaiduSyncdisk\02_Precex。
