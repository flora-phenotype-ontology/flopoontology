#!/bin/bash
# SOTA comparison 3/6: the Schiller et al. 2021 CNNs (6 TRY traits x 3 architectures, Keras, 512 px) on
#   ours : manifest roles small (3 photographs per species) and field                     -> sota-out/schiller
#   ptn  : the PlantTraitNet validation subset and the in-situ reference photographs       -> sota-out/schiller-val, sota-out/schiller-ref
#   sbatch traitvision_sota_schiller.sbatch ours [SHARD NSHARDS]
#   sbatch traitvision_sota_schiller.sbatch ptn
# 18 networks per photograph: read the rate (photographs per second) in the log after 5 minutes. About 155 000 photographs in 'ours';
# if the projected time is above 100 minutes, split with SHARD/NSHARDS (e.g. 0 3, 1 3, 2 3 as three jobs; results go to schiller-s<SHARD>).
#SBATCH --job-name=tv-sota-schiller
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=48
#SBATCH --mem=120G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export TF_CPP_MIN_LOG_LEVEL=1 TF_FORCE_GPU_ALLOW_GROWTH=true OMP_NUM_THREADS=1
MODE=${1:-ours}; SHARD=${2:-0}; NSH=${3:-1}
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/sota-tf-env/bin/python        # TensorFlow 2.15 (Keras 2) in its own venv
M=$ROOT/sota-models/schiller2021
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
if [ "$MODE" = ours ]; then
  OUT=$DATA/sota-out/schiller; [ "$NSH" != 1 ] && OUT=$DATA/sota-out/schiller-s$SHARD
  "$PY" -u run_schiller.py --data "$DATA" --manifest sota-photos.tsv --roles small,field --models "$M" --out "$OUT" \
    --workers 44 --shard "$SHARD" --shards "$NSH" --worldclim "$ROOT/sota-benchmarks/worldclim14"
else
  B=$ROOT/sota-benchmarks/planttraitnet
  "$PY" -u run_schiller.py --data "$DATA" --items "$DATA/sota-out/ptn-val.tsv" --root "$B" --models "$M" --out "$DATA/sota-out/schiller-val" --workers 44 --worldclim "$ROOT/sota-benchmarks/worldclim14"
  "$PY" -u run_schiller.py --data "$DATA" --items "$DATA/sota-out/ptn-reference.tsv" --root "$B" --models "$M" --out "$DATA/sota-out/schiller-ref" --workers 44 --worldclim "$ROOT/sota-benchmarks/worldclim14"
fi
