// PreCex - fifo_sync L3 缺陷样本 s04（buggy 版）
// 作者：Toylog | 版本：v0.1 | 功能概述：注入『FIFO 满空』类缺陷——半满标志比较 >= 改 >（count==DEPTH/2 时半满错误为 0，击穿 A5）
// 来源：rtl/fifo_sync/fifo_sync.sv 单点注入（行 35）| 击穿断言：fifo_sync A5（half_full==(count>=DEPTH/2)）

// PreCex - fifo_sync 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：参数化同步 FIFO（读优先语义，full/empty/半满输出，count 计数防指针回绕错）
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
    assign half_full = (count > (DEPTH >> 1));

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

    // formal 初值约束（避免任意初始状态空洞反例；仿真中与复位时序兼容）
    initial begin
        head = 1'b0;
        tail = 1'b0;
        count = 1'b0;
    end
endmodule
