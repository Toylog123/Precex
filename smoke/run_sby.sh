#!/bin/bash
# PreCex - Gate-1 smoke: 运行 sby 的统一入口（注入 z3 路径与 SMTBMC 包装）
# 作者：Toylog | 版本：v0.2 | 功能概述：export PATH/SMTBMC 后执行 sby，参数透传
set -u
export PATH="$HOME/.local/bin:$PATH"
export SMTBMC="$(cd "$(dirname "$0")" && pwd)/yosys-smtbmc-z3.sh"
cd "$(dirname "$0")" || exit 1
exec sby "$@"
