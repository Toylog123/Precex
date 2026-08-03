// PreCex - uart_rx 黄金基线弱 tb（与 uart_tx 回环联测）
// 作者：Toylog | 版本：v0.1 | 功能概述：tx 发送多帧 → rx 接收回环，验证 rx_data/rx_valid 与帧格式，触发 A1-A7 断言
`timescale 1ns / 1ps

module tb_uart_rx;

    localparam CLK_FREQ = 50000000;
    localparam BAUD     = 115200;
    localparam DATA_W   = 8;

    reg              clk      = 0;
    reg              rst_n    = 0;
    reg              tx_start = 0;
    reg  [DATA_W-1:0] tx_data = 0;
    wire             rxd;                     // tx 输出直接接 rx 输入
    wire             tx_busy;                 // tx 忙标志（帧间同步用）
    wire             rx_valid;
    wire [DATA_W-1:0] rx_data;
    wire             rx_busy;

    integer frame_cnt = 0;
    reg [DATA_W-1:0] expect_data;

    // 发射机实例
    uart_tx #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD    (BAUD),
        .DATA_W  (DATA_W)
    ) u_tx (
        .clk     (clk),
        .rst_n   (rst_n),
        .tx_start(tx_start),
        .tx_data (tx_data),
        .txd     (rxd),
        .tx_busy (tx_busy)
    );

    // 接收机实例
    uart_rx #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD    (BAUD),
        .DATA_W  (DATA_W)
    ) uut (
        .clk     (clk),
        .rst_n   (rst_n),
        .rxd     (rxd),
        .rx_valid(rx_valid),
        .rx_data (rx_data),
        .rx_busy (rx_busy)
    );

    // 断言实例：内部信号分层引用接入（注意接收机实例名必须为 uut）
    uart_rx_assert #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD    (BAUD),
        .DATA_W  (DATA_W)
    ) u_assert (
        .clk      (clk),
        .rst_n    (rst_n),
        .rxd      (rxd),
        .rx_valid (rx_valid),
        .rx_data  (rx_data),
        .rx_busy  (rx_busy),
        .state    (uut.state),
        .baud_cnt (uut.baud_cnt),
        .bit_cnt  (uut.bit_cnt)
    );

    // 时钟 10ns
    always #5 clk = ~clk;

    // 任务：发送一帧并等待接收完成，比对 rx_data
    task send_and_check(input [DATA_W-1:0] data);
        begin
            expect_data = data;
            // 等待上一帧发送完全结束（tx 回空闲）再发下一帧
            // （rx 帧周期比 tx 短约半个位周期，若不等待会与 tx 忙冲突）
            wait (tx_busy === 1'b0);
            // 发起发送
            @(negedge clk);
            tx_start = 1'b1;
            tx_data  = data;
            @(negedge clk);
            tx_start = 1'b0;
            // 等待接收完成脉冲
            wait (rx_valid === 1'b1);
            @(negedge clk);                   // 等待数据稳定
            if (rx_data !== expect_data) begin
                $fatal(1, "FAIL: rx_data mismatch, expect %0h got %0h", expect_data, rx_data);
            end
            frame_cnt = frame_cnt + 1;
            $display("INFO: frame %0d (0x%02h) received OK", frame_cnt, rx_data);
        end
    endtask

    // 主流程
    initial begin
        // 复位
        rst_n = 0;
        #30 rst_n = 1;

        // 帧1：0xA5
        send_and_check(8'hA5);
        // 帧2：0x5A
        send_and_check(8'h5A);
        // 帧3：0xFF
        send_and_check(8'hFF);
        // 帧4：0x00
        send_and_check(8'h00);
        // 帧5：0x3C
        send_and_check(8'h3C);

        // 全部通过
        if (frame_cnt !== 5) $fatal(1, "FAIL: expected 5 frames, got %0d", frame_cnt);
        $display("PASS: uart_rx weak testbench passed (golden, %0d frames loopback)", frame_cnt);
        $finish;
    end

    // 仿真超时保护
    initial begin
        #600000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
