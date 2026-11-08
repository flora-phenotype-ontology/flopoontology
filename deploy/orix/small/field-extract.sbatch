#!/bin/bash
#SBATCH --job-name=flopo-small-field
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:15:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export OMP_NUM_THREADS=4
.pixi/envs/default/bin/python -m flopo2.vision.extract --data /mnt/data/u/hohndor/flopo-vision/visual-small-v1 --models /mnt/data/u/hohndor/flopo-vision/models --out /mnt/data/u/hohndor/flopo-vision/visual-small-v1/extraction
