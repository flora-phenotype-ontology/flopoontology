#!/bin/bash
#SBATCH --job-name=flopo-profile-ablation
#SBATCH --account=pi-hohndor
#SBATCH --partition=batch-h200
#SBATCH --qos=batch
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:05:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
cd /home/hohndor/orix-workbench/flopo-vision
export HF_HOME=/mnt/data/u/hohndor/flopo-vision/hf-cache
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
data_dir=/mnt/data/u/hohndor/flopo-vision/visual-v2
py=.pixi/envs/default/bin/python
"$py" -m flopo2.vision.multi --data "$data_dir" --out "$data_dir/runs/$SLURM_JOB_ID" \
    --device cuda --source-policy partial --validation-only
exec "$py" -m flopo2.vision.predict --checkpoint "$data_dir/runs/$SLURM_JOB_ID/model.pt" \
    --image "$data_dir/images/683222324.jpg" --models /mnt/data/u/hohndor/flopo-vision/models \
    --phenotypes "$data_dir/phenotype-queries.json" --out "$data_dir/runs/$SLURM_JOB_ID/raw-image-example.json"
