#!/bin/bash
# Trait-vision pilot on ORIX: organ boxes (Grounding DINO) and BioCLIP 2 embeddings of the crops.
#   sbatch --job-name=tv-det-NAME traitvision_detect.sbatch NAME MANIFEST IMAGES [SHARD SHARDS]
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=30
#SBATCH --mem=200G
#SBATCH --time=12:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
NAME=$1 MANIFEST=$2 IMAGES=$3 SHARD=${4:-0} SHARDS=${5:-1}
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
# GPU use is logged every 30 s: the cluster cancels jobs that stay under 75%
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$DATA/../logs/gpu-$SLURM_JOB_ID.txt" &
mkdir -p "$DATA/crops-$NAME"
BOXES="$DATA/crops-$NAME/boxes-$SHARD.tsv"
if ! tail -1 "$BOXES.log" 2>/dev/null | grep -q '^done'; then
  "$PY" -u detect.py --manifest "$DATA/$MANIFEST" --images "$DATA/$IMAGES" --shard "$SHARD" --shards "$SHARDS" \
    --model /mnt/data/u/hohndor/flopo-vision/baseline-models/grounding-dino-base --out "$BOXES" | tee "$BOXES.log"
fi
"$PY" -u embed_crops.py --boxes "$BOXES" --manifest "$DATA/$MANIFEST" --images "$DATA/$IMAGES" \
  --model /mnt/data/u/hohndor/flopo-vision/staged-models-v1/bioclip2 --out "$DATA/crops-$NAME" --tag "$SHARD"
