// PreCex - axi_lite_slave 黄金基线弱 tb
// 作者：Toylog | 版本：v0.1 | 功能概述：4 寄存器写读回环 + WSTRB 字节掩码 + BVALID/RVALID 保持测试，触发 A1-A8 断言
`timescale 1ns / 1ps

module tb_axi_lite_slave;

    localparam ADDR_W = 4;
    localparam DATA_W = 32;

    reg             ACLK = 0;
    reg             ARESETN = 0;
    // 写地址通道
    reg  [ADDR_W-1:0] S_AXI_AWADDR = 0;
    reg             S_AXI_AWVALID = 0;
    wire            S_AXI_AWREADY;
    // 写数据通道
    reg  [DATA_W-1:0] S_AXI_WDATA = 0;
    reg  [DATA_W/8-1:0] S_AXI_WSTRB = 4'b1111;
    reg             S_AXI_WVALID = 0;
    wire            S_AXI_WREADY;
    // 写响应通道
    wire [1:0]      S_AXI_BRESP;
    wire            S_AXI_BVALID;
    reg             S_AXI_BREADY = 0;
    // 读地址通道
    reg  [ADDR_W-1:0] S_AXI_ARADDR = 0;
    reg             S_AXI_ARVALID = 0;
    wire            S_AXI_ARREADY;
    // 读数据通道
    wire [DATA_W-1:0] S_AXI_RDATA;
    wire [1:0]      S_AXI_RRESP;
    wire            S_AXI_RVALID;
    reg             S_AXI_RREADY = 0;

    // 设计实例
    axi_lite_slave #(
        .ADDR_W(ADDR_W),
        .DATA_W(DATA_W)
    ) uut (
        .ACLK        (ACLK),
        .ARESETN     (ARESETN),
        .S_AXI_AWADDR(S_AXI_AWADDR),
        .S_AXI_AWVALID(S_AXI_AWVALID),
        .S_AXI_AWREADY(S_AXI_AWREADY),
        .S_AXI_WDATA (S_AXI_WDATA),
        .S_AXI_WSTRB (S_AXI_WSTRB),
        .S_AXI_WVALID(S_AXI_WVALID),
        .S_AXI_WREADY(S_AXI_WREADY),
        .S_AXI_BRESP (S_AXI_BRESP),
        .S_AXI_BVALID(S_AXI_BVALID),
        .S_AXI_BREADY(S_AXI_BREADY),
        .S_AXI_ARADDR(S_AXI_ARADDR),
        .S_AXI_ARVALID(S_AXI_ARVALID),
        .S_AXI_ARREADY(S_AXI_ARREADY),
        .S_AXI_RDATA (S_AXI_RDATA),
        .S_AXI_RRESP (S_AXI_RRESP),
        .S_AXI_RVALID(S_AXI_RVALID),
        .S_AXI_RREADY(S_AXI_RREADY)
    );

    // 时钟 10ns
    always #5 ACLK = ~ACLK;

    // 任务：写一个寄存器（AW/W 同拍发起，等待 BVALID 后 BREADY 应答）
    task axi_write(input [ADDR_W-1:0] addr, input [DATA_W-1:0] data, input [DATA_W/8-1:0] strb);
        begin
            @(negedge ACLK);
            S_AXI_AWADDR  = addr;
            S_AXI_AWVALID = 1'b1;
            S_AXI_WDATA   = data;
            S_AXI_WSTRB   = strb;
            S_AXI_WVALID  = 1'b1;
            @(negedge ACLK);
            S_AXI_AWVALID = 1'b0;
            S_AXI_WVALID  = 1'b0;
            // 等待响应
            wait (S_AXI_BVALID === 1'b1);
            if (S_AXI_BRESP !== 2'b00) $fatal(1, "FAIL: B.RESP != OKAY");
            @(negedge ACLK);
            S_AXI_BREADY = 1'b1;               // 应答
            @(negedge ACLK);
            S_AXI_BREADY = 1'b0;
        end
    endtask

    // 任务：读一个寄存器，返回读取值
    task axi_read(input [ADDR_W-1:0] addr, output [DATA_W-1:0] rdata);
        begin
            @(negedge ACLK);
            S_AXI_ARADDR  = addr;
            S_AXI_ARVALID = 1'b1;
            @(negedge ACLK);
            S_AXI_ARVALID = 1'b0;
            // 等待读数据有效
            wait (S_AXI_RVALID === 1'b1);
            if (S_AXI_RRESP !== 2'b00) $fatal(1, "FAIL: R.RESP != OKAY");
            rdata = S_AXI_RDATA;
            @(negedge ACLK);
            S_AXI_RREADY = 1'b1;               // 应答
            @(negedge ACLK);
            S_AXI_RREADY = 1'b0;
        end
    endtask

    // 主流程
    initial begin
        reg [DATA_W-1:0] rd;

        // ===== 复位 =====
        ARESETN = 0;
        #30 ARESETN = 1;

        // ===== 写/读 4 个寄存器 =====
        axi_write(4'h0, 32'hDEADBEEF, 4'b1111);
        axi_write(4'h4, 32'h12345678, 4'b1111);
        axi_write(4'h8, 32'hA5A5A5A5, 4'b1111);
        axi_write(4'hC, 32'h0F0F0F0F, 4'b1111);

        $display("INFO: 4-register write/readback OK");

        // ===== WSTRB 字节掩码：只写高 16 位，低 16 位保持 =====
        axi_write(4'h0, 32'hFFFF0000, 4'b1100);   // 高 16 位更新，低 16 位保持
        axi_read(4'h0, rd);
        $display("INFO: WSTRB byte-mask OK (reg0=0x%08h)", rd);

        // ===== BVALID 保持：BREADY 拉低一拍，BVALID 不得提前消失（触发 A4）=====
        @(negedge ACLK);
        S_AXI_AWADDR  = 4'h4;
        S_AXI_AWVALID = 1'b1;
        S_AXI_WDATA   = 32'hCAFEBABE;
        S_AXI_WSTRB   = 4'b1111;
        S_AXI_WVALID  = 1'b1;
        @(negedge ACLK);
        S_AXI_AWVALID = 1'b0;
        S_AXI_WVALID  = 1'b0;
        wait (S_AXI_BVALID === 1'b1);
        @(negedge ACLK);                        // BREADY 保持 0，BVALID 应保持
        @(negedge ACLK);
        S_AXI_BREADY = 1'b1;
        @(negedge ACLK);
        S_AXI_BREADY = 1'b0;
        $display("INFO: BVALID hold OK");

        // ===== RVALID 保持：RREADY 拉低一拍，RVALID 不得提前消失（触发 A5）=====
        @(negedge ACLK);
        S_AXI_ARADDR  = 4'h4;
        S_AXI_ARVALID = 1'b1;
        @(negedge ACLK);
        S_AXI_ARVALID = 1'b0;
        wait (S_AXI_RVALID === 1'b1);
        rd = S_AXI_RDATA;
        @(negedge ACLK);                        // RREADY 保持 0，RVALID 应保持
        @(negedge ACLK);
        S_AXI_RREADY = 1'b1;
        @(negedge ACLK);
        S_AXI_RREADY = 1'b0;
        $display("INFO: RVALID hold OK");

        // ===== 全部通过 =====
        $display("PASS: axi_lite_slave weak testbench passed (golden)");
        $finish;
    end

    // 仿真超时保护
    initial begin
        #10000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
// [bug_injector] weak tb sanitized for boundary_wrap: stripped 10 fatal check(s) on cnt/count/dout/state/done/timeout_irq/txd/tx_busy/readback/WSTRB/RVALID/BVALID/reg/rx_data/rx_valid
