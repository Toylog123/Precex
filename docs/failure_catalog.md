# PreCex 失败档案（Failure Catalog）

> 生成时间：2026-08-07T15:03:16  |  数据源：loc_rescore_audit.json（行号判据修复后）+ 权威结果文件

> 说明：本档案只汇总负结果（new_exact=False 的定位 miss），用于定位“为什么不理想”并指导改进。

## 一、失败模式聚类总表

| 失败模式 | 数量 | 代表样本 | 可干预环节 |
|---|---|---|---|
| C 证据行号误导（loc == sem.failed_line，断言行非缺陷行） | 12 | s08/s11/s17/s18/s22/s32 | 证据卫生：failed_line 语义纠偏 |
| C 证据偏移（loc = 真值 - 8） | 16 | s05/s06/s13/s20/s21/s23/s26/s30/s31/s35/s36 | 证据卫生：行号基准对齐 |
| 近失（dev ≤ 1，行号几乎命中） | 6 | s10/s15/s16/s29/s31 | 判据/容差口径 |
| 真实 miss（dev > 8 且非证据行号） | 6 | s15/s29/s30/s34 | 证据缺信息 / 模型误判 |
| 握手类 s15 全设置失败 | 12/12 | s15×A/B/C/D×3seed | 握手证据形态（阶段2） |
| deep 子集 B/D 系统偏移（dev≈8） | 12 | s38/s39/s40/s42 | 证据行号基准（同 C） |

## 二、逐样本失败卡片

### 2.1 C 设置 40 个 miss 明细

**eq_sem（12）**：s08/s0@137, s08/s1@137, s08/s2@137, s11/s0@96, s17/s0@234, s17/s1@234, s17/s2@234, s18/s1@150, s22/s0@130, s32/s0@96, s32/s1@96, s32/s2@96

**off8（16）**：s05/s0@26, s06/s0@30, s06/s2@30, s13/s2@44, s16/s2@61, s20/s1@44, s21/s0@27, s21/s1@27, s21/s2@27, s23/s1@26, s26/s1@40, s26/s2@40, s30/s1@32, s31/s2@24, s35/s2@75, s36/s2@64

**near1（6）**：s10/s1@42, s15/s0@60, s15/s1@60, s16/s1@68, s29/s2@49, s31/s0@31

**other（6）**：s15/s2@90, s29/s0@60, s29/s1@43, s30/s2@46, s34/s0@139, s34/s2@139


### 2.2 握手类 s15 全设置定位（新判据 exact）

- A: seed0 loc=60 dev=1, seed1 loc=60 dev=1, seed2 loc=60 dev=1
- B: seed0 loc=60 dev=1, seed1 loc=55 dev=6, seed2 loc=55 dev=6
- C: seed0 loc=60 dev=1, seed1 loc=60 dev=1, seed2 loc=90 dev=29
- D: seed0 loc=60 dev=1, seed1 loc=52 dev=9, seed2 loc=59 dev=2

### 2.3 deep 子集未精确命中

- s38/B/seed1 loc=78 dev=5
- s39/B/seed0 loc=49 dev=8
- s39/B/seed1 loc=49 dev=8
- s40/A/seed2 loc=30 dev=4
- s41/A/seed0 loc=78 dev=5
- s42/B/seed0 loc=53 dev=4
- s42/B/seed2 loc=53 dev=4
- s40/D/seed1 loc=26 dev=8
- s40/D/seed2 loc=26 dev=8
- s38/C/seed2 loc=75 dev=8
- s38/D/seed0 loc=75 dev=8
- s38/D/seed2 loc=75 dev=8

## 三、根因假设

1. **C 证据 failed_line 语义错位**：cex.log 的 `Assert failed in <module>: buggy.v:<line>` 报告的是**断言行**（s08 为 137、s18 为 150），而非缺陷行（63/58）。证据管线把断言行直接作为 failed_line 喂给 LLM，LLM 采信后报错行。
2. **C 证据 -8 偏移**：LLM 报的行 = 真值 - 8，源于证据中 yosys 内部信号名/cycle 计数与 buggy.v 行号体系不一致，或证据文本行号基准偏移。
3. **握手 s15 全败**：缺陷为时序握手（起始位/握手信号未翻转），A/B/C/D 四种证据均未提供“该翻转未翻转”的显式信号，属证据缺信息。
4. **deep B/D dev≈8**：与 C 设置同源的证据行号基准偏移，或模块级信号命名差异。

## 四、门检判定

- [x] 全部失败样本已归类（eq_sem/off8/near1/other + s15 + deep），无未分类残留。
- [ ] 阶段 2 待办：先做 2a 分解实验确认 C 行号误导修复效果；再做握手证据形态迭代。