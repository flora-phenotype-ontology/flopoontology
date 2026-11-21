#!/bin/bash
# Trait-vision pilot on ORIX: retrain the trait heads on embeddings that already exist (minutes).
#   sbatch traitvision_crops.sbatch   (after detection: heads trained on organ crops, with and without the whole photo)
#SBATCH --job-name=tv-crops
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=06:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=8
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
declare -A TRAITS=([flower]=flower_colour,inflorescence [fruit]=fruit_colour [leaf]=leaf_complexity,leaf_margin [leafstem]=leaf_arrangement [thornstem]=spines)
[ -f "$DATA/crop-field-thornstem.tsv" ] || "$PY" -u crop_split.py --data "$DATA"
[ -f "$DATA/crop-field-thornstem+w.tsv" ] || "$PY" -u crop_split.py --data "$DATA" --whole
for g in flower fruit leaf leafstem thornstem; do
  for name in "$g" "$g+w"; do
    for pool in mean max; do
      "$PY" -u train.py --data "$DATA" --emb "emb-crop-$name" --out "$DATA/run-crop-$name-$pool" --labels pilot-labels-v3.tsv \
        --photos "crop-photos-$name.tsv" --field "crop-field-$name.tsv" --traits "${TRAITS[$g]}" --pool "$pool"
    done
  done
done
