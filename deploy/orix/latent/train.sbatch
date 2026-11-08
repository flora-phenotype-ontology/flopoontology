#!/bin/bash
#SBATCH --job-name=flopo-latent-bears
#SBATCH --account=pi-hohndor
#SBATCH --partition=freecycle-h200
#SBATCH --qos=freecycle
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:20:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-latent
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
run_dir=/mnt/data/u/hohndor/flopo-vision/latent-runs/$SLURM_JOB_ID
.pixi/envs/default/bin/python -m flopo2.vision.latent_train train \
    --prepared /mnt/data/u/hohndor/flopo-vision/latent-prepared-20261025 \
    --out "$run_dir" --members 5 --epochs 200 --world-samples 64
cp pixi.toml pixi.lock "$run_dir/"
cp flopo2/vision/{latent,latent_train,bears}.py "$run_dir/"
sha256sum "$run_dir/"*.pt > "$run_dir/checkpoint-sha256.txt"
