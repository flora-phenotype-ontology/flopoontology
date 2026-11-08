#!/bin/bash
#SBATCH --job-name=flopo-pxgpt
#SBATCH --account=pi-hohndor
#SBATCH --partition=batch-h200
#SBATCH --qos=batch
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%A_%a.err
set -euo pipefail
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=4
DATA=/mnt/data/u/hohndor/flopo-vision
cd "$DATA/pxgpt-source-v1"
PY=/home/hohndor/orix-workbench/flopo-vision/.pixi/envs/default/bin/python
extra=()
if test "${1:-}" = preflight; then
  output="$DATA/pxgpt-preflight-v1/shard-0"
  extra=(--limit 6 --shards 1 --shard-index 0)
else
  output="$DATA/pxgpt-inference-v1/shard-${SLURM_ARRAY_TASK_ID}"
  extra=(--shards 4 --shard-index "$SLURM_ARRAY_TASK_ID")
fi
"$PY" -u -m flopo2.vision.benchmark_infer \
  --benchmark "$DATA/pxgpt-benchmark-v1" --images "$DATA/pxgpt-v2/pxgpt_brassica_release" \
  --runs "$DATA/staged-runs-v1" --models "$DATA/modern-models" \
  --extra-models "$DATA/staged-models-v1" --detector "$DATA/models" \
  --out "$output" "${extra[@]}"
