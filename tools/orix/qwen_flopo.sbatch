#!/bin/bash
# vLLM serving Qwen3.8-27B-FP8 (the model behind the BORG unimatrix endpoint) on one ORIX freecycle
# GPU for the FLOPO flora runs. The server listens on the node's network with a per-job random key;
# the client is tools/run_floras_full.sh on ws, reached through an SSH tunnel that
# tools/orix_qwen_lane.sh opens via the login node. Partition and GPU type come from the sbatch
# command line (freecycle requires an explicit type):
#   sbatch --partition=freecycle-h100 --gres=gpu:nvidia_h100_80gb_hbm3:1 qwen_flopo.sbatch
# The job ends when the server dies, when it is cancelled or preempted, after 24 h, or when no
# request has been served for 30 minutes (so an orphaned job does not hold an idle GPU).
#SBATCH --job-name=flopo-qwen
#SBATCH --qos=freecycle
#SBATCH --time=1-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err
set -uo pipefail
cd /mnt/data/u/hohndor/flopo-qwen
export PATH=$HOME/.pixi/bin:$PATH HF_HOME=/mnt/data/u/hohndor/hf HF_HUB_OFFLINE=1
PORT=$((8300 + RANDOM % 100))
umask 077; mkdir -p state logs
KEYF=state/$SLURM_JOB_ID.key EPF=state/$SLURM_JOB_ID.endpoint
python3 -c "import secrets; print(secrets.token_hex(24))" > "$KEYF"
echo "[$(date -Is)] node=$(hostname) job=$SLURM_JOB_ID port=$PORT"
nvidia-smi --query-gpu=name,memory.total --format=csv

VLLM_API_KEY="$(cat "$KEYF")" pixi run --manifest-path /mnt/data/u/hohndor/qwen-serve-cu129/pixi.toml \
  vllm serve Qwen/Qwen3.8-27B-FP8 --served-model-name qwen3.8-27b --host 0.0.0.0 --port "$PORT" \
  --max-model-len 32768 --max-num-seqs 256 --kv-cache-dtype fp8 --gpu-memory-utilization 0.92 \
  --reasoning-parser qwen3 --speculative-config '{"method":"mtp","num_speculative_tokens":2}' \
  > "logs/vllm-$SLURM_JOB_ID.log" 2>&1 &
VPID=$!
cleanup() { kill "$VPID" 2>/dev/null; rm -f "$KEYF" "$EPF"; echo "[$(date -Is)] stopped"; }
trap 'cleanup; exit 0' TERM INT HUP
trap 'cleanup' EXIT

for i in $(seq 1 120); do
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  kill -0 "$VPID" 2>/dev/null || break
  sleep 10
done
if ! curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
  echo "vllm did not start"; tail -50 "logs/vllm-$SLURM_JOB_ID.log"; exit 1
fi
echo "$(hostname) $PORT" > "$EPF"
echo "[$(date -Is)] vllm up"

served() { curl -sf "http://127.0.0.1:$PORT/metrics" | awk '/^vllm:request_success_total/ {s+=$NF} END {printf "%d", s}'; }
last=$(served); idle=0
while kill -0 "$VPID" 2>/dev/null; do
  sleep 60
  now=$(served)
  if [[ $now == "$last" ]]; then idle=$((idle + 1)); else idle=0; last=$now; fi
  if (( idle >= 30 )); then echo "[$(date -Is)] no request for 30 min; releasing the GPU"; break; fi
done
echo "[$(date -Is)] served $(served) requests"
