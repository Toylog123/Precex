// PreCex - counter_alu 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：参数化计数器 + 组合 ALU（add/sub/and/or/xor 5 种运算，非法 op 安全归 xor），计数器仅使能时自增、异步复位归 0、模 2^DATA_W 自然回绕
// 说明：可综合风格；ALU 为纯组合逻辑（assign 三元链，无锁存），计数器为同步自增寄存器

module counter_alu #(
    parameter DATA_W = 8,          // 计数器/ALU 数据位宽
    parameter OP_W   = 3           // ALU 运算选择位宽（有效值 0..4，共 5 种运算）
) (
    input  wire             clk,   // 时钟
    input  wire             rst_n, // 异步复位（低有效）
    input  wire             cnt_en,// 计数器使能（1：自增 1；0：保持）
    input  wire [OP_W-1:0]  op,    // ALU 运算选择（0=add 1=sub 2=and 3=or 4=xor，其余归 xor）
    input  wire [DATA_W-1:0] a,    // ALU 输入 a
    input  wire [DATA_W-1:0] b,    // ALU 输入 b
    output reg  [DATA_W-1:0] cnt,  // 计数器值（复位归 0，使能时 +1）
    output wire [DATA_W-1:0] alu_out // ALU 组合输出（纯组合，本拍输入立即生效）
);

    // ALU 运算编码
    localparam OP_ADD = 3'd0;
    localparam OP_SUB = 3'd1;
    localparam OP_AND = 3'd2;
    localparam OP_OR  = 3'd3;
    localparam OP_XOR = 3'd4;

    // 组合 ALU：纯 assign 三元链实现（无 always 块，避免 iverilog 12 对 always @(*)
    // 时间 0 初始求值不可靠的问题；非法 op 统一归 XOR，防 X/锁存）
    assign alu_out = (op == OP_ADD) ? (a + b)   // 加法（模 2^DATA_W 回绕）
                   : (op == OP_SUB) ? (a - b)   // 减法（模 2^DATA_W 借位）
                   : (op == OP_AND) ? (a & b)   // 按位与
                   : (op == OP_OR)  ? (a | b)   // 按位或
                   :                 (a ^ b);   // 异或（含 4=xor 与全部非法 op）

    // 计数器：异步复位归 0，仅使能时自增，模 2^DATA_W 自然回绕
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= {DATA_W{1'b0}};
        end else if (cnt_en) begin
            cnt <= cnt + 1'b1;
        end
    end


    // ------------------------------------------------------------------
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；源自 rtl/counter_alu/assertions.sv）
    // ------------------------------------------------------------------
    initial begin
        rst_n_d = 1'b0;
        cnt_en_d = 1'b0;
        cnt_d = 1'b0;
        op_d = 1'b0;
        a_d = 1'b0;
        b_d = 1'b0;
        alu_out_d = 1'b0;
    end
// 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格，兼容 iverilog/yosys）
    localparam OP_NUM = 5;                    // 有效运算个数（0..4）

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

    // 环境约束：初始拍处于复位（rst_n==0），复位释放沿（0->1）输入静默，与弱 tb 复位行为一致；设计内部状态由复位分支初始化（避免 initial 覆盖注入缺陷）
    initial assume (!rst_n);
    always @(posedge clk) begin
        if (!rst_n) begin
            assume (!cnt_en);
            assume (!op);
            assume (!a);
            assume (!b);
        end
    end


    // 环境约束：op < OP_NUM（断言依赖的环境假设，避免与缺陷无关的假反例）
    always @(posedge clk) assume (op < OP_NUM);

endmodule



