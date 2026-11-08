#!/bin/bash
#SBATCH --job-name=flopo-full-workers
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:nvidia_h200:4
#SBATCH --mem=256G
#SBATCH --time=12:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
python3 /mnt/data/u/hohndor/flopo-vision/full-operations-v1/full_workers.py
