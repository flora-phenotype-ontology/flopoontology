#!/usr/bin/env bash
# ORIX lane of the full flora run: keep one Qwen (vLLM) job queued on an ORIX freecycle GPU, and
# whenever it runs, tunnel to it through the login node and run floras through it with
# LANE=orix tools/run_floras_full.sh (largest flora first, WFO excluded). The job is preemptible
# and limited to 24 h; when it ends, the driver stops within two minutes, the job is resubmitted,
# and the flora resumes from its caches when the next job comes up.
#
#   tmux new -d -s flopo-orix 'tools/orix_qwen_lane.sh'
#   tools/run_floras_full.sh --status          # shows "orix lane: ..." from local-corpora/run-logs/orix/state
#   ORIX_WORKERS=32 (concurrent requests), ORIX_LOCAL_PORT=8200, ORIX_HOST=orix
set -uo pipefail
cd "$(dirname "$0")/.."
ORIX=${ORIX_HOST:-orix}
RDIR=/mnt/data/u/hohndor/flopo-qwen
LOGS=local-corpora/run-logs; OD=$LOGS/orix; mkdir -p "$OD"
LPORT=${ORIX_LOCAL_PORT:-8200}
SOCK=$OD/tunnel.sock
PY=${PY:-$HOME/.cache/flopo-venv/bin/python}
export LANE=orix WORKERS=${ORIX_WORKERS:-32}
export LLM_BASE_URL=http://127.0.0.1:$LPORT/v1 LLM_KEY_FILE=$OD/key HEALTH_URL=http://127.0.0.1:$LPORT/health
declare -A GRES=([h100]=gpu:nvidia_h100_80gb_hbm3:1 [h200]=gpu:nvidia_h200:1)

log() { echo "== $(date -Is) $*" | tee -a "$OD/lane.log" >&2; }
state() { echo "$(date -Is) $*" > "$OD/state"; }
rssh() { ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 "$ORIX" "$@"; }

close_tunnel() { [[ -S $SOCK ]] && ssh -S "$SOCK" -O exit "$ORIX" 2>/dev/null; rm -f "$SOCK"; }
open_tunnel() {  # ip port
  close_tunnel
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -M -S "$SOCK" -f -N -L "127.0.0.1:$LPORT:$1:$2" "$ORIX"
}

# "RUNNING node", "PENDING reason", "" (gone); exit 1 when the cluster could not be asked.
job_state() {
  local out; out=$(rssh "squeue -h -j $1 -o '%T %N %r' 2>/dev/null; echo END") || return 1
  [[ $out == *END ]] || return 1
  echo "${out%END}" | head -1
}
idle_gpus() {  # prints "<idle h100> <idle h200>" over the freecycle partitions
  rssh "scontrol show node -o" | "$PY" -c '
import re, sys
idle = {"h100": 0, "h200": 0}
for line in sys.stdin:
    parts = re.search(r"Partitions=(\S+)", line)
    if not parts or "State=" not in line or re.search(r"State=\S*(DOWN|DRAIN|NOT_RESPONDING)", line):
        continue
    kind = "h100" if "freecycle-h100" in parts.group(1) else "h200" if "freecycle-h200" in parts.group(1) else None
    if not kind:
        continue
    cfg = re.search(r"CfgTRES=\S*gres/gpu=(\d+)", line); alloc = re.search(r"AllocTRES=\S*gres/gpu=(\d+)", line)
    idle[kind] += int(cfg.group(1) if cfg else 0) - int(alloc.group(1) if alloc else 0)
print(idle["h100"], idle["h200"])'
}
pick_type() {
  local h100 h200; read -r h100 h200 < <(idle_gpus) || { echo h100; return; }
  if (( ${h100:-0} > 0 )); then echo h100; elif (( ${h200:-0} > 0 )); then echo h200; else echo h100; fi
}
submit() {  # type -> job id
  rssh "cd $RDIR && sbatch --parsable --partition=freecycle-$1 --gres=${GRES[$1]} qwen_flopo.sbatch" | cut -d';' -f1
}
node_ip() { rssh "scontrol show node -o $1" | sed -n 's/.*NodeAddr=\([^ ]*\).*/\1/p' | head -1; }

JOB=$(cat "$OD/job" 2>/dev/null || true); JOB_TYPE=$(cat "$OD/job.type" 2>/dev/null || true)
DRIVER_PID="" RUN_SEEN=0 PEND_SEEN=0
finish() {
  close_tunnel
  if [[ -n ${DRIVER_PID:-} ]] && kill -0 "$DRIVER_PID" 2>/dev/null; then kill "$DRIVER_PID" 2>/dev/null; fi
  if [[ -n ${JOB:-} ]]; then rssh "scancel $JOB" 2>/dev/null && log "cancelled job $JOB"; rm -f "$OD/job"; fi
  state "stopped"
}
trap 'finish; exit 0' TERM INT HUP

