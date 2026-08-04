# PreCex Gate-0 决策记录（M0.5 预研完成）

> 作者：Toylog｜日期：2026-08-03｜版本：v1.1（2026-08-04 主实验修正）
> 功能概述：记录 M0.5 三例预研（s01/s02/s03 x A/B/C x 真实 MiniMax M3）评测结果、
> 证据管线（EvidenceEngine / CexSemantizer / T1）落地状态与 Gate-0 叙事决策。

## 0. 主实验修正（2026-08-04，重要）

**原 Gate-0 结论（反例语义化驱动，C 主设置）被 34 样本主实验推翻，修正为：结构化证据驱动（B 主设置）+ 充分性闭环。**

### 0.1 主实验最终结果（306 次真实 MiniMax M3：34 样本 × A/B/C × 3 种子，含失败离线重放与网络补跑修正）

| 设置 | loc_top1 | repair_pass | PASS/102 | tokens | cost(USD) |
| --- | --- | --- | --- | --- | --- |
| A 原始日志 | 46.1% | 73.5% | 75 | 1,977,971 | 2.751 |
| B 结构化证据 | **61.8%** | 73.5% | 75 | **1,753,835** | **2.705** |
| C 反例语义化 | 55.9% | 73.5% | 75 | 3,490,804 | 4.155 |

### 0.2 修正要点

1. **修复率三设置收敛一致（73.5%）**：规模化后证据表示对"能否修好"无显著影响。预研 s01–s03（简单 FIFO/FSM/counter）9/9 全过、C 表现最好，是小样本 + 简单模块的偶然；34 样本加入 axi_lite_slave/uart 复杂协议后，C 无增益。
2. **B（结构化证据）在定位精度与成本全面占优**：loc_top1 61.8% vs C 55.9%（+5.9pt）；tokens 1.75M vs C 3.49M（C 多 99%），cost 2.70 vs 4.16（C 高 54%）。根因：C 的 semantics.json 是 evidence.json 的 10–36 倍大（中位 22.5 倍），长上下文稀释关键信号且成本高。
3. **真实修复能力边界**：s16/s17/s18/s25/s26/s27/s28/s33/s34（axi/uart 复杂协议：握手/复位/边界回绕/状态跳转）9 样本修复率 0%（离线重放确认，非应用器问题）；s08/s15/s20/s29/s35 等 loc_top1=0 但 repair=100%（LLM 能修但对行号不敏感）。
4. **基础设施修正**：diff 应用器模糊空白匹配修复（39 条失败离线重放，10 条转 PASS）；4 条网络超时补跑，s30/A2 PASS，3 条（s16/A0、s16/C0、s17/B2）补跑超时后用已落盘 LLM 输出离线重放确认全部 FAIL（与 repair=0% 一致），**306 条记录现已全部有真实 verdict、无缺失**。


> **2026-08-04 重大修正（prove 判据翻案）**：本节"修复率边界由模块复杂度决定"结论**已被推翻**。
> 根因：主实验修复判定用 verify_repair.sby（prove/k-induction），对 axi/uart 门控时序断言不收敛
> （golden.v 本身在 prove 下也 UNKNOWN），正确修复被误判 FAIL（假阴性 96.2%）。
> 用 bmc 判据（verify.sby，与 golden 对照一致）批量重验 303 条 + 补跑 3 条缺失：
> **修复率 306/306 = 100%**（prove 旧数据 74.3% 作废）。axi_lite_slave/uart_rx 0% 是判据 bug，非模型能力。
> 详见 docs/进度.md 2026-08-04 记录与 experiments/runs/reverify_bmc_all.json。
> **保留修正后仍成立的部分**：B 定位精度/成本占优、B 的定位增益集中在算术/位宽/边界类缺陷。
### 0.2b 模块/错误类型细粒度分析（补充，2026-08-04）

按模块（排除 3 条网络失败后，B vs C）：

| 模块 | B loc_top1 | B repair | C loc_top1 | C repair | 样本数(每设置) |
| --- | --- | --- | --- | --- | --- |
| counter_alu | **92%** | **100%** | 58% | **100%** | 12 |
| fifo_sync | 61% | **100%** | 67% | **100%** | 36 |
| fsm_ctrl | 60% | **100%** | 60% | **100%** | 15 |
| uart_tx | 33% | **100%** | 25% | **100%** | 9 |
| uart_rx | 42% | **100%** | **50%** | **100%** | 12 |
| axi_lite_slave | **76%** | **100%** | 50% | **100%** | 17 |

要点：
1. ~~**修复率边界由模块复杂度决定**~~（2026-08-04 翻案：bmc 判据下全部 100%，见上方注记）**修复率与模块复杂度无关，由判据决定**；
   bmc 判据下 axi_lite_slave/uart_rx/uart_tx 均 100%（旧 0%/50%/67-75% 为 prove 误判）；
   跨周期语义复杂影响的是**定位精度**（axi B 76% vs C 50%）与成本，而非修复能力。
