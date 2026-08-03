# uart_rx — UART 接收机黄金基线

> 作者：Toylog | 版本：v0.1 | 功能概述：UART 接收机（起始位下降沿检测 + 位周期中点采样）接口文档

## 端口

| 端口 | 方向 | 位宽 | 说明 |
|------|------|------|------|
| `clk` | input | 1 | 系统时钟 |
| `rst_n` | input | 1 | 异步复位（低有效） |
| `rxd` | input | 1 | 串行输入（空闲为高） |
| `rx_valid` | output | 1 | 接收完成脉冲（帧结束一拍） |
| `rx_data` | output | `DATA_W` | 接收数据（LSB 先收） |
| `rx_busy` | output | 1 | 接收忙标志 |

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CLK_FREQ` | 50000000 | 系统时钟频率（Hz） |
| `BAUD` | 115200 | 波特率 |
| `DATA_W` | 8 | 数据位宽 |

## 功能描述

- 状态机 `IDLE → START → DATA → STOP`；分频系数 `DIV = CLK_FREQ/BAUD`。
- 起始位检测：IDLE 中 `rxd` 拉低即进入 START；在 `HALF = DIV/2` 处中点二次采样确认（抗毛刺），为高则回 IDLE。
- 数据位在每位周期中点（`baud_cnt == DIV-1`）采样，LSB 先收。
- 停止位中点校验后输出 `rx_data` 并产生一拍 `rx_valid`；停止位为 0 时仍输出已采数据（容忍帧错误）。

## 断言覆盖的性质清单（assertions.sv，安全子集写法）

| 编号 | 性质 | 实现方式 |
|------|------|----------|
| A1 | 起始位中点毛刺（`rxd==1`）→ 必须回 IDLE | 打拍门控 `assert` |
| A2 | 起始位中点真起始位（`rxd==0`）→ 必须进 DATA | 打拍门控 `assert` |
| A3 | 停止位中点 `rxd` 必须为 1（正常帧） | 状态+计数门控 `assert` |
| A4 | 状态机跳转合法性：IDLE→{IDLE,START}、START→{START,DATA,IDLE}、DATA→{DATA,STOP}、STOP→{STOP,IDLE} | `state` 打拍 + case `assert` |
| A5 | 忙标志一致：`rx_busy` 有效期间 `state != IDLE` | 门控 `assert` |
| A6 | 帧完成脉冲关联：`rx_valid` 置位时上一拍必须处于 STOP | `state` 打拍 + 门控 `assert` |
| A7 | 数据位计数不越界：DATA 内 `bit_cnt < DATA_W` | 状态门控 `assert` |

## 编译与仿真（回环联测）

```bash
cd /mnt/d/BaiduSyncdisk/02_Precex/rtl/uart_rx
# 注意：回环 tb 需要同目录下的 uart_tx.sv（或指定路径）
iverilog -g2012 uart_rx.sv ../uart_tx/uart_tx.sv assertions.sv tb_uart_rx.sv -o tb_out && vvp tb_out
# 期望：PASS: uart_rx weak testbench passed (golden, 5 frames loopback)，无 ERROR/FAIL
```

## 综合检查

```bash
yosys -p "read_verilog -sv uart_rx.sv; prep -top uart_rx"
# 期望：无 ERROR
```
