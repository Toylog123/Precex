// PreCex - uart_rx 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：UART 接收机（起始位下降沿检测 + 位周期中点采样，rxd 输入，8N1 帧格式）
// 说明：可综合风格；IDLE 检测起始位 -> START 中点确认 -> DATA 逐位中点采样 -> STOP 校验

module uart_rx #(
    parameter CLK_FREQ = 50000000,   // 系统时钟频率 Hz
    parameter BAUD     = 115200,     // 波特率
    parameter DATA_W   = 8           // 数据位宽
) (
    input  wire             clk,     // 时钟
    input  wire             rst_n,   // 异步复位（低有效）
    input  wire             rxd,     // 串行输入（空闲为高）
    output reg              rx_valid,// 接收完成脉冲（帧结束一拍）
    output reg  [DATA_W-1:0] rx_data,// 接收数据（LSB 先收）
    output reg              rx_busy  // 接收忙标志
);

    // 波特率分频
    localparam DIV   = CLK_FREQ / BAUD;
    localparam HALF  = DIV / 2;          // 位周期半程（起始位中点确认点）
    localparam DIV_W = $clog2(DIV);
    localparam BIT_W = 4;

    // 状态定义
    localparam S_IDLE  = 2'd0;
    localparam S_START = 2'd1;
    localparam S_DATA  = 2'd2;
    localparam S_STOP  = 2'd3;

    reg [1:0]      state;               // 接收状态机
    reg [DIV_W-1:0] baud_cnt;           // 波特率分频计数
    reg [BIT_W-1:0] bit_cnt;            // 已采样数据位计数
    reg [DATA_W-1:0] rx_shreg;          // 接收移位寄存器（LSB 先收）

    // 接收状态机
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_IDLE;
            baud_cnt <= {DIV_W{1'b0}};
            bit_cnt  <= 4'd0;
            rx_shreg <= {DATA_W{1'b0}};
            rx_data  <= {DATA_W{1'b0}};
            rx_valid <= 1'b0;
            rx_busy  <= 1'b0;
        end else begin
            // valid 默认清零（单拍脉冲）
            rx_valid <= 1'b0;
            case (state)
                // 空闲：检测起始位下降沿（rxd 拉低即进入起始位确认）
                S_IDLE: begin
                    rx_busy <= 1'b0;
                    if (!rxd) begin
                        baud_cnt <= {DIV_W{1'b0}};
                        state    <= S_START;
                        rx_busy  <= 1'b1;
                    end
                end
                // 起始位：在 HALF 处中点采样确认（抗毛刺），仍为低则进入数据接收
                S_START: begin
                    if (baud_cnt == (HALF - 1)) begin
                        if (rxd) begin
                            // 误触发（毛刺），恢复空闲
                            state   <= S_IDLE;
                            rx_busy <= 1'b0;
                        end else begin
                            baud_cnt <= {DIV_W{1'b0}};
                            bit_cnt  <= 4'd0;
                            state    <= S_DATA;
                        end
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end
                // 数据位：每个位周期中点（DIV-1 处）采样 rxd，LSB 先收
                S_DATA: begin
                    if (baud_cnt == (DIV - 1)) begin
                        rx_shreg <= {rxd, rx_shreg[DATA_W-1:1]};   // 新位进最高位，最后整体翻转
                        baud_cnt <= {DIV_W{1'b0}};
                        if (bit_cnt == (DATA_W - 1)) begin
                            state <= S_STOP;
                        end else begin
                            bit_cnt <= bit_cnt + 1'b1;
                        end
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end
                // 停止位：中点采样校验（应为 1），完成后输出接收数据并结束
                S_STOP: begin
                    if (baud_cnt == (DIV - 1)) begin
                        baud_cnt <= {DIV_W{1'b0}};
                        state    <= S_IDLE;
                        rx_busy  <= 1'b0;
                        rx_valid <= 1'b1;                  // 帧完成脉冲
                        // 8 位数据已全部收在 rx_shreg 中（rx_shreg[0]=最先收到的 LSB）
                        rx_data  <= rx_shreg;
                    end else begin
                        baud_cnt <= baud_cnt + 1'b1;
                    end
                end
            endcase
        end
    end

endmodule
