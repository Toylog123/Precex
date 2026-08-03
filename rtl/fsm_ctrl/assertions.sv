// PreCex - fsm_ctrl 黄金基线强断言（安全子集写法：always 块内 immediate assert + 寄存器打拍）
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖状态跳转合法性、done 前置/单拍、超时中断前置/单拍/互斥、停留拍数上界、启动进入、步进计数单调性 6 条性质
// 说明：本文件为独立模块，由 tb 显式实例化；内部信号通过 tb 分层引用 uut.xxx 接入

module fsm_ctrl_assert #(
    parameter TIMEOUT = 32,       // 全局超时步数（与设计一致）
    parameter S1_HOLD = 2,        // S1 停留拍数
    parameter S2_HOLD = 3,        // S2 停留拍数
    parameter S3_HOLD = 2         // S3 停留拍数
) (
    clk, rst_n, start, data_in,
    done, timeout_irq, state,
    hold_cnt, step_cnt
);

    // 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）
    input  wire       clk;
    input  wire       rst_n;
    input  wire       start;
    input  wire [7:0] data_in;
    input  wire       done;
    input  wire       timeout_irq;
    input  wire [1:0] state;
    input  wire [3:0] hold_cnt;
    input  wire [5:0] step_cnt;

    // 状态编码（与设计一致）
    localparam S_IDLE = 2'd0;
    localparam S1     = 2'd1;
    localparam S2     = 2'd2;
    localparam S3     = 2'd3;

    // 打拍寄存器：用于跨周期跳转/单拍脉冲检查
    reg [1:0] state_d;        // 上周期状态
    reg       start_d;        // 上周期 start
    reg       done_d;         // 上周期 done（单拍脉冲检查）
    reg       tirq_d;         // 上周期 timeout_irq（单拍脉冲检查）
    reg [3:0] hold_cnt_d;     // 上周期停留计数
    reg [5:0] step_cnt_d;     // 上周期步数

    always @(posedge clk or negedge rst_n) begin
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
    always @(posedge clk or negedge rst_n) begin
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
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && done) begin
            assert (state_d == S3);               // 上一拍状态必须为 S3
            assert (hold_cnt_d == S3_HOLD);       // 且上一拍停留满
        end
    end

    // done 单拍脉冲：上一拍有效则本拍必须已清除（设计默认清零保证）
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && done_d) begin
            assert (!done);
        end
    end

    // A3 timeout_irq 前置条件：仅在非空闲且步数达超时阈值时产生
    // 注意：timeout_irq 与返回 IDLE 同拍置位，须用上一拍状态/步数校验
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && timeout_irq) begin
            assert (state_d != S_IDLE);
            assert (step_cnt_d >= TIMEOUT);
        end
    end

    // timeout_irq 单拍脉冲：上一拍有效则本拍必须已清除
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && tirq_d) begin
            assert (!timeout_irq);
        end
    end

    // done 与 timeout_irq 互斥：完成与超时不得同拍（设计分支互斥，此处留痕）
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && done) begin
            assert (!timeout_irq);
        end
    end

    // A4 停留拍数上界：各阶段停留计数不得超过对应 HOLD（0xAA 卡 S1 时 hold 保持不越界）
    always @(posedge clk or negedge rst_n) begin
        if (rst_n) begin
            case (state)
                S1: assert (hold_cnt <= S1_HOLD);
                S2: assert (hold_cnt <= S2_HOLD);
                S3: assert (hold_cnt <= S3_HOLD);
            endcase
        end
    end

    // A5 启动语义：空闲时 start 生效必须进入 S1（非空闲时 start 被忽略，由 A1 合法跳转覆盖）
    always @(posedge clk or negedge rst_n) begin
        if (rst_n && start_d && (state_d == S_IDLE)) begin
            assert (state == S1);
        end
    end

    // A6 步进计数单调性：非空闲阶段 step_cnt 每拍 +1；空闲阶段清零
    always @(posedge clk or negedge rst_n) begin
        if (rst_n) begin
            if (state_d == S_IDLE) begin
                assert (step_cnt == 6'd0);        // 空闲清零
            end else begin
                assert (step_cnt == step_cnt_d + 6'd1);  // 运行期单调递增
            end
        end
    end

endmodule