2. **B 的定位优势集中在 counter（92% vs 58%）与 axi（76% vs 50%）**；fifo/fsm 基本持平；
   uart_rx 反而是 C 略高（50% vs 42%）。说明"结构化证据更利于精确行号定位"在算术/状态机类模块成立，
   但对协议握手类（uart_rx）语义化描述更有帮助。
3. **错误类型维度**：边界回绕 B 定位 81% vs C 57%（差异最大）；位宽截断 B 100% vs C 67%；
   握手/状态跳转 B≈C。即 B 的定位增益主要来自"数值/位宽/边界"类缺陷，C 在"时序握手"类无劣势。

结论：论文应报告**模块×证据表示的交互效应**（而非单一主效应），
B 作为默认主设置（整体定位+成本最优），C 保留为 uart 协议模块的可解释性探索选项。
### 0.3 论文叙事建议（替换原第 1 节结论）

- **主论点**：以形式反例为最高置信证据 + **结构化证据表示（B）** + 形式再验证充分性闭环，使跨周期 RTL 缺陷定位-修复在开源工具链上达到 73.5% 稳定三通过。
- **B 为主设置**（定位精度最高、成本最低），A 为基线，C 语义化降级为可解释性/成本探索章节（诚实报告其无修复增益但有可解释价值）。
- 定位精度（Top-1/3）与成本作为核心指标；修复率天花板由复杂协议样本决定（后续 Gate-2 补充更难样本验证边界）。
## 1. 结论（Gate-0 决策，2026-08-04 主实验修正后）

**主叙事定案：结构化证据驱动（B 为主设置）+ 充分性闭环；C 语义化降级为可解释性/成本探索章节**。

依据：
1. 三样本 x A/B/C 全部在不超过 3 次重试内**修复三通过（prove PASS）**，C 从未落后于 A/B；
2. C 在 s01（FIFO 同拍读写计数错乱）与 s02（FSM 步进停滞）中给出**信号级因果链**，
   M3 直接命中故障锥信号（count/can_wr/can_rd、step_cnt/S3），修复 diff 最小；
3. T1 视觉通道（VCD 到 PNG 到 M3 多模态）成功读出 s01 count 0到1到2到0 异常、s03 计数回绕，
   视觉通道（FVDebug 未覆盖）可行且成本低（约 0.004-0.006 USD/次）；
4. 3 样本规模不足以做 A/B/C 统计显著区分（n=3），故以"全设置均可达三通过 +
   C 证据因果性最清晰"作为叙事支撑，不宣称 C 在成功率上显著优于 B；
5. 风险 5（C 相对 B 无增益）实际演化为：**在反例充分且 LLM 强大时 A/B/C 都能修好，
   差异体现在证据可解释性/定位精度（s03 的 A/B/C 均未精确 Top-1 但修复均通过）与成本**。
   论文叙事应强调"证据表示对成功率无显著影响、对定位精度与可解释性有影响 +
   验证充分性闭环（mutation/vacuity/非空洞）才是跨周期修复可靠性的关键贡献"。

**叙事主线修订**：从"反例语义化带来修复率提升"调整为——
"以形式反例为最高置信证据 + 结构化/语义化证据表示 + 形式再验证充分性闭环，
使跨周期 RTL 缺陷定位-修复在开源工具链上达到稳定三通过"。
B 作为主设置（定位精度与成本最优），A 为基线，C 语义化作为可解释性消融（诚实报告其无修复增益但有可解释价值）；T1 视觉通道保留为探索章节。

## 2. 评测结果（真实 MiniMax M3，温度 0.2，不超过 3 次重试）

| 样本 | 设置 | 定位 Top-1 | 修复三通过 | 验证模式 | tokens | 费用(USD) |
| --- | --- | --- | --- | --- | --- | --- |
| s01 fifo_count | A | 是 | 是 PASS | prove | 13,726 | 0.0207 |
| s01 fifo_count | B | 是 | 是 PASS | prove | 5,724 | 0.0059 |
| s01 fifo_count | C | 是 | 是 PASS | prove | 15,012 | 0.0170 |
| s02 state_jump | A | 是 | 是 PASS | prove | 14,671 | 0.0206 |
| s02 state_jump | B | 是（重试后） | 是 PASS | prove | 29,687 | 0.0439 |
| s02 state_jump | C | 是 | 是 PASS | prove | 19,279 | 0.0179 |
| s03 wrap_around | A | 否（报相邻行） | 是 PASS | prove | 28,494 | 0.0231 |
| s03 wrap_around | B | 否（报相邻行） | 是 PASS | prove | 20,138 | 0.0319 |
| s03 wrap_around | C | 否（报相邻行） | 是 PASS | prove | 160,003 | 0.1024 |

注：s02/B 首次运行 diff 应用失败（LLM 输出的 hunk 上下文行与 CRLF 文件不匹配），
重试后定位 Top-1 + 修复通过；s03 三设置均定位到注入点附近但未精确命中行号
（A6 断言行 138 vs 注入行 51），修复均通过。

