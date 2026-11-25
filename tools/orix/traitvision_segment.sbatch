#!/bin/bash
# Trait-vision: petal masks (SAM, prompted by the flower boxes) and the colour measured inside them.
#   sbatch traitvision_segment.sbatch BOXES MANIFEST IMAGES OUT
#SBATCH --job-name=tv-seg
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=30
#SBATCH --mem=120G
#SBATCH --time=02:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
# GPU use is logged every 30 s: the cluster cancels jobs that stay under 75%
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$DATA/../logs/gpu-$SLURM_JOB_ID.txt" &
"$PY" -u segment_colour.py --boxes "$DATA/$1" --manifest "$DATA/$2" --images "$DATA/$3" --out "$DATA/$4" \
  --model /mnt/data/u/hohndor/flopo-vision/baseline-models/sam-vit-huge --centres "$DATA/block-centres.npz"
