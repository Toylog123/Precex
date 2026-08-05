#!/bin/bash
export HOME=/home/toylog
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/home/toylog/.local/bin
cd /mnt/d/BaiduSyncdisk/02_Precex
/usr/bin/python3 scripts/top_audit.py --jobs 6 --out experiments/runs/top_audit_report.json