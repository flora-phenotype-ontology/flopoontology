#!/bin/bash
# Baseline 2: all photographs, flora + observer labels, flora sizes, species identification (baseline_v2.py). About 1 h.
#SBATCH --job-name=tv-baseline2
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=8
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$DATA/../logs/gpu-$SLURM_JOB_ID.txt" &
"$PY" -u baseline_v2.py fit --data "$DATA" --out "$DATA/baseline-v2" "$@"
