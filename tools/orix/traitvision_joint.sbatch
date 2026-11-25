#!/bin/bash
# Trait-vision: small tests of the training regime (regime_tests.py) on embeddings that exist.
#   sbatch traitvision_regime.sbatch [--traits a,b] [--arms x,y]
#SBATCH --job-name=tv-regime
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=8
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$DATA/../logs/gpu-$SLURM_JOB_ID.txt" &
"$PY" -u joint_train.py --data "$DATA" --out "$DATA/joint" "$@"
