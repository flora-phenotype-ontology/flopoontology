#!/bin/bash
# Several runs of baseline_v2.py side by side on one GPU (seeds, ablation arms).
#   sbatch traitvision_baseline_multi.sbatch NAME=OPTIONS,NAME=OPTIONS,...     options with "_" for spaces, e.g. s1=--seed_1
# -> pilot-v1/baseline-v6/NAME
#SBATCH --job-name=tv-multi
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=24
#SBATCH --mem=400G
#SBATCH --time=04:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=6
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
PIDS=""
for RUN in ${1//,/ }; do
  NAME=${RUN%%=*}; OPTS=${RUN#*=}
  "$ROOT/vision-pixi/envs/default/bin/python" -u baseline_v2.py fit --data "$DATA" --out "$DATA/baseline-v6/$NAME" ${OPTS//_/ } > "$ROOT/logs/multi-$SLURM_JOB_ID-$NAME.log" 2>&1 &
  PIDS="$PIDS $!"
done
wait $PIDS || true
tail -n 2 "$ROOT"/logs/multi-$SLURM_JOB_ID-*.log
