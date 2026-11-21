#!/bin/bash
# Trait-vision pilot on ORIX: fine-tune the BioCLIP 2 image model on the flora trait labels.
#   sbatch traitvision_finetune.sbatch [extra finetune.py arguments]
#SBATCH --job-name=flopo-trait-ft
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=10:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
MODEL=/mnt/data/u/hohndor/flopo-vision/staged-models-v1/bioclip2
cd "$DATA/src"
"$PY" -u finetune.py --data "$DATA" --model "$MODEL" --heads "$DATA/run-403976" \
  --out "$DATA/ft-$SLURM_JOB_ID" "$@"
