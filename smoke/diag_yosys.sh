#!/bin/bash
# PreCex - Gate-1 yosys 0.33 SVA 语法诊断
# 作者：Toylog | 版本：v0.1 | 功能概述：测试 yosys -formal 对多种 SVA 断言格式的接受度
cd /tmp/svatest || exit 1

run_ys() {  # $1=name $2=sv_content
  local f="$1.sv"
  printf '%s\n' "$2" > "$f"
  local out
  out=$(yosys -p "read_verilog -sv -formal $f; prep -top t" 2>&1)
  if echo "$out" | grep -q "ERROR"; then
    echo "[$1] FAIL: $(echo "$out" | grep ERROR | head -1)"
  else
    n=$(echo "$out" | grep -ci "assert")
    echo "[$1] PASS (assert/assume cells: $n)"
  fi
}

HDR='module t(input logic clk, rst_n, en, input logic [1:0] cnt);'
FTR='endmodule'

run_ys y_f1 "$HDR
  assert property (en == 1'b1);
$FTR"

run_ys y_f2 "$HDR
  assert property (@(posedge clk) (en == 1'b1));
$FTR"

run_ys y_f3 "$HDR
  always @(posedge clk) assert (en == 1'b1 || cnt == 2'd0);
$FTR"

run_ys y_f4 "$HDR
  reg [1:0] cnt_d;
  always @(posedge clk) cnt_d <= cnt;
  assert property (@(posedge clk) ($past(en) == 1'b1));
$FTR"

run_ys y_f5 "$HDR
  assert property (@(posedge clk) $rose(en) |-> (cnt == 2'd0));
$FTR"

run_ys y_f6 "$HDR
  assert property (en |-> cnt == 2'd0);
$FTR"

run_ys y_f7 "$HDR
  assume property (@(posedge clk) (en == 1'b1 || !en == 1'b1));
$FTR"
