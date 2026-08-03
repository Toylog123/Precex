# BugBench-PS 数据集说明（samples/）

> 作者：Toylog | 版本：v0.2（2026-08-03）｜功能概述：L3 缺陷样本数据集规范：样本清单、模块×错误类型矩阵、件套定义、校验流程与复现方式

## 1. 数据集总览

- **规模**：31 个 L3 样本（s04–s34 连续编号；s01–s03 为预研样本，见 samples/prestudy/）
- **模块**：6 个黄金模块（fifo_sync / fsm_ctrl / uart_tx / uart_rx / axi_lite_slave / counter_alu）
- **错误类型**：7 类（state_trans 状态跳转 / handshake 握手 / fifo_full 满空 / boundary_wrap 边界回绕 / reset 复位 / width_trunc 位宽截断 / edge 边沿）
- **判定标准**：全部样本通过三通过校验（① iverilog 编译 0 error；② 弱 tb 仿真全绿放过 buggy；③ sby smtbmc+z3 BMC 抓到反例）+ golden 双对照（golden.v 同配置 BMC PASS，断言非空洞）

## 2. 样本清单（s04–s34）

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

## 3. 模块 × 错误类型矩阵

| 模块 | state_trans | handshake | fifo_full | boundary_wrap | reset | width_trunc | edge | 小计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fifo_sync | - | s21,s23 | s04,s05,s06,s19,s29 | s13,s20 | s12,s22 | s14 | - | 12 |
| fsm_ctrl | s07,s08,s09 | - | - | s24 | s30 | - | - | 5 |
| uart_tx | - | s15 | - | - | - | - | s16 | 2 |
| uart_rx | s18 | - | - | - | s26 | - | - | 2 |
| axi_lite_slave | s33 | s17 | - | s27,s34 | s25 | s28 | - | 6 |
| counter_alu | s31 | - | - | s32 | s10 | s11 | - | 4 |

## 4. 件套定义（每样本 10 文件）

- buggy.v / golden.v / tb_weak.sv / verify.sby / verify_golden.sby / cex.vcd / cex.log / meta.json / evidence.json / notes.md
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

## 6. 已知限制与后续

- uart_tx/uart_rx 各仅 2 例；edge 类型仅 1 例（注入器变体池瓶颈）；边沿变体（posedge→negedge）因 yosys 双极性冲突不可用
- uart_rx 深时序反例（START 中点等）需 BMC depth≥230，运行成本过高，暂不入库；counter 满值回绕（≥第 256 拍）同理，采用低阈值提前回绕变体（s32）
- 目标 30–40：当前 31 例达下限；Gate-2 前按矩阵缺口补足（重点：uart_tx/uart_rx/handshake/edge 新变体）
