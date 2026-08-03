// PreCex - fsm_ctrl 黄金基线弱 tb
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖正常序列完成/异常数据跳回/超时保护/非空闲忽略 start/复位行为，触发 A1-A6 断言，应全绿
// 时序说明：负沿驱动输入、负沿采样输出（跨过 NBA 区，状态已稳定）；S1 遇 0xAA 停留、S2 遇 0xFF 跳回
`timescale 1ns / 1ps

module tb_fsm_ctrl;

    localparam TIMEOUT = 32;
    localparam S1_HOLD = 2;
    localparam S2_HOLD = 3;
    localparam S3_HOLD = 2;

    localparam S_IDLE = 2'd0;
    localparam S1     = 2'd1;
    localparam S2     = 2'd2;
    localparam S3     = 2'd3;

    reg        clk      = 0;
    reg        rst_n    = 0;
    reg        start    = 0;
    reg  [7:0] data_in  = 0;
    wire       done;
    wire       timeout_irq;
    wire [1:0] state;

    integer k;

    // 设计实例
    fsm_ctrl #(
        .TIMEOUT (TIMEOUT),
        .S1_HOLD (S1_HOLD),
        .S2_HOLD (S2_HOLD),
        .S3_HOLD (S3_HOLD)
    ) uut (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start),
        .data_in     (data_in),
        .done        (done),
        .timeout_irq (timeout_irq),
        .state       (state)
    );

    // 断言实例：内部信号通过分层引用接入（注意实例名必须为 uut）
    fsm_ctrl_assert #(
        .TIMEOUT (TIMEOUT),
        .S1_HOLD (S1_HOLD),
        .S2_HOLD (S2_HOLD),
        .S3_HOLD (S3_HOLD)
    ) u_assert (
        .clk         (clk),
        .rst_n       (rst_n),
        .start       (start),
        .data_in     (data_in),
        .done        (done),
        .timeout_irq (timeout_irq),
        .state       (state),
        .hold_cnt    (uut.hold_cnt),
        .step_cnt    (uut.step_cnt)
    );

    // 时钟 10ns
    always #5 clk = ~clk;

    // 任务：在下一个时钟下降沿校验状态/done/timeout_irq（负沿采样，跨过 NBA 区）
    task check_neg(input [1:0] exp_state, input exp_done, input exp_tirq);
        begin
            @(negedge clk);
            if (state !== exp_state)
                $fatal(1, "FAIL: state expect %0d got %0d", exp_state, state);
            if (done !== exp_done)
                $fatal(1, "FAIL: done expect %0b got %0b (state=%0d)", exp_done, done, state);
            if (timeout_irq !== exp_tirq)
                $fatal(1, "FAIL: timeout_irq expect %0b got %0b (state=%0d)", exp_tirq, timeout_irq, state);
        end
    endtask

    // 任务：发起一次启动（data_in 一并给定）
    task launch(input [7:0] din);
        begin
            @(negedge clk);
            start   = 1'b1;
            data_in = din;
            @(negedge clk);
            start = 1'b0;
        end
    endtask

    // 主测试流程
    initial begin
        // ===== 复位 =====
        rst_n = 0;
        #30 rst_n = 1;
        check_neg(S_IDLE, 1'b0, 1'b0);   // 复位后空闲，无脉冲
        $display("INFO: reset OK, state=IDLE");

        // ===== 场景1：正常序列 S1->S2->S3->done，S1 期间脉冲 start 验证非空闲忽略 =====
        // 说明：launch 的第二个负沿占用 S1 首个采样沿，故每个状态在观测序列中比停留拍数少出现 1 次
        launch(8'h00);
        check_neg(S1, 1'b0, 1'b0);       // S1（hold 第 2 拍）
        // 注入 start 脉冲（落在 S2 窗口，应被忽略，不打断流程）
        @(negedge clk);
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        check_neg(S2, 1'b0, 1'b0);       // S2（start 未生效，流程照常推进）
        check_neg(S3, 1'b0, 1'b0);
        check_neg(S3, 1'b0, 1'b0);
        check_neg(S_IDLE, 1'b1, 1'b0);   // 完成：done 单拍脉冲（与回 IDLE 同拍）
        check_neg(S_IDLE, 1'b0, 1'b0);   // done 已清除
        $display("INFO: normal sequence done OK (start ignored during non-IDLE)");

        // ===== 场景2a：S2 遇 0xFF 异常跳回 IDLE =====
        launch(8'h00);
        check_neg(S1, 1'b0, 1'b0);
        check_neg(S2, 1'b0, 1'b0);
        @(negedge clk);
        data_in = 8'hFF;                 // S2 期间注入异常数据
        check_neg(S_IDLE, 1'b0, 1'b0);   // 异常跳回 IDLE，无 done/超时
        check_neg(S_IDLE, 1'b0, 1'b0);   // 稳定空闲
        $display("INFO: abort on 0xFF OK");

        // ===== 场景2b：异常跳转后重新启动可正常完成 =====
        launch(8'h00);
        check_neg(S1, 1'b0, 1'b0);
        check_neg(S2, 1'b0, 1'b0);
        check_neg(S2, 1'b0, 1'b0);
        check_neg(S2, 1'b0, 1'b0);
        check_neg(S3, 1'b0, 1'b0);
        check_neg(S3, 1'b0, 1'b0);
        check_neg(S_IDLE, 1'b1, 1'b0);
        check_neg(S_IDLE, 1'b0, 1'b0);
        $display("INFO: restart after abort OK");

        // ===== 场景3：S1 卡 0xAA 触发全局超时保护 =====
        launch(8'hAA);                   // 0xAA 令 S1 停留等待（同时隐式验证非空闲 start 被忽略）
        check_neg(S1, 1'b0, 1'b0);       // 进入 S1（hold 卡住）
        for (k = 0; k < 31; k = k + 1) begin
            check_neg(S1, 1'b0, 1'b0);   // 持续卡在 S1（共 32 个采样拍），期间不产生 done
        end
        check_neg(S_IDLE, 1'b0, 1'b1);   // 超时：回 IDLE + timeout_irq 单拍脉冲
        check_neg(S_IDLE, 1'b0, 1'b0);   // timeout_irq 已清除
        $display("INFO: timeout protection OK (step_cnt=%0d)", uut.step_cnt);

        // ===== 全部通过 =====
        $display("PASS: fsm_ctrl weak testbench passed (golden)");
        $finish;
    end

    // 仿真超时保护
    initial begin
        #100000;
        $display("FAIL: simulation timeout");
        $finish;
    end

endmodule
