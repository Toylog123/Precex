// PreCex - fsm_ctrl L3 缺陷样本 s02（buggy 版，含内联强断言）
// 作者：Toylog | 版本：v0.2 | 功能概述：注入"状态跳转/流程控制错误"缺陷——S3 分支删除 step_cnt 递增语句，
//        进入 S3 后全局步数计数停止增长（黄金实现每拍 +1），跨周期违反步进计数单调性（A6 击穿）；
//        断言内联于模块内（formal 友好写法：always @(posedge clk) 单边沿 + initial 初值，参照 smoke/counter.sv 已验证模式）
// 来源：基于 rtl/fsm_ctrl/fsm_ctrl.sv 注入单点缺陷；内联断言与 rtl/fsm_ctrl/assertions.sv 性质一致（A1-A6）
// 击穿点：A6（步进计数单调性：非空闲阶段 step_cnt 每拍必须 +1）——S3 停留期间 step_cnt 停止增长

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

    // initial 初值：formal 友好（yosys 提取 init 属性，避免任意初始状态引入与缺陷无关的假反例）
    initial begin
        state       = S_IDLE;
        done        = 1'b0;
        timeout_irq = 1'b0;
        hold_cnt    = 4'd0;
        step_cnt    = 6'd0;
    end

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
                // ===== BUG (inject) =====
                // 缺陷：删除了黄金实现的 step_cnt 递增语句（正确行为：S3 分支首行应有
                //       step_cnt <= step_cnt + 1'b1;，与 S1/S2 一致）。
                // 后果：进入 S3 后全局步数计数停止增长（卡在进入 S3 时的值），跨周期违反
                //       A6 断言（非空闲阶段 step_cnt 每拍必须 +1）；同时 S3 内超时判定
                //       使用停滞的 step_cnt，时间越界风险被推迟。
                S3: begin
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
                // ===== /BUG =====
            endcase
        end
    end

    // ------------------------------------------------------------------
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；与 rtl 断言性质 A1-A6 一致）
    // ------------------------------------------------------------------
    reg [1:0] state_d;        // 上周期状态
    reg       start_d;        // 上周期 start
    reg       done_d;         // 上周期 done（单拍脉冲检查）
    reg       tirq_d;         // 上周期 timeout_irq（单拍脉冲检查）
    reg [3:0] hold_cnt_d;     // 上周期停留计数
    reg [5:0] step_cnt_d;     // 上周期步数

    // initial 初值：formal 友好
    initial begin
        state_d    = S_IDLE;
        start_d    = 1'b0;
        done_d     = 1'b0;
        tirq_d     = 1'b0;
        hold_cnt_d = 4'd0;
        step_cnt_d = 6'd0;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state_d    <= S_IDLE;
            start_d    <= 1'b0;
            done_d     <= 1'b0;
            tirq_d     <= 1'b0;
            hold_cnt_d <= 4'd0;
            step_cnt_d <= 6'd0;
        end else begin
            state_d    <= state;
            start_d    <= start;
            done_d     <= done;
            tirq_d     <= timeout_irq;
            hold_cnt_d <= hold_cnt;
            step_cnt_d <= step_cnt;
            // A1 状态跳转合法性：(state_d, state) 必须属于合法跳转集合（含自环）
            case (state_d)
                S_IDLE: assert ((state == S_IDLE) || (state == S1));     // 空闲保持或启动
                S1:     assert ((state == S1) || (state == S2) || (state == S_IDLE));
                S2:     assert ((state == S2) || (state == S3) || (state == S_IDLE));
                S3:     assert ((state == S3) || (state == S_IDLE));
            endcase
            // A2 done 前置：done 仅在 S3 停留满 S3_HOLD 拍时产生（done 与 S3->IDLE 同拍置位，用上拍校验）
            if (done) begin
                assert (state_d == S3);
                assert (hold_cnt_d == S3_HOLD);
            end
            // done 单拍脉冲
            if (done_d) begin
                assert (!done);
            end
            // A3 timeout_irq 前置：仅在非空闲且步数达超时阈值时产生
            if (timeout_irq) begin
                assert (state_d != S_IDLE);
                assert (step_cnt_d >= TIMEOUT);
            end
            // timeout_irq 单拍脉冲
            if (tirq_d) begin
                assert (!timeout_irq);
            end
            // done 与 timeout_irq 互斥
            if (done) begin
                assert (!timeout_irq);
            end
            // A4 停留拍数上界
            case (state)
                S1: assert (hold_cnt <= S1_HOLD);
                S2: assert (hold_cnt <= S2_HOLD);
                S3: assert (hold_cnt <= S3_HOLD);
            endcase
            // A5 启动语义：空闲时 start 生效必须进入 S1
            if (start_d && (state_d == S_IDLE)) begin
                assert (state == S1);
            end
            // A6 步进计数单调性：非空闲阶段 step_cnt 每拍 +1；空闲阶段清零
            // —— 击穿点：buggy 在 S3 停留时 step_cnt 不再 +1，违反 step_cnt == step_cnt_d + 6'd1
            if (state_d == S_IDLE) begin
                assert (step_cnt == 6'd0);
            end else begin
                assert (step_cnt == step_cnt_d + 6'd1);
            end
        end
    end

endmodule
