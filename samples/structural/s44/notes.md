# s44 - fsm_ctrl L3 缺陷样本构造说明

> 作者：Toylog | 版本：v0.1 | 功能概述：记录注入方式、校验结果与人工核对记录

- 来源模块：`rtl/fsm_ctrl/fsm_ctrl.sv`（黄金基线）
- 错误类型：边界回绕（boundary_wrap）
- 注入点：第 1 行，规则化文本变换：

```

```

- 击穿断言：fsm_ctrl 强断言 A8（step_cnt 超阈值后必须回 IDLE）
- 三通过校验（L3 判定）：① iverilog 编译 0 error ✓；② 弱 tb 仿真全绿（放过 buggy）✓；③ sby (smtbmc+z3) BMC 抓到反例 ✓
- 复现命令：`python3 scripts/build_structural_samples.py --module fsm_ctrl`
- 人工核对：反例波形见 cex.vcd，引擎日志见 cex.log（构造日期 2026-08-03）
