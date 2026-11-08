#!/bin/bash
#SBATCH --job-name=flopo-visual-audit
#SBATCH --account=pi-hohndor
#SBATCH --partition=batch-h200
#SBATCH --qos=batch
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export HF_HOME=/mnt/data/u/hohndor/flopo-vision/hf-cache
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export PYTHONUNBUFFERED=1
data_dir=${1:-/mnt/data/u/hohndor/flopo-vision/audit-20261024}
exec .pixi/envs/default/bin/python extract.py \
    --data "$data_dir" \
    --models /mnt/data/u/hohndor/flopo-vision/models \
    --out "$data_dir/extraction" "${@:2}"
