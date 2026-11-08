#!/bin/bash
#SBATCH --job-name=flopo-modern-cohort
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=02:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export OMP_NUM_THREADS=4
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=.pixi/envs/default/bin/python
DATA=/mnt/data/u/hohndor/flopo-vision
"$PY" -u -m flopo2.vision.modern_weak extract \
  --data "$DATA/modern-cohort-v1" --models "$DATA/modern-models" \
  --detector "$DATA/models" --model fgclip2-base --out "$DATA/modern-cohort-features-v1"
"$PY" -u -m flopo2.vision.modern_weak fit --data "$DATA/modern-cohort-v1" \
  --out "$DATA/modern-cohort-features-v1" --device cuda --steps 300
if test -f "$DATA/modern-screen-v1/fgclip2-base/extraction.json"; then
  "$PY" -u -m flopo2.vision.modern_weak evaluate --data "$DATA/modern-cohort-v1" \
    --out "$DATA/modern-cohort-features-v1" --screen "$DATA/modern-screen-v1/fgclip2-base" \
    --audit "$DATA/trait-evaluation-v1"
fi
