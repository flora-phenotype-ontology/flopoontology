#!/bin/bash
# SOTA comparison 6/6: the fruit-colour test (agreed species and observers) with fruit photographs chosen by
#   phenovision : PhenoVision's fruit probability >= 0.6 (its published threshold)       needs sota-out/phenovision/phenovision-as-pheno.npz
#   organ       : the Pl@ntNet-300K organ head, fruit probability >= 0.5               needs sota-out/plantnet-organ/organ-as-pheno.npz
#   (default detector choice, Grounding DINO boxes, is the existing allphotos result: pilot-v1/allphotos/*fruit_colour*.json)
#   sbatch traitvision_sota_fruit.sbatch            (about 40 min; allphotos_train.py is the existing script, unchanged)
#SBATCH --job-name=tv-sota-fruit
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=160G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export OMP_NUM_THREADS=4
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
GPULOG=$!
"$PY" -u allphotos_train.py --data "$DATA" --out "$DATA/sota-out/fruit-phenovision" --traits fruit_colour \
  --pheno "$DATA/sota-out/phenovision/phenovision-as-pheno.npz" --thr 0.6 > "$ROOT/logs/sota-fruit-phenovision.log" 2>&1 &
"$PY" -u allphotos_train.py --data "$DATA" --out "$DATA/sota-out/fruit-organ" --traits fruit_colour \
  --pheno "$DATA/sota-out/plantnet-organ/organ-as-pheno.npz" --thr 0.5 > "$ROOT/logs/sota-fruit-organ.log" 2>&1 &
wait $(jobs -p | grep -v "^$GPULOG$") || true
tail -n 12 "$ROOT/logs/sota-fruit-phenovision.log" "$ROOT/logs/sota-fruit-organ.log"
