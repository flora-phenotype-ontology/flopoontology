#!/bin/bash
#SBATCH --job-name=flopo-staged-train
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=12:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/staged-train-source-v2"
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
for encoder in fgclip2 bioclip2; do
  if test "${1:-}" = preflight; then
    teacher="$DATA/staged-teacher-preflight-v4"
    output="$DATA/staged-preflight-v2/$encoder"
    extra=(--preflight)
  else
    teacher="$DATA/staged-teacher-v2"
    output="$DATA/staged-runs-v1/$encoder"
    extra=()
  fi
  "$PY" -u -m flopo2.vision.staged_train --features "$DATA/staged-features-v1/$encoder" \
    --base-features "$DATA/full-features-v1" --data "$DATA/flopo-full-v1" \
    --teacher "$teacher" --audit "$DATA/trait-evaluation-v1" --out "$output" --steps 6000 "${extra[@]}"
done
