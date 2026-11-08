#!/bin/bash
#SBATCH --job-name=flopo-small-extract
#SBATCH --account=pi-hohndor
#SBATCH --partition=freecycle-h200
#SBATCH --qos=freecycle
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:25:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export OMP_NUM_THREADS=4
PY=.pixi/envs/default/bin/python
DATA=/mnt/data/u/hohndor/flopo-vision
$PY -m flopo2.vision.extract --data "$DATA/visual-small-v1" --models "$DATA/models" --out "$DATA/visual-small-v1/extraction"
$PY -m flopo2.vision.leaf_control encode --data "$DATA/leaf-control-v1" --models "$DATA/models"
$PY -m flopo2.vision.leaf_control weak-gaussian --data "$DATA/leaf-control-v1"
