# PreCex

> Counterexample-driven Pre-synthesis RTL Bug Localization and Repair Agent
> 作者：Toylog｜版本：v0.2（2026-08-03）

**反例驱动的综合前 RTL 缺陷定位与修复智能体**：以形式验证反例为最高置信证据源，构建"结构化证据 → 反例语义化 → 切片约束修复 → 形式再验证"闭环，系统定位并修复综合前 RTL 中的**跨周期行为缺陷**。

## 项目简介

综合前验证的真正难点是**"测试通过但形式验证失败"**的跨周期行为缺陷（状态跳转错误、握手协议违例、FIFO 满空竞争、边界回绕等）——这类缺陷仿真难以命中、形式反例却必然暴露。本项目针对这一缺口：

- **核心命题**：形式反例是综合前缺陷定位与修复的最高置信证据，关键在把原始反例"语义化"为可修复的周期级事件序列；
- **主创新**：反例语义化（CexSemantizer，含 T1 多模态波形图通道）；
- **差异化三支柱**：① 开源全链路可复现（iverilog/verilator/yosys/sby，无商业依赖）；② 三设置消融方法论（A 原始日志 / B 结构化 / C 反例语义化）；③ 跨周期专项数据集 + 验证充分性量化（mutation/非空洞/假阳性率）；
- **目标**：2026-10 论文初稿 + BugBench-PS 数据集（30–40 个 L3 样本）+ 开源工具链。

## 系统结构（核心 4 组件 + 2 支撑要素）

```
输入层(3类失败证据) → ①EvidenceEngine(结构化) → ②CexSemantizer(语义化★) → ③LocalRepairer(切片patch) → ④Verifier(三通过+充分性)
                          └──────────── 失败回灌（≤N 轮）────────────┘
贯穿层：MiniMax M3 API ｜ Controller（实验变量，T4 MCP 工具层）
支撑层：工具链 ｜ BugBench-PS 资产 ｜ 自动化管线
```

| 核心组件 | 职责 |
| --- | --- |
| EvidenceEngine | 编译/lint/仿真/反例日志 → 统一 JSON schema（含 X 态归一化） |
| CexSemantizer | VCD → 周期事件序列/状态轨迹/故障锥 + NL 摘要（+T1 视觉通道） |
| LocalRepairer | 切片约束（状态相关域）→ 最小 patch + 修改意图 |
| Verifier | 编译→弱 tb 回归→sby k-induction/bmc 三通过 + mutation/非空洞/假阳性 + T2 独立验证 agent |

| 支撑要素 | 说明 |
| --- | --- |
| Controller | 工具/预算调度，**消融实验变量**（无增益为合法负结果） |
| BugBench-PS | 30–40 个 L3 样本数据集（6 模块 × 7 错误类型，7 件套） |

## 实验设置

| 设置 | 证据表示 | 说明 |
| --- | --- | --- |
| A | 原始日志/反例原文 | 基线 |
| B | 结构化 JSON | 消融 |
| C | 反例语义化（周期事件+轨迹+故障锥+NL） | **主设置** |
| D | FVDebug 式因果图摘要 | 对照（文献最强基线） |
| T1 | C + 多模态波形图通道 | 探索章节 |

## 快速开始

前置：WSL（工具链）+ Python 3.10+ + MiniMax M3 API Key。

```bash
# 1. 工具链（WSL 内）
sudo apt-get update && sudo apt-get install -y iverilog verilator yosys sby

# 2. 冒烟测试（Gate-1）
cd smoke && ./run_smoke.sh        # 断言子集双工具实测

# 3. 数据注入（M1）
python scripts/bug_injector.py --module fifo_sync

# 4. 评测一键化（M3）
python scripts/run_experiments.py --setting C --samples samples/
```

详见 [docs/方案.md](docs/方案.md)。

## 目录结构

```
precex/
├── README.md          # 本文件
├── docs/              # 文档（权威副本）
│   ├── 方案.md          # 唯一方案文档（背景/组件/数据集/评测/里程碑/难度）
│   ├── 文献调研与评估.md # 文献地图与差异化分析
│   └── 进度.md          # 周报/进度记录（每次推进必须更新）
├── rtl/               # 黄金 RTL 模块（6 模块：fifo_sync/uart_tx/uart_rx/axi_lite_slave/fsm_ctrl/counter_alu）
├── samples/           # BugBench-PS 数据集（L3 样本，每样本 7 件套）
│   ├── golden/        # 黄金设计 + 断言 + 弱 tb
│   └── bugs/          # buggy 变体（s01, s02, ...）
├── harness/           # 评测管线（三通过/mutation/vacuity/指标）
├── agents/            # 核心 4 组件实现 + controller（实验变量）
│   ├── evidence_engine/
│   ├── cex_semantizer/
│   ├── local_repairer/
│   ├── verifier/
│   └── controller/
├── scripts/           # 自动化管线（注入器/评测一键化/token 记账/env 安装）
├── experiments/       # 实验配置（configs/）与运行产物（runs/ 不入库）
├── paper/             # 论文初稿（draft/）与图表（figures/）
└── smoke/             # Gate-1 工具链冒烟测试
```

## 里程碑（13 周，目标 2026-10）

| 周次 | 里程碑 | 内容 | Gate |
| --- | --- | --- | --- |
| W1 | M0 | 工具链验证、harness、6 模块基线、断言子集实测 | Gate-1 |
| W2–3 | M0.5 | 3 例预研：C vs B + A 基线 + T1 快测 | **Gate-0**（定主叙事） |
| W4–7 | M1+M2 | 数据集 30–40；EvidenceEngine + CexSemantizer 文本通道 | Gate-2 |
| W7–9 | M3+M4 | 主实验 A/B/C/D 批量跑；Verifier 充分性；T1 探索 | — |
| W9–10 | M5 | Controller 消融 + 全指标复跑 + token 审计 | — |
| W11–13 | M6 | 论文初稿 | — |

## 当前状态

- **2026-08-03**：方案定稿 v1.6，文档体系重构完成，待启动 W1（M0 工具链验证）
- 进度详情见 [docs/进度.md](docs/进度.md)

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/方案.md](docs/方案.md) | 唯一方案文档：背景、系统结构、组件设计、数据集、评测、里程碑、风险、难度评估 |
| [docs/文献调研与评估.md](docs/文献调研与评估.md) | 26 篇核心文献 + 2025–2026 最新工作调研与差异化结论 |
| [docs/进度.md](docs/进度.md) | 周报/进度总记录（含 Gate 状态表与更新模板） |
