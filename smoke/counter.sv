// PreCex - Gate-1 smoke test: buggy 2-bit counter with cross-cycle bug
// 作者：Toylog | 版本：v0.2 | 功能概述：L3 样本原型验证（弱tb过 + formal败），断言改用 Gate-1 收敛安全子集
// 缺陷类型：状态跳转错误（cnt==2 时本应跳 3，实际跳 0）
// 断言写法说明：不使用 assert property（双工具不兼容），改用
//   immediate assert + 寄存器打拍 + 条件门控（iverilog 12 与 yosys -formal 双工具兼容）

module counter(
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    output reg  [1:0] cnt
);

    // 时序逻辑（注入缺陷：2->0，正确应为 2->3）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 2'd0;
        end else if (en) begin
            if (cnt == 2'd2) begin
                cnt <= 2'd0;  // BUG: 应为 2'd3
            end else begin
                cnt <= cnt + 1'b1;
            end
        end
    end

    // ---- 跨周期断言（安全子集：immediate assert + 打拍，不依赖 assert property）----
    // 性质：en 有效的那一拍，下一周期 cnt 必须为 当前值+1
    // en_d/cnt_d 在 posedge 打拍：en_d=1 表示上一拍 en 有效，cnt_d 为上一拍计数值
    // buggy 设计在 cnt==2 时跳 0（应为 3），断言 cnt == cnt_d + 1 将在下一拍被击穿
    reg        en_d;
    reg  [1:0] cnt_d;

    // 初始状态（formal 友好：yosys 提取为 init 属性，为断言提供合法初值，
    // 避免"任意初始状态"导致的反例与设计缺陷无关；iverilog 仿真中与 tb 复位时序一致）
    initial begin
        cnt   = 2'd0;
        en_d  = 1'b0;
        cnt_d = 2'd0;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            en_d <= 1'b0;
        end else begin
            en_d <= en;
            cnt_d <= cnt;
            if (en_d) begin
                assert (cnt == cnt_d + 1'b1);
            end
        end
    end

endmodule
