#!/bin/bash
#SBATCH --job-name=flopo-full-diagnostic
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=00:45:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/full-diagnostic-source-v1"
/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python -u -m flopo2.vision.full_diagnostic \
  --runs "$DATA/full-runs-v1" --features "$DATA/full-features-v1" --models "$DATA/modern-models" \
  --data "$DATA/flopo-full-v1" \
  --small "$DATA/visual-small-v1" --external "$DATA/leaf-control-v1" \
  --screen "$DATA/modern-screen-v1/fgclip2-large" --audit "$DATA/trait-evaluation-v1" --out "$DATA/full-diagnostic-v1"
