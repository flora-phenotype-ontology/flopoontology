#!/bin/bash
#SBATCH --job-name=flopo-small-train
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:15:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-latent
export OMP_NUM_THREADS=4
.pixi/envs/default/bin/python -m flopo2.vision.small_train run --out /mnt/data/u/hohndor/flopo-vision/small-run-v1
