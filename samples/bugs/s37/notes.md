# s37 - uart_rx L3 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/uart_rx/uart_rx.sv`（黄金基线）
- 错误类型：边界回绕（boundary_wrap）
- 注入点：第 60 行，规则化文本变换：

```
- if (baud_cnt == (HALF - 1)) begin
+ if (baud_cnt == (HALF)) begin
```

- 击穿断言：uart_rx A1/A2（起始位中点确认）
- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓
- 复现命令：`python3 scripts/bug_injector.py --module uart_rx --error-type boundary_wrap --sample-id s37 --variant 8 --param CLK_FREQ=1600,BAUD=100`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
