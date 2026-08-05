#!/bin/bash
export HOME=/home/toylog
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/toylog/.local/bin
export SMTBMC=/mnt/d/BaiduSyncdisk/02_Precex/smoke/yosys-smtbmc-z3.sh
cd /mnt/d/BaiduSyncdisk/02_Precex
/usr/bin/python3 scripts/trace_analyzer.py --samples "$1"