#!/bin/bash
# SOTA comparison 1/6: PhenoVision (flower/fruit) and PhenoVisionL on every photograph of the pilot, then scored against iNaturalist's
# phenology annotations next to our own BioCLIP 2 head (score_phenology.py), and written as phenology scores for allphotos_train.py --pheno.
#   sbatch traitvision_sota_phenovision.sbatch          (about 30-45 min: 1.62 million photographs through two ViT-L, then 5 small head fits)
#SBATCH --job-name=tv-sota-pheno
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
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
cd "$DATA/src"
# GPU use is logged every 30 s: the cluster cancels jobs that stay under 75%
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
OUT=$DATA/sota-out/phenovision
if [ ! -f "$OUT/scores.npz" ]; then
  "$PY" -u run_phenovision.py --data "$DATA" --manifest sota-photos.tsv --models "$ROOT/sota-models" --out "$OUT" \
    --roles all,field --workers 44
fi
"$PY" -u score_phenology.py --data "$DATA" --scores "$OUT/scores.npz" --out "$OUT"
