// PreCex - uart_tx 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：UART 发射机（8N1 帧格式 + 波特率分频，txd 输出，LSB 先发）
// 说明：可综合风格；状态机 IDLE->START->DATA->STOP，baud_tick 分频脉冲控制位节奏

module uart_tx #(
    parameter CLK_FREQ = 400,   // 系统时钟频率 Hz
    parameter BAUD     = 100,     // 波特率
    parameter DATA_W   = 8           // 数据位宽（8N1 固定 8 位数据）
) (
    input  wire             clk,     // 时钟
    input  wire             rst_n,   // 异步复位（低有效）
    input  wire             tx_start,// 发送启动脉冲（单拍）
    input  wire [DATA_W-1:0] tx_data,// 待发送数据
    output reg              txd,     // 串行输出（空闲为高）
    output reg              tx_busy  // 发送忙标志
);

    // 波特率分频：每个位周期 DIV 个时钟
    localparam DIV    = CLK_FREQ / BAUD;
    localparam DIV_W  = $clog2(DIV);
    localparam BIT_W  = 4;           // 位计数位宽（最多 10 位）

    // 状态定义
    localparam S_IDLE  = 2'd0;
    localparam S_START = 2'd1;
    localparam S_DATA  = 2'd2;
    localparam S_STOP  = 2'd3;

    reg [1:0]      state;            // 发送状态机
    reg [DIV_W-1:0] baud_cnt;        // 波特率分频计数（DIV-1 .. 0）
    reg [BIT_W-1:0] bit_cnt;         // 数据位计数
    reg [DATA_W-1:0] shreg;          // 发送移位寄存器（LSB 先发）

    // 波特率脉冲：每 DIV 个时钟产生一个 tick
    wire baud_tick = (baud_cnt == {DIV_W{1'b0}});

    // 发送状态机
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_IDLE;
            baud_cnt <= {DIV_W{1'b0}};
            bit_cnt  <= 4'd0;
            shreg    <= {DATA_W{1'b0}};
            txd      <= 1'b1;
            tx_busy  <= 1'b0;
        end else begin
            case (state)
                // 空闲：检测发送请求（起始位在检测拍立即拉低）
                S_IDLE: begin
                    tx_busy <= 1'b0;
                    if (tx_start) begin
                        shreg    <= tx_data;
                        bit_cnt  <= 4'd0;
                        baud_cnt <= DIV - 1'b1;
                        state    <= S_START;
                        tx_busy  <= 1'b1;
                        txd      <= 1'b0;   // 起始位立即输出低电平
                    end else begin
                        txd      <= 1'b1;   // 空闲保持高电平
                    end
                end
                // 起始位：输出低电平，持续 1 个位周期
                S_START: begin
                    txd <= 1'b0;
                    if (baud_tick) begin
                        baud_cnt <= DIV - 1'b1;
                        state    <= S_DATA;
                    end else begin
                        baud_cnt <= baud_cnt - 1'b1;
                    end
                end
                // 数据位：LSB 先发，逐位移出
                S_DATA: begin
                    txd <= shreg[0];
                    if (baud_tick) begin
                        baud_cnt <= DIV - 1'b1;
                        shreg    <= shreg >> 1;
                        if (bit_cnt == DATA_W - 1) begin
                            state <= S_STOP;
                            txd   <= 1'b1;   // 停止位在进 STOP 的当拍立即拉高
                        end else begin
                            bit_cnt <= bit_cnt + 1'b1;
                        end
                    end else begin
                        baud_cnt <= baud_cnt - 1'b1;
                    end
                end
                // 停止位：输出高电平，持续 1 个位周期
                S_STOP: begin
                    txd <= 1'b1;
                    if (baud_tick) begin
                        baud_cnt <= DIV - 1'b1;
                        state    <= S_IDLE;
                        tx_busy  <= 1'b0;   // 停止位结束与回空闲同步清除忙标志
                    end else begin
                        baud_cnt <= baud_cnt - 1'b1;
                    end
                end
            endcase
        end
    end

endmodule
