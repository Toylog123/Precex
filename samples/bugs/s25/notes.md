# s25 - axi_lite_slave L3 故障样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/axi_lite_slave/axi_lite_slave.sv`（黄金基线）
- 错误类型：复位（reset）
- 注入点：第 138 行，规则化文本变换：

```
- S_AXI_RVALID <= 1'b0;
            S_AXI_RDATA  <= {DATA_W{1'b0}};
+ S_AXI_RVALID <= 1'b1;
            S_AXI_RDATA  <= {DATA_W{1'b0}};
```

- 击穿断言：axi A8（复位释放输出）
- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓
- golden 双对照：golden.v 同配置 BMC PASS（断言非空洞）
- 复现命令：`python3 scripts/bug_injector.py --module axi_lite_slave --error-type reset --sample-id s25`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
