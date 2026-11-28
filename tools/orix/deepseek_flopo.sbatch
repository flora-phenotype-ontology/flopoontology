#!/bin/bash
# vLLM serving DeepSeek-V4.1-Flash-1017 (MIT; 761B parameters, 511 GB) on four H200 of one ORIX
# node, for the second-model review of FLOPO candidates (tools/llm_candidate_review.py) and other
# curation work that needs a stronger model than Qwen3.8-27B. Settings are the H200 recipe of
# https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4.1-Flash (tensor parallel 4, Engram tables in
# host memory), text only. Environment and weights: docs/deepseek-on-orix.md.
#   sbatch --partition=pi-hohndor --gres=gpu:nvidia_h200:4 deepseek_flopo.sbatch
# The server listens on the node's network with a per-job random key (state/<job>.key, .endpoint);
# reach it from ws through an SSH tunnel via the login node. ORIX cancels jobs that keep a GPU
# below 75 % utilisation: the utilisation of every GPU is logged every 30 s to logs/gpu-<job>.csv,
# and the job ends when no request has been served for IDLE_MIN minutes (default 10).
#SBATCH --job-name=flopo-deepseek
#SBATCH --time=1-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=28
#SBATCH --mem=480G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
set -uo pipefail
cd /mnt/data/u/hohndor/flopo-deepseek
export PATH=$HOME/.pixi/bin:$PATH HF_HOME=/mnt/data/u/hohndor/hf HF_HUB_OFFLINE=1
export VLLM_ENGINE_READY_TIMEOUT_S=3600 VLLM_USE_RUST_FRONTEND=${VLLM_USE_RUST_FRONTEND:-1}
PORT=$((8400 + RANDOM % 100))
umask 077; mkdir -p state logs
KEYF=state/$SLURM_JOB_ID.key EPF=state/$SLURM_JOB_ID.endpoint
python3 -c "import secrets; print(secrets.token_hex(24))" > "$KEYF"
echo "[$(date -Is)] node=$(hostname) job=$SLURM_JOB_ID port=$PORT"
nvidia-smi --query-gpu=index,name,memory.total --format=csv
# Triton compiles the MXFP4 expert kernel when the engine starts and needs the driver library; on
# ORIX it is not in the linker cache. Checked here, before 15 minutes of loading.
CUDA_LIB=$(find /usr/lib /usr/lib64 /usr/local /run /opt /lib -name 'libcuda.so.1' 2>/dev/null | head -1)
[ -n "$CUDA_LIB" ] && export TRITON_LIBCUDA_PATH=$(dirname "$CUDA_LIB")
pixi run --manifest-path /mnt/data/u/hohndor/deepseek-serve/pixi.toml python -c "
from triton.backends.nvidia.driver import libcuda_dirs; print('libcuda in', libcuda_dirs())" || { echo "no libcuda.so.1 for Triton"; exit 1; }
nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used --format=csv,noheader -l 30 \
  > "logs/gpu-$SLURM_JOB_ID.csv" 2>&1 &
SMI=$!

VLLM_API_KEY="$(cat "$KEYF")" pixi run --manifest-path /mnt/data/u/hohndor/deepseek-serve/pixi.toml \
  vllm serve deepseek-ai/DeepSeek-V4.1-Flash-1017 --served-model-name deepseek-v4.1-flash \
  --host 0.0.0.0 --port "$PORT" \
  --tokenizer-mode deepseek_v41 --tensor-parallel-size 4 --engram-config '{"cpu_offload":true}' \
  --tool-call-parser deepseek_v41 --enable-auto-tool-choice --reasoning-parser deepseek_v41 \
  --language-model-only --max-model-len ${MAX_MODEL_LEN:-262144} --max-num-seqs ${MAX_NUM_SEQS:-128} \
  > "logs/vllm-$SLURM_JOB_ID.log" 2>&1 &
VPID=$!
cleanup() { kill "$VPID" "$SMI" 2>/dev/null; rm -f "$KEYF" "$EPF"; echo "[$(date -Is)] stopped"; }
trap 'cleanup; exit 0' TERM INT HUP
trap 'cleanup' EXIT

for i in $(seq 1 360); do   # loading 511 GB takes a while
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  kill -0 "$VPID" 2>/dev/null || break
  sleep 10
done
if ! curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
  echo "vllm did not start"; tail -80 "logs/vllm-$SLURM_JOB_ID.log"; exit 1
fi
echo "$(hostname) $PORT" > "$EPF"
echo "[$(date -Is)] vllm up"

served() { curl -sf "http://127.0.0.1:$PORT/metrics" | awk '/^vllm:request_success_total/ {s+=$NF} END {printf "%d", s}'; }
last=$(served); idle=0
while kill -0 "$VPID" 2>/dev/null; do
  sleep 60
  now=$(served)
  if [[ $now == "$last" ]]; then idle=$((idle + 1)); else idle=0; last=$now; fi
  if (( idle >= ${IDLE_MIN:-10} )); then echo "[$(date -Is)] no request for ${IDLE_MIN:-10} min; releasing the GPUs"; break; fi
done
echo "[$(date -Is)] served $(served) requests"
