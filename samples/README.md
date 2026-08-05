# BugBench-PS 数据集说明（samples/）

> 作者：Toylog | 版本：v0.2（2026-08-03）｜功能概述：L3 缺陷样本数据集规范：样本清单、模块×错误类型矩阵、件套定义、校验流程与复现方式

## 1. 数据集总览

- **规模**：34 个 L3 样本（s04–s37 连续编号；s01–s03 预研样本位于 samples/prestudy/）
- **模块**：6 个黄金模块（fifo_sync / fsm_ctrl / uart_tx / uart_rx / axi_lite_slave / counter_alu）
- **错误类型**：7 类（state_trans 状态跳转 / handshake 握手 / fifo_full 满空 / boundary_wrap 边界回绕 / reset 复位 / width_trunc 位宽截断 / edge 边沿）
- **判定标准**：全部样本通过三通过校验（① iverilog 编译 0 error；② 弱 tb 仿真全绿放过 buggy；③ sby smtbmc+z3 BMC 抓到反例）+ golden 双对照（golden.v 同配置 BMC PASS，断言非空洞）

## 2. 样本清单（s04–s37）

| 样本 | 模块 | 错误类型 | 注入行 | 击穿断言 |
| --- | --- | --- | --- | --- |
| s04 | fifo_sync | FIFO 满空 | L35 | fifo_sync A5（half_full==(count>=DEPTH/2)） |
| s05 | fifo_sync | FIFO 满空 | L30 | fifo_sync A1（满时不写） |
| s06 | fifo_sync | FIFO 满空 | L34 | fifo_sync A2（空时不读） |
| s07 | fsm_ctrl | 状态跳转 | L43 | fsm_ctrl A6（空闲期 step_cnt 必须为 0） |
| s08 | fsm_ctrl | 状态跳转 | L58 | 状态跳转合法性断言 |
| s09 | fsm_ctrl | 状态跳转 | L45 | 启动语义断言 |
| s10 | counter_alu | 复位 | L37 | counter_alu A3（复位释放归 0） |
| s11 | counter_alu | 位宽截断 | L39 | counter_alu A1（仅使能自增 1） |
| s12 | fifo_sync | 复位 | L40 | fifo_sync A3（head<DEPTH） |
| s13 | fifo_sync | 边界回绕 | L48 | fifo_sync A4/A3 类指针性质 |
| s14 | fifo_sync | 位宽截断 | L27 | fifo_sync A1/A4 |
| s15 | uart_tx | 握手 | L57 | uart_tx A1（START 时 txd==0） |
| s16 | uart_tx | 边沿 | L65 | uart_tx 位周期性质 |
| s17 | axi_lite_slave | 握手 | L116 | axi 写通道握手断言（BVALID 不释放） |
| s18 | uart_rx | 状态跳转 | L50 | uart_rx A1/A2（起始位中点确认） |
| s19 | fifo_sync | FIFO 满空 | L54 | fifo_sync A4（count 增量守恒） |
| s20 | fifo_sync | 边界回绕 | L47 | fifo_sync A6（写指针推进） |
| s21 | fifo_sync | 握手 | L31 | fifo_sync A2（空时不读） |
| s22 | fifo_sync | 复位 | L41 | fifo_sync A3（tail 复位归 0） |
| s23 | fifo_sync | 握手 | L30 | fifo_sync A1（满时不写） |
| s24 | fsm_ctrl | 边界回绕 | L53 | fsm_ctrl A3（timeout_irq 前置 step_cnt_d>=TIMEOUT） |
| s25 | axi_lite_slave | 复位 | L138 | axi A8（复位释放输出） |
| s26 | uart_rx | 复位 | L44 | uart_rx A5（忙标志与状态一致） |
| s27 | axi_lite_slave | 边界回绕 | L100 | axi A7（写数据生效） |
| s28 | axi_lite_slave | 位宽截断 | L43 | axi A6/A7（读数据译码/写数据生效） |
| s29 | fifo_sync | FIFO 满空 | L44 | fifo_sync A6（写指针推进） |
| s30 | fsm_ctrl | 复位 | L36 | fsm_ctrl A6（空闲期 step_cnt 归 0） |
| s31 | counter_alu | 状态跳转 | L28 | counter_alu A4（ALU 输出正确性） |
| s32 | counter_alu | 边界回绕 | L39 | counter_alu A1（仅使能自增 1） |
| s33 | axi_lite_slave | 状态跳转 | L114 | axi A3（BVALID 前置 AW/W 完成） |
| s34 | axi_lite_slave | 边界回绕 | L144 | axi A6（读数据译码正确性） |
| s35 | uart_tx | 状态跳转 | L78 | uart_tx A4（DATA→STOP 收尾，帧缺停止位） |
| s36 | uart_rx | 状态跳转 | L67 | uart_rx A4（状态机跳转合法性） |
| s37 | uart_rx | 边界回绕 | L60 | uart_rx A1/A2（起始位中点确认） |

