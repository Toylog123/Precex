# l2_fsm_02 - fsm_ctrl L2 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/fsm_ctrl/fsm_ctrl.sv`（黄金基线）
- 错误类型：状态跳转（state_trans）
- 注入点：第 58 行，规则化文本变换：

```
- hold_cnt == S1_HOLD) begin
                        state    <= S2;
+ hold_cnt == S1_HOLD) begin
                        state    <= S3;
```

- 击穿断言：状态跳转合法性断言
- L2 双检校验：① iverilog 编译 0 error ✓；② 弱 tb 仿真 FAIL（弱 tb 可抓）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓（伪 L3 判据成立）
- 复现命令：`python3 scripts/bug_injector.py --module fsm_ctrl --error-type state_trans --sample-id l2_fsm_02 --variant 2`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
