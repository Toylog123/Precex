// PreCex - fifo_sync L3 缺陷样本 s01 强断言（安全子集写法：always 块内 immediate assert + 寄存器打拍实现跨周期性质）
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖 FIFO 满时不写/空时不读/指针不越界/count 增量守恒/半满标志 5 条关键性质
// 来源：本文件为 rtl/fifo_sync/assertions.sv 的黄金断言拷贝（未改动），保证与 rtl 断言矩阵一致
// 说明：本文件为独立模块，由 tb/formal_top 显式实例化；内部信号通过分层引用 uut.xxx 接入
// 击穿点：A4（count 增量守恒）命中 buggy 的"写优先"计数缺陷——同拍读写时 delta==0 但 count 错误 +1

module fifo_sync_assert #(
    parameter DATA_W = 8,
    parameter DEPTH  = 8
) (
    clk, rst_n, wr_en, rd_en, din, dout,
    full, empty, half_full, count, head, tail, can_wr, can_rd
);

    // 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格，兼容 iverilog/yosys）
    localparam ADDR_W = $clog2(DEPTH);
    localparam CNT_W  = ADDR_W + 1;
    input  wire             clk;
    input  wire             rst_n;
    input  wire             wr_en;
    input  wire             rd_en;
    input  wire [DATA_W-1:0] din;
    input  wire [DATA_W-1:0] dout;
    input  wire             full;
    input  wire             empty;
    input  wire             half_full;
    input  wire [CNT_W-1:0]  count;   // 含 DEPTH 值，比指针比较更安全
    input  wire [ADDR_W-1:0] head;
    input  wire [ADDR_W-1:0] tail;
    input  wire             can_wr;
    input  wire             can_rd;

    // 打拍寄存器：用于跨周期性质
    reg        full_d;               // 上周期满标志
    reg        empty_d;              // 上周期空标志
    reg        wr_en_d;              // 上周期写请求
    reg        rd_en_d;              // 上周期读请求
    reg [CNT_W-1:0] count_d;         // 上周期 count
    reg [1:0]       delta_d;         // 上周期实际净增减量（打拍后的 2 位补码）

    // 组合：本周期实际净增减量 = can_wr - can_rd（2 位补码表示）
    wire [1:0] delta = (can_wr ? 2'b01 : 2'b00) - (can_rd ? 2'b01 : 2'b00);

    // 打拍逻辑
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            full_d  <= 1'b0;
            empty_d <= 1'b0;
            wr_en_d <= 1'b0;
            rd_en_d <= 1'b0;
            count_d <= {CNT_W{1'b0}};
            delta_d <= 2'b00;
        end else begin
            full_d  <= full;
            empty_d <= empty;
            wr_en_d <= wr_en;
            rd_en_d <= rd_en;
            count_d <= count;
            delta_d <= delta;
        end
    end

    // A1 满时不写：上周期满且上周期请求写（且无同拍读）→ 写被拒绝，本周期 count 必须保持满值（防溢出/回绕）
    // 注：使能排除 rd_en_d——满时写拒但同拍读合法（count 会 -1），避免读优先语义下的误报
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // 复位期不检查
        end else if (full_d && wr_en_d && !rd_en_d) begin
            assert (count == DEPTH);
        end
    end

    // A2 空时不读：上周期已空且上周期请求读（且无同拍写）→ 读被拒绝，本周期 count 必须保持 0（防下溢）
    // 注：使能排除 wr_en_d——空时读拒但同拍写合法（count 会 +1），避免读优先语义下的误报
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // 复位期不检查
        end else if (empty_d && rd_en_d && !wr_en_d) begin
            assert (count == 0);
        end
    end

    // A3 指针永不越界：head/tail 始终 < DEPTH（防回绕错）
    always @(posedge clk or negedge rst_n) begin
        if (rst_n) begin
            assert (head < DEPTH);
            assert (tail < DEPTH);
        end
    end

    // A4 count 增量守恒（打拍两拍）：count 变化量必须恰好等于 (can_wr - can_rd)
    // —— 击穿点：buggy 写优先计数在 delta==0（同拍读写）时 count 仍 +1，违反 count == count_d
    always @(posedge clk or negedge rst_n) begin
        if (rst_n) begin
            if (delta_d == 2'b00) begin
                assert (count == count_d);          // 同拍读写或不动作：count 不变
            end else if (delta_d == 2'b01) begin
                assert (count == count_d + 1'b1);   // 仅写：count +1
            end else if (delta_d == 2'b11) begin    // -1 的补码
                assert (count == count_d - 1'b1);   // 仅读：count -1
            end
        end
    end

    // A5 半满标志正确性：half_full == (count >= DEPTH/2)
    always @(posedge clk or negedge rst_n) begin
        if (rst_n) begin
            assert (half_full == (count >= (DEPTH >> 1)));
        end
    end

endmodule
