// PreCex - fifo_sync L3 缺陷样本 s01 弱 tb（buggy 版必须 PASS）
// 作者：Toylog | 版本：v0.1 | 功能概述：仅测基本正常场景——复位/顺序写满/满时写拒绝/顺序读空/空时读拒绝，
//        刻意避开"同拍读写"缺陷路径（该路径由强断言 A4 在 formal 中击穿），保证 buggy 弱 tb 通过
// 说明：断言模块 u_assert 正常例化；上述正常路径下 A1-A5 对 buggy/golden 均成立，弱 tb 全绿
`timescale 1ns / 1ps

module tb_fifo_sync;

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

    // 断言实例：内部信号通过分层引用接入（实例名必须为 uut）
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
        // ===== 阶段1：复位 =====
        rst_n = 0;
        #30 rst_n = 1;
        if (!empty) $fatal(1, "FAIL: empty not asserted after reset");

        // ===== 阶段2：顺序写 0..7，直至填满 =====
        for (i = 0; i < 8; i = i + 1) begin
            @(negedge clk);
            wr_en = 1'b1;
            din   = i[7:0];
            @(negedge clk);
            wr_en = 1'b0;
        end
        if (!full)       $fatal(1, "FAIL: full not asserted after 8 writes");
        if (uut.count !== 8) $fatal(1, "FAIL: count!=8 after 8 writes, got %0d", uut.count);
        $display("INFO: FIFO full after 8 writes, count=%0d", uut.count);

        // ===== 阶段3：满时写应被拒绝（can_wr 由 full 门控，count 保持 8）=====
        @(negedge clk);
        wr_en = 1'b1;
        din   = 8'hFF;
        @(negedge clk);
        wr_en = 1'b0;
        if (uut.count !== 8) $fatal(1, "FAIL: write accepted while full, count=%0d", uut.count);

        // ===== 阶段4：顺序读 0..7，验证数据完整性与回绕 =====
        for (i = 0; i < 8; i = i + 1) begin
            @(negedge clk);
            rd_en = 1'b1;
            @(negedge clk);
            rd_en = 1'b0;
            if (dout !== i[7:0]) $fatal(1, "FAIL: dout mismatch, expect %0d got %0d", i, dout);
        end
        if (!empty) $fatal(1, "FAIL: empty not asserted after 8 reads");
        $display("INFO: FIFO empty after 8 reads, dout sequence OK");

        // ===== 阶段5：空时读应被拒绝（can_rd 由 empty 门控，count 保持 0）=====
        @(negedge clk);
        rd_en = 1'b1;
        @(negedge clk);
        rd_en = 1'b0;
        if (uut.count !== 0) $fatal(1, "FAIL: read accepted while empty, count=%0d", uut.count);

        // ===== 全部通过 =====
        $display("PASS: fifo_sync weak testbench passed (buggy tolerated)");
        $finish;
    end

    // 仿真超时保护
    initial begin
        #2000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
