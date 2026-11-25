#!/bin/bash
# Flora sizes (height, leaf length and width) learned from photographs, tested against TRY on unseen genera (flora_try.py). About 10 min.
#SBATCH --job-name=tv-floratry
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=120G
#SBATCH --time=00:40:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
ROOT=/mnt/data/u/hohndor/flopo-vision
D=$ROOT/pilot-v1
cd "$D/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
"$ROOT/vision-pixi/envs/default/bin/python" -u flora_try.py fit --data $D --emb-val $D/sota-out/emb-ptn-val --emb-ref $D/sota-out/emb-ptn-ref --out $D/flora-try
