#!/bin/bash
#SBATCH --job-name=flopo-full-preflight
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=00:15:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/full-source-preflight"
/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python -u -m flopo2.vision.full_train fit \
  --data "$DATA/modern-cohort-v1" --features "$DATA/modern-followup-v1/fgclip2-large" \
  --models "$DATA/modern-models" --out "$DATA/full-preflight-v1" --mode projected --steps 3 --warmup 1
