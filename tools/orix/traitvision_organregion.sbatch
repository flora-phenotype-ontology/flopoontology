#!/bin/bash
# Flower colour and leaf traits from organ regions (organ_region.py): choose the boxes, embed them with BioCLIP 2,
# fit and score the arms.
#   sbatch traitvision_organregion.sbatch            (steps and traits already done are skipped)
#SBATCH --job-name=tv-organregion
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=96
#SBATCH --mem=300G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=1
ROOT=/mnt/data/u/hohndor/flopo-vision
D=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
MODEL=$ROOT/staged-models-v1/bioclip2
O=$D/organ-region
cd "$D/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
[ -f $O/boxes-field.tsv ] || "$PY" -u organ_region.py select --data $D
[ -f $O/emb-train/emb-0.npy ] || "$PY" -u embed_crops.py --boxes $O/boxes-train.tsv --manifest $D/inat-photos-v3-all.tsv --images $D/images --model $MODEL --out $O/emb-train --tag 0 --batch 128 --workers 92
[ -f $O/emb-field/emb-0.npy ] || "$PY" -u embed_crops.py --boxes $O/boxes-field.tsv --manifest $D/field-obs-photos.tsv --images $D/field/images --model $MODEL --out $O/emb-field --tag 0 --batch 128 --workers 92
export OMP_NUM_THREADS=8
"$PY" -u organ_region.py fit --data $D --seeds 0,1,2
