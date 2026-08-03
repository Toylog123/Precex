# PreCex Gate-0 决策记录（M0.5 预研完成）

> 作者：Toylog｜日期：2026-08-03｜版本：v1.0
> 功能概述：记录 M0.5 三例预研（s01/s02/s03 x A/B/C x 真实 MiniMax M3）评测结果、
> 证据管线（EvidenceEngine / CexSemantizer / T1）落地状态与 Gate-0 叙事决策。

## 1. 结论（Gate-0 决策）

**主叙事定案：反例语义化驱动（C 为主设置），证据工程 + 充分性闭环为支撑**。

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
C 作为主设置（可解释性最好），B 作为消融对照，A 为基线；T1 视觉通道保留为探索章节。

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

- s03 的 C 证据 tokens 过高（160K）到 状态轨迹压缩（仅保留触发窗口加减 8 拍 + 故障锥信号）
  为 M1 必做优化；
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
