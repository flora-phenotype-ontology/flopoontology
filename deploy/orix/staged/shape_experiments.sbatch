#!/bin/bash
#SBATCH --job-name=flopo-shape-study
#SBATCH --account=pi-hohndor
#SBATCH --partition=freecycle-h200
#SBATCH --qos=freecycle
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --requeue
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
cd "$DATA/shape-source-v1"
encoders=(fgclip2 bioclip2)
if test "${1:-}" = preflight; then
  for encoder in "${encoders[@]}"; do
    "$PY" -u -m flopo2.vision.shape_experiments_train --data "$DATA/shape-experiments-v1/prepared" \
      --models "$DATA/modern-models" --extra-models "$DATA/staged-models-v1" \
      --encoder "$encoder" --out "$DATA/shape-experiments-v1/preflight/$encoder" --preflight
  done
else
  encoder="${encoders[$SLURM_ARRAY_TASK_ID]}"
  "$PY" -u -m flopo2.vision.shape_experiments_train --data "$DATA/shape-experiments-v1/prepared" \
    --models "$DATA/modern-models" --extra-models "$DATA/staged-models-v1" \
    --encoder "$encoder" --out "$DATA/shape-experiments-v1/runs/$encoder"
fi
