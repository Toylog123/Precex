#!/bin/bash
# PreCex - SoC 互联回归（WP4）
# 3 场景：uart_loopback / axi_fifo / fsm_uart
set -u
cd "$(dirname "$0")/../samples/soc" || exit 1
pass=0
fail=0

run_one() {
  local dir="$1"
  local tb="$2"
  shift 2
  echo "[soc] compiling $dir ..."
  cd "$dir" || return 1
  iverilog -g2012 -s "$tb" -o tb_out "$tb.sv" "$@" 2>compile.err
  if [ $? -ne 0 ]; then
    echo "[soc] $dir COMPILE_FAIL"; cat compile.err; fail=$((fail+1)); cd ..; return 1
  fi
  local out
  out=$(vvp tb_out 2>&1)
  if echo "$out" | grep -q PASS; then
    echo "[soc] $dir PASS"; pass=$((pass+1))
  else
    echo "[soc] $dir FAIL"; echo "$out" | tail -8; fail=$((fail+1))
  fi
  cd ..
}

RTL=../../../rtl
run_one uart_loopback tb_soc_uart_loopback "$RTL/uart_tx/uart_tx.sv" "$RTL/uart_rx/uart_rx.sv" soc_uart_loopback.v
run_one axi_fifo tb_soc_axi_fifo "$RTL/axi_lite_slave/axi_lite_slave.sv" "$RTL/fifo_sync/fifo_sync.sv" soc_axi_fifo.v
run_one fsm_uart tb_soc_fsm_uart "$RTL/fsm_ctrl/fsm_ctrl.sv" "$RTL/uart_tx/uart_tx.sv" soc_fsm_uart.v

echo "== SOC_REGRESSION pass=$pass fail=$fail =="
[ "$fail" -eq 0 ]