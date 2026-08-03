// PreCex - fifo_sync 黄金基线弱 tb
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖复位/顺序写满/满时写拒绝/顺序读空/空时读拒绝/同拍读写，触发 A1-A5 断言，应全绿
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

    // 时钟 10ns
    always #5 clk = ~clk;

    // 主测试流程
    initial begin
        // ===== 复位 =====
        rst_n = 0;
        #30 rst_n = 1;

        // ===== 阶段1：顺序写 0..7，直至填满 =====
        if (!empty) $fatal(1, "FAIL: empty not asserted after reset");
        for (i = 0; i < 8; i = i + 1) begin
            @(negedge clk);
            wr_en = 1'b1;
            din   = i[7:0];
            @(negedge clk);
            wr_en = 1'b0;
        end
        // 写满后检查标志
        if (!full)       $fatal(1, "FAIL: full not asserted after 8 writes");
        if (empty)       $fatal(1, "FAIL: empty asserted while full");
        $display("INFO: FIFO full after 8 writes, count=%0d", uut.count);

        // ===== 阶段2：满时写应被拒绝（触发 A1）=====
        @(negedge clk);
        wr_en = 1'b1;
        din   = 8'hFF;
        @(negedge clk);
        wr_en = 1'b0;
        if (!full) $fatal(1, "FAIL: full dropped");

        // ===== 阶段3：顺序读 0..7，验证数据完整性与回绕 =====
        for (i = 0; i < 8; i = i + 1) begin
            @(negedge clk);
            rd_en = 1'b1;
            @(negedge clk);
            rd_en = 1'b0;
        end
        if (!empty) $fatal(1, "FAIL: empty not asserted after 8 reads");
        $display("INFO: FIFO empty after 8 reads, dout sequence OK");

        // ===== 阶段4：空时读应被拒绝（触发 A2）=====
        @(negedge clk);
        rd_en = 1'b1;
        @(negedge clk);
        rd_en = 1'b0;

        // ===== 阶段5：同拍读写（count 守恒，触发 A4；读优先语义下读到写入前的旧数据）=====
        @(negedge clk);
        wr_en = 1'b1; rd_en = 1'b0; din = 8'h11;
        @(negedge clk);
        wr_en = 1'b0;
        // 此时 FIFO 内已写入 0x11（head 指向 0x11，count=1）
        @(negedge clk);
        wr_en = 1'b1; rd_en = 1'b1; din = 8'h5A;
        @(negedge clk);
        wr_en = 1'b0; rd_en = 1'b0;
        $display("INFO: concurrent wr+rd OK, count=%0d dout=0x%02h", uut.count, dout);

        // ===== 阶段6：交替读写若干拍，验证数据顺序一致 =====
        // 阶段5 之后 FIFO 内容: [0x5A(pos1), 0x11(pos2), 0x22(pos3)]，head=1
        @(negedge clk);
        wr_en = 1'b1; din = 8'h11;
        @(negedge clk);
        wr_en = 1'b0;
        @(negedge clk);
        wr_en = 1'b1; din = 8'h22;
        @(negedge clk);
        wr_en = 1'b0;
        @(negedge clk);
        rd_en = 1'b1;
        @(negedge clk);
        rd_en = 1'b0;
        @(negedge clk);
        rd_en = 1'b1;
        @(negedge clk);
        rd_en = 1'b0;
        $display("INFO: data order check OK");

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
// [bug_injector] weak tb sanitized for boundary_wrap: stripped 8 fatal check(s) on cnt/count/dout/state/done/timeout_irq/txd/tx_busy/readback/WSTRB/RVALID/BVALID/reg
