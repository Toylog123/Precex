# axi_lite_slave — AXI4-Lite 从机黄金基线

> 作者：Toylog | 版本：v0.1 | 功能概述：AXI4-Lite 从机（五通道握手 + 4 个 32 位寄存器，WSTRB 字节掩码）接口文档

## 端口

| 端口 | 方向 | 位宽 | 说明 |
|------|------|------|------|
| `ACLK` | input | 1 | 总线时钟 |
| `ARESETN` | input | 1 | 总线复位（低有效） |
| `S_AXI_AWADDR` / `S_AXI_AWVALID` / `S_AXI_AWREADY` | in/in/out | ADDR_W/1/1 | 写地址通道（一拍应答） |
| `S_AXI_WDATA` / `S_AXI_WSTRB` / `S_AXI_WVALID` / `S_AXI_WREADY` | in/in/in/out | DATA_W/4/1/1 | 写数据通道（一拍应答 + 字节掩码） |
| `S_AXI_BRESP` / `S_AXI_BVALID` / `S_AXI_BREADY` | out/out/in | 2/1/1 | 写响应通道（保持至 BREADY） |
| `S_AXI_ARADDR` / `S_AXI_ARVALID` / `S_AXI_ARREADY` | in/in/out | ADDR_W/1/1 | 读地址通道（一拍应答） |
| `S_AXI_RDATA` / `S_AXI_RRESP` / `S_AXI_RVALID` / `S_AXI_RREADY` | out/out/out/in | DATA_W/2/1/1 | 读数据通道（保持至 RREADY） |

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ADDR_W` | 4 | 地址位宽（`[ADDR_W-1:2]` 译码 4 个寄存器） |
| `DATA_W` | 32 | 数据位宽 |

## 功能描述

- 4 个 32 位寄存器：地址 `0x0/0x4/0x8/0xC`（reg0..reg3）。
- 写事务：AW/W 一拍应答（`AWREADY`/`WREADY` 各高 1 拍），AW/W 均完成后 `BVALID` 置位并保持至 `BREADY`，随后释放通道。
- `WSTRB` 按字节掩码写入（`mask_write` 函数，`WSTRB[i]` 控制第 i 字节）。
- 读事务：`ARREADY` 一拍应答，`RVALID` 置位并保持至 `RREADY`，`RDATA` 由锁存地址译码；响应 `RESP=OKAY`。

## 断言覆盖的性质清单（assertions.sv，安全子集写法）

| 编号 | 性质 | 实现方式 |
|------|------|----------|
| A1 | AWREADY 一拍应答：`aw_done` 期间 `AWREADY` 必须为 0 | 门控 `assert` |
| A2 | WREADY 一拍应答：`w_done` 期间 `WREADY` 必须为 0 | 门控 `assert` |
| A3 | BVALID 前置：`BVALID` 有效时 `aw_done && w_done` 必须均成立 | 门控 `assert` |
| A4 | BVALID 保持：上周期有效且无 `BREADY` 时必须仍有效 | `bvalid` 打拍 |
| A5 | RVALID 保持：上周期有效且无 `RREADY` 时必须仍有效 | `rvalid` 打拍 |
| A6 | 读数据译码：`RVALID` 时 `RDATA` 等于 `ar_addr` 选中寄存器 | 译码门控 `assert` |
| A7 | 写数据生效：`BVALID` 时最近写入寄存器等于写数据（跨周期打拍） | `wdata`/`waddr` 打拍 |
| A8 | 复位输出：`ARESETN` 无效期间所有 valid/ready 为 0 | 复位门控 `assert` |

## 编译与仿真

```bash
cd /mnt/d/BaiduSyncdisk/02_Precex/rtl/axi_lite_slave
iverilog -g2012 axi_lite_slave.sv assertions.sv tb_axi_lite_slave.sv -o tb_out && vvp tb_out
# 期望：PASS: axi_lite_slave weak testbench passed (golden)，无 ERROR/FAIL
```

## 综合检查

```bash
yosys -p "read_verilog -sv axi_lite_slave.sv; prep -top axi_lite_slave"
# 期望：无 ERROR
```
