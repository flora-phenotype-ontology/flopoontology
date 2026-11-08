#!/bin/bash
#SBATCH --job-name=flopo-weak-training
#SBATCH --account=pi-hohndor
#SBATCH --partition=batch-h200
#SBATCH --qos=batch
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:05:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export HF_HOME=/mnt/data/u/hohndor/flopo-vision/hf-cache
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
data_dir=/mnt/data/u/hohndor/flopo-vision/audit-200-20261024
.pixi/envs/default/bin/python -m flopo2.vision.prototypes \
    --models /mnt/data/u/hohndor/flopo-vision/models \
    --vocabulary "$data_dir/vocabulary.json" --out "$data_dir/text-prior"
exec .pixi/envs/default/bin/python -m flopo2.vision.weak_train \
    --data "$data_dir" --out "$data_dir/weak-runs/$SLURM_JOB_ID" --device cuda
