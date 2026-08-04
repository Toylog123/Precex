# l2_fifo_04 - fifo_sync L2 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/fifo_sync/fifo_sync.sv`（黄金基线）
- 错误类型：复位（reset）
- 注入点：第 40 行，规则化文本变换：

```
- head  <= {ADDR_W{1'b0}};
+ head  <= {ADDR_W{1'b1}};
```

- 击穿断言：fifo_sync A3（head<DEPTH）
- L2 双检校验：① iverilog 编译 0 error ✓；② 弱 tb 仿真 FAIL（弱 tb 可抓）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓（伪 L3 判据成立）
- 复现命令：`python3 scripts/bug_injector.py --module fifo_sync --error-type reset --sample-id l2_fifo_04 --variant 1`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
