// PreCex - axi_lite_slave 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：AXI4-Lite 从机（AW/W/AR/B/R 五通道握手 + 4 个 32 位寄存器读写，WSTRB 字节掩码）
// 说明：可综合风格；写通道一拍应答（AWREADY/WREADY），BVALID 待 AW/W 完成后置位并保持至 BREADY；
//       读通道 ARREADY 一拍应答，RVALID 置位并保持至 RREADY，RDATA 由锁存地址译码

module axi_lite_slave #(
    parameter ADDR_W = 4,             // 地址位宽（低 2 位为字节偏移，[ADDR_W-1:2] 译码 4 个寄存器）
    parameter DATA_W = 32             // 数据位宽
) (
    input  wire                   ACLK,        // 总线时钟
    input  wire                   ARESETN,     // 总线复位（低有效）
    // ---- 写地址通道 ----
    input  wire [ADDR_W-1:0]       S_AXI_AWADDR,
    input  wire                   S_AXI_AWVALID,
    output reg                    S_AXI_AWREADY,
    // ---- 写数据通道 ----
    input  wire [DATA_W-1:0]       S_AXI_WDATA,
    input  wire [DATA_W/8-1:0]     S_AXI_WSTRB,
    input  wire                   S_AXI_WVALID,
    output reg                    S_AXI_WREADY,
    // ---- 写响应通道 ----
    output reg  [1:0]              S_AXI_BRESP,
    output reg                    S_AXI_BVALID,
    input  wire                   S_AXI_BREADY,
    // ---- 读地址通道 ----
    input  wire [ADDR_W-1:0]       S_AXI_ARADDR,
    input  wire                   S_AXI_ARVALID,
    output reg                    S_AXI_ARREADY,
    // ---- 读数据通道 ----
    output reg  [DATA_W-1:0]       S_AXI_RDATA,
    output reg  [1:0]              S_AXI_RRESP,
    output reg                    S_AXI_RVALID,
    input  wire                   S_AXI_RREADY
);

    // 内部握手状态
    reg [ADDR_W-1:0] aw_addr;                // 写地址锁存
    reg [ADDR_W-1:0] ar_addr;                // 读地址锁存
    reg              aw_done;                // 写地址已应答
    reg              w_done;                 // 写数据已应答

    // 4 个 32 位寄存器（地址 0x0/0x4/0x8/0xC）
    reg [DATA_W-1:0] reg0, reg1, reg2, reg3;

    // 按字节掩码写函数
    function [DATA_W-1:0] mask_write(input [DATA_W-1:0] old_d,
                                     input [DATA_W-1:0] new_d,
                                     input [DATA_W/8-1:0] strb);
        integer i;
        begin
            for (i = 0; i < DATA_W/8; i = i + 1) begin
                mask_write[i*8 +: 8] = strb[i] ? new_d[i*8 +: 8] : old_d[i*8 +: 8];
            end
        end
    endfunction

    // ---- 写地址通道：一拍应答，完成写事务后释放 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_AWREADY <= 1'b0;
            aw_done       <= 1'b0;
            aw_addr       <= {ADDR_W{1'b0}};
        end else if (S_AXI_AWVALID && !aw_done) begin
            S_AXI_AWREADY <= 1'b1;             // 应答一拍
            aw_done       <= 1'b1;
            aw_addr       <= S_AXI_AWADDR;
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            S_AXI_AWREADY <= 1'b0;             // 事务完成，释放
            aw_done       <= 1'b0;
        end else begin
            S_AXI_AWREADY <= 1'b0;             // 默认清零，确保只应答一拍
        end
    end

    // ---- 写数据通道：一拍应答，完成写事务后释放 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_WREADY <= 1'b0;
            w_done       <= 1'b0;
        end else if (S_AXI_WVALID && !w_done) begin
            S_AXI_WREADY <= 1'b1;              // 应答一拍
            w_done       <= 1'b1;
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            S_AXI_WREADY <= 1'b0;              // 事务完成，释放
            w_done       <= 1'b0;
        end else begin
            S_AXI_WREADY <= 1'b0;              // 默认清零，确保只应答一拍
        end
    end

    // ---- 寄存器写入：WVALID 且通道空闲（!w_done）时按字节掩码写入选中的寄存器 ----
    // 注意：写入条件用 !w_done 而非 WREADY（WREADY 是滞后一拍的应答输出，会导致写入永远错过）
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            reg0 <= {DATA_W{1'b0}};
            reg1 <= {DATA_W{1'b0}};
            reg2 <= {DATA_W{1'b0}};
            reg3 <= {DATA_W{1'b0}};
        end else if (S_AXI_WVALID && !w_done) begin
            case (S_AXI_AWADDR[ADDR_W-1:2])
                2'd0: reg0 <= mask_write(reg0, S_AXI_WDATA, S_AXI_WSTRB);
                2'd1: reg1 <= mask_write(reg1, S_AXI_WDATA, S_AXI_WSTRB);
                2'd2: reg2 <= mask_write(reg2, S_AXI_WDATA, S_AXI_WSTRB);
                2'd3: reg3 <= mask_write(reg3, S_AXI_WDATA, S_AXI_WSTRB);
            endcase
        end
    end

    // ---- 写响应通道：AW/W 均完成后置位，保持至 BREADY ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_BVALID <= 1'b0;
            S_AXI_BRESP  <= 2'b00;
        end else if (aw_done && w_done && !S_AXI_BVALID) begin
            S_AXI_BVALID <= 1'b1;
            S_AXI_BRESP  <= 2'b00;             // OKAY
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            S_AXI_BVALID <= 1'b0;
        end
    end

    // ---- 读地址通道：一拍应答 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_ARREADY <= 1'b0;
            ar_addr       <= {ADDR_W{1'b0}};
        end else if (S_AXI_ARVALID && !S_AXI_RVALID) begin
            S_AXI_ARREADY <= 1'b1;             // 应答一拍
            ar_addr       <= S_AXI_ARADDR;
        end else begin
            S_AXI_ARREADY <= 1'b0;
        end
    end

    // ---- 读数据通道：RVALID 置位保持至 RREADY，RDATA 按锁存地址译码 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_RVALID <= 1'b0;
            S_AXI_RDATA  <= {DATA_W{1'b0}};
            S_AXI_RRESP  <= 2'b00;
        end else if (S_AXI_ARVALID && !S_AXI_RVALID) begin
            S_AXI_RVALID <= 1'b1;
            S_AXI_RRESP  <= 2'b00;             // OKAY
            case (S_AXI_ARADDR[ADDR_W-1:2])
                2'd0: S_AXI_RDATA <= reg0;
                2'd1: S_AXI_RDATA <= reg1;
                2'd2: S_AXI_RDATA <= reg2;
                2'd3: S_AXI_RDATA <= reg3;
            endcase
        end else if (S_AXI_RVALID && S_AXI_RREADY) begin
            S_AXI_RVALID <= 1'b0;
        end
    end

endmodule
