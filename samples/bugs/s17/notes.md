# s17 - axi_lite_slave L3 故障样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/axi_lite_slave/axi_lite_slave.sv`（黄金基线）
- 错误类型：握手（handshake）
- 注入点：第 116 行，规则化文本变换：

```
- 
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            S_AXI_BVALID <= 1'b0;
        end
+ 
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            // BUG: BVALID 释放分支被删除（写响应不释放）
            // S_AXI_BVALID <= 1'b0;
        end
```

- 击穿断言：axi 写通道握手断言（BVALID 不释放）
- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓
- golden 双对照：golden.v 同配置 BMC PASS（断言非空洞）
- 复现命令：`python3 scripts/bug_injector.py --module axi_lite_slave --error-type handshake --sample-id s17`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
