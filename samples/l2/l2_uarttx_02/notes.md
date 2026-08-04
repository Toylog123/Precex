# l2_uarttx_02 - uart_tx L2 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/uart_tx/uart_tx.sv`（黄金基线）
- 错误类型：状态跳转（state_trans）
- 注入点：第 78 行，规则化文本变换：

```
- if (bit_cnt == DATA_W - 1) begin
                            state <= S_STOP;
+ if (bit_cnt == DATA_W - 1) begin
                            state    <= S_IDLE;
```

- 击穿断言：uart_tx A4（DATA→STOP 收尾）
- L2 双检校验：① iverilog 编译 0 error ✓；② 弱 tb 仿真 FAIL（弱 tb 可抓）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓（伪 L3 判据成立）
- 复现命令：`python3 scripts/bug_injector.py --module uart_tx --error-type state_trans --sample-id l2_uarttx_02 --variant 7 --param CLK_FREQ=400,BAUD=100`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
