#!/bin/bash
#SBATCH --job-name=flopo-full-extract
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --array=0-3%4
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/full-source-v1"
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
"$PY" -u -m flopo2.vision.modern_weak extract --data "$DATA/flopo-full-v1" \
  --models "$DATA/modern-models" --detector "$DATA/models" --model fgclip2-large \
  --out "$DATA/full-shards-v1/shard-$SLURM_ARRAY_TASK_ID" --shard-index "$SLURM_ARRAY_TASK_ID" --shard-count 4