## 3. 模块 × 错误类型矩阵

| 模块 | state_trans | handshake | fifo_full | boundary_wrap | reset | width_trunc | edge | 小计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fifo_sync | - | s21,s23 | s04,s05,s06,s19,s29 | s13,s20 | s12,s22 | s14 | - | 12 |
| fsm_ctrl | s07,s08,s09 | - | - | s24 | s30 | - | - | 5 |
| uart_tx | s35 | s15 | - | - | - | - | s16 | 3 |
| uart_rx | s18,s36 | - | - | s37 | s26 | - | - | 4 |
| axi_lite_slave | s33 | s17 | - | s27,s34 | s25 | s28 | - | 6 |
| counter_alu | s31 | - | - | s32 | s10 | s11 | - | 4 |

## 4. 件套定义（每样本 12 文件）

- buggy.v / golden.v / tb_weak.sv / verify.sby / verify_golden.sby / verify_repair.sby /
  cex.vcd / cex.log / meta.json / evidence.json / semantics.json / notes.md
- verify_repair.sby：修复验证配置（prove 模式，k-induction）——修复后三通过判定第 ③ 步用
  证明而非 BMC，避免只查有限深度；golden 对照已 PASS（bmc），此处证明修复充分性
- uart_rx 样本额外含 uart_tx.sv（回环联测依赖，编译时同目录提供）
- 断言已内联于 buggy.v/golden.v（不再生成独立 assertions.sv/formal_top.sv）

## 5. 复现与校验

WSL 内执行（需 注入 z3 PATH 与 SMTBMC wrapper，见 smoke/run_sby.sh）：

```bash
export PATH=$HOME/.local/bin:$PATH; export SMTBMC=$PWD/smoke/yosys-smtbmc-z3.sh
cd samples/bugs/s04 && sby -f verify.sby -d sby_work        # 期望 DONE FAIL（反例）
sby -f verify_golden.sby -d sby_golden                     # 期望 DONE PASS（非空洞）
```

重生样本：`python3 scripts/bug_injector.py --module <m> --error-type <t> --sample-id sNN --variant N`（参见各 meta.json 的 reproduce_cmd）
- 参数化覆写：`--param CLK_FREQ=<clk>,BAUD=<baud>` 同步替换设计/tb/uart_tx.sv 参数；s35 用 DIV=4（depth 56），
  s36/s37 用 DIV=16（depth 176）——小 DIV 使 uart_rx 深时序反例 BMC 可收敛；meta.json 记录 param_override

## 6. 已知限制与后续

- edge 类型仍仅 1 例（注入器变体池瓶颈）；边沿变体（posedge→negedge）因 yosys 双极性冲突不可用；uart_tx 3 例（s15,s16,s35）、uart_rx 4 例（s18,s26,s36,s37），s35–s37 为参数化深时序样本
- 深时序反例成本控制：uart_rx START 中点类原需 depth≥230 不可收敛，经 --param 小 DIV（DIV=16）降为 depth 176 入库（s36/s37）；DIV=4 过激进（HALF=2 竞态）不可用；counter 满值回绕仍用低阈值变体（s32）
- 目标 30–40：当前 34 例；Gate-2 前按矩阵缺口补足（重点：edge/handshake 新变体）

