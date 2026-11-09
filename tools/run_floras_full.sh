#!/usr/bin/env bash
# Run every external flora in full against a Qwen endpoint, one flora at a time, and republish the
# trait atlas (flopo2.saudi.build + tools/deploy_atlas.sh) after each completed flora
# (docs/full-flora-run-plan.md).
#
# Two lanes share one queue. LANE=unimatrix (default) uses the shared endpoint on unimatrix01 and
# takes the smallest flora first; LANE=orix is started by tools/orix_qwen_lane.sh against a vLLM job
# on an ORIX freecycle GPU and takes the largest flora first (WFO excluded until decided). A lane
# claims a flora in local-corpora/run-logs/claims/<source> while it works on it, so the lanes never
# take the same flora; a claim whose holder process is gone counts as released.
#
#   tmux new -d -s flopo-floras 'tools/run_floras_full.sh'
#   WORKERS=4 tools/run_floras_full.sh            # default: 4 concurrent Qwen requests
#   tools/run_floras_full.sh --status             # what is done, running, failed, and the ORIX lane
#
# Endpoint: LLM_BASE_URL / LLM_MODEL / LLM_KEY_FILE (read by tools/build_flora.sh; default the
# unimatrix endpoint). With HEALTH_URL set, a build is stopped when the endpoint has not answered
# for two minutes and the driver exits with status 3 so the lane runner can bring up a new server.
#
# A flora is "done" when local-corpora/run-logs/done/<source> exists; delete that file to rerun it.
# Every Qwen answer is cached per flora, so stopping and restarting the script resumes.
set -uo pipefail
cd "$(dirname "$0")/.."
export WORKERS="${WORKERS:-4}" LIMIT=0
LANE=${LANE:-unimatrix}
PY=${PY:-$HOME/.cache/flopo-venv/bin/python}
LOGS=local-corpora/run-logs
DONE=$LOGS/done
CLAIMS=$LOGS/claims
PENDF=$LOGS/publish-pending
PUBLOCK=$LOGS/publish.lock
RELEASES=local-corpora/saudi-flora/releases
mkdir -p "$DONE" "$CLAIMS"; touch "$PENDF"

