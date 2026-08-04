# l2_cnt_03 - counter_alu L2 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/counter_alu/counter_alu.sv`（黄金基线）
- 错误类型：复位（reset）
- 注入点：第 37 行，规则化文本变换：

```
- cnt <= {DATA_W{1'b0}};
+ cnt <= {DATA_W{1'b1}};
```

- 击穿断言：counter_alu A3（复位释放归 0）
- L2 双检校验：① iverilog 编译 0 error ✓；② 弱 tb 仿真 FAIL（弱 tb 可抓）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓（伪 L3 判据成立）
- 复现命令：`python3 scripts/bug_injector.py --module counter_alu --error-type reset --sample-id l2_cnt_03 --variant 2`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
