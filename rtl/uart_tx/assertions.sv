// PreCex - uart_tx 黄金基线强断言（安全子集写法：always 块内 immediate assert + 寄存器打拍）
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖起始位/停止位/空闲电平/状态机合法跳转/忙标志与状态一致性 5 条关键性质
// 说明：本文件为独立模块，由 tb 显式实例化；内部信号通过 tb 分层引用 uut.xxx 接入

module uart_tx_assert #(
    parameter CLK_FREQ = 50000000,
    parameter BAUD     = 115200,
    parameter DATA_W   = 8
) (
    clk, rst_n, tx_start, tx_data, txd, tx_busy,
    state, bit_cnt, baud_tick
);

    // 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）
    localparam DIV   = CLK_FREQ / BAUD;
    localparam DIV_W = $clog2(DIV);
    localparam S_IDLE  = 2'd0;
    localparam S_START = 2'd1;
    localparam S_DATA  = 2'd2;
    localparam S_STOP  = 2'd3;

    input wire              clk;
    input wire              rst_n;
    input wire              tx_start;
    input wire [DATA_W-1:0] tx_data;
    input wire              txd;
    input wire              tx_busy;
    input wire [1:0]        state;
    input wire [3:0]        bit_cnt;
    input wire              baud_tick;

    // 打拍寄存器：用于跨周期跳转合法性检查
    reg [1:0] state_d;            // 上周期状态

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) state_d <= S_IDLE;
        else        state_d <= state;
    end

    // A1 起始位为低：处于 START 状态时 txd 必须为 0
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && (state == S_START)) begin
            assert (txd == 1'b0);
        end
    end

    // A2 停止位为高：处于 STOP 状态时 txd 必须为 1
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && (state == S_STOP)) begin
            assert (txd == 1'b1);
        end
    end

    // A3 空闲电平与忙标志：处于 IDLE 时 txd 为高且 tx_busy 为低
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && (state == S_IDLE)) begin
            assert (txd == 1'b1);
            assert (tx_busy == 1'b0);
        end
    end

    // A4 状态机跳转合法性（打拍检查）：(state_d, state) 必须属于合法跳转集合（含自环）
    // 合法跳转对：IDLE->{IDLE,START}, START->{START,DATA}, DATA->{DATA,STOP}, STOP->{STOP,IDLE}
    always @(posedge clk or negedge rst_n) begin
        if (rst_n) begin
            case (state_d)
                S_IDLE:  assert ((state == S_IDLE)  || (state == S_START)); // 空闲保持或启动
                S_START: assert ((state == S_START) || (state == S_DATA));  // 起始位停留或进入数据
                S_DATA:  assert ((state == S_DATA)  || (state == S_STOP));  // 数据位续传或收尾
                S_STOP:  assert ((state == S_STOP)  || (state == S_IDLE));  // 停止位停留或回空闲
            endcase
        end
    end

    // A5 忙标志与状态一致：tx_busy 有效期间不得处于 IDLE
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && tx_busy) begin
            assert (state != S_IDLE);
        end
    end

endmodule
