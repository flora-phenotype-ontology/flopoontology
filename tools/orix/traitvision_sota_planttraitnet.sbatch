#!/bin/bash
# SOTA comparison 2/6: PlantTraitNet (4 continuous traits; 3 multi-trait + 4 single-trait checkpoints) on
#   ours : the pilot photographs of the manifest roles pheno, field, train (about 470 000)  -> sota-out/planttraitnet
#   ptn  : the PlantTraitNet validation subset and the in-situ reference photographs         -> sota-out/ptn-val, sota-out/ptn-ref
#   sbatch traitvision_sota_planttraitnet.sbatch ours      (about 30-50 min)
#   sbatch traitvision_sota_planttraitnet.sbatch ptn       (about 10 min; needs sota-out/ptn-val.tsv and ptn-reference.tsv, see the doc)
#SBATCH --job-name=tv-sota-ptn
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
MODE=${1:-ours}
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/sota-env/bin/python            # pixi environment + rshf, omegaconf (needed to unpickle the checkpoints), pandas, sklearn
M=$ROOT/sota-models/planttraitnet
export TORCH_HOME=$M/torch-home
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
if [ "$MODE" = ours ]; then
  "$PY" -u run_planttraitnet.py --data "$DATA" --manifest sota-photos.tsv --roles pheno,field,train --models "$M" \
    --out "$DATA/sota-out/planttraitnet" --workers 44 --batch 256
else
  B=$ROOT/sota-benchmarks/planttraitnet
  "$PY" -u run_planttraitnet.py --data "$DATA" --items "$DATA/sota-out/ptn-val.tsv" --root "$B" --models "$M" \
    --out "$DATA/sota-out/ptn-val" --workers 44 --batch 256
  "$PY" -u run_planttraitnet.py --data "$DATA" --items "$DATA/sota-out/ptn-reference.tsv" --root "$B" --models "$M" \
    --out "$DATA/sota-out/ptn-ref" --workers 44 --batch 256
fi
