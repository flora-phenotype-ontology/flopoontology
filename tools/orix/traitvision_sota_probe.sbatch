#!/bin/bash
# SOTA comparison 5/6: every encoder scored on OUR tests with the same head and protocol (probe_any.py; MLP + bag loss, held-out genera,
# balanced accuracy on agreed species and on observers' labels), restricted to the photographs of the SOTA manifest.
#   sbatch traitvision_sota_probe.sbatch [NAMES]      NAMES default: bioclip2,planttraitnet,planttraitnet-pred,schiller-pred
#   bioclip2 is the reference row; planttraitnet = its 1024-d representation (needs sota-out/planttraitnet/emb-0.*);
#   *-pred = the predicted continuous traits only (pred_to_emb.py first), linear head on standardised columns.
# One process per encoder and trait half, all on the one GPU at the same time (each fit is small; together they keep it busy).
# About 30-40 min. Check logs/gpu-<job>.txt in the first minutes: below 75% means add seeds or encoders, not wait.
#SBATCH --job-name=tv-sota-probe
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=24
#SBATCH --mem=160G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=2
NAMES=${1:-bioclip2,planttraitnet,planttraitnet-pred,schiller-pred}
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
GPULOG=$!
A=habit,flower_colour,leaf_margin,leaf_complexity
Bt=leaf_arrangement,spines,inflorescence,fruit_colour
for N in ${NAMES//,/ }; do
  EXTRA="--require-geo"           # every arm sees the same photographs: those with a location (PlantTraitNet needs one)
  case "$N" in *-pred) EXTRA="--require-geo --head linear --standardize";; esac
  for HALF in A Bt; do
    TR=${!HALF}
    "$PY" -u probe_any.py --data "$DATA" --names "$N" --traits "$TR" --seeds 0,1,2 $EXTRA --out "$DATA/sota-out/probe-$N-$HALF" > "$ROOT/logs/sota-probe-$N-$HALF.log" 2>&1 &
  done
done
wait $(jobs -p | grep -v "^$GPULOG$") || true
cat "$ROOT"/logs/sota-probe-*.log | grep -E "MEAN|seed 0 " | tail -60
