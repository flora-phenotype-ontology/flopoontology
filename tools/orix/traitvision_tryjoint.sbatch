#!/bin/bash
# TRY traits on the PlantTraitNet photographs, trained on TRY labels and flora labels together (try_joint.py).
#   sbatch traitvision_tryjoint.sbatch [ARMS] [extra options for try_joint.py]
# One process per arm on the one GPU. About 10 min. Scoring afterwards on the login node: ptn_benchmark.py score --ours <arm>.npz
#SBATCH --job-name=tv-tryjoint
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=200G
#SBATCH --time=01:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=4
ARMS=${1:-try,try+sizes,try+sizes+traits}
shift || true
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
PIDS=""
for ARM in ${ARMS//,/ }; do
  "$PY" -u try_joint.py --data "$DATA" --out "$DATA/try-joint" --arms "$ARM" "$@" > "$ROOT/logs/tryjoint-$SLURM_JOB_ID-$ARM.log" 2>&1 &
  PIDS="$PIDS $!"
done
wait $PIDS || true
tail -n 4 "$ROOT"/logs/tryjoint-$SLURM_JOB_ID-*.log
