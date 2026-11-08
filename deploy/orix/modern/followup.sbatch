#!/bin/bash
#SBATCH --job-name=flopo-trait-followup
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=00:30:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/modern-followup-source-v1"
export OMP_NUM_THREADS=4
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
for MODEL in fgclip2-base fgclip2-large; do
  OUT="$DATA/modern-followup-v1/$MODEL"
  "$PY" -u -m flopo2.vision.followup --previous "$DATA/modern-cohort-features-v1" \
    --data "$DATA/modern-cohort-v1" --models "$DATA/modern-models" --model "$MODEL" --out "$OUT"
  "$PY" -u -m flopo2.vision.modern_weak fit --data "$DATA/modern-cohort-v1" \
    --out "$OUT" --device cuda --steps 300 --followup
  "$PY" -u -m flopo2.vision.modern_weak evaluate --data "$DATA/modern-cohort-v1" \
    --out "$OUT" --screen "$DATA/modern-screen-v1/$MODEL" --audit "$DATA/trait-evaluation-v1"
done
