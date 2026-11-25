#!/bin/bash
# Baselines without training (zeroshot.py): trait prompts, trait text, flora text, species name; then the
# identification of baseline_v2.py on the trait-prompt answers. About 20 min.
#SBATCH --job-name=tv-zeroshot
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=8
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
OUT=$DATA/baseline-v6/zeroshot
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
"$PY" -u zeroshot.py run --data "$DATA" --model "$ROOT/staged-models-v1/bioclip2" --out "$OUT" --ref "$DATA/baseline-v6/s0"
"$PY" -u baseline_v2.py fit --data "$DATA" --out "$OUT" --reuse "$OUT" --regions=
