#!/bin/bash
# Trait-vision pilot on ORIX: BioCLIP 2 embeddings of the pilot photos, then the trait heads.
# Submit from the login node after download.py has finished:
#   sbatch /mnt/data/u/hohndor/flopo-vision/pilot-v1/src/traitvision_pilot.sbatch
#SBATCH --job-name=flopo-trait-pilot
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=08:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=8
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
MODEL=/mnt/data/u/hohndor/flopo-vision/staged-models-v1/bioclip2
cd "$DATA/src"
if [ ! -f "$DATA/emb/emb-0.npy" ]; then
  "$PY" -u embed.py --manifest "$DATA/inat-photos.tsv" --images "$DATA/images" --model "$MODEL" \
    --out "$DATA/emb" --prompts "$DATA/prompts.tsv"
fi
if [ -f "$DATA/field-photos.tsv" ] && [ ! -f "$DATA/emb-field/emb-0.npy" ]; then
  "$PY" -u embed.py --manifest "$DATA/field-photos.tsv" --images "$DATA/field/images" --model "$MODEL" \
    --out "$DATA/emb-field"
fi
"$PY" -u train.py --data "$DATA" --out "$DATA/run-$SLURM_JOB_ID"
