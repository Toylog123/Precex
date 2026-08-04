// PreCex - uart_tx 黄金基线弱 tb
// 作者：Toylog | 版本：v0.1 | 功能概述：发送多帧数据，按位周期中点采样 txd 验证 8N1 帧格式与数据位序列，触发 A1-A5 断言
`timescale 1ns / 1ps

module tb_uart_tx;

    localparam CLK_FREQ = 50000000;
    localparam BAUD     = 115200;
    localparam DATA_W   = 8;
    localparam DIV      = CLK_FREQ / BAUD;   // 434

    reg              clk      = 0;
    reg              rst_n    = 0;
    reg              tx_start = 0;
    reg  [DATA_W-1:0] tx_data = 0;
    wire             txd;
    wire             tx_busy;

    integer k;
    reg [DATA_W-1:0] send_data;

    // 设计实例
    uart_tx #(
        .CLK_FREQ(400),
        .BAUD(100),
        .DATA_W  (DATA_W)
    ) uut (
        .clk     (clk),
        .rst_n   (rst_n),
        .tx_start(tx_start),
        .tx_data (tx_data),
        .txd     (txd),
        .tx_busy (tx_busy)
    );

    // 时钟 10ns
    always #5 clk = ~clk;

    // 任务：发送一帧并在位周期中点采样比对（8N1：start + 8 data + stop）
    task send_and_check(input [DATA_W-1:0] data);
        begin
            send_data = data;
            // 发起发送
            @(negedge clk);
            tx_start = 1'b1;
            tx_data  = data;
            @(negedge clk);
            tx_start = 1'b0;
            // n0：检测拍（起始位拉低，baud_cnt=DIV-1）
            @(posedge clk);                    // n0
            if (!tx_busy) $fatal(1, "FAIL: tx_busy not asserted");
            // 起始位中点采样（应为 0）：n0 + DIV/2
            repeat (DIV/2) @(posedge clk);
            if (txd !== 1'b0) $fatal(1, "FAIL: start bit not low (data=%0h)", data);
            // 走到第一个数据位起始拍（n0+DIV+1）
            repeat (DIV/2 - 1) @(posedge clk); // n0+DIV-1
            @(posedge clk);                    // n0+DIV：tick 拍（进入 DATA）
            @(posedge clk);                    // n0+DIV+1：数据位 bit0 开始
            // 逐数据位中点采样（LSB 先发）
            for (k = 0; k < DATA_W; k = k + 1) begin
                repeat (DIV/2) @(posedge clk); // 数据位中点
                if (txd !== send_data[k]) $fatal(1, "FAIL: data bit %0d mismatch, expect %b got %b", k, send_data[k], txd);
                repeat (DIV/2) @(posedge clk); // 到下一数据位起始拍
            end
            // 循环后位于 n0+DIV+1+8*DIV（进 STOP 的 tick 拍，停止位已拉高）
            @(posedge clk);                    // STOP 分支第一拍
            repeat (DIV/2) @(posedge clk);     // 停止位中点采样（应为 1）
            if (txd !== 1'b1) $fatal(1, "FAIL: stop bit not high (data=%0h)", data);
            // 等待回到空闲
            repeat (DIV/2 + 1) @(posedge clk);
            if (tx_busy) $fatal(1, "FAIL: tx_busy not cleared after frame");
            if (txd !== 1'b1) $fatal(1, "FAIL: txd not idle-high after frame");
        end
    endtask

    // 主流程
    initial begin
        // 复位
        rst_n = 0;
        #30 rst_n = 1;

        // 帧1：0xA5（1010_0101，LSB 先发 → 1,0,1,0,0,1,0,1）
        send_and_check(8'hA5);
        $display("INFO: frame 0xA5 OK");

        // 帧2：0x5A（0101_1010）
        send_and_check(8'h5A);
        $display("INFO: frame 0x5A OK");

        // 帧3：0xFF（全 1）
        send_and_check(8'hFF);
        $display("INFO: frame 0xFF OK");

        // 帧4：0x00（全 0）
        send_and_check(8'h00);
        $display("INFO: frame 0x00 OK");

        // 全部通过
        $display("PASS: uart_tx weak testbench passed (golden)");
        $finish;
    end

    // 仿真超时保护
    initial begin
        #500000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
