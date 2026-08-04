# l2_fifo_02 - fifo_sync L2 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/fifo_sync/fifo_sync.sv`（黄金基线）
- 错误类型：FIFO 满空（fifo_full）
- 注入点：第 54 行，规则化文本变换：

```
- 
            // 计数守恒：同拍读写 count 不变
            if (can_wr && can_rd) begin
                count <= count;
            end else 
+ 
            // 计数守恒：同拍读写 count 不变
            
```

- 击穿断言：fifo_sync A4（count 增量守恒）
- L2 双检校验：① iverilog 编译 0 error ✓；② 弱 tb 仿真 FAIL（弱 tb 可抓）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓（伪 L3 判据成立）
- 复现命令：`python3 scripts/bug_injector.py --module fifo_sync --error-type fifo_full --sample-id l2_fifo_02 --variant 4`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
