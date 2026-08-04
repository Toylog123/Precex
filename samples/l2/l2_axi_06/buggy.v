// PreCex - axi_lite_slave L2 缺陷样本 l2_axi_06（buggy 版）
// 作者：Toylog | 版本：v0.1 | 功能概述：注入『复位』类缺陷——axi 复位后读响应错误：复位时 RVALID 改为 1（复位释放后读响应错误，击穿 A8）
// 来源：rtl/axi_lite_slave/axi_lite_slave.sv 单点注入（行 138）| 击穿断言：axi A8（复位释放输出）

// PreCex - axi_lite_slave 黄金基线
// 作者：Toylog | 版本：v0.1 | 功能概述：AXI4-Lite 从机（AW/W/AR/B/R 五通道握手 + 4 个 32 位寄存器读写，WSTRB 字节掩码）
// 说明：可综合风格；写通道一拍应答（AWREADY/WREADY），BVALID 待 AW/W 完成后置位并保持至 BREADY；
//       读通道 ARREADY 一拍应答，RVALID 置位并保持至 RREADY，RDATA 由锁存地址译码

module axi_lite_slave #(
    parameter ADDR_W = 4,             // 地址位宽（低 2 位为字节偏移，[ADDR_W-1:2] 译码 4 个寄存器）
    parameter DATA_W = 32             // 数据位宽
) (
    input  wire                   ACLK,        // 总线时钟
    input  wire                   ARESETN,     // 总线复位（低有效）
    // ---- 写地址通道 ----
    input  wire [ADDR_W-1:0]       S_AXI_AWADDR,
    input  wire                   S_AXI_AWVALID,
    output reg                    S_AXI_AWREADY,
    // ---- 写数据通道 ----
    input  wire [DATA_W-1:0]       S_AXI_WDATA,
    input  wire [DATA_W/8-1:0]     S_AXI_WSTRB,
    input  wire                   S_AXI_WVALID,
    output reg                    S_AXI_WREADY,
    // ---- 写响应通道 ----
    output reg  [1:0]              S_AXI_BRESP,
    output reg                    S_AXI_BVALID,
    input  wire                   S_AXI_BREADY,
    // ---- 读地址通道 ----
    input  wire [ADDR_W-1:0]       S_AXI_ARADDR,
    input  wire                   S_AXI_ARVALID,
    output reg                    S_AXI_ARREADY,
    // ---- 读数据通道 ----
    output reg  [DATA_W-1:0]       S_AXI_RDATA,
    output reg  [1:0]              S_AXI_RRESP,
    output reg                    S_AXI_RVALID,
    input  wire                   S_AXI_RREADY
);

    // 内部握手状态
    reg [ADDR_W-1:0] aw_addr;                // 写地址锁存
    reg [ADDR_W-1:0] ar_addr;                // 读地址锁存
    reg              aw_done;                // 写地址已应答
    reg              w_done;                 // 写数据已应答

    // 4 个 32 位寄存器（地址 0x0/0x4/0x8/0xC）
    reg [DATA_W-1:0] reg0, reg1, reg2, reg3;

    // 按字节掩码写函数
    function [DATA_W-1:0] mask_write(input [DATA_W-1:0] old_d,
                                     input [DATA_W-1:0] new_d,
                                     input [DATA_W/8-1:0] strb);
        integer i;
        begin
            for (i = 0; i < DATA_W/8; i = i + 1) begin
                mask_write[i*8 +: 8] = strb[i] ? new_d[i*8 +: 8] : old_d[i*8 +: 8];
            end
        end
    endfunction

    // ---- 写地址通道：一拍应答，完成写事务后释放 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_AWREADY <= 1'b0;
            aw_done       <= 1'b0;
            aw_addr       <= {ADDR_W{1'b0}};
        end else if (S_AXI_AWVALID && !aw_done) begin
            S_AXI_AWREADY <= 1'b1;             // 应答一拍
            aw_done       <= 1'b1;
            aw_addr       <= S_AXI_AWADDR;
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            S_AXI_AWREADY <= 1'b0;             // 事务完成，释放
            aw_done       <= 1'b0;
        end else begin
            S_AXI_AWREADY <= 1'b0;             // 默认清零，确保只应答一拍
        end
    end

    // ---- 写数据通道：一拍应答，完成写事务后释放 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_WREADY <= 1'b0;
            w_done       <= 1'b0;
        end else if (S_AXI_WVALID && !w_done) begin
            S_AXI_WREADY <= 1'b1;              // 应答一拍
            w_done       <= 1'b1;
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            S_AXI_WREADY <= 1'b0;              // 事务完成，释放
            w_done       <= 1'b0;
        end else begin
            S_AXI_WREADY <= 1'b0;              // 默认清零，确保只应答一拍
        end
    end

    // ---- 寄存器写入：WVALID 且通道空闲（!w_done）时按字节掩码写入选中的寄存器 ----
    // 注意：写入条件用 !w_done 而非 WREADY（WREADY 是滞后一拍的应答输出，会导致写入永远错过）
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            reg0 <= {DATA_W{1'b0}};
            reg1 <= {DATA_W{1'b0}};
            reg2 <= {DATA_W{1'b0}};
            reg3 <= {DATA_W{1'b0}};
        end else if (S_AXI_WVALID && !w_done) begin
            case (S_AXI_AWADDR[ADDR_W-1:2])
                2'd0: reg0 <= mask_write(reg0, S_AXI_WDATA, S_AXI_WSTRB);
                2'd1: reg1 <= mask_write(reg1, S_AXI_WDATA, S_AXI_WSTRB);
                2'd2: reg2 <= mask_write(reg2, S_AXI_WDATA, S_AXI_WSTRB);
                2'd3: reg3 <= mask_write(reg3, S_AXI_WDATA, S_AXI_WSTRB);
            endcase
        end
    end

    // ---- 写响应通道：AW/W 均完成后置位，保持至 BREADY ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_BVALID <= 1'b0;
            S_AXI_BRESP  <= 2'b00;
        end else if (aw_done && w_done && !S_AXI_BVALID) begin
            S_AXI_BVALID <= 1'b1;
            S_AXI_BRESP  <= 2'b00;             // OKAY
        end else if (S_AXI_BVALID && S_AXI_BREADY) begin
            S_AXI_BVALID <= 1'b0;
        end
    end

    // ---- 读地址通道：一拍应答 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_ARREADY <= 1'b0;
            ar_addr       <= {ADDR_W{1'b0}};
        end else if (S_AXI_ARVALID && !S_AXI_RVALID) begin
            S_AXI_ARREADY <= 1'b1;             // 应答一拍
            ar_addr       <= S_AXI_ARADDR;
        end else begin
            S_AXI_ARREADY <= 1'b0;
        end
    end

    // ---- 读数据通道：RVALID 置位保持至 RREADY，RDATA 按锁存地址译码 ----
    always @(posedge ACLK or negedge ARESETN) begin
        if (!ARESETN) begin
            S_AXI_RVALID <= 1'b1;
            S_AXI_RDATA  <= {DATA_W{1'b0}};
            S_AXI_RRESP  <= 2'b00;
        end else if (S_AXI_ARVALID && !S_AXI_RVALID) begin
            S_AXI_RVALID <= 1'b1;
            S_AXI_RRESP  <= 2'b00;             // OKAY
            case (S_AXI_ARADDR[ADDR_W-1:2])
                2'd0: S_AXI_RDATA <= reg0;
                2'd1: S_AXI_RDATA <= reg1;
                2'd2: S_AXI_RDATA <= reg2;
                2'd3: S_AXI_RDATA <= reg3;
            endcase
        end else if (S_AXI_RVALID && S_AXI_RREADY) begin
            S_AXI_RVALID <= 1'b0;
        end
    end


    // ------------------------------------------------------------------
    // 内联强断言（安全子集：immediate assert + 单边沿打拍；源自 rtl/axi_lite_slave/assertions.sv）
    // ------------------------------------------------------------------
    initial begin
        bvalid_d = 1'b0;
        rvalid_d = 1'b0;
        bready_d = 1'b0;
        rready_d = 1'b0;
        aresetn_d = 1'b0;
        aw_done_d = 1'b0;
        w_done_d = 1'b0;
        wdata_d = 1'b0;
        waddr_d = 1'b0;
        wstrb_d = 1'b0;
        rd_exp = 1'b0;
        rd_exp_valid = 1'b0;
    end
// 端口方向/宽度体内声明（Verilog-2001 非 ANSI 风格）

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

    // 环境约束：初始拍处于复位（ARESETN==0），复位释放沿（0->1）输入静默，与弱 tb 复位行为一致；设计内部状态由复位分支初始化（避免 initial 覆盖注入缺陷）
    initial assume (!ARESETN);
    always @(posedge ACLK) begin
        if (!ARESETN) begin
            assume (!S_AXI_AWADDR);
            assume (!S_AXI_AWVALID);
            assume (!S_AXI_WDATA);
            assume (!S_AXI_WSTRB);
            assume (!S_AXI_WVALID);
            assume (!S_AXI_BREADY);
            assume (!S_AXI_ARADDR);
            assume (!S_AXI_ARVALID);
            assume (!S_AXI_RREADY);
        end
    end

endmodule


