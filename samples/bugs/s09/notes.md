# s09 - fsm_ctrl L3 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/fsm_ctrl/fsm_ctrl.sv`（黄金基线）
- 错误类型：状态跳转（state_trans）
- 注入点：第 43 行，规则化文本变换：

```
- S_IDLE: begin
                    step_cnt <= 6'd0;
+ S_IDLE: begin
```

- 击穿断言：fsm_ctrl A6（空闲期 step_cnt 必须为 0）
- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓
- 复现命令：`python3 scripts/bug_injector.py --module fsm_ctrl --error-type state_trans --sample-id s09`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
