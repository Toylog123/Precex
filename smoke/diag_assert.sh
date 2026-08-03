#!/bin/bash
# PreCex - Gate-1 断言子集双工具诊断脚本 v2（iverilog 12 vs yosys -formal）
# 作者：Toylog | 版本：v0.2 | 功能概述：逐条构造最小断言样例，验证双工具兼容性
# 用法：bash diag_assert.sh

set -u
cd "$(dirname "$0")"
WORK=/tmp/svatest
mkdir -p "$WORK"

make_case() {  # $1=name $2=assert_code
  local f="$WORK/$1.sv"
  cat > "$f" <<EOF
module t(input logic clk, rst_n, en, input logic [1:0] cnt);
  $2
endmodule
EOF
}

# 候选断言清单（关键点：iverilog 12 与 yosys -formal 各自支持的 SVA 子集）
make_case 1_immediate_assert 'always @(posedge clk) assert (en == 1'"'"'b1 || cnt == 2'"'"'d0);'
make_case 2_simple_concurrent 'assert property (@(posedge clk) (en == 1'"'"'b1));'
make_case 3_disable_iff 'assert property (@(posedge clk) disable iff (!rst_n) (en == 1'"'"'b1));'
make_case 4_past 'assert property (@(posedge clk) disable iff (!rst_n) ($past(en) == 1'"'"'b1));'
make_case 5_implication 'assert property (@(posedge clk) disable iff (!rst_n) (en == 1'"'"'b1) |-> (cnt == 2'"'"'d0));'
make_case 6_cycle_delay 'assert property (@(posedge clk) disable iff (!rst_n) (en == 1'"'"'b1) |-> ##1 (cnt == 2'"'"'d0));'
make_case 7_assume 'assume property (@(posedge clk) disable iff (!rst_n) (en == 1'"'"'b1 || !en == 1'"'"'b1));'
make_case 8_rose 'assert property (@(posedge clk) disable iff (!rst_n) $rose(en) |-> (cnt == 2'"'"'d0));'

PASS=0; FAIL=0
for f in "$WORK"/*.sv; do
  name=$(basename "$f" .sv)
  iverilog -g2012 "$f" -o /dev/null 2>/dev/null; IV=$?
  yosys -ql /dev/null -p "read -sv $f; prep -top t; check" 2>/dev/null; YS=$?
  if [ "$IV" -eq 0 ] && [ "$YS" -eq 0 ]; then st="PASS"; PASS=$((PASS+1)); else st="FAIL"; FAIL=$((FAIL+1)); fi
  printf '%-24s iverilog=%s yosys=%s => %s\n' "$name" "$IV" "$YS" "$st"
done
echo "---- summary: PASS=$PASS FAIL=$FAIL ----"
