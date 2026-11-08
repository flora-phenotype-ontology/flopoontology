#!/bin/bash
#SBATCH --job-name=flopo-cotleaf
#SBATCH --account=pi-hohndor
#SBATCH --partition=freecycle-h200
#SBATCH --qos=freecycle
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=01:00:00
#SBATCH --requeue
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
cd "$DATA/cotleaf-source-v1"
encoders=(fgclip2 bioclip2)
encoder="${encoders[$SLURM_ARRAY_TASK_ID]}"
"$PY" -u -m flopo2.vision.cotleaf_infer --data "$DATA/cotleaf-x-v1" --models "$DATA/modern-models" \
  --extra-models "$DATA/staged-models-v1" --runs "$DATA/staged-runs-v1" \
  --encoder "$encoder" --out "$DATA/cotleaf-inference-v1/$encoder"
