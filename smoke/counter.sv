// PreCex - Gate-1 smoke test: buggy 2-bit counter with cross-cycle bug
// 作者：Toylog | 版本：v0.1 | 功能概述：L3 样本原型验证（弱tb过 + formal败）
// 缺陷类型：状态跳转错误（cnt==2 时本应跳 3，实际跳 0）

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

    // 强断言：en 使能时，下一周期 cnt 应为当前值 +1（跨周期性质）
    // 该断言在 buggy 版本上应被形式验证击穿（产生反例）
    assert property (@(posedge clk) disable iff (!rst_n)
        (en == 1'b1) |-> ##1 (cnt == $past(cnt) + 1'b1));

endmodule
