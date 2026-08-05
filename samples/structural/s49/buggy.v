// PreCex - fifo_sync L3 缺陷样本 s49（buggy 版）
// 作者：Toylog | 版本：v0.1 | 功能概述：注入『边界判断』类缺陷——half_full 半满边界改写（count > DEPTH/2 误判，修复需恢复 >= 边界 guard_boundary）
// 来源：rtl/fifo_sync/fifo_sync.sv 单点注入（行 1）| 击穿断言：fifo_sync A5（half_full == (count >= DEPTH/2)）

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
    assign half_full = (count >  (DEPTH >> 1));

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
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；源自 rtl/fifo_sync/assertions.sv）
    // ------------------------------------------------------------------
    initial begin
        full_d = 1'b0;
        empty_d = 1'b0;
        wr_en_d = 1'b0;
        rd_en_d = 1'b0;
        count_d = 1'b0;
        delta_d = 1'b0;
        tail_d = 1'b0;
        can_wr_d = 1'b0;
    end
// 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格，兼容 iverilog/yosys）

    reg        full_d;               // 上周期满标志
    reg        empty_d;              // 上周期空标志
    reg        wr_en_d;              // 上周期写请求
    reg        rd_en_d;              // 上周期读请求
    reg [CNT_W-1:0] count_d;         // 上周期 count
    reg [1:0]       delta_d;         // 上周期实际净增减量（打拍后的 2 位补码）
    reg [ADDR_W-1:0] tail_d;         // 上周期写指针（A6 写指针推进检查）
    reg             can_wr_d;        // 上周期写有效（A6 用）

    // 组合：本周期实际净增减量 = can_wr - can_rd（2 位补码表示）
    wire [1:0] delta = (can_wr ? 2'b01 : 2'b00) - (can_rd ? 2'b01 : 2'b00);

    // 打拍逻辑
    always @(posedge clk) begin
        if (!rst_n) begin
            full_d  <= 1'b0;
            empty_d <= 1'b0;
            wr_en_d <= 1'b0;
            rd_en_d <= 1'b0;
            count_d <= {CNT_W{1'b0}};
            delta_d <= 2'b00;
            tail_d  <= {ADDR_W{1'b0}};
            can_wr_d <= 1'b0;
        end else begin
            full_d  <= full;
            empty_d <= empty;
            wr_en_d <= wr_en;
            rd_en_d <= rd_en;
            count_d <= count;
            delta_d <= delta;
            tail_d  <= tail;
            can_wr_d <= can_wr;
        end
    end

    // A1 满时不写：上周期满且上周期请求写 → 写被拒绝，本周期 count 必须保持满值（防溢出/回绕）
    // （使能排除 rd_en_d：满时写拒但同拍读合法，count -1，避免误报）
    always @(posedge clk) begin
        if (!rst_n) begin
            // 复位期不检查
        end else if (full_d && wr_en_d && !rd_en_d) begin
            assert (count == DEPTH);
        end
    end

    // A2 空时不读：上周期已空且上周期请求读 → 读被拒绝，本周期 count 必须保持 0（防下溢）
    // （使能排除 wr_en_d：空时读拒但同拍写合法，count +1，避免误报）
    always @(posedge clk) begin
        if (!rst_n) begin
            // 复位期不检查
        end else if (empty_d && rd_en_d && !wr_en_d) begin
            assert (count == 0);
        end
    end

    // A3 指针永不越界 + 复位值正确：head/tail 始终 < DEPTH（防回绕错）；复位期必须归 0（抓复位值缺陷）
    always @(posedge clk) begin
        if (!rst_n) begin
            assert (head == {ADDR_W{1'b0}});
            assert (tail == {ADDR_W{1'b0}});
        end else begin
            assert (head < DEPTH);
            assert (tail < DEPTH);
        end
    end

    // A4 count 增量守恒（打拍两拍）：count 变化量必须恰好等于 (can_wr - can_rd)
    always @(posedge clk) begin
        if (rst_n) begin
            if (delta_d == 2'b00) begin
                assert (count == count_d);          // 同拍读写或不动作：count 不变
            end else if (delta_d == 2'b01) begin
                assert (count == count_d + 1'b1);   // 仅写：count +1
            end else if (delta_d == 2'b11) begin    // -1 的补码
                assert (count == count_d - 1'b1);   // 仅读：count -1
            end
        end
    end

    // A5 半满标志正确性：half_full == (count >= DEPTH/2)
    always @(posedge clk) begin
        if (rst_n) begin
            assert (half_full == (count >= (DEPTH >> 1)));
        end
    end

    // A6 写指针推进：can_wr 写成功拍后，下一拍 tail 必须 +1（抓写指针不回绕/同址覆写）
    always @(posedge clk) begin
        if (rst_n) begin
            if (can_wr_d) begin
                assert (tail == tail_d + 1'b1);
            end
        end
    end

    // 环境约束：初始拍处于复位（rst_n==0），复位释放沿（0->1）输入静默，与弱 tb 复位行为一致；设计内部状态由复位分支初始化（避免 initial 覆盖注入缺陷）
    initial assume (!rst_n);
    always @(posedge clk) begin
        if (!rst_n) begin
            assume (!wr_en);
            assume (!rd_en);
        end
    end

endmodule