# Ascending by number of species treatments (flopo2.ingest.external stats, 2026-11-08).
ORDER=(
  powo-tong eflora-andes eflora-fom powo-grassbase powo-fiq powo-cate korup-flora powo-cayman
  silvics-na powo-fsom phytokeys powo-fwta powo-kew powo-ildis plants-tibet plazi africa-tree-db
  usda-plants powo-fz powo-ftea feis-plants flora-guianas illinois-wildflowers smithsonian-botany
  eflora-mfoc flora-malesiana flora-gabon flora-zimbabwe eflora-fop eflora-other powo-neotropical
  fdac nybg-naf eflora-fna kew-african eflora-foc wfo
)
if [[ $LANE == orix ]]; then  # largest first; ORIX_SKIP (default wfo) is left to a decision
  skip=" ${ORIX_SKIP:-wfo} " rev=()
  for ((i = ${#ORDER[@]} - 1; i >= 0; i--)); do
    [[ $skip == *" ${ORDER[i]} "* ]] || rev+=("${ORDER[i]}")
  done
  ORDER=("${rev[@]}")
fi

# Segments with no successful transcription yet (the cache is append-only: an error row is
# superseded by a later good row for the same source_id).
segment_errors() {
  "$PY" - "local-corpora/$1/raw/$1-qwen.jsonl" <<'PYEND'
import json, sys
from pathlib import Path
path = Path(sys.argv[1]); ok, err = set(), set()
if path.exists():
    for line in path.open(encoding="utf-8"):
        try: row = json.loads(line)
        except json.JSONDecodeError: continue
        (err if "error" in row else ok).add(row["source_id"])
print(len(err - ok))
PYEND
}

log() { echo "== $(date -Is) [$LANE] $*" | tee -a "$LOGS/driver.log" >&2; }

# Claims: "<lane> <pid>" per flora. claim_holder prints a live claim held by another process.
claim_holder() {
  local f=$CLAIMS/$1 lane pid
  [[ -f $f ]] || return 1
  read -r lane pid < "$f" || return 1
  [[ $pid == "$$" ]] && return 1
  if kill -0 "$pid" 2>/dev/null; then echo "$lane"; return 0; fi
  rm -f "$f"; return 1
}
CLAIMED=""
claim() { echo "$LANE $$" > "$CLAIMS/$1"; CLAIMED=$1; }
release() { [[ -n $CLAIMED ]] && rm -f "$CLAIMS/$CLAIMED"; CLAIMED=""; }

if [[ ${1:-} == --status ]]; then
  [[ -d $PUBLOCK ]] && echo "atlas publish in progress (queued for the next one: $(tr '\n' ' ' < "$PENDF" 2>/dev/null))"
  [[ -f $LOGS/orix/state ]] && echo "orix lane: $(cat "$LOGS/orix/state")"
  tail -2 "$LOGS/driver.log" 2>/dev/null
  for src in "${ORDER[@]}"; do
    if [[ -f $DONE/$src ]]; then echo "done     $src  ($(cat "$DONE/$src"); errored segments: $(segment_errors "$src"))"
    elif [[ -f $LOGS/$src.failed ]]; then echo "FAILED   $src"
    elif lane=$(claim_holder "$src"); then echo "running  $src [$lane]  ($(tail -c 300 "$LOGS/$src.log" 2>/dev/null | tr '\n' ' ' | tail -c 160))"
    elif [[ -f $LOGS/$src.log ]]; then echo "paused   $src  (partly transcribed; resumes when a lane takes it)"
    else echo "pending  $src"; fi
  done
  exit 0
fi
trap 'release' EXIT
BUILD_PID=""
on_signal() { [[ -n $BUILD_PID ]] && kill -TERM -- "-$BUILD_PID" 2>/dev/null; release; exit 130; }
trap on_signal TERM INT HUP

# Keep the live and previous atlas releases (and the releases their web-only builds are based on).
prune_releases() {
  "$PY" - <<'PYEOF'
import json, shutil, os
from pathlib import Path
rel = Path("local-corpora/saudi-flora/releases")
env = dict(l.rstrip("\n").split("=", 1) for l in (rel / "state/live.env").read_text().splitlines() if "=" in l)
keep = {env.get("LIVE_STAMP", ""), env.get("PREV_STAMP", "")} - {""}
for stamp in list(keep):
    meta = rel / stamp / "release.json"
    if meta.exists():
        base = json.loads(meta.read_text()).get("base_release")
        if base:
            keep.add(base)
for d in sorted(rel.iterdir()):
    if d.is_dir() and d.name != "state" and d.name not in keep:
        shutil.rmtree(d)
        print(f"pruned atlas release {d.name}")
PYEOF
}

publish() {  # label: one flora, or several joined with '+'
  local alog=$LOGS/atlas-$1.log stamp
  stamp=$(date +%Y%m%d-%H%M)-$(echo "$1" | tr '+' '-' | cut -c1-60)
  log "atlas build after $1 -> $alog"
  if ! "$PY" -m flopo2.saudi.build >> "$alog" 2>&1; then log "ATLAS BUILD FAILED after $1 (see $alog)"; return 1; fi
  log "atlas deploy $stamp"
  if ! tools/deploy_atlas.sh --stamp "$stamp" >> "$alog" 2>&1; then log "ATLAS DEPLOY FAILED after $1 (see $alog)"; return 1; fi
  log "atlas live: $stamp"
  prune_releases >> "$alog" 2>&1 || true
}

# The atlas rebuild and deployment take about 40 minutes and run in the background so the next
# flora's Qwen work starts at once. Completed floras queue in $PENDF; whichever lane takes the lock
# publishes everything queued, round after round, and floras completed meanwhile join the next round.
PUB_PID=""
publish_pending() {
  [[ -s $PENDF ]] || return 0
  if ! mkdir "$PUBLOCK" 2>/dev/null; then
    local holder; holder=$(cat "$PUBLOCK/pid" 2>/dev/null)
    if [[ -n $holder ]] && kill -0 "$holder" 2>/dev/null; then return 0; fi
    rm -rf "$PUBLOCK"; mkdir "$PUBLOCK" 2>/dev/null || return 0
  fi
  (
    echo $BASHPID > "$PUBLOCK/pid"
    trap 'rm -rf "$PUBLOCK"' EXIT
    while [[ -s $PENDF ]]; do
      label=$(sort -u "$PENDF" | paste -sd+ -); : > "$PENDF"
      publish "$label"
    done
  ) &
  PUB_PID=$!
}

ENDPOINT_DOWN=0
endpoint_up() { [[ -z ${HEALTH_URL:-} ]] || curl -sf -m 10 "$HEALTH_URL" >/dev/null; }
run_build() {  # a build is stopped when the endpoint has not answered for two minutes
  if [[ -z ${HEALTH_URL:-} ]]; then tools/build_flora.sh "$1" >> "$LOGS/$1.log" 2>&1; return; fi
  setsid tools/build_flora.sh "$1" >> "$LOGS/$1.log" 2>&1 &
  local pid=$! fails=0; BUILD_PID=$pid
  while kill -0 "$pid" 2>/dev/null; do
    sleep 30
    if endpoint_up; then fails=0; else fails=$((fails + 1)); fi
    if (( fails >= 4 )); then
      log "$1: endpoint $HEALTH_URL has not answered for 2 min; stopping the build"
      kill -TERM -- "-$pid" 2>/dev/null; sleep 10; kill -KILL -- "-$pid" 2>/dev/null
      wait "$pid" 2>/dev/null; BUILD_PID=""; ENDPOINT_DOWN=1; return 1
    fi
  done
  wait "$pid"; local rc=$?; BUILD_PID=""; return $rc
}

log "driver start: WORKERS=$WORKERS endpoint=${LLM_BASE_URL:-unimatrix} ${#ORDER[@]} floras"
first_pass=1
while :; do
  worked=0 blocked=0
  for src in "${ORDER[@]}"; do
    [[ -f $DONE/$src ]] && continue
    if [[ -f $LOGS/$src.failed ]]; then (( first_pass )) && rm -f "$LOGS/$src.failed" || continue; fi
    if claim_holder "$src" >/dev/null; then blocked=1; continue; fi
    if ! endpoint_up; then log "endpoint down before $src; lane stops"; ENDPOINT_DOWN=1; break 2; fi
    claim "$src"; worked=1 ok=0
    for attempt in 1 2 3 4; do
      log "$src attempt $attempt (WORKERS=$WORKERS)"
      if run_build "$src"; then
        # Segments whose transcription failed stay in the cache as error rows and are retried by
        # the next pass (with a higher output cap); rerun until none remain or the passes are used up.
        errs=$(segment_errors "$src")
        if [[ $errs == 0 ]]; then ok=1; break; fi
        log "$src pass $attempt left $errs errored segments; retrying them in 5 min"
        [[ $attempt == 4 ]] && { ok=1; log "$src keeps $errs errored segments (see $LOGS/$src.log)"; break; }
        sleep 300
        continue
      fi
      (( ENDPOINT_DOWN )) && break
      log "$src attempt $attempt failed; waiting 10 min before retrying"
      sleep 600
    done
    if (( ENDPOINT_DOWN )); then release; break 2; fi
    if [[ $ok == 0 ]]; then
      log "$src FAILED four times; moving on (tail of $LOGS/$src.log follows)"
      tail -5 "$LOGS/$src.log" >> "$LOGS/driver.log"
      touch "$LOGS/$src.failed"
      release; continue
    fi
    date -Is > "$DONE/$src"
    log "$src complete"
    release
    echo "$src" >> "$PENDF"
    publish_pending
  done
  first_pass=0
  if (( worked == 0 )); then
    (( blocked )) || break
    sleep 600   # what is left is being worked on by the other lane; look again later
  fi
done
if (( ENDPOINT_DOWN )); then
  [[ -n $PUB_PID ]] && kill -0 "$PUB_PID" 2>/dev/null && log "atlas publish continues in the background (pid $PUB_PID)"
  log "driver stops: endpoint down"
  exit 3
fi
if [[ -n $PUB_PID ]]; then wait "$PUB_PID" || true; fi
publish_pending
if [[ -n $PUB_PID ]]; then wait "$PUB_PID" || true; fi
log "driver finished; failed: $(ls "$LOGS"/*.failed 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/.failed//' | tr '\n' ' ')"
