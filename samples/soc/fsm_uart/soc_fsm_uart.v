// PreCex - SoC 互联场景 3：fsm_ctrl 控制 uart_tx
// 功能概述：序列控制器完成（done 单拍）时触发 UART 发射机发送一字节 0x5A，
//          验证状态机控制器驱动外设发射的协同行为（控制-数据通路互连）。
module soc_fsm_uart #(
    parameter TIMEOUT = 32,
    parameter S1_HOLD = 2,
    parameter S2_HOLD = 3,
    parameter S3_HOLD = 2,
    parameter CLK_FREQ = 50000000,
    parameter BAUD     = 115200
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,
    input  wire [7:0] data_in,
    output wire       done,
    output wire       timeout_irq,
    output wire [1:0] ctrl_state,
    output wire       txd,
    output wire       tx_busy
);

    reg tx_start_r;

    fsm_ctrl #(
        .TIMEOUT(TIMEOUT),
        .S1_HOLD(S1_HOLD),
        .S2_HOLD(S2_HOLD),
        .S3_HOLD(S3_HOLD)
    ) u_fsm (
        .clk        (clk),
        .rst_n      (rst_n),
        .start      (start),
        .data_in    (data_in),
        .done       (done),
        .timeout_irq(timeout_irq),
        .state      (ctrl_state)
    );

    // done 单拍 -> tx_start 单拍（打一拍避免组合环，且 done 与 state==IDLE 同拍）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx_start_r <= 1'b0;
        end else begin
            tx_start_r <= done;
        end
    end

    uart_tx #(
        .CLK_FREQ(CLK_FREQ),
        .BAUD    (BAUD),
        .DATA_W  (8)
    ) u_tx (
        .clk     (clk),
        .rst_n   (rst_n),
        .tx_start(tx_start_r),
        .tx_data (8'h5A),
        .txd     (txd),
        .tx_busy (tx_busy)
    );

endmodule