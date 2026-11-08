#!/bin/bash
#SBATCH --job-name=flopo-staged-extract
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/staged-extract-source-v1"
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
for encoder in fgclip2 bioclip2; do
  if test -f "$DATA/staged-features-v1/$encoder/extraction.json"; then continue; fi
  "$PY" -u -m flopo2.vision.staged_features --encoder "$encoder" \
    --features "$DATA/full-features-v1" --data "$DATA/flopo-full-v1" \
    --models "$DATA/modern-models" --extra-models "$DATA/staged-models-v1" \
    --small "$DATA/visual-small-v1" --external "$DATA/leaf-control-v1" \
    --out "$DATA/staged-features-v1/$encoder"
done
