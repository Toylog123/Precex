# counter_alu — 计数器 + 组合 ALU 黄金基线

> 作者：Toylog | 版本：v0.1 | 功能概述：参数化计数器（使能自增/复位归 0/满值回绕）+ 组合 ALU（add/sub/and/or/xor 5 种运算）接口文档

## 端口

| 端口 | 方向 | 位宽 | 说明 |
|------|------|------|------|
| `clk` | input | 1 | 时钟 |
| `rst_n` | input | 1 | 异步复位（低有效），复位归 0 |
| `cnt_en` | input | 1 | 计数器使能（1：自增 1；0：保持） |
| `op` | input | `OP_W` | ALU 运算选择（0=add 1=sub 2=and 3=or 4=xor，其余安全归 xor） |
| `a` | input | `DATA_W` | ALU 输入 a |
| `b` | input | `DATA_W` | ALU 输入 b |
| `cnt` | output | `DATA_W` | 计数器值（复位归 0，使能时 +1，模 `2^DATA_W` 自然回绕） |
| `alu_out` | output | `DATA_W` | ALU 组合输出（纯组合，输入变化当拍生效） |

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `DATA_W` | 8 | 计数器/ALU 数据位宽 |
| `OP_W` | 3 | 运算选择位宽（有效值 0..4，共 5 种运算） |

## 功能描述

- **计数器**：异步复位归 0；`cnt_en` 为 1 时每拍 `+1`，为 0 时保持；满值（全 1）再使能时自然回绕为 0（模 `2^DATA_W` 计数）。
- **组合 ALU**：纯 `assign` 三元链实现，无锁存；非法 `op`（5..7）统一安全归为 xor，避免 X/锁存。
- 计数器与 ALU 相互独立，`cnt` 不参与 ALU 运算（`alu_out` 仅由 `a/b/op` 决定）。

## 断言覆盖的性质清单（assertions.sv，安全子集写法）

| 编号 | 性质 | 实现方式 |
|------|------|----------|
| A1 | 计数器仅在使能时自增：上周期 `cnt_en` → 本周期 `cnt == cnt_d + 1`（防漏计） | `cnt_en`/`cnt` 打拍 + 门控 `assert` |
| A2 | 计数器未使能时保持：上周期 `!cnt_en` → 本周期 `cnt == cnt_d`（防多计） | `cnt_en`/`cnt` 打拍 + 门控 `assert` |
| A3 | 复位释放后归 0：上周期复位中（`!rst_n_d`）且本周期释放 → `cnt == 0` | `rst_n` 打拍 + 门控 `assert` |
| A4 | ALU 输出正确性：`alu_out`（打拍）== `alu_ref(op, a, b)` 参考模型（add/sub/and/or/xor） | `op/a/b/alu_out` 四路打拍 + `assert` |
| A5 | 运算选择不越界：`op` 恒为有效运算（`< OP_NUM=5`） | 每周期 immediate `assert` |
| A6 | 计数器满值回绕：上周期 `cnt==全 1` 且使能 → 本周期 `cnt == 0`（模 `2^DATA_W`） | `cnt` 打拍 + 门控 `assert` |

## 编译与仿真

```bash
cd /mnt/d/BaiduSyncdisk/02_Precex/rtl/counter_alu
iverilog -g2012 counter_alu.sv assertions.sv tb_counter_alu.sv -o tb_out && vvp tb_out
# 期望：PASS: counter_alu weak testbench passed (golden)，无 ERROR/FAIL
```

## 综合检查

```bash
yosys -p "read_verilog -sv counter_alu.sv; prep -top counter_alu"
# 期望：无 ERROR
```
