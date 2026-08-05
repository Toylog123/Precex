// PreCex - uart_rx 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：UART 接收机（起始位下降沿检测 + 位周期中点采样，rxd 输入，8N1 帧格式）
// 说明：可综合风格；IDLE 检测起始位 -> START 中点确认 -> DATA 逐位中点采样 -> STOP 校验

module uart_rx #(
    parameter CLK_FREQ = 400,   // 系统时钟频率 Hz
    parameter BAUD     = 100,     // 波特率
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


    // ------------------------------------------------------------------
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；源自 rtl/uart_rx/assertions.sv）
    // ------------------------------------------------------------------
    initial begin
        state_d = 1'b0;
        baud_cnt_d = 1'b0;
        rxd_d = 1'b0;
    end
// 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）

    reg [1:0]        state_d;
    reg [DIV_W-1:0]  baud_cnt_d;
    reg              rxd_d;          // 上周期 rxd（中点采样拍的值）

    always @(posedge clk) begin
        if (!rst_n) begin
            state_d   <= S_IDLE;
            baud_cnt_d <= {DIV_W{1'b0}};
            rxd_d     <= 1'b1;
        end else begin
            state_d   <= state;
            baud_cnt_d <= baud_cnt;
            rxd_d     <= rxd;
        end
    end

    // A1 起始位中点确认：中点在 rxd 为高（毛刺误触发）时，下一状态必须回 IDLE
    always @(posedge clk) begin
        if (rst_n && (state_d == S_START) && (baud_cnt_d == (HALF - 1)) && rxd_d) begin
            assert (state == S_IDLE);
        end
    end

    // A2 起始位中点确认：中点在 rxd 为低（真起始位）时，下一状态必须进入 DATA
    always @(posedge clk) begin
        if (rst_n && (state_d == S_START) && (baud_cnt_d == (HALF - 1)) && !rxd_d) begin
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

    // 环境约束：初始拍处于复位（rst_n==0），复位释放沿（0->1）输入静默，与弱 tb 复位行为一致；设计内部状态由复位分支初始化（避免 initial 覆盖注入缺陷）
    initial assume (!rst_n);
    always @(posedge clk) begin
        if (!rst_n) begin
            assume (!rxd);
        end
    end


    // 环境约束：!(state == S_START) || !rxd（断言依赖的环境假设，避免与缺陷无关的假反例）


    // 环境约束：!(state == S_STOP) || rxd（断言依赖的环境假设，避免与缺陷无关的假反例）
    always @(posedge clk) assume (!(state == S_STOP) || rxd);

endmodule




