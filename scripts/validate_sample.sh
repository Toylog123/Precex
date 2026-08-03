#!/bin/bash
# PreCex - 样本三通过校验脚本（弱 tb 过 + formal 败/过）
# 作者：Toylog | 版本：v0.1 | 功能概述：对单个样本目录执行 iverilog 编译 + vvp 弱 tb 仿真 + sby 形式验证
set -u
export HOME=/home/toylog
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin"

SAMPLE_DIR="${1:?usage: validate_sample.sh <sample_dir> [sby_file]}"
SBY_FILE="${2:-verify.sby}"
SBY_FILE="$(cd "$SAMPLE_DIR" && pwd)/$SBY_FILE"
SAMPLE_DIR="$(cd "$SAMPLE_DIR" && pwd)"
cd "$SAMPLE_DIR" || exit 2

DESIGN_SV=""
for f in *.sv; do
  case "$f" in
    tb_*|*golden*|assertions.sv) ;;
    *) DESIGN_SV="$DESIGN_SV $f" ;;
  esac
done
DESIGN_SV="$(echo $DESIGN_SV | xargs)"
if [ -z "$DESIGN_SV" ]; then
  echo "ERROR: no design sv found in $SAMPLE_DIR"; exit 2
fi

echo "== [1/3] compile"
rm -f tb_out
if iverilog -g2012 $DESIGN_SV assertions.sv tb_weak.sv -o tb_out 2>compile.err; then
  echo "compile: OK"
else
  echo "compile: FAIL"; cat compile.err; rm -f compile.err; exit 3
fi
rm -f compile.err

echo "== [2/3] weak tb sim"
if out=$(vvp tb_out 2>&1); then
  if echo "$out" | grep -q "PASS:"; then
    echo "sim: PASS (weak tb tolerant)"
  else
    echo "sim: PASS (no PASS marker)"
  fi
else
  echo "sim: FAIL"; echo "$out" | tail -8; exit 4
fi

echo "== [3/3] sby"
if [ -f "$SBY_FILE" ]; then
  WORK="$(mktemp -d /tmp/sby_validate.XXXXXX)"
  export SMTBMC="/mnt/d/BaiduSyncdisk/02_Precex/smoke/yosys-smtbmc-z3.sh"
  if sby -f "$SBY_FILE" -d "$WORK" >sby_run.log 2>&1; then
    echo "formal: PASS (rc=0)"
    rm -rf "$WORK" sby_run.log
  else
    rc=$?
    echo "formal: FAIL (rc=$rc)"
    grep -E "DONE|Assert failed|BMC failed" sby_run.log | tail -4
  fi
else
  echo "formal: SKIP ($SBY_FILE not found)"
fi
echo "== done: $SAMPLE_DIR"
