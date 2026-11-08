#!/bin/bash
#SBATCH --job-name=flopo-multi-traits
#SBATCH --account=pi-hohndor
#SBATCH --partition=batch-h200
#SBATCH --qos=batch
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:20:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export HF_HOME=/mnt/data/u/hohndor/flopo-vision/hf-cache
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
data_dir=/mnt/data/u/hohndor/flopo-vision/visual-v2
py=.pixi/envs/default/bin/python
"$py" -m flopo2.vision.extract --data "$data_dir" \
    --models /mnt/data/u/hohndor/flopo-vision/models --out "$data_dir/extraction"
for vocabulary in "$data_dir"/vocabulary-*.json; do
    name=$(basename "$vocabulary" .json)
    "$py" -m flopo2.vision.prototypes --models /mnt/data/u/hohndor/flopo-vision/models \
        --vocabulary "$vocabulary" --out "$data_dir/multi-priors/${name#vocabulary-}"
done
exec "$py" -m flopo2.vision.multi --data "$data_dir" --out "$data_dir/runs/$SLURM_JOB_ID" --device cuda
