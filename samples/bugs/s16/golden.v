// PreCex - uart_tx 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：UART 发射机（8N1 帧格式 + 波特率分频，txd 输出，LSB 先发）
// 说明：可综合风格；状态机 IDLE->START->DATA->STOP，baud_tick 分频脉冲控制位节奏

module uart_tx #(
    parameter CLK_FREQ = 50000000,   // 系统时钟频率 Hz
    parameter BAUD     = 115200,     // 波特率
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


    // ------------------------------------------------------------------
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；源自 rtl/uart_tx/assertions.sv）
    // ------------------------------------------------------------------
// 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）

    reg [1:0] state_d;            // 上周期状态

    always @(posedge clk) begin
        if (!rst_n) state_d <= S_IDLE;
        else        state_d <= state;
    end

    // A1 起始位为低：处于 START 状态时 txd 必须为 0
    always @(posedge clk) begin
        if (rst_n && (state == S_START)) begin
            assert (txd == 1'b0);
        end
    end

    // A2 停止位为高：处于 STOP 状态时 txd 必须为 1
    always @(posedge clk) begin
        if (rst_n && (state == S_STOP)) begin
            assert (txd == 1'b1);
        end
    end

    // A3 空闲电平与忙标志：处于 IDLE 时 txd 为高且 tx_busy 为低
    always @(posedge clk) begin
        if (rst_n && (state == S_IDLE)) begin
            assert (txd == 1'b1);
            assert (tx_busy == 1'b0);
        end
    end

    // A4 状态机跳转合法性（打拍检查）：(state_d, state) 必须属于合法跳转集合（含自环）
    // 合法跳转对：IDLE->{IDLE,START}, START->{START,DATA}, DATA->{DATA,STOP}, STOP->{STOP,IDLE}
    always @(posedge clk) begin
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
    always @(posedge clk) begin
        if (rst_n && tx_busy) begin
            assert (state != S_IDLE);
        end
    end

    // A6 位周期节奏：START/DATA/STOP 之间切换必须发生在 baud_tick 拍（位节奏正确）
    // 排除 IDLE->START（启动检测拍不在 tick 拍）；抓波特率脉冲取反/缺失类缺陷（切换拍 baud_tick 应为 1）
    always @(posedge clk) begin
        if (rst_n && (state_d != state) &&
            !(state_d == S_IDLE && state == S_START)) begin
            assert (baud_tick);
        end
    end

    // 环境约束：初始拍处于复位（rst_n==0），复位释放沿（0->1）输入静默，与弱 tb 复位行为一致；设计内部状态由复位分支初始化（避免 initial 覆盖注入缺陷）
    initial assume (!rst_n);
    always @(posedge clk) begin
        if (!rst_n) begin
            assume (!tx_start);
            assume (!tx_data);
        end
    end

endmodule


