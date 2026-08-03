// PreCex - fifo_sync L3 缺陷样本 s01（golden 版，含内联强断言）
// 作者：Toylog | 版本：v0.2 | 功能概述：参数化同步 FIFO 黄金基线（读优先语义，full/empty/半满输出，count 计数防指针回绕错）；
//        断言内联于模块内（formal 友好写法：always @(posedge clk) 单边沿 + initial 初值，参照 smoke/counter.sv 已验证模式）
// 来源：设计逻辑为 rtl/fifo_sync/fifo_sync.sv 的黄金基线拷贝（参数 DATA_W=8/DEPTH=8 与 rtl 默认一致）；
//        内联断言与 rtl/fifo_sync/assertions.sv 性质一致（A1-A5）
// 说明：可综合风格；读优先：同拍读写且满/空时以读/写自身合法性为准，count 保持守恒

module fifo_sync #(
    parameter DATA_W = 8,          // 数据位宽
    parameter DEPTH  = 8           // 深度（应为 2 的幂）
) (
    input  wire             clk,   // 时钟
    input  wire             rst_n, // 异步复位（低有效）
    input  wire             wr_en, // 写使能
    input  wire             rd_en, // 读使能
    input  wire [DATA_W-1:0] din,  // 写数据
    output reg  [DATA_W-1:0] dout, // 读数据
    output wire             full,  // 满标志
    output wire             empty, // 空标志
    output wire             half_full // 半满标志（count >= DEPTH/2）
);

    localparam ADDR_W = $clog2(DEPTH);   // 指针位宽
    localparam CNT_W  = ADDR_W + 1;      // count 位宽（需容纳 DEPTH）

    // 存储体与读写指针
    reg [DATA_W-1:0] mem [0:DEPTH-1];
    reg [ADDR_W-1:0] head;              // 读指针
    reg [ADDR_W-1:0] tail;              // 写指针
    reg [CNT_W-1:0]  count;             // 已存元素数（直接计数，杜绝指针回绕错）

    // 实际生效的读写
    wire can_wr = wr_en && !full;
    wire can_rd = rd_en && !empty;

    assign full      = (count == DEPTH);
    assign empty     = (count == 0);
    assign half_full = (count >= (DEPTH >> 1));

    // initial 初值：formal 友好（yosys 提取 init 属性，避免任意初始状态引入与缺陷无关的假反例）
    initial begin
        head  = {ADDR_W{1'b0}};
        tail  = {ADDR_W{1'b0}};
        count = {CNT_W{1'b0}};
        dout  = {DATA_W{1'b0}};
    end

    // 时序逻辑：指针与计数更新
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            head  <= {ADDR_W{1'b0}};
            tail  <= {ADDR_W{1'b0}};
            count <= {CNT_W{1'b0}};
            dout  <= {DATA_W{1'b0}};
        end else begin
            // 写：非满时写入 tail 位置并回绕
            if (can_wr) begin
                mem[tail] <= din;
                tail      <= tail + 1'b1;
            end
            // 读：非空时读出 head 位置并回绕
            if (can_rd) begin
                dout  <= mem[head];
                head  <= head + 1'b1;
            end
            // 计数守恒：同拍读写 count 不变
            if (can_wr && can_rd) begin
                count <= count;
            end else if (can_wr) begin
                count <= count + 1'b1;
            end else if (can_rd) begin
                count <= count - 1'b1;
            end
        end
    end

    // ------------------------------------------------------------------
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；与 rtl 断言性质 A1-A5 一致）
    // ------------------------------------------------------------------
    reg        full_d;               // 上周期满标志
    reg        empty_d;              // 上周期空标志
    reg        wr_en_d;              // 上周期写请求
    reg        rd_en_d;              // 上周期读请求
    reg [CNT_W-1:0] count_d;         // 上周期 count
    reg [1:0]       delta_d;         // 上周期实际净增减量（2 位补码）

    // 组合：本周期实际净增减量 = can_wr - can_rd（2 位补码表示）
    wire [1:0] delta = (can_wr ? 2'b01 : 2'b00) - (can_rd ? 2'b01 : 2'b00);

    // initial 初值：formal 友好（yosys 提取 init 属性，避免任意初始状态引入无关反例）；iverilog 中与复位后一致
    initial begin
        full_d  = 1'b0;
        empty_d = 1'b0;
        wr_en_d = 1'b0;
        rd_en_d = 1'b0;
        count_d = {CNT_W{1'b0}};
        delta_d = 2'b00;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            full_d  <= 1'b0;
            empty_d <= 1'b0;
            wr_en_d <= 1'b0;
            rd_en_d <= 1'b0;
            count_d <= {CNT_W{1'b0}};
            delta_d <= 2'b00;
        end else begin
            full_d  <= full;
            empty_d <= empty;
            wr_en_d <= wr_en;
            rd_en_d <= rd_en;
            count_d <= count;
            delta_d <= delta;
            // A1 满时不写（使能排除 rd_en_d：满时写拒但同拍读合法，count -1，避免误报）
            if (full_d && wr_en_d && !rd_en_d) begin
                assert (count == DEPTH);
            end
            // A2 空时不读（使能排除 wr_en_d：空时读拒但同拍写合法，count +1，避免误报）
            if (empty_d && rd_en_d && !wr_en_d) begin
                assert (count == 0);
            end
            // A3 指针永不越界
            assert (head < DEPTH);
            assert (tail < DEPTH);
            // A4 count 增量守恒
            if (delta_d == 2'b00) begin
                assert (count == count_d);          // 同拍读写或不动作：count 不变
            end else if (delta_d == 2'b01) begin
                assert (count == count_d + 1'b1);   // 仅写：count +1
            end else if (delta_d == 2'b11) begin    // -1 的补码
                assert (count == count_d - 1'b1);   // 仅读：count -1
            end
            // A5 半满标志正确性
            assert (half_full == (count >= (DEPTH >> 1)));
        end
    end

endmodule
