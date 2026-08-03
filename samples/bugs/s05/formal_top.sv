// PreCex - fifo_sync L3 缺陷样本 formal 顶层 wrapper（sby 用）
// 作者：Toylog | 版本：v0.1 | 功能概述：例化设计 uut 与断言 u_assert，供 sby (smtbmc+z3) BMC 检查断言

module fifo_sync_formal_top #(
    parameter DATA_W = 8,
    parameter DEPTH = 8           // 深度（应为 2 的幂）

) (
    input wire  clk,
    input wire  rst_n,
    input wire  wr_en,
    input wire  rd_en,
    input wire [DATA_W-1:0] din,
    output wire [DATA_W-1:0] dout,
    output wire  full,
    output wire  empty,
    output wire  half_full
);

    // 设计实例（实例名 uut 与弱 tb 一致）
    fifo_sync #(
        .DATA_W(DATA_W),
        .DEPTH(DEPTH)
    ) uut (
        .clk(clk),
        .rst_n(rst_n),
        .wr_en(wr_en),
        .rd_en(rd_en),
        .din(din),
        .dout(dout),
        .full(full),
        .empty(empty),
        .half_full(half_full)
    );

    // 断言实例：内部信号分层引用 uut.xxx
    fifo_sync_assert #(
        .DATA_W(DATA_W),
        .DEPTH(DEPTH)
    ) u_assert (
        .clk(clk),
        .rst_n(rst_n),
        .wr_en(wr_en),
        .rd_en(rd_en),
        .din(din),
        .dout(dout),
        .full(full),
        .empty(empty),
        .half_full(half_full),
        .count(uut.count),
        .head(uut.head),
        .tail(uut.tail),
        .can_wr(uut.can_wr),
        .can_rd(uut.can_rd)
    );

endmodule
