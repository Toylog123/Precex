#!/bin/bash
cd /mnt/d/BaiduSyncdisk/02_Precex
export HOME=/home/toylog

echo launching 4 shards...

# Shard A: 8 tasks
nohup python3 scripts/run_experiments.py --tasks s07/C/0,s18/C/0,s19/C/1,s19/C/2,s24/C/0,s24/C/1,s25/C/0,s25/C/1 --retries 2 --provider deepseek --out /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_c_stubborn_a.json > /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_c_stubborn_a.log 2>&1 &
echo shard A PID=\$!

# Shard B: 9 tasks
nohup python3 scripts/run_experiments.py --tasks s25/C/2,s27/C/2,s33/C/0,s33/C/1,s33/C/2,s34/C/1,s37/C/0,s37/C/1,s37/C/2 --retries 2 --provider deepseek --out /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_c_stubborn_b.json > /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_c_stubborn_b.log 2>&1 &
echo shard B PID=\$!

# Shard L2: 9 tasks
nohup python3 scripts/run_experiments.py --tasks l2_axi_03/C/0,l2_axi_06/C/2,l2_cnt_03/C/1,l2_fifo_02/C/0,l2_fifo_04/C/2,l2_fsm_01/C/1,l2_fsm_04/C/0,l2_uartrx_02/C/2,l2_uarttx_02/C/1 --retries 2 --provider deepseek --samples-dir l2 --out /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_cl2_missing.json > /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_cl2_missing.log 2>&1 &
echo shard L2 PID=\$!

# Shard Deep: 8 tasks
nohup python3 scripts/run_experiments.py --tasks s39/C/0,s39/C/1,s39/C/2,s40/C/0,s41/C/1,s42/C/0,s42/C/1,s42/C/2 --retries 2 --provider deepseek --samples-dir deep --out /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_cdeep_retry.json > /mnt/d/BaiduSyncdisk/02_Precex/experiments/runs/exp_cdeep_retry.log 2>&1 &
echo shard Deep PID=\$!

sleep 3
echo checking processes...
ps aux | grep run_experiments | grep -v grep | wc -l
echo done