rssh "mkdir -p $RDIR/logs $RDIR/state" && scp -q tools/orix/qwen_flopo.sbatch "$ORIX:$RDIR/" || { log "cannot reach $ORIX"; exit 1; }
log "lane start: WORKERS=$WORKERS local port $LPORT${JOB:+, job $JOB from an earlier run}"

while :; do
  if [[ -z $JOB ]]; then
    JOB_TYPE=$(pick_type)
    if JOB=$(submit "$JOB_TYPE") && [[ $JOB =~ ^[0-9]+$ ]]; then
      echo "$JOB" > "$OD/job"; echo "$JOB_TYPE" > "$OD/job.type"; PEND_SEEN=0 RUN_SEEN=0
      log "submitted job $JOB to freecycle-$JOB_TYPE"; state "queued job $JOB (freecycle-$JOB_TYPE)"
    else
      JOB=""; log "sbatch failed; retrying in 10 min"; sleep 600
    fi
    sleep 60; continue
  fi
  if ! st=$(job_state "$JOB"); then log "cannot query $ORIX; retrying in 2 min"; sleep 120; continue; fi
  case "${st%% *}" in
    "")
      log "job $JOB ended"
      close_tunnel   # the driver notices the dead endpoint and stops its build within 2 min
      state "job $JOB ended; resubmitting"
      JOB=""; rm -f "$OD/job" "$OD/key"
      ;;
    PENDING)
      PEND_SEEN=$((PEND_SEEN + 1))
      if (( PEND_SEEN % 5 == 0 )); then  # every 10 min: move to the other GPU type if that one has room
        read -r h100 h200 < <(idle_gpus) || true
        other=h200; (( ${h200:-0} > 0 )) || other=""
        [[ $JOB_TYPE == h200 ]] && { other=h100; (( ${h100:-0} > 0 )) || other=""; }
        if [[ -n $other ]]; then
          log "job $JOB still pending on freecycle-$JOB_TYPE while freecycle-$other has an idle GPU; resubmitting there"
          rssh "scancel $JOB"; JOB=""; rm -f "$OD/job"; continue
        fi
      fi
      state "queued job $JOB (freecycle-$JOB_TYPE, ${st#* })"
      sleep 120
      ;;
    RUNNING)
      node=$(echo "$st" | awk '{print $2}')
      RUN_SEEN=$((RUN_SEEN + 1))
      if [[ -n $DRIVER_PID ]] && ! kill -0 "$DRIVER_PID" 2>/dev/null; then
        wait "$DRIVER_PID"; rc=$?; DRIVER_PID=""
        if (( rc == 0 )); then
          log "no flora left for the ORIX lane; releasing job $JOB"
          close_tunnel; rssh "scancel $JOB"; rm -f "$OD/job" "$OD/key"; state "finished: no flora left"
          exit 0
        fi
        log "driver exited with status $rc while job $JOB runs; reconnecting"
        close_tunnel
      fi
      if [[ -z $DRIVER_PID ]]; then
        ep=$(rssh "cat $RDIR/state/$JOB.endpoint 2>/dev/null" || true)
        if [[ -z $ep ]]; then
          if (( RUN_SEEN > 20 )); then log "job $JOB has run 20 min without a server; cancelling"; rssh "scancel $JOB"; JOB=""; rm -f "$OD/job"; continue; fi
          state "job $JOB starting on $node"; sleep 60; continue
        fi
        host=${ep% *}; port=${ep#* }; ip=$(node_ip "$host")
        if [[ -z $ip ]]; then log "no address for $host"; sleep 60; continue; fi
        (umask 077; rssh "cat $RDIR/state/$JOB.key" > "$OD/key.tmp") && mv "$OD/key.tmp" "$OD/key" || { sleep 60; continue; }
        if ! open_tunnel "$ip" "$port"; then log "tunnel to $host:$port failed"; sleep 60; continue; fi
        up=0; for i in 1 2 3 4 5 6; do curl -sf -m 10 "$HEALTH_URL" >/dev/null && { up=1; break; }; sleep 10; done
        if (( up == 0 )); then log "no answer from $host:$port through the tunnel"; close_tunnel; sleep 60; continue; fi
        log "qwen up: job $JOB on $host:$port, local port $LPORT"; state "running job $JOB on $host ($JOB_TYPE)"
        tools/run_floras_full.sh >> "$OD/driver-console.log" 2>&1 &
        DRIVER_PID=$!
      fi
      sleep 60
      ;;
    *)  # COMPLETING, CONFIGURING, ...
      sleep 60
      ;;
  esac
done
