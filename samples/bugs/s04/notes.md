# s04 - fifo_sync L3 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/fifo_sync/fifo_sync.sv`（黄金基线）
- 错误类型：FIFO 满空（fifo_full）
- 注入点：第 35 行，规则化文本变换：

```
- assign half_full = (count >= (DEPTH >> 1));
+ assign half_full = (count > (DEPTH >> 1));
```

- 击穿断言：fifo_sync A5（half_full==(count>=DEPTH/2)）
- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓
- 复现命令：`python3 scripts/bug_injector.py --module fifo_sync --error-type fifo_full --sample-id s04`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
