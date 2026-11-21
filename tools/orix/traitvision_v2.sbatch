#!/bin/bash
# Trait-vision pilot, second round: embed the photos added by synonym matching, then retrain.
#   sbatch /mnt/data/u/hohndor/flopo-vision/pilot-v1/src/traitvision_v2.sbatch
#SBATCH --job-name=flopo-trait-v2
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=8
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
MODEL=/mnt/data/u/hohndor/flopo-vision/staged-models-v1/bioclip2
cd "$DATA/src"
if [ ! -f "$DATA/emb/emb-new.npy" ]; then
  "$PY" -u embed.py --manifest "$DATA/inat-photos-new.tsv" --images "$DATA/images" --model "$MODEL" \
    --out "$DATA/emb" --tag new
fi
"$PY" -u train.py --data "$DATA" --out "$DATA/run-$SLURM_JOB_ID" --labels pilot-labels-v2.tsv \
  --photos inat-photos-v2.tsv --field field-test-v2.tsv
