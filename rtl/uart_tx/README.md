# uart_tx — UART 发射机黄金基线

> 作者：Toylog | 版本：v0.1 | 功能概述：UART 发射机（8N1 帧格式 + 波特率分频）接口文档

## 端口

| 端口 | 方向 | 位宽 | 说明 |
|------|------|------|------|
| `clk` | input | 1 | 系统时钟 |
| `rst_n` | input | 1 | 异步复位（低有效） |
| `tx_start` | input | 1 | 发送启动脉冲（单拍有效，空闲状态接受） |
| `tx_data` | input | `DATA_W` | 待发送数据（启动拍采样） |
| `txd` | output | 1 | 串行输出（空闲为高） |
| `tx_busy` | output | 1 | 发送忙标志（帧内为高） |

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CLK_FREQ` | 50000000 | 系统时钟频率（Hz） |
| `BAUD` | 115200 | 波特率 |
| `DATA_W` | 8 | 数据位宽（8N1 固定 8） |

## 功能描述

- 状态机 `IDLE → START → DATA → STOP`；波特率分频系数 `DIV = CLK_FREQ/BAUD`，每位周期持续 `DIV` 个时钟。
- 8N1 帧：1 起始位（低）+ 8 数据位（LSB 先发）+ 1 停止位（高）。
- `tx_busy` 在 `tx_start` 被接受的当拍拉高，帧结束（回到 IDLE）时拉低。

## 断言覆盖的性质清单（assertions.sv，安全子集写法）

| 编号 | 性质 | 实现方式 |
|------|------|----------|
| A1 | 起始位为低：`state == START` 时 `txd == 0` | 状态门控 immediate `assert` |
| A2 | 停止位为高：`state == STOP` 时 `txd == 1` | 状态门控 immediate `assert` |
| A3 | 空闲电平：`state == IDLE` 时 `txd == 1` 且 `tx_busy == 0` | 状态门控 immediate `assert` |
| A4 | 状态机跳转合法性：`(state_d, state)` 必须属于合法跳转集合（含自环）：IDLE→{IDLE,START}、START→{START,DATA}、DATA→{DATA,STOP}、STOP→{STOP,IDLE} | `state` 打拍 + case 门控 `assert` |
| A5 | 忙标志一致：`tx_busy` 有效期间 `state != IDLE` | 门控 immediate `assert` |

## 编译与仿真

```bash
cd /mnt/d/BaiduSyncdisk/02_Precex/rtl/uart_tx
iverilog -g2012 uart_tx.sv assertions.sv tb_uart_tx.sv -o tb_out && vvp tb_out
# 期望：PASS: uart_tx weak testbench passed (golden)，无 ERROR/FAIL
```

## 综合检查

```bash
yosys -p "read_verilog -sv uart_tx.sv; prep -top uart_tx"
# 期望：无 ERROR
```
