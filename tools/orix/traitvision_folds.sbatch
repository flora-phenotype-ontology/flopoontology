#!/bin/bash
# Trait-vision pilot on ORIX: retrain the trait heads on embeddings that already exist (minutes).
#   sbatch traitvision_folds.sbatch   (five runs, each holding out another fifth of the genera; predictions are kept)
#SBATCH --job-name=tv-folds
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=8
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
for f in 0 1 2 3 4; do
  "$PY" -u train.py --data "$DATA" --out "$DATA/run-fold-$f" --labels pilot-labels-v3.tsv --photos inat-photos-v3.tsv \
    --field field-test-v3.tsv --fold "$f" --seeds 1 --dump
done
