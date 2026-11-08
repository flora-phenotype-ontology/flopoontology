#!/bin/bash
#SBATCH --job-name=flopo-full-train
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --array=0-14%4
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/full-source-v1"
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
MODES=(direct mil hierarchy projected shuffled)
MODE=${MODES[$((SLURM_ARRAY_TASK_ID % 5))]}
SEED=$((20261026 + SLURM_ARRAY_TASK_ID / 5))
fit_run() {
  local MODE_ARG=$1 OBS_ARG=$2 OUT_ARG=$3
  if ! test -f "$OUT_ARG/training.json"; then
    "$PY" -u -m flopo2.vision.full_train fit --data "$DATA/flopo-full-v1" --features "$DATA/full-features-v1" \
      --models "$DATA/modern-models" --out "$OUT_ARG" --mode "$MODE_ARG" --observations "$OBS_ARG" \
      --seed "$SEED" --steps 1200 --warmup 200
  fi
  if ! test -f "$OUT_ARG/prediction-manifest.json"; then
    "$PY" -u -m flopo2.vision.full_eval predict --data "$DATA/flopo-full-v1" --features "$DATA/full-features-v1" \
      --models "$DATA/modern-models" --run "$OUT_ARG"
  fi
}
# Matched frozen baselines and nested data-size controls accompany each MIL seed.
if test "$MODE" = mil; then
  if test "$SEED" = 20261026; then
    BASE="$DATA/full-runs-v1/pretrained"
    if ! test -f "$BASE/training.json"; then
      "$PY" -u -m flopo2.vision.full_train fit --data "$DATA/flopo-full-v1" --features "$DATA/full-features-v1" \
        --models "$DATA/modern-models" --out "$BASE" --mode pretrained --seed "$SEED" --steps 0 --warmup 0
    fi
    "$PY" -u -m flopo2.vision.full_eval predict --data "$DATA/flopo-full-v1" --features "$DATA/full-features-v1" \
      --models "$DATA/modern-models" --run "$BASE"
  fi
  for OBS in 10 50 200; do
    fit_run frozen "$OBS" "$DATA/full-runs-v1/frozen-$OBS-$SEED"
  done
  for OBS in 10 50; do
    fit_run mil "$OBS" "$DATA/full-runs-v1/mil-$OBS-$SEED"
  done
fi
fit_run "$MODE" 200 "$DATA/full-runs-v1/$MODE-200-$SEED"
