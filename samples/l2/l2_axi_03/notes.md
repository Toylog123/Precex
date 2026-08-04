# l2_axi_03 - axi_lite_slave L2 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/axi_lite_slave/axi_lite_slave.sv`（黄金基线）
- 错误类型：位宽截断（width_trunc）
- 注入点：第 43 行，规则化文本变换：

```
- reg [DATA_W-1:0] reg0, reg1, reg2, reg3;
+ reg [DATA_W-2:0] reg0, reg1, reg2, reg3;
```

- 击穿断言：axi A6/A7（读数据译码/写数据生效）
- L2 双检校验：① iverilog 编译 0 error ✓；② 弱 tb 仿真 FAIL（弱 tb 可抓）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓（伪 L3 判据成立）
- 复现命令：`python3 scripts/bug_injector.py --module axi_lite_slave --error-type width_trunc --sample-id l2_axi_03 --variant 4`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
