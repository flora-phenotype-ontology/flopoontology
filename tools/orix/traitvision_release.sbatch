#!/bin/bash
# FLOPOVision release heads: one head per categorical trait on all species (flopovision/train_release.py).
#SBATCH --job-name=tv-release
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=200G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
cd "$DATA/src"
OMP_NUM_THREADS=8 /mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python -u train_release.py "$DATA" "$DATA/release-v0.1"
