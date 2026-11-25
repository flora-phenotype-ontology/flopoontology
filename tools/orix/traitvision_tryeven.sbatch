#!/bin/bash
# Even comparison with PlantTraitNet (try_even.py): BioCLIP 2 embedding of PlantTraitNet's training photographs, the Climplicit
# embedding of the locations, then one process per arm and regime on the one GPU.
#   sbatch traitvision_tryeven.sbatch ARM@REGIME,ARM@REGIME,... [extra options for try_even.py fit]
# Before, on the login node: try_even.py lists (ptn-train.tsv). Scoring afterwards on the login node: try_even.py score.
#SBATCH --job-name=tv-tryeven
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=48
#SBATCH --mem=300G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=1
RUNS=${1:-emb@all}
shift || true
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
O=$DATA/sota-out
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
[ -f $O/emb-ptn-train/emb-0.npy ] || "$PY" -u embed_paths.py --list $O/ptn-train.tsv --root $ROOT/sota-benchmarks/planttraitnet --model $ROOT/staged-models-v1/bioclip2 --out $O/emb-ptn-train --workers 44
[ -f $O/loc-ptn-train.npy ] || "$ROOT/sota-env/bin/python" -u try_even.py climplicit --data "$DATA" --models $ROOT/sota-models/planttraitnet
export OMP_NUM_THREADS=3
PIDS=""
for RUN in ${RUNS//,/ }; do
  "$PY" -u try_even.py fit --data "$DATA" --out "$DATA/try-even" --arm "${RUN%@*}" --regime "${RUN#*@}" "$@" > "$ROOT/logs/tryeven-$SLURM_JOB_ID-$RUN.log" 2>&1 &
  PIDS="$PIDS $!"
done
wait $PIDS || true
grep -h RESULT "$ROOT"/logs/tryeven-$SLURM_JOB_ID-*.log || true
tail -n 3 "$ROOT"/logs/tryeven-$SLURM_JOB_ID-*.log
