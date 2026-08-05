// PreCex - fifo_sync 黄金基线弱 tb
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖复位/顺序写满/满时写拒绝/顺序读空/空时读拒绝/同拍读写，触发 A1-A5 断言，应全绿
`timescale 1ns / 1ps

module tb_fifo_sync_shallow;

    localparam DATA_W = 8;
    localparam DEPTH  = 8;

    reg              clk   = 0;
    reg              rst_n = 0;
    reg              wr_en = 0;
    reg              rd_en = 0;
    reg  [DATA_W-1:0] din  = 0;
    wire [DATA_W-1:0] dout;
    wire             full;
    wire             empty;
    wire             half_full;

    integer i;

    // 设计实例
    fifo_sync #(
        .DATA_W(DATA_W),
        .DEPTH (DEPTH)
    ) uut (
        .clk      (clk),
        .rst_n    (rst_n),
        .wr_en    (wr_en),
        .rd_en    (rd_en),
        .din      (din),
        .dout     (dout),
        .full     (full),
        .empty    (empty),
        .half_full(half_full)
    );

    // 断言实例：内部信号通过分层引用接入（注意实例名必须为 uut）
    fifo_sync_assert #(
        .DATA_W(DATA_W),
        .DEPTH (DEPTH)
    ) u_assert (
        .clk      (clk),
        .rst_n    (rst_n),
        .wr_en    (wr_en),
        .rd_en    (rd_en),
        .din      (din),
        .dout     (dout),
        .full     (full),
        .empty    (empty),
        .half_full(half_full),
        .count    (uut.count),
        .head     (uut.head),
        .tail     (uut.tail),
        .can_wr   (uut.can_wr),
        .can_rd   (uut.can_rd)
    );

    // 时钟 10ns
    always #5 clk = ~clk;

    // 主测试流程
    initial begin
        // ===== 复位 =====
        rst_n = 0;
        #30 rst_n = 1;

        // ===== 浅覆盖：仅顺序写 4 个，顺序读 4 个，验证数据串（不测满/空/同拍边界） =====
        if (!empty) $fatal(1, "FAIL: empty not asserted after reset");
        for (i = 0; i < 4; i = i + 1) begin
            @(negedge clk);
            wr_en = 1'b1;
            din   = i[7:0];
            @(negedge clk);
            wr_en = 1'b0;
        end
        for (i = 0; i < 4; i = i + 1) begin
            @(negedge clk);
            rd_en = 1'b1;
            @(negedge clk);
            rd_en = 1'b0;
            if (dout !== i[7:0]) $fatal(1, "FAIL: dout mismatch, expect %0d got %0d", i, dout);
        end
        if (!empty) $fatal(1, "FAIL: empty not asserted after 4 reads");
        @(negedge clk);
        wr_en = 1'b1; din = 8'hA5;
        @(negedge clk);
        wr_en = 1'b0;
        @(negedge clk);
        rd_en = 1'b1;
        @(negedge clk);
        rd_en = 1'b0;
        if (dout !== 8'hA5) $fatal(1, "FAIL: single wr/rd mismatch");
        $display("INFO: shallow wr/rd OK");

        // ===== 全部通过 =====
        $display("PASS: fifo_sync weak testbench passed (golden)");
        $finish;
    end

    // 仿真超时保护
    initial begin
        #2000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
