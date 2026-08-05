# s53 - uart_rx L3 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/uart_rx/uart_rx.sv`（黄金基线）
- 错误类型：状态跳转（state_trans）
- 注入点：第 1 行，规则化文本变换：

```

```

- 击穿断言：uart_rx A2（起始位中点确认后才进数据接收）
- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓
- 复现命令：`python3 scripts/build_structural_samples.py --module uart_rx`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
