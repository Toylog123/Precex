// PreCex - axi_lite_slave 黄金基线强断言（安全子集写法：always 块内 immediate assert + 寄存器打拍）
// 作者：Toylog | 版本：v0.1 | 功能概述：覆盖 AW/WREADY 一拍应答、BVALID 前置/保持、RVALID 保持、读数据译码、写数据生效 8 条性质
// 说明：本文件为独立模块，由 tb 显式实例化；内部信号通过 tb 分层引用 uut.xxx 接入

module axi_lite_slave_assert #(
    parameter ADDR_W = 4,
    parameter DATA_W = 32
) (
    ACLK, ARESETN,
    S_AXI_AWADDR, S_AXI_AWVALID, S_AXI_AWREADY,
    S_AXI_WDATA, S_AXI_WSTRB, S_AXI_WVALID, S_AXI_WREADY,
    S_AXI_BRESP, S_AXI_BVALID, S_AXI_BREADY,
    S_AXI_ARADDR, S_AXI_ARVALID, S_AXI_ARREADY,
    S_AXI_RDATA, S_AXI_RRESP, S_AXI_RVALID, S_AXI_RREADY,
    aw_done, w_done, aw_addr, ar_addr,
    reg0, reg1, reg2, reg3
);

    // 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）
    input  wire             ACLK;
    input  wire             ARESETN;
    input  wire [ADDR_W-1:0] S_AXI_AWADDR;
    input  wire             S_AXI_AWVALID;
    input  wire             S_AXI_AWREADY;
    input  wire [DATA_W-1:0] S_AXI_WDATA;
    input  wire [DATA_W/8-1:0] S_AXI_WSTRB;
    input  wire             S_AXI_WVALID;
    input  wire             S_AXI_WREADY;
    input  wire [1:0]       S_AXI_BRESP;
    input  wire             S_AXI_BVALID;
    input  wire             S_AXI_BREADY;
    input  wire [ADDR_W-1:0] S_AXI_ARADDR;
    input  wire             S_AXI_ARVALID;
    input  wire             S_AXI_ARREADY;
    input  wire [DATA_W-1:0] S_AXI_RDATA;
    input  wire [1:0]       S_AXI_RRESP;
    input  wire             S_AXI_RVALID;
    input  wire             S_AXI_RREADY;
    input  wire             aw_done;
    input  wire             w_done;
    input  wire [ADDR_W-1:0] aw_addr;
    input  wire [ADDR_W-1:0] ar_addr;
    input  wire [DATA_W-1:0] reg0, reg1, reg2, reg3;

    // 打拍寄存器
    reg bvalid_d;                 // 上周期 BVALID
    reg rvalid_d;                 // 上周期 RVALID
    reg bready_d;                 // 上周期 BREADY（用于排除刚应答拍）
    reg rready_d;                 // 上周期 RREADY
    reg aresetn_d;                // 上周期 ARESETN（复位释放沿检测）
    reg aw_done_d;                // 上周期 aw_done（排除应答拍：应答拍两者同拍置位）
    reg w_done_d;                 // 上周期 w_done
    reg [DATA_W-1:0] wdata_d;     // 最近一次写数据（写入拍锁存）
    reg [ADDR_W-1:0] waddr_d;     // 最近一次写地址
    reg [DATA_W/8-1:0] wstrb_d;   // 最近一次写掩码
    reg [DATA_W-1:0] rd_exp;      // 读请求拍按地址译码的期望 RDATA（A6 快照）
    reg              rd_exp_valid;// rd_exp 有效（读请求已锁存）

    always @(posedge ACLK) begin
        if (!ARESETN) begin
            bvalid_d  <= 1'b0;
            rvalid_d  <= 1'b0;
            bready_d  <= 1'b0;
            rready_d  <= 1'b0;
            aresetn_d <= 1'b0;
            aw_done_d <= 1'b0;
            w_done_d  <= 1'b0;
            wdata_d   <= {DATA_W{1'b0}};
            waddr_d   <= {ADDR_W{1'b0}};
            wstrb_d   <= {(DATA_W/8){1'b0}};
            rd_exp    <= {DATA_W{1'b0}};
            rd_exp_valid <= 1'b0;
        end else begin
            bvalid_d  <= S_AXI_BVALID;
            rvalid_d  <= S_AXI_RVALID;
            bready_d  <= S_AXI_BREADY;
            rready_d  <= S_AXI_RREADY;
            aresetn_d <= ARESETN;
            aw_done_d <= aw_done;
            w_done_d  <= w_done;
            if (S_AXI_WVALID && !w_done) begin
                wdata_d <= S_AXI_WDATA;
                waddr_d <= S_AXI_AWADDR;       // 写入拍用当前输入地址，与设计译码同源
                wstrb_d <= S_AXI_WSTRB;
            end
            // 读请求应答拍：按输入地址锁存期望 RDATA 快照
            if (S_AXI_ARVALID && !S_AXI_RVALID) begin
                rd_exp_valid <= 1'b1;
                case (S_AXI_ARADDR[ADDR_W-1:2])
                    2'd0: rd_exp <= reg0;
                    2'd1: rd_exp <= reg1;
                    2'd2: rd_exp <= reg2;
                    2'd3: rd_exp <= reg3;
                endcase
            end else if (S_AXI_RVALID && S_AXI_RREADY) begin
                rd_exp_valid <= 1'b0;           // 应答完成清除快照
            end
        end
    end

    // A1 写地址一拍应答：aw_done 连续两拍有效（事务进行中）时 AWREADY 必须为 0
    // （应答拍 aw_done 与 AWREADY 同拍置位，属合法一拍应答，故排除）
    always @(posedge ACLK) begin
        if (ARESETN && aw_done && aw_done_d) begin
            assert (!S_AXI_AWREADY);
        end
    end

    // A2 写数据一拍应答：w_done 连续两拍有效（事务进行中）时 WREADY 必须为 0
    always @(posedge ACLK) begin
        if (ARESETN && w_done && w_done_d) begin
            assert (!S_AXI_WREADY);
        end
    end

    // A3 BVALID 前置条件：写响应有效时 AW/W 必须均已完成
    always @(posedge ACLK) begin
        if (ARESETN && S_AXI_BVALID) begin
            assert (aw_done && w_done);
        end
    end

    // A4 BVALID 保持：上周期有效、本周期无 BREADY 且上周期未应答时，本周期必须仍有效
    always @(posedge ACLK) begin
        if (ARESETN && bvalid_d && !S_AXI_BREADY && !bready_d) begin
            assert (S_AXI_BVALID);
        end
    end

    // A5 RVALID 保持：上周期有效、本周期无 RREADY 且上周期未应答时，本周期必须仍有效
    always @(posedge ACLK) begin
        if (ARESETN && rvalid_d && !S_AXI_RREADY && !rready_d) begin
            assert (S_AXI_RVALID);
        end
    end

    // A6 读数据译码正确：RVALID 有效时 RDATA 必须等于读请求拍锁存的期望快照
    // （排除 ARVALID 同拍：新读请求拍 RDATA 按新地址更新但快照/ar_addr 仍为旧值，非阻塞窗口不查）
    always @(posedge ACLK) begin
        if (ARESETN && S_AXI_RVALID && !S_AXI_ARVALID && rd_exp_valid) begin
            assert (S_AXI_RDATA == rd_exp);
        end
    end

    // A7 写数据生效（跨周期）：全字节掩码写入时，BVALID 后寄存器必须等于写数据
    // （掩码写（WSTRB 非全 1）只更新部分字节，无法与原始数据整体比对，故仅全掩码时检查）
    always @(posedge ACLK) begin
        if (ARESETN && S_AXI_BVALID && (wstrb_d == {(DATA_W/8){1'b1}})) begin
            case (waddr_d[ADDR_W-1:2])
                2'd0: assert (reg0 == wdata_d);
                2'd1: assert (reg1 == wdata_d);
                2'd2: assert (reg2 == wdata_d);
                2'd3: assert (reg3 == wdata_d);
            endcase
        end
    end

    // A8 复位输出：复位释放当拍（ARESETN 上升沿）所有 valid/ready 必须为 0
    // （复位期间输出为 X/未稳定，故只在释放沿检查）
    always @(posedge ACLK) begin
        if (ARESETN && !aresetn_d) begin
            assert (!S_AXI_AWREADY);
            assert (!S_AXI_WREADY);
            assert (!S_AXI_BVALID);
            assert (!S_AXI_ARREADY);
            assert (!S_AXI_RVALID);
        end
    end

endmodule
