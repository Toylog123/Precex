// PreCex - fsm_ctrl 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：3 状态序列控制器（S1/S2/S3 分级停留 + 异常跳转 + 全局超时保护，done/timeout_irq 单拍脉冲）
// 说明：可综合风格；IDLE->S1->S2->S3->done；S1 遇 data_in==0xAA 停留等待（触发超时保护），S2 遇 data_in==0xFF 异常跳回 IDLE

module fsm_ctrl #(
    parameter TIMEOUT = 32,       // 全局超时步数（从 start 起计）
    parameter S1_HOLD = 2,        // S1 停留拍数
    parameter S2_HOLD = 3,        // S2 停留拍数
    parameter S3_HOLD = 2         // S3 停留拍数
) (
    input  wire       clk,        // 时钟
    input  wire       rst_n,      // 异步复位（低有效）
    input  wire       start,      // 启动脉冲（单拍，IDLE 接受）
    input  wire [7:0] data_in,    // 条件输入（0xAA 停 S1 / 0xFF 异常跳转）
    output reg        done,       // 序列完成脉冲（单拍）
    output reg        timeout_irq,// 超时中断脉冲（单拍）
    output reg  [1:0] state       // 当前状态（观测/断言用）
);

    // 状态编码
    localparam S_IDLE = 2'd0;
    localparam S1     = 2'd1;
    localparam S2     = 2'd2;
    localparam S3     = 2'd3;

    reg [3:0] hold_cnt;           // 当前状态停留计数（1..HOLD）
    reg [5:0] step_cnt;           // 全局步数计数（start 后递增，超时判定）

    // 状态机主逻辑
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state       <= S_IDLE;
            done        <= 1'b0;
            timeout_irq <= 1'b0;
            hold_cnt    <= 4'd0;
            step_cnt    <= 6'd0;
        end else begin
            // 单拍脉冲默认清零
            done        <= 1'b0;
            timeout_irq <= 1'b0;
            case (state)
                // 空闲：等待启动
                S_IDLE: begin
                    step_cnt <= 6'd0;
                    if (start) begin
                        state    <= S1;
                        hold_cnt <= 4'd1;
                    end
                end
                // 阶段1：停留 S1_HOLD 拍；data_in==0xAA 时停留等待（触发超时保护）
                S1: begin
                    step_cnt <= step_cnt + 1'b1;
                    if (step_cnt >= TIMEOUT) begin
                        state       <= S_IDLE;
                        timeout_irq <= 1'b1;      // 超时保护
                    end else if (data_in == 8'hAA) begin
                        hold_cnt    <= hold_cnt;  // 等待条件（卡住，直到超时）
                    end else if (hold_cnt == S1_HOLD) begin
                        state    <= S2;
                        hold_cnt <= 4'd1;
                    end else begin
                        hold_cnt <= hold_cnt + 1'b1;
                    end
                end
                // 阶段2：停留 S2_HOLD 拍；data_in==0xFF 时异常跳回空闲
                S2: begin
                    step_cnt <= step_cnt + 1'b1;
                    if (step_cnt >= TIMEOUT) begin
                        state       <= S_IDLE;
                        timeout_irq <= 1'b1;      // 超时保护
                    end else if (data_in == 8'hFF) begin
                        state    <= S_IDLE;       // 异常数据，提前终止
                        hold_cnt <= 4'd0;
                    end else if (hold_cnt == S2_HOLD) begin
                        state    <= S3;
                        hold_cnt <= 4'd1;
                    end else begin
                        hold_cnt <= hold_cnt + 1'b1;
                    end
                end
                // 阶段3：停留 S3_HOLD 拍后完成
                S3: begin
                    step_cnt <= step_cnt + 1'b1;
                    if (step_cnt >= TIMEOUT) begin
                        state       <= S_IDLE;
                        timeout_irq <= 1'b1;      // 超时保护
                    end else if (hold_cnt == S3_HOLD) begin
                        state    <= S_IDLE;
                        done     <= 1'b1;         // 序列完成
                    end else begin
                        hold_cnt <= hold_cnt + 1'b1;
                    end
                end
            endcase
        end
    end

endmodule
