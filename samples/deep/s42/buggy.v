// PreCex - fsm_ctrl L3 缺陷样本 s42（buggy 版）
// 作者：Toylog | 版本：v0.1 | 功能概述：注入『边界回绕』类缺陷——超时阈值提前一拍：step_cnt >= TIMEOUT 改 >= TIMEOUT-1（提前触发超时，击穿 A3 前置）
// 来源：rtl/fsm_ctrl/fsm_ctrl.sv 单点注入（行 53）| 击穿断言：fsm_ctrl A3（timeout_irq 前置 step_cnt_d>=TIMEOUT）

// PreCex - fsm_ctrl 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：3 状态序列控制器（S1/S2/S3 分级停留 + 异常跳转 + 全局超时保护，done/timeout_irq 单拍脉冲）
// 说明：可综合风格；IDLE->S1->S2->S3->done；S1 遇 data_in==0xAA 停留等待（触发超时保护），S2 遇 data_in==0xFF 异常跳回 IDLE

module fsm_ctrl #(
    parameter TIMEOUT = 62,       // 全局超时步数（从 start 起计）
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
                    if (step_cnt >= (TIMEOUT - 1'b1)) begin
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


    // ------------------------------------------------------------------
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；源自 rtl/fsm_ctrl/assertions.sv）
    // ------------------------------------------------------------------
    initial begin
        state_d = 1'b0;
        start_d = 1'b0;
        done_d = 1'b0;
        tirq_d = 1'b0;
        hold_cnt_d = 1'b0;
        step_cnt_d = 1'b0;
    end
// 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）

    // 打拍寄存器：用于跨周期跳转/单拍脉冲检查
    reg [1:0] state_d;        // 上周期状态
    reg       start_d;        // 上周期 start
    reg       done_d;         // 上周期 done（单拍脉冲检查）
    reg       tirq_d;         // 上周期 timeout_irq（单拍脉冲检查）
    reg [3:0] hold_cnt_d;     // 上周期停留计数
    reg [5:0] step_cnt_d;     // 上周期步数

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
        end
    end

    // A1 状态跳转合法性（打拍检查）：(state_d, state) 必须属于合法跳转集合（含自环）
    // 合法集合：IDLE->{IDLE,S1}；S1->{S1,S2,IDLE}（0xAA 停留/正常推进/超时）；
    //          S2->{S2,S3,IDLE}（正常推进/0xFF 异常/超时）；S3->{S3,IDLE}（停留/完成/超时）
    always @(posedge clk) begin
        if (rst_n) begin
            case (state_d)
                S_IDLE: assert ((state == S_IDLE) || (state == S1));     // 空闲保持或启动
                S1:     assert ((state == S1) || (state == S2) || (state == S_IDLE));
                S2:     assert ((state == S2) || (state == S3) || (state == S_IDLE));
                S3:     assert ((state == S3) || (state == S_IDLE));
            endcase
        end
    end

    // A2 done 前置条件与单拍脉冲：done 仅在 S3 停留满 S3_HOLD 拍时产生，且为单拍
    // 注意：done 与 S3->IDLE 转换同拍置位（done==1 时 state 已为 IDLE），须用上一拍状态/计数校验
    always @(posedge clk) begin
        if (rst_n && done) begin
            assert (state_d == S3);               // 上一拍状态必须为 S3
            assert (hold_cnt_d == S3_HOLD);       // 且上一拍停留满
        end
    end

    // done 单拍脉冲：上一拍有效则本拍必须已清除（设计默认清零保证）
    always @(posedge clk) begin
        if (rst_n && done_d) begin
            assert (!done);
        end
    end

    // A3 timeout_irq 前置条件：仅在非空闲且步数达超时阈值时产生
    // 注意：timeout_irq 与返回 IDLE 同拍置位，须用上一拍状态/步数校验
    always @(posedge clk) begin
        if (rst_n && timeout_irq) begin
            assert (state_d != S_IDLE);
            assert (step_cnt_d >= TIMEOUT);
        end
    end

    // timeout_irq 单拍脉冲：上一拍有效则本拍必须已清除
    always @(posedge clk) begin
        if (rst_n && tirq_d) begin
            assert (!timeout_irq);
        end
    end

    // done 与 timeout_irq 互斥：完成与超时不得同拍（设计分支互斥，此处留痕）
    always @(posedge clk) begin
        if (rst_n && done) begin
            assert (!timeout_irq);
        end
    end

    // A4 停留拍数上界：各阶段停留计数不得超过对应 HOLD（0xAA 卡 S1 时 hold 保持不越界）
    always @(posedge clk) begin
        if (rst_n) begin
            case (state)
                S1: assert (hold_cnt <= S1_HOLD);
                S2: assert (hold_cnt <= S2_HOLD);
                S3: assert (hold_cnt <= S3_HOLD);
            endcase
        end
    end

    // A5 启动语义：空闲时 start 生效必须进入 S1（非空闲时 start 被忽略，由 A1 合法跳转覆盖）
    always @(posedge clk) begin
        if (rst_n && start_d && (state_d == S_IDLE)) begin
            assert (state == S1);
        end
    end

    // A6 步进计数单调性：非空闲阶段 step_cnt 每拍 +1；空闲阶段清零
    always @(posedge clk) begin
        if (rst_n) begin
            if (state_d == S_IDLE) begin
                assert (step_cnt == 6'd0);        // 空闲清零
            end else begin
                assert (step_cnt == step_cnt_d + 6'd1);  // 运行期单调递增
            end
        end
    end

    // 环境约束：初始拍处于复位（rst_n==0），复位释放沿（0->1）输入静默，与弱 tb 复位行为一致；设计内部状态由复位分支初始化（避免 initial 覆盖注入缺陷）
    initial assume (!rst_n);
    always @(posedge clk) begin
        if (!rst_n) begin
            assume (!start);
            assume (!data_in);
        end
    end

endmodule


