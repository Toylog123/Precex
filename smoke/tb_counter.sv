// PreCex - Gate-1 smoke test: weak testbench (buggy 版应通过)
// 作者：Toylog | 版本：v0.1 | 功能概述：弱 tb：只测复位与单周期使能，不测连续计数到 2->3
`timescale 1ns / 1ps

module tb_counter;

    reg        clk = 0;
    reg        rst_n = 0;
    reg        en = 0;
    wire [1:0] cnt;

    counter uut (
        .clk  (clk),
        .rst_n(rst_n),
        .en   (en),
        .cnt  (cnt)
    );

    // 时钟 10ns
    always #5 clk = ~clk;

    initial begin
        // 复位
        rst_n = 0;
        #20 rst_n = 1;
        // 弱场景 1：en=0 保持
        #20
        if (cnt !== 2'd0) $fatal("FAIL: cnt != 0 after idle");
        // 弱场景 2：单周期使能，只验证 en 有效时 cnt 变化一拍的可见行为
        en = 1; #10 en = 0;
        if (cnt !== 2'd1) $fatal("FAIL: cnt != 1 after one en pulse");
        // 弱场景 3：再给一拍
        en = 1; #10 en = 0;
        if (cnt !== 2'd2) $fatal("FAIL: cnt != 2 after two en pulses");
        $display("PASS: weak testbench passed (buggy design)");
        $finish;
    end

endmodule
