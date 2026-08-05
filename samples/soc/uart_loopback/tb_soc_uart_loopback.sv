// PreCex - SoC 互联场景 1 tb：UART 回环数据完整性
`timescale 1ns / 1ps
module tb_soc_uart_loopback;

    localparam CLK_FREQ = 50000000;
    localparam BAUD     = 115200;
    localparam DATA_W   = 8;
    localparam DIV      = CLK_FREQ / BAUD;

    reg              clk      = 0;
    reg              rst_n    = 0;
    reg              tx_start = 0;
    reg  [DATA_W-1:0] tx_data = 0;
    wire             txd;
    wire             tx_busy;
    wire             rx_valid;
    wire [DATA_W-1:0] rx_data;
    wire             rx_busy;

    integer          send_cnt = 0;
    integer          recv_cnt = 0;
    reg  [DATA_W-1:0] exp0 = 8'hA5;
    reg  [DATA_W-1:0] exp1 = 8'h5A;
    reg  [DATA_W-1:0] got0 = 0;
    reg  [DATA_W-1:0] got1 = 0;

    soc_uart_loopback #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD    (BAUD),
        .DATA_W  (DATA_W)
    ) uut (
        .clk     (clk),
        .rst_n   (rst_n),
        .tx_start(tx_start),
        .tx_data (tx_data),
        .txd     (txd),
        .tx_busy (tx_busy),
        .rx_valid(rx_valid),
        .rx_data (rx_data),
        .rx_busy (rx_busy)
    );

    always #5 clk = ~clk;

    initial begin
        // 复位
        rst_n = 0;
        repeat (5) @(posedge clk);
        rst_n = 1;

        // 帧 1
        @(posedge clk);
        tx_data  = exp0;
        tx_start = 1;
        @(posedge clk);
        tx_start = 0;
        send_cnt = 1;
        repeat (10 * DIV + 80) @(posedge clk);

        // 帧 2
        @(posedge clk);
        tx_data  = exp1;
        tx_start = 1;
        @(posedge clk);
        tx_start = 0;
        send_cnt = 2;
        repeat (10 * DIV + 80) @(posedge clk);

        // 等待接收完成
        wait (recv_cnt >= 2);
        if (got0 === exp0 && got1 === exp1) begin
            $display("SOC_UART_LOOPBACK PASS");
        end else begin
            $display("SOC_UART_LOOPBACK FAIL: got=%h,%h exp=%h,%h", got0, got1, exp0, exp1);
            $fatal(1, "soc loopback data mismatch");
        end
        $finish;
    end

    always @(posedge clk) begin
        if (rx_valid) begin
            if (recv_cnt == 0) begin
                got0 = rx_data;
                recv_cnt = 1;
            end else if (recv_cnt == 1) begin
                got1 = rx_data;
                recv_cnt = 2;
            end
        end
    end

endmodule