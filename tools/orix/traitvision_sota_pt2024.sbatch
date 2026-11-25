#!/bin/bash
# PlantTraits2024 (Kaggle): heads on the frozen BioCLIP 2 embeddings (embedded by traitvision_sota_benchmarks.sbatch). About 15 min.
#SBATCH --job-name=sota-pt2024
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:40:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
ROOT=/mnt/data/u/hohndor/flopo-vision
O=$ROOT/pilot-v1/sota-out
cd "$ROOT/pilot-v1/src"
"$ROOT/vision-pixi/envs/default/bin/python" -u planttraits2024.py fit --root $ROOT/sota-benchmarks/planttraits2024/competitions/planttraits2024 \
  --emb $O/emb-pt2024 --emb-test $O/emb-pt2024-test --out $O/pt2024
