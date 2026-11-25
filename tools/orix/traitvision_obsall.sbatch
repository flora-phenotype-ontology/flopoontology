#!/bin/bash
# Trait-vision: classifiers trained on observers' labels, with the label on the observation (observer_allphotos.py).
#SBATCH --job-name=tv-obs
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
cd "$DATA/src"
/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python -u observer_allphotos.py "$DATA"
