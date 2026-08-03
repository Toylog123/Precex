#!/bin/bash
# PreCex - Gate-1 断言安全子集双工具实测矩阵 v3（完整收敛用）
# 作者：Toylog | 版本：v0.3 | 功能概述：逐条构造最小断言样例，对 iverilog 12 / yosys(read -sv 与 -formal 双路径) 实测接受度，确认 assert cell 生成
# 用法：bash diag_assert_v3.sh   （结果打印矩阵，另存 /tmp/svatest/matrix.txt）
set -u
cd "$(dirname "$0")"
# 注意：WSL 的 /tmp 在实例重启后会被清空，故用项目内隐藏目录（脚本每次运行自重建，跑完可清理）
WORK="$(pwd)/.svatest"
mkdir -p "$WORK"
OUT="$WORK/matrix.txt"
: > "$OUT"

HDR='module t(input logic clk, rst_n, en, input logic [1:0] cnt);'
FTR='endmodule'

make_case() {  # $1=name $2=body(完整 module 内容，可含 HDR/FTR)
  cat > "$WORK/$1.sv" <<EOF
$2
EOF
}

# ---- 用例清单（覆盖 Gate-1 全部候选格式）----
make_case a1_imm_plain "$HDR
  always @(posedge clk) assert (en == 1'b1 || cnt == 2'd0);
$FTR"

make_case a2_imm_if "$HDR
  always @(posedge clk) if (en) assert (cnt == 2'd1);
$FTR"

make_case a3_imm_pipe "$HDR
  reg en_d;
  reg [1:0] cnt_d;
  always @(posedge clk) begin
    if (!rst_n) begin
      en_d <= 1'b0;
    end else begin
      en_d <= en;
      cnt_d <= cnt;
      if (en_d) assert (cnt == cnt_d + 1'b1);
    end
  end
$FTR"

make_case b1_conc_noclk "$HDR
  assert property (en == 1'b1 || en == 1'b0);
$FTR"

make_case b2_conc_clk "$HDR
  assert property (@(posedge clk) (en == 1'b1));
$FTR"

make_case b3_conc_disable "$HDR
  assert property (@(posedge clk) disable iff (!rst_n) (en == 1'b1));
$FTR"

make_case c1_past_clk "$HDR
  assert property (@(posedge clk) (\$past(en) == 1'b1));
$FTR"

make_case c2_rose_impl "$HDR
  assert property (@(posedge clk) \$rose(en) |-> (cnt == 2'd0));
$FTR"

make_case c3_past_noclk "$HDR
  assert property (\$past(en) == 1'b1);
$FTR"

make_case c4_rose_imm "$HDR
  always @(posedge clk) assert (\$rose(en));
$FTR"

make_case d1_fatal_init "$HDR
  initial \$fatal(1, \"boom\");
$FTR"

make_case d2_fatal_always "$HDR
  always @(posedge clk) if (en) \$fatal(1, \"boom\");
$FTR"

make_case e1_assume_clk "$HDR
  assume property (@(posedge clk) (en == 1'b1 || en == 1'b0));
$FTR"

make_case e2_assume_noclk "$HDR
  assume property (en == 1'b1 || en == 1'b0);
$FTR"

make_case e3_assume_imm "$HDR
  always @(posedge clk) assume (en == 1'b1 || en == 1'b0);
$FTR"

# ---- 三个检查通道 ----
# iv : iverilog 12 编译
# yf : yosys read_verilog -sv -formal（任务指定的 sby 等价读取路径）
# yp : yosys read_verilog -sv 无 -formal（sby [script] read -sv 的实际默认路径）
run_all() {  # $1=name
  local f="$WORK/$1.sv"
  iverilog -g2012 "$f" -o /dev/null 2>/dev/null; local IV=$?
  # 注意：不传 -q（-q 会连 stat 输出一起吞掉），用 -F 做固定字符串匹配
  local YF YFA
  YFA=$(yosys -p "read -sv -formal $f; prep -top t; stat" 2>&1); YF=$?
  local nfa nfu; nfa=$(echo "$YFA" | grep -F -c '$assert'); nfu=$(echo "$YFA" | grep -F -c '$assume')
  local YP YPA
  YPA=$(yosys -p "read -sv $f; prep -top t; stat" 2>&1); YP=$?
  local npa npu; npa=$(echo "$YPA" | grep -F -c '$assert'); npu=$(echo "$YPA" | grep -F -c '$assume')
  printf '%-18s iv=%s yf=%s(a:%s,u:%s) yp=%s(a:%s,u:%s)\n' "$1" "$IV" "$YF" "$nfa" "$nfu" "$YP" "$npa" "$npu" | tee -a "$OUT"
}

echo '==== 断言子集双工具实测矩阵 (iv=iverilog rc, yf=yosys -formal rc, yp=yosys plain rc, ac=assert cell 数) ====' | tee -a "$OUT"
for n in a1_imm_plain a2_imm_if a3_imm_pipe b1_conc_noclk b2_conc_clk b3_conc_disable \
         c1_past_clk c2_rose_impl c3_past_noclk c4_rose_imm d1_fatal_init d2_fatal_always \
         e1_assume_clk e2_assume_noclk e3_assume_imm; do
  run_all "$n"
done
echo "矩阵原始输出: $OUT"
