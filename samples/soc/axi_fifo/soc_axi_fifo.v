// PreCex - SoC 互联场景 2：AXI 写通道 -> FIFO 缓冲
// 功能概述：AXI4-Lite 从机写寄存器 0 事务的 WDATA 低 8 位在 WVALID&&WREADY 拍同时写入同步 FIFO，
//          读端从 FIFO 读回。验证 AXI 写协议与 FIFO 缓冲的协同行为。
module soc_axi_fifo #(
    parameter ADDR_W = 4,
    parameter DATA_W = 32,
    parameter FIFO_DEPTH = 8
) (
    input  wire                   ACLK,
    input  wire                   ARESETN,
    input  wire [ADDR_W-1:0]      S_AXI_AWADDR,
    input  wire                   S_AXI_AWVALID,
    output wire                   S_AXI_AWREADY,
    input  wire [DATA_W-1:0]      S_AXI_WDATA,
    input  wire [DATA_W/8-1:0]    S_AXI_WSTRB,
    input  wire                   S_AXI_WVALID,
    output wire                   S_AXI_WREADY,
    output wire [1:0]             S_AXI_BRESP,
    output wire                   S_AXI_BVALID,
    input  wire                   S_AXI_BREADY,
    input  wire [ADDR_W-1:0]      S_AXI_ARADDR,
    input  wire                   S_AXI_ARVALID,
    output wire                   S_AXI_ARREADY,
    output wire [DATA_W-1:0]      S_AXI_RDATA,
    output wire [1:0]             S_AXI_RRESP,
    output wire                   S_AXI_RVALID,
    input  wire                   S_AXI_RREADY,
    // FIFO 读侧
    input  wire                   fifo_rd_en,
    output wire [7:0]             fifo_dout,
    output wire                   fifo_full,
    output wire                   fifo_empty,
    output wire                   fifo_half_full
);

    wire fifo_wr_ev;
    wire [7:0] fifo_din;

    axi_lite_slave #(
        .ADDR_W(ADDR_W),
        .DATA_W(DATA_W)
    ) u_axi (
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

    // AXI 写 reg0 事务：WVALID&&WREADY 且地址译码为 0 时，把 WDATA 低 8 位写入 FIFO
    assign fifo_wr_ev = S_AXI_WVALID && S_AXI_WREADY && (S_AXI_AWADDR[ADDR_W-1:2] == 0);
    assign fifo_din  = S_AXI_WDATA[7:0];

    fifo_sync #(
        .DATA_W(8),
        .DEPTH (FIFO_DEPTH)
    ) u_fifo (
        .clk       (ACLK),
        .rst_n     (ARESETN),
        .wr_en     (fifo_wr_ev),
        .rd_en     (fifo_rd_en),
        .din       (fifo_din),
        .dout      (fifo_dout),
        .full      (fifo_full),
        .empty     (fifo_empty),
        .half_full (fifo_half_full)
    );

endmodule