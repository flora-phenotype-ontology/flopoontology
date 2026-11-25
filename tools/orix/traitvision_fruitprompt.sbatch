#!/bin/bash
# Trait-vision: try prompts for the fruit detector on labelled observations (short job).
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=48G
#SBATCH --time=00:20:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
DATA=/mnt/data/u/hohndor/flopo-vision/pilot-v1
PY=/mnt/data/u/hohndor/flopo-vision/vision-pixi/envs/default/bin/python
cd "$DATA/src"
run() { "$PY" -u detect.py --manifest "$DATA/fruit-prompt-test.tsv" --images "$DATA/field/images" --out "$DATA/crops-field/fruitprompt-$1.tsv" \
  --model /mnt/data/u/hohndor/flopo-vision/baseline-models/grounding-dino-base --workers 16 --threshold 0.12 --min-side 0.01 --prompt "$2"; }
run a 'a leaf. a flower. a fruit. a stem. a thorn.'
run b 'a leaf. a flower. a fruit. a berry. a seed pod. a nut. a stem. a thorn.'
run c 'a leaf. a flower. a fruit or berry or seed pod. a stem. a thorn.'
