# l2_uartrx_01 - uart_rx L2 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/uart_rx/uart_rx.sv`（黄金基线）
- 错误类型：状态跳转（state_trans）
- 注入点：第 50 行，规则化文本变换：

```
- S_IDLE: begin
                    rx_busy <= 1'b0;
                    if (!rxd) begin
                        baud_cnt <= {DIV_W{1'b0}};
                        state    <= S_START;
+ S_IDLE: begin
                    rx_busy <= 1'b0;
                    if (!rxd) begin
                        baud_cnt <= {DIV_W{1'b0}};
                        state    <= S_DATA;
```

- 击穿断言：uart_rx A1/A2（起始位中点确认）
- L2 双检校验：① iverilog 编译 0 error ✓；② 弱 tb 仿真 FAIL（弱 tb 可抓）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓（伪 L3 判据成立）
- 复现命令：`python3 scripts/bug_injector.py --module uart_rx --error-type state_trans --sample-id l2_uartrx_01 --variant 4`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
