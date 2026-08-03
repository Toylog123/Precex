# fsm_ctrl — 状态机序列控制器黄金基线

> 作者：Toylog | 版本：v0.1 | 功能概述：3 阶段序列控制器（S1/S2/S3 分级停留 + 异常跳转 + 全局超时保护）接口文档

## 端口

| 端口 | 方向 | 位宽 | 说明 |
|------|------|------|------|
| `clk` | input | 1 | 时钟 |
| `rst_n` | input | 1 | 异步复位（低有效） |
| `start` | input | 1 | 启动脉冲（单拍，仅在 IDLE 生效） |
| `data_in` | input | 8 | 条件输入（`0xAA` 卡 S1 等待 / `0xFF` 在 S2 异常跳回） |
| `done` | output | 1 | 序列完成脉冲（单拍，S3 停留满后产生） |
| `timeout_irq` | output | 1 | 超时中断脉冲（单拍，非空闲超 `TIMEOUT` 步后产生） |
| `state` | output | 2 | 当前状态（`0`=IDLE `1`=S1 `2`=S2 `3`=S3，观测/断言用） |

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `TIMEOUT` | 32 | 全局超时步数（进入非空闲后开始计数，步数达阈值触发超时） |
| `S1_HOLD` | 2 | S1 停留拍数 |
| `S2_HOLD` | 3 | S2 停留拍数 |
| `S3_HOLD` | 2 | S3 停留拍数 |

## 功能描述

- 状态流：`IDLE → S1(停 S1_HOLD 拍) → S2(停 S2_HOLD 拍) → S3(停 S3_HOLD 拍) → done`。
- **异常处理**：S1 期间 `data_in == 0xAA` 时停留等待（触发全局超时保护）；S2 期间 `data_in == 0xFF` 时异常跳回 IDLE（提前终止，不产生 done）。
- **超时保护**：自 `start` 后（非空闲状态）每拍 `step_cnt + 1`，`step_cnt >= TIMEOUT` 时跳回 IDLE 并产生单拍 `timeout_irq`。
- `done` / `timeout_irq` 均为单拍脉冲，默认每拍清零；`start` 在非 IDLE 状态下被忽略。

## 断言覆盖的性质清单（assertions.sv，安全子集写法）

| 编号 | 性质 | 实现方式 |
|------|------|----------|
| A1 | 状态跳转合法性：`(state_d, state)` 必须属于合法集合（含自环）：IDLE→{IDLE,S1}、S1→{S1,S2,IDLE}、S2→{S2,S3,IDLE}、S3→{S3,IDLE} | `state` 打拍 + case 门控 `assert` |
| A2 | done 前置与单拍：done 仅在 `state==S3 && hold_cnt==S3_HOLD` 时产生；上一拍 done 有效则本拍必须清除 | `done` 打拍 + 门控 `assert` |
| A3 | timeout_irq 前置与单拍：仅在 `state!=IDLE && step_cnt>=TIMEOUT` 时产生；上一拍有效则本拍必须清除；与 done 互斥 | `timeout_irq` 打拍 + 门控 `assert` |
| A4 | 停留拍数上界：S1/S2/S3 内 `hold_cnt` 分别不超过 S1_HOLD/S2_HOLD/S3_HOLD（0xAA 卡住时保持不越界） | 按 `state` case 门控 `assert` |
| A5 | 启动语义：空闲时 `start` 生效后一拍必须进入 S1（非空闲忽略由 A1 覆盖） | `start` 打拍 + 门控 `assert` |
| A6 | 步进计数单调性：非空闲阶段 `step_cnt` 每拍 +1；空闲阶段清零 | `step_cnt` 打拍比较 |

## 编译与仿真

```bash
cd /mnt/d/BaiduSyncdisk/02_Precex/rtl/fsm_ctrl
iverilog -g2012 fsm_ctrl.sv assertions.sv tb_fsm_ctrl.sv -o tb_out && vvp tb_out
# 期望：PASS: fsm_ctrl weak testbench passed (golden)，无 ERROR/FAIL
```

## 综合检查

```bash
yosys -p "read_verilog -sv fsm_ctrl.sv; prep -top fsm_ctrl"
# 期望：无 ERROR
```
