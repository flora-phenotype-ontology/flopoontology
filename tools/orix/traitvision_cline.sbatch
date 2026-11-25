#!/bin/bash
# Flower colour within species: BioCLIP 2 embeddings of the photographs of the colour-form species, then the flower-colour head
# trained without their genera and its predictions (cline/pred.npz).
#SBATCH --job-name=tv-cline
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=32
#SBATCH --mem=200G
#SBATCH --time=03:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=1
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
SET=${CLINE_SET:-cline}
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
[ -s "$DATA/emb-$SET/emb-$SET.npy" ] || "$PY" -u embed.py --manifest "$DATA/$SET/inat-photos-cline.tsv" --images "$DATA/$SET/images" \
  --model $ROOT/staged-models-v1/bioclip2 --out "$DATA/emb-$SET" --tag $SET --batch 1024 --workers 30
OMP_NUM_THREADS=8 "$PY" -u colour_cline_fit.py "$DATA" $SET
