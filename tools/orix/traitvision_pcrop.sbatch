#!/bin/bash
# Crop embeddings averaged per photograph (on the GPU, seconds), then three runs of baseline_v2.py on them side by side.
#SBATCH --job-name=tv-pcrop
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=24
#SBATCH --mem=400G
#SBATCH --time=04:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=6
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
[ -s "$DATA/emb-pcrop-fruit-field/emb-0.npy" ] || "$PY" -u crop_to_photo.py "$DATA" leaf flower fruit
PIDS=""
for G in leaf flower fruit; do
  "$PY" -u baseline_v2.py fit --data "$DATA" --out "$DATA/baseline-v6/pcrop-$G" --emb emb-pcrop-$G > "$ROOT/logs/pcrop-$SLURM_JOB_ID-$G.log" 2>&1 &
  PIDS="$PIDS $!"
done
wait $PIDS || true
tail -n 2 "$ROOT"/logs/pcrop-$SLURM_JOB_ID-*.log
