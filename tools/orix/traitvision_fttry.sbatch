#!/bin/bash
# Train the BioCLIP 2 image model on TRY values and flora labels together (finetune_try.py).
#   sbatch traitvision_fttry.sbatch NAME [finetune_try.py options]        -> pilot-v1/ft-try/NAME
#SBATCH --job-name=tv-fttry
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=48
#SBATCH --mem=300G
#SBATCH --time=03:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1
NAME=$1
shift
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
"$ROOT/vision-pixi/envs/default/bin/python" -u finetune_try.py --data "$DATA" --model "$ROOT/staged-models-v1/bioclip2" \
  --root "$ROOT/sota-benchmarks/planttraitnet" --out "$DATA/ft-try/$NAME" "$@"
