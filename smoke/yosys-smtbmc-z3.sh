#!/bin/bash
# PreCex - Gate-1: yosys-smtbmc 包装脚本（本机无 yices，强制使用 z3）
# 作者：Toylog | 版本：v0.1 | 功能概述：sby 通过环境变量 SMTBMC 调用本脚本，注入 -s z3
exec /usr/bin/yosys-smtbmc -s z3 "$@"
