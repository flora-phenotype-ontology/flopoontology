#!/bin/bash
# Trait-vision pilot on ORIX: score another published image model as a baseline.
#   sbatch --job-name=tv-NAME traitvision_baseline.sbatch NAME KIND MODELDIR [SIZE]
# Embeds the training photos and the human-labelled test photos, then runs the same train.py.
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=08:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1
NAME=$1 KIND=$2 MODEL=$3 SIZE=${4:-0}
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
if [ ! -f "$DATA/emb-$NAME/emb-0.npy" ]; then
  "$PY" -u embed_any.py --kind "$KIND" --model "$MODEL" --size "$SIZE" --manifest "$DATA/inat-photos-v3.tsv" \
    --images "$DATA/images" --out "$DATA/emb-$NAME" --prompts "$DATA/prompts.tsv"
fi
if [ ! -f "$DATA/emb-$NAME-field/emb-0.npy" ]; then
  "$PY" -u embed_any.py --kind "$KIND" --model "$MODEL" --size "$SIZE" --manifest "$DATA/field-photos.tsv" \
    --images "$DATA/field/images" --out "$DATA/emb-$NAME-field"
fi
"$PY" -u train.py --data "$DATA" --emb "emb-$NAME" --out "$DATA/run-$NAME-$SLURM_JOB_ID" \
  --labels pilot-labels-v3.tsv --photos inat-photos-v3.tsv --field field-test-v3.tsv
