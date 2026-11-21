#!/bin/bash
# Trait-vision pilot on ORIX: retrain the trait heads on embeddings that already exist (minutes).
#   sbatch traitvision_cwa.sbatch   (stated-only, then four assumed-absent variants, spines and simple/compound leaves)
#SBATCH --job-name=tv-cwa
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=8
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
for v in "none 0" "genus 0" "family 0" "genus 1" "family 1" "all 1" "all 0"; do
  set -- $v
  "$PY" -u train.py --data "$DATA" --out "$DATA/run-cwa3-$1-$2" --labels pilot-labels-v3-cwa.tsv --photos inat-photos-v3.tsv \
    --field field-test-v3.tsv --traits spines,leaf_complexity --assumed "$1" --assumed-mass "$2"
done
