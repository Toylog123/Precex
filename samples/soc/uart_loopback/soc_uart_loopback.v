// PreCex - SoC 互联场景 1：UART 回环（uart_tx -> uart_rx）
// 功能概述：发射机 txd 直接连接收机 rxd，构成片内回环。顶层不做逻辑，仅互联 + 端口透出。
// 说明：可综合风格；参数 CLK_FREQ/BAUD 两端对齐。
module soc_uart_loopback #(
    parameter CLK_FREQ = 50000000,
    parameter BAUD     = 115200,
    parameter DATA_W   = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             tx_start,
    input  wire [DATA_W-1:0] tx_data,
    output wire             txd,
    output wire             tx_busy,
    output wire             rx_valid,
    output wire [DATA_W-1:0] rx_data,
    output wire             rx_busy
);

    wire txd_w;

    uart_tx #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD    (BAUD),
        .DATA_W  (DATA_W)
    ) u_tx (
        .clk     (clk),
        .rst_n   (rst_n),
        .tx_start(tx_start),
        .tx_data (tx_data),
        .txd     (txd_w),
        .tx_busy (tx_busy)
    );

    uart_rx #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD    (BAUD),
        .DATA_W  (DATA_W)
    ) u_rx (
        .clk     (clk),
        .rst_n   (rst_n),
        .rxd     (txd_w),
        .rx_valid(rx_valid),
        .rx_data (rx_data),
        .rx_busy (rx_busy)
    );

    assign txd = txd_w;

endmodule