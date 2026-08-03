// PreCex - counter_alu L3 缺陷样本 s03 弱 tb（buggy 版必须 PASS）
// 作者：Toylog | 版本：v0.1 | 功能概述：仅测基本正常场景——复位归 0/使能计数 5 拍/未使能保持/ALU 五种运算/再次复位归 0；
//        刻意避开"满值回绕"缺陷路径（计数不超过 255，该路径由强断言 A6 在 formal 中击穿），保证 buggy 弱 tb 通过
// 说明：断言模块 u_assert 正常例化；上述正常路径下 A1-A6 对 buggy/golden 均成立（A6 不触发），弱 tb 全绿
`timescale 1ns / 1ps

module tb_counter_alu;

    localparam DATA_W = 8;
    localparam OP_W   = 3;

    reg              clk    = 0;
    reg              rst_n  = 0;
    reg              cnt_en = 0;
    reg  [OP_W-1:0]  op     = 0;
    reg  [DATA_W-1:0] a     = 0;
    reg  [DATA_W-1:0] b     = 0;
    wire [DATA_W-1:0] cnt;
    wire [DATA_W-1:0] alu_out;

    integer i;
    reg [DATA_W-1:0] expect_cnt;   // 期望计数值（expect 是 SV 关键字，不可用作变量名）

    // 设计实例
    counter_alu #(
        .DATA_W(DATA_W),
        .OP_W  (OP_W)
    ) uut (
        .clk     (clk),
        .rst_n   (rst_n),
        .cnt_en  (cnt_en),
        .op      (op),
        .a       (a),
        .b       (b),
        .cnt     (cnt),
        .alu_out (alu_out)
    );

    // 断言实例
    counter_alu_assert #(
        .DATA_W(DATA_W),
        .OP_W  (OP_W)
    ) u_assert (
        .clk     (clk),
        .rst_n   (rst_n),
        .cnt_en  (cnt_en),
        .op      (op),
        .a       (a),
        .b       (b),
        .cnt     (cnt),
        .alu_out (alu_out)
    );

    // 时钟 10ns
    always #5 clk = ~clk;

    // 主测试流程
    initial begin
        // ===== 阶段1：复位 =====
        rst_n = 0;
        #30 rst_n = 1;
        @(negedge clk);
        if (cnt !== 8'd0) $fatal(1, "FAIL: cnt not zero after reset, got %0d", cnt);
        $display("INFO: reset OK, cnt=%0d", cnt);

        // ===== 阶段2：使能计数 5 拍（1..5，远未触及 255 回绕路径）=====
        expect_cnt = 8'd1;
        for (i = 0; i < 5; i = i + 1) begin
            @(negedge clk);
            cnt_en = 1'b1;
            @(negedge clk);
            cnt_en = 1'b0;
            if (cnt !== expect_cnt) $fatal(1, "FAIL: cnt mismatch at iter=%0d, expect=%0d got=%0d", i, expect_cnt, cnt);
            expect_cnt = expect_cnt + 1'b1;
        end
        $display("INFO: 5-cycle counting OK, cnt=%0d", cnt);

        // ===== 阶段3：使能关断保持（触发 A2）=====
        expect_cnt = cnt;
        for (i = 0; i < 3; i = i + 1) begin
            @(negedge clk);
            cnt_en = 1'b0;
            @(negedge clk);
            if (cnt !== expect_cnt) $fatal(1, "FAIL: cnt changed while disabled, expect=%0d got=%0d", expect_cnt, cnt);
        end
        $display("INFO: counter hold while disabled OK, cnt=%0d", cnt);

        // ===== 阶段4：ALU 五种运算验证（触发 A4）=====
        cnt_en = 1'b0;
        @(negedge clk); a = 8'hA5; b = 8'h3C; op = 3'd0; #1;
        if (alu_out !== 8'hE1) $fatal(1, "FAIL: add 0xA5+0x3C, got %0h", alu_out);
        @(negedge clk); a = 8'hA5; b = 8'h3C; op = 3'd1; #1;
        if (alu_out !== 8'h69) $fatal(1, "FAIL: sub 0xA5-0x3C, got %0h", alu_out);
        @(negedge clk); a = 8'hA5; b = 8'h3C; op = 3'd2; #1;
        if (alu_out !== 8'h24) $fatal(1, "FAIL: and 0xA5&0x3C, got %0h", alu_out);
        @(negedge clk); a = 8'hA5; b = 8'h3C; op = 3'd3; #1;
        if (alu_out !== 8'hBD) $fatal(1, "FAIL: or 0xA5|0x3C, got %0h", alu_out);
        @(negedge clk); a = 8'hA5; b = 8'h3C; op = 3'd4; #1;
        if (alu_out !== 8'h99) $fatal(1, "FAIL: xor 0xA5^0x3C, got %0h", alu_out);
        $display("INFO: ALU basic ops OK (add/sub/and/or/xor)");

        // ===== 阶段5：再次复位验证归 0（触发 A3）=====
        @(negedge clk); rst_n = 1'b0;
        @(negedge clk); rst_n = 1'b1;
        @(negedge clk);
        if (cnt !== 8'd0) $fatal(1, "FAIL: cnt not zero after re-reset, got %0d", cnt);
        $display("INFO: re-reset OK, cnt=%0d", cnt);

        // ===== 全部通过 =====
        $display("PASS: counter_alu weak testbench passed (buggy tolerated)");
        $finish;
    end

    // 仿真超时保护
    initial begin
        #20000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
