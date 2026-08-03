// PreCex - uart_rx 黄金基线强断言（安全子集写法：always 块内 immediate assert + 寄存器打拍）
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖起始位中点确认/停止位校验/状态机合法跳转/忙标志一致/帧完成脉冲关联/数据位计数 6 条性质
// 说明：本文件为独立模块，由 tb 显式实例化；内部信号通过 tb 分层引用 uut.xxx 接入

module uart_rx_assert #(
    parameter CLK_FREQ = 50000000,
    parameter BAUD     = 115200,
    parameter DATA_W   = 8
) (
    clk, rst_n, rxd, rx_valid, rx_data, rx_busy,
    state, baud_cnt, bit_cnt
);

    // 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）
    localparam DIV  = CLK_FREQ / BAUD;
    localparam HALF = DIV / 2;
    localparam DIV_W = $clog2(DIV);
    localparam S_IDLE  = 2'd0;
    localparam S_START = 2'd1;
    localparam S_DATA  = 2'd2;
    localparam S_STOP  = 2'd3;

    input  wire              clk;
    input  wire              rst_n;
    input  wire              rxd;
    input  wire              rx_valid;
    input  wire [DATA_W-1:0] rx_data;
    input  wire              rx_busy;
    input  wire [1:0]        state;
    input  wire [DIV_W-1:0]  baud_cnt;
    input  wire [3:0]        bit_cnt;

    // 打拍寄存器：用于跨周期性质
    reg [1:0]        state_d;
    reg [DIV_W-1:0]  baud_cnt_d;

    always @(posedge clk) begin
        if (!rst_n) begin
            state_d   <= S_IDLE;
            baud_cnt_d <= {DIV_W{1'b0}};
        end else begin
            state_d   <= state;
            baud_cnt_d <= baud_cnt;
        end
    end

    // A1 起始位中点确认：中点在 rxd 为高（毛刺误触发）时，下一状态必须回 IDLE
    always @(posedge clk) begin
        if (rst_n && (state_d == S_START) && (baud_cnt_d == (HALF - 1)) && rxd) begin
            assert (state == S_IDLE);
        end
    end

    // A2 起始位中点确认：中点在 rxd 为低（真起始位）时，下一状态必须进入 DATA
    always @(posedge clk) begin
        if (rst_n && (state_d == S_START) && (baud_cnt_d == (HALF - 1)) && !rxd) begin
            assert (state == S_DATA);
        end
    end

    // A3 停止位中点校验：STOP 状态中点采样时 rxd 必须为 1（正常帧）
    always @(posedge clk) begin
        if (rst_n && (state == S_STOP) && (baud_cnt == (DIV - 1))) begin
            assert (rxd == 1'b1);
        end
    end

    // A4 状态机跳转合法性（打拍对，含自环）：
    // IDLE->{IDLE,START}, START->{START,DATA,IDLE}, DATA->{DATA,STOP}, STOP->{STOP,IDLE}
    always @(posedge clk) begin
        if (rst_n) begin
            case (state_d)
                S_IDLE:  assert ((state == S_IDLE)  || (state == S_START));
                S_START: assert ((state == S_START) || (state == S_DATA) || (state == S_IDLE));
                S_DATA:  assert ((state == S_DATA)  || (state == S_STOP));
                S_STOP:  assert ((state == S_STOP)  || (state == S_IDLE));
            endcase
        end
    end

    // A5 忙标志一致：rx_busy 有效期间不得处于 IDLE
    always @(posedge clk) begin
        if (rst_n && rx_busy) begin
            assert (state != S_IDLE);
        end
    end

    // A6 帧完成脉冲关联：rx_valid 置位时，上一拍必须处于 STOP（帧刚结束）
    always @(posedge clk) begin
        if (rst_n && rx_valid) begin
            assert (state_d == S_STOP);
        end
    end

    // A7 数据位计数不越界：DATA 状态内 bit_cnt 恒 < DATA_W
    always @(posedge clk) begin
        if (rst_n && (state == S_DATA)) begin
            assert (bit_cnt < DATA_W);
        end
    end

endmodule
