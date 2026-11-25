#!/bin/bash
# SOTA comparison 4/6: OUR model on THEIR benchmarks. BioCLIP 2 embeddings of
#   * the PlantTraitNet validation subset and in-situ reference photographs  (sota-out/emb-ptn-val, emb-ptn-ref)
#   * Pl@ntNet-300K (306 146 images with organ labels)                        (sota-out/emb-plantnet)
# then ptn_benchmark.py fit (continuous traits + plant functional type, genus-held-out) and plantnet_organ.py fit (organ head, test split,
# and the head applied to our photographs against iNaturalist phenology annotations).
# Needs, from the login node and after the downloads have finished (see docs/flopo-trait-vision-sota.md):
#   python ptn_lists.py --root $ROOT/sota-benchmarks/planttraitnet --out $DATA/sota-out
#   python plantnet_organ.py lists --zip $ROOT/sota-benchmarks/plantnet-300k/plantnet_300K.zip --out $DATA/sota-out
#   sbatch traitvision_sota_benchmarks.sbatch            (about 30 min)
#SBATCH --job-name=tv-sota-bench
#SBATCH --account=pi-hohndor
#SBATCH --partition=pi-hohndor
#SBATCH --qos=pi-hohndor
#SBATCH --gres=gpu:nvidia_h200:1
#SBATCH --cpus-per-task=48
#SBATCH --mem=300G
#SBATCH --time=01:55:00
#SBATCH --output=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.out
#SBATCH --error=/mnt/data/u/hohndor/flopo-vision/logs/%x-%j.err
set -euo pipefail
export HF_HUB_OFFLINE=1 OMP_NUM_THREADS=1
ROOT=/mnt/data/u/hohndor/flopo-vision
DATA=$ROOT/pilot-v1
PY=$ROOT/vision-pixi/envs/default/bin/python
MODEL=$ROOT/staged-models-v1/bioclip2
B=$ROOT/sota-benchmarks
cd "$DATA/src"
stdbuf -oL nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits -l 30 > "$ROOT/logs/gpu-$SLURM_JOB_ID.txt" &
O=$DATA/sota-out
[ -f $O/emb-plantnet/emb-0.npy ] || "$PY" -u embed_paths.py --list $O/plantnet-list.tsv --zip $B/plantnet-300k/plantnet_300K.zip --model $MODEL --out $O/emb-plantnet --workers 44
[ -f $O/emb-ptn-val/emb-0.npy ] || "$PY" -u embed_paths.py --list $O/ptn-val.tsv --root $B/planttraitnet --model $MODEL --out $O/emb-ptn-val --workers 44
[ -f $O/emb-ptn-ref/emb-0.npy ] || "$PY" -u embed_paths.py --list $O/ptn-reference.tsv --root $B/planttraitnet --model $MODEL --out $O/emb-ptn-ref --workers 44
"$PY" -u ptn_benchmark.py fit --data $O --emb-val $O/emb-ptn-val --emb-ref $O/emb-ptn-ref --out $O/ptn
"$PY" -u plantnet_organ.py fit --data $DATA --emb $O/emb-plantnet --out $O/plantnet-organ
# PlantTraits2024 (Kaggle): lists from the login node first (planttraits2024.py lists)
P=$B/planttraits2024/competitions/planttraits2024
[ -f $O/emb-pt2024/emb-0.npy ] || "$PY" -u embed_paths.py --list $O/pt2024-list.tsv --root $P --model $MODEL --out $O/emb-pt2024 --workers 44
[ -f $O/emb-pt2024-test/emb-0.npy ] || "$PY" -u embed_paths.py --list $O/pt2024-test-list.tsv --root $P --model $MODEL --out $O/emb-pt2024-test --workers 44
"$PY" -u planttraits2024.py fit --root $P --emb $O/emb-pt2024 --emb-test $O/emb-pt2024-test --out $O/pt2024
# the fruit-colour test with fruit photographs chosen by the Pl@ntNet organ head (the PhenoVision arm is in traitvision_sota_fruit.sbatch)
"$PY" -u allphotos_train.py --data "$DATA" --out "$O/fruit-organ" --traits fruit_colour --pheno "$O/plantnet-organ/organ-as-pheno.npz" --thr 0.5 | tail -n 12