**成本观察**：C 在 s03 上 tokens 最高（160K，因 257 拍状态轨迹较长）
到 C 需要"轨迹压缩 + 聚焦故障锥"优化（后文列为待办）。

## 3. T1 视觉通道快测

| 样本 | 模式 | in/out tokens | 费用(USD) | 摘要质量 |
| --- | --- | --- | --- | --- |
| s01 | real 多模态 | 986/2,118 | 0.0057 | 正确读出 FIFO count 0到1到2到0 异常、can_rd/can_wr 时序 |
| s03 | real 多模态 | 986/1,317 | 0.0038 | 识别计数回绕（cnt 末段全 1、cnt_en 边沿） |

结论：T1 可行、成本低、能正确提取关键信号异常；波形图质量受信号选择影响
（当前 12 条自动选择含部分内部信号），需优化关键信号筛选。

## 4. 证据管线落地状态

- **EvidenceEngine**（agents/evidence_engine/）：cex.log 到统一 JSON
  （error_type/module/file/line/code_slice/signals/trigger_condition/fail_stage/fail_step/
  x_state_warn/raw_trace_ref），s01-s03 evidence.json 已生成；
- **CexSemantizer**（agents/cex_semantizer/）：VCD 到周期事件表/状态轨迹/故障锥 +
  M3 NL 摘要（附录 A 模板），s01-s03 semantics.json 已生成（真实 M3 摘要）；
- **T1 波形渲染**（waveform_svg.py）：VCD 到 SVG/PNG（Pillow），多模态调用已通；
- **A/B/C prompt 模板族**（experiments/configs/prompt_templates.py）：同模板族仅证据段替换；
- **预研评测一键化**（scripts/run_prestudy.py）：LLM 定位+修复 到 diff 应用 到 三通过，
  重试不超过 3、token 记账、LLM 原始输出落盘（experiments/runs/llm_outputs/，不入库）；
- **修复验证**：s01-s03 verify_repair.sby（prove/k-induction，快且充分），
  golden 对照 s01/s02 已证明，s03 golden prove（depth 270）超时到 BMC 反例已抓（step 257）。

## 5. 已知问题与后续（Gate-0 之后）

- s03 的 C 证据 tokens 过高（160K）——**已优化（2026-08-03 同日）**：
  CexSemantizer 增加 window 压缩（触发窗口 ±8 拍 + 周期事件降采样 + 故障锥过滤内部信号），
  重建后 s03 摘要调用 85K → 32K input tokens（-62%），s03/C 评测 160K → 56K tokens（-65%）、
  费用 0.1024 → 0.0460 USD（-55%），修复三通过保持 PASS；
- s03 golden prove（depth 270）超时到 golden 对照改 BMC depth 270（已 PASS）或
  prove depth 更小 + 分段归纳；
- diff 应用器对 LLM 输出格式鲁棒性已显著提升（剥离 think 块/CRLF 归一化/行尾容错），
  但仍建议 LocalRepairer 增加"只输出代码 hunk"约束与 iverilog 语法预检；
- 预研 n=3 样本 A/B/C 无统计显著差异到 主实验（n>=20）须加入定位精度（Top-1/3）、
  可解释性（人工评分）与成本三个维度，避免"成功率天花板"无法区分设置。

## 6. 决策对方案的影响

- 方案 3（核心论点）：CexSemantizer 从"主创新"保留为"核心组件"，但论文主张从
  "语义化提升修复率"改为"语义化提升可解释性与定位精度 + 充分性闭环保证可靠修复"；
- 方案 8（评测）：主实验指标加入定位 Top-1/3、人工可解释性评分、token 成本；
- 方案 11（风险 5）：C 无增益风险的缓解从"切叙事"改为"叙事已包含双支柱
  （证据表示 x 充分性闭环）"，Gate-0 已证伪"无增益即全盘失败"。

## 7. 复现命令

（代码块见下，均为 WSL 内命令）

1) 样本证据（已入库 cex.vcd/cex.log）
   bash scripts/validate_sample.sh samples/prestudy/s01 verify.sby
   bash scripts/validate_sample.sh samples/prestudy/s02 verify.sby
   bash scripts/validate_sample.sh samples/prestudy/s03 verify.sby   # 需要约 60 分钟 BMC

2) 生成 B 证据
   python3 agents/evidence_engine/evidence_engine.py samples/prestudy/sNN --out samples/prestudy/sNN/evidence.json

3) 生成 C 证据（真实 M3）
   python3 agents/cex_semantizer/cex_semantizer.py samples/prestudy/sNN --out samples/prestudy/sNN/semantics.json --real

4) T1 视觉（真实多模态）
   python3 scripts/t1_visual_test.py samples/prestudy/sNN --out experiments/runs/t1_sNN.json --real

5) A/B/C 预研评测（真实 LLM）
   python3 scripts/run_prestudy.py --samples s01,s02,s03 --settings A,B,C --retries 3 --out experiments/runs/prestudy_results.json
