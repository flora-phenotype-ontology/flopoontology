#!/bin/bash
# Trait-vision pilot on ORIX: BioCLIP 2 embeddings of one more photo manifest, added to pilot-v1/emb.
#   sbatch traitvision_embed.sbatch MANIFEST TAG [IMAGES default images] [OUT default emb]
#SBATCH --job-name=tv-embed
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=1
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
cd "$DATA/src"
/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python -u embed.py --manifest "$DATA/$1" \
  --images "$DATA/${3:-images}" --model /mnt/data/u/hohndor/flopo-vision/staged-models-v1/bioclip2 --out "$DATA/${4:-emb}" --tag "$2"
