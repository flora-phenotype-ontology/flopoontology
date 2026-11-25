#!/bin/bash
# Image models compared on our tests with the same head and the same photographs (probe_any.py): BioCLIP 2, DINOv2 ViT-L,
# PlantCLEF-2024 DINOv2 ViT-B, and BioCLIP 2 joined with each. One process per row, all on one GPU. About 20 min.
#SBATCH --job-name=tv-encoders
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=24
#SBATCH --mem=240G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=2
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
PIDS=""
for N in bioclip2 dinov2 plantclef bioclip2+dinov2 bioclip2+plantclef; do
  "$PY" -u probe_any.py --data "$DATA" --names "$N" --ids-from dinov2 --seeds 0,1,2 --out "$DATA/encoders/probe-$N" > "$ROOT/logs/encoders-$N.log" 2>&1 &
  PIDS="$PIDS $!"
done
wait $PIDS || true
grep -h -E "MEAN|dim" "$ROOT"/logs/encoders-*.log | cut -c1-300
