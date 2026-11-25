#!/bin/bash
# Trait-vision: organ boxes only (Grounding DINO; image preparation in the loader workers).
#   sbatch --job-name=tv-box-NAME traitvision_boxes.sbatch MANIFEST IMAGES OUT [detect.py options, e.g. --shard 0 --shards 4 --skip FILE]
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=48
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
MANIFEST=$1 IMAGES=$2 OUT=$3; shift 3
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
# GPU use is logged every 30 s: the cluster cancels jobs that stay under 75%
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$DATA/../logs/gpu-$SLURM_JOB_ID.txt" &
mkdir -p "$(dirname "$DATA/$OUT")"
"$PY" -u detect.py --manifest "$DATA/$MANIFEST" --images "$DATA/$IMAGES" --out "$DATA/$OUT" \
  --model /mnt/data/u/hohndor/flopo-vision/baseline-models/grounding-dino-base --workers 44 "$@"
