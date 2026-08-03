# fifo_sync — 同步 FIFO 黄金基线

> 作者：Toylog | 版本：v0.1 | 功能概述：参数化同步 FIFO（读优先语义）接口文档

## 端口

| 端口 | 方向 | 位宽 | 说明 |
|------|------|------|------|
| `clk` | input | 1 | 时钟 |
| `rst_n` | input | 1 | 异步复位（低有效） |
| `wr_en` | input | 1 | 写使能 |
| `rd_en` | input | 1 | 读使能 |
| `din` | input | `DATA_W` | 写数据 |
| `dout` | output | `DATA_W` | 读数据（读使能上升沿后一拍有效） |
| `full` | output | 1 | 满标志（`count == DEPTH`） |
| `empty` | output | 1 | 空标志（`count == 0`） |
| `half_full` | output | 1 | 半满标志（`count >= DEPTH/2`） |

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `DATA_W` | 8 | 数据位宽 |
| `DEPTH` | 8 | FIFO 深度（建议 2 的幂） |

## 功能描述

- 同步 FIFO，读写指针按模 `DEPTH` 回绕；内部用 `count`（元素计数）判定满/空，杜绝指针回绕错。
- **读优先语义**：同拍读写时 `count` 守恒不变；满时写被拒绝、空时读被拒绝。
- 读操作一拍延迟：`rd_en` 上升沿采样后 `dout` 更新为对应存储内容。

## 断言覆盖的性质清单（assertions.sv，安全子集写法）

| 编号 | 性质 | 实现方式 |
|------|------|----------|
| A1 | 满时不写：上周期 `full` 且上周期 `wr_en` → 写被拒绝，本周期 `count` 保持 `DEPTH`（防溢出/回绕） | `full`/`wr_en` 打拍 + 门控 `assert` |
| A2 | 空时不读：上周期 `empty` 且上周期 `rd_en` → 读被拒绝，本周期 `count` 保持 0（防下溢） | `empty`/`rd_en` 打拍 + 门控 `assert` |
| A3 | 指针永不越界：`head`/`tail` 恒 `< DEPTH` | 每周期 immediate `assert` |
| A4 | count 增量守恒：每周期 `count` 变化量 = `can_wr - can_rd`（两拍打拍比较） | `count`/`delta` 打拍 |
| A5 | 半满标志正确性：`half_full == (count >= DEPTH/2)` | 每周期 immediate `assert` |

## 编译与仿真

```bash
cd /mnt/d/BaiduSyncdisk/02_Precex/rtl/fifo_sync
iverilog -g2012 fifo_sync.sv assertions.sv tb_fifo_sync.sv -o tb_out && vvp tb_out
# 期望：PASS: fifo_sync weak testbench passed (golden)，无 ERROR/FAIL
```

## 综合检查

```bash
yosys -p "read_verilog -sv fifo_sync.sv; prep -top fifo_sync"
# 期望：无 ERROR
```
