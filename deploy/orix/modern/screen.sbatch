#!/bin/bash
#SBATCH --job-name=flopo-modern-screen
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=00:30:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export OMP_NUM_THREADS=4
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PY=.pixi/envs/default/bin/python
DATA=/mnt/data/u/hohndor/flopo-vision
OUT=${1:-$DATA/modern-screen-v1}
for MODEL in fgclip2-base siglip2-base fgclip2-large; do
  "$PY" -u -m flopo2.vision.modern extract --data "$DATA/visual-small-v1" \
    --external "$DATA/leaf-control-v1" --models "$DATA/modern-models" \
    --model "$MODEL" --out "$OUT/$MODEL"
  "$PY" -u -m flopo2.vision.modern evaluate --out "$OUT/$MODEL" \
    --audit "$DATA/trait-evaluation-v1" --phenotypes "$DATA/visual-v2/phenotype-queries.json"
done
