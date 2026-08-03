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

endmodule