- **缺口补齐尝试（2026-08-04，6 个候选变体全部无效 → 可证明变体饱和结论）**：
  | 候选 | 模块 × 类型 × 变体 | 失败阶段 | 原因 |
  | --- | --- | --- | --- |
  | s38 | fsm_ctrl × width_trunc × v3（hold_cnt 3bit） | formal PASS | 断言未击穿：hold_cnt 截断不改状态转移合法性（A4 自环合法） |
  | s39a | uart_tx × boundary_wrap × v3（bit_cnt==DATA_W 卡死） | formal PASS | 无 liveness 断言，DATA 自环合法 |
  | s40a | axi × edge × v3（ACLK negedge） | formal ERROR rc=16 | yosys 双极性冲突（复核确认） |
  | s39b | axi × handshake × v5（RVALID 释放删除） | sim FAIL | 弱 tb 读回检查抓到（tb_weak.sv:153），清洗键未覆盖该检查 |
  | s40b | uart_rx × handshake × v6（rx_busy 不释放，本日新增） | formal PASS | A5 非阻塞时序：进入 S_IDLE 当拍 rx_busy 已清零，断言永不触发 |
  | — | uart_rx × edge（baud_tick 取反） | 未建 | uart_rx 无 baud_tick 线网；位定时偏移不触发结构性断言 |
  - **结论**：34 样本是当前断言集下可证明变体的近饱和点。缺口变体要么断言未击穿（formal PASS）、
    要么弱 tb 不容忍（sim FAIL）、要么工具链不支持（yosys 双沿）。uart_rx 断言以结构型（状态机合法性）
    为主，对位定时序常量/边沿变异不敏感；edge 类型仅 uart_tx baud_tick 一个可证明模式。
  - **待办（future work）**：闭合 edge/handshake 缺口须新增数值型断言（rx_data 帧比对、采样点周期精确性），
    属断言基线变更（红线），不做。数据集维持 34 例定案。

## 7. 深时序专项子集（samples/deep/s38-s42，2026-08-05）

- **机制**：natural weak tb（不消毒，原始黄金 tb 检查自然放过深缺陷）+ `--min-fail-step 20` 深度门禁 + 可选 `--tb-shallow` 浅覆盖 tb
- **样本**：s38（uart_tx 帧缺停止位，DIV=4，fail_step=39，natural）、s39（fsm_ctrl 超时提前，TIMEOUT=48，fail_step=51，natural+shallow）、s40（fifo_sync 满时仍写，DEPTH=32，fail_step=35，natural+shallow）、s41（uart_tx 帧缺停止位，DIV=8，fail_step=75，natural）、s42（fsm_ctrl 超时提前，TIMEOUT=62，fail_step=65，natural+shallow）
- **对比旧 34 样本**：旧集 fail_step 中位数 4、>=20 拍仅 3 个；新子集全部 >=35 拍且弱 tb 自然通过
- **BMC 收敛上限**：fifo DEPTH<=32（90s）、uart DIV<=16-32、fsm TIMEOUT<=48-62；DEPTH=64/DIV=64 超时 >8min
- **复现**：`python3 scripts/bug_injector.py --module uart_tx --error-type state_trans --sample-id s38 --variant 7 --param CLK_FREQ=400,BAUD=100 --natural-tb --min-fail-step 20 --samples-dir deep` 等（见各 meta.json reproduce_cmd，均已带 --samples-dir deep）
- **目录约定**：深时序样本位于 `samples/deep/`（独立于 BugBench-PS 34 样本 `samples/bugs/`），
  与主基准分离以保持 bugs=34 不变量（gate2/measure_slim 等工具假设）；LLM 评测结果见 docs/审查-数据集真实性.md 12.3
