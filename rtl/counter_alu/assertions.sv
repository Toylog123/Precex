// PreCex - counter_alu 黄金基线强断言（安全子集写法：always 块内 immediate assert + 寄存器打拍实现跨周期性质）
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖计数器仅使能自增/未使能保持/复位释放归 0/满值回绕/ALU 输出打拍正确性/运算选择不越界 6 条关键性质
// 说明：本文件为独立模块，由 tb 显式实例化；内部信号通过 tb 分层引用 uut.xxx 接入

module counter_alu_assert #(
    parameter DATA_W = 8,         // 数据位宽（与设计一致）
    parameter OP_W   = 3          // 运算选择位宽（与设计一致）
) (
    clk, rst_n, cnt_en, op, a, b,
    cnt, alu_out
);

    // 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格，兼容 iverilog/yosys）
    localparam OP_NUM = 5;                    // 有效运算个数（0..4）
    input  wire             clk;
    input  wire             rst_n;
    input  wire             cnt_en;
    input  wire [OP_W-1:0]  op;
    input  wire [DATA_W-1:0] a;
    input  wire [DATA_W-1:0] b;
    input  wire [DATA_W-1:0] cnt;
    input  wire [DATA_W-1:0] alu_out;

    // 打拍寄存器：用于跨周期性质
    reg              rst_n_d;                 // 上周期复位信号
    reg              cnt_en_d;                // 上周期计数器使能
    reg [DATA_W-1:0] cnt_d;                   // 上周期计数值
    reg [OP_W-1:0]   op_d;                    // 上周期运算选择
    reg [DATA_W-1:0] a_d;                     // 上周期 ALU 输入 a
    reg [DATA_W-1:0] b_d;                     // 上周期 ALU 输入 b
    reg [DATA_W-1:0] alu_out_d;               // 上周期 ALU 组合输出

    // ALU 参考模型（与设计一致的组合函数，用于输出正确性比较）
    function [DATA_W-1:0] alu_ref(input [OP_W-1:0] f_op,
                                  input [DATA_W-1:0] f_a,
                                  input [DATA_W-1:0] f_b);
        begin
            case (f_op)
                3'd0:    alu_ref = f_a + f_b;  // add
                3'd1:    alu_ref = f_a - f_b;  // sub
                3'd2:    alu_ref = f_a & f_b;  // and
                3'd3:    alu_ref = f_a | f_b;  // or
                default: alu_ref = f_a ^ f_b;  // xor（含 4 与非法 op）
            endcase
        end
    endfunction

    // 打拍逻辑
    always @(posedge clk) begin
        if (!rst_n) begin
            rst_n_d   <= 1'b0;
            cnt_en_d  <= 1'b0;
            cnt_d     <= {DATA_W{1'b0}};
            op_d      <= {OP_W{1'b0}};
            a_d       <= {DATA_W{1'b0}};
            b_d       <= {DATA_W{1'b0}};
            alu_out_d <= {DATA_W{1'b0}};
        end else begin
            rst_n_d   <= rst_n;
            cnt_en_d  <= cnt_en;
            cnt_d     <= cnt;
            op_d      <= op;
            a_d       <= a;
            b_d       <= b;
            alu_out_d <= alu_out;
        end
    end

    // A1 计数器仅在使能时自增：上周期使能 → 本周期 cnt 必须等于上周期 cnt + 1（模 2^DATA_W）
    always @(posedge clk) begin
        if (rst_n && cnt_en_d) begin
            assert (cnt == cnt_d + 1'b1);
        end
    end

    // A2 计数器未使能时保持：上周期未使能 → 本周期 cnt 必须不变（防漏计/多计）
    always @(posedge clk) begin
        if (rst_n && !cnt_en_d) begin
            assert (cnt == cnt_d);
        end
    end

    // A3 复位释放后归 0：上周期处于复位（rst_n_d==0）且本周期复位释放 → cnt 必须为 0
    always @(posedge clk) begin
        if (rst_n && !rst_n_d) begin
            assert (cnt == {DATA_W{1'b0}});
        end
    end

    // A4 ALU 输出正确性（打拍比较）：上周期 ALU 组合输出必须等于上周期输入 (op,a,b) 的参考计算结果
    always @(posedge clk) begin
        if (rst_n) begin
            assert (alu_out_d == alu_ref(op_d, a_d, b_d));
        end
    end

    // A5 运算选择不越界：op 恒为有效运算（0..OP_NUM-1），非法值由 tb 环境约束不得驱动
    always @(posedge clk) begin
        if (rst_n) begin
            assert (op < OP_NUM);
        end
    end

    // A6 计数器满值回绕：上周期 cnt 为全 1 且使能 → 本周期 cnt 必须回绕为 0（模 2^DATA_W）
    always @(posedge clk) begin
        if (rst_n && cnt_en_d && (cnt_d == {DATA_W{1'b1}})) begin
            assert (cnt == {DATA_W{1'b0}});
        end
    end

endmodule
