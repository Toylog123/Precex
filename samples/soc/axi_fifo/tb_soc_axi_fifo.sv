// PreCex - SoC 场景 2 tb：AXI 写 -> FIFO 读回
`timescale 1ns / 1ps
module tb_soc_axi_fifo;

    localparam ADDR_W = 4;
    localparam DATA_W = 32;

    reg  ACLK = 0;
    reg  ARESETN = 0;
    reg  [ADDR_W-1:0] S_AXI_AWADDR = 0;
    reg  S_AXI_AWVALID = 0;
    wire S_AXI_AWREADY;
    reg  [DATA_W-1:0] S_AXI_WDATA = 0;
    reg  [DATA_W/8-1:0] S_AXI_WSTRB = 4'hF;
    reg  S_AXI_WVALID = 0;
    wire S_AXI_WREADY;
    wire [1:0] S_AXI_BRESP;
    wire S_AXI_BVALID;
    reg  S_AXI_BREADY = 0;
    reg  [ADDR_W-1:0] S_AXI_ARADDR = 0;
    reg  S_AXI_ARVALID = 0;
    wire S_AXI_ARREADY;
    wire [DATA_W-1:0] S_AXI_RDATA;
    wire [1:0] S_AXI_RRESP;
    wire S_AXI_RVALID;
    reg  S_AXI_RREADY = 0;
    reg  fifo_rd_en = 0;
    wire [7:0] fifo_dout;
    wire fifo_full, fifo_empty, fifo_half_full;

    integer recv_cnt = 0;
    reg [7:0] exp0 = 8'hAB;
    reg [7:0] exp1 = 8'hCD;
    reg [7:0] got0 = 0;
    reg [7:0] got1 = 0;

    soc_axi_fifo #(
        .ADDR_W(ADDR_W),
        .DATA_W(DATA_W),
        .FIFO_DEPTH(8)
    ) uut (
        .ACLK        (ACLK),
        .ARESETN     (ARESETN),
        .S_AXI_AWADDR(S_AXI_AWADDR),
        .S_AXI_AWVALID(S_AXI_AWVALID),
        .S_AXI_AWREADY(S_AXI_AWREADY),
        .S_AXI_WDATA (S_AXI_WDATA),
        .S_AXI_WSTRB (S_AXI_WSTRB),
        .S_AXI_WVALID(S_AXI_WVALID),
        .S_AXI_WREADY(S_AXI_WREADY),
        .S_AXI_BRESP (S_AXI_BRESP),
        .S_AXI_BVALID(S_AXI_BVALID),
        .S_AXI_BREADY(S_AXI_BREADY),
        .S_AXI_ARADDR(S_AXI_ARADDR),
        .S_AXI_ARVALID(S_AXI_ARVALID),
        .S_AXI_ARREADY(S_AXI_ARREADY),
        .S_AXI_RDATA (S_AXI_RDATA),
        .S_AXI_RRESP (S_AXI_RRESP),
        .S_AXI_RVALID(S_AXI_RVALID),
        .S_AXI_RREADY(S_AXI_RREADY),
        .fifo_rd_en  (fifo_rd_en),
        .fifo_dout   (fifo_dout),
        .fifo_full   (fifo_full),
        .fifo_empty  (fifo_empty),
        .fifo_half_full(fifo_half_full)
    );

    always #5 ACLK = ~ACLK;

    task do_axi_write(input [ADDR_W-1:0] addr, input [DATA_W-1:0] data);
        begin
            @(posedge ACLK);
            S_AXI_AWADDR  = addr;
            S_AXI_AWVALID = 1;
            S_AXI_WDATA   = data;
            S_AXI_WVALID  = 1;
            S_AXI_BREADY  = 1;
            wait (S_AXI_BVALID);
            wait (!S_AXI_BVALID);
            @(posedge ACLK);
            S_AXI_AWVALID = 0;
            S_AXI_WVALID  = 0;
            S_AXI_BREADY  = 0;
            S_AXI_AWADDR  = 0;
        end
    endtask

    initial begin
        ARESETN = 0;
        repeat (5) @(posedge ACLK);
        ARESETN = 1;

        do_axi_write(4'h0, 32'h000000AB);
        do_axi_write(4'h0, 32'h000000CD);

        // FIFO 同步读：rd_en 在 posedge 后置位 → 下一拍 FIFO 才读 → 再下一拍 dout 更新
        @(posedge ACLK);
        fifo_rd_en = 1;
        @(posedge ACLK);   // FIFO 读 AB，dout<=AB（本拍末）
        @(posedge ACLK);
        got0 = fifo_dout;  // 采到 AB
        @(posedge ACLK);   // FIFO 读 CD，dout<=CD（本拍末）
        @(posedge ACLK);
        got1 = fifo_dout;  // 采到 CD
        fifo_rd_en = 0;

        if (got0 === exp0 && got1 === exp1) begin
            $display("SOC_AXI_FIFO PASS");
        end else begin
            $display("SOC_AXI_FIFO FAIL: got=%h,%h exp=%h,%h", got0, got1, exp0, exp1);
            $fatal(1, "axi fifo mismatch");
        end
        $finish;
    end

endmodule