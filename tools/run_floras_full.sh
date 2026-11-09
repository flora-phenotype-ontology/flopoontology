#!/usr/bin/env bash
# Run every external flora in full against the Qwen endpoint on unimatrix, smallest flora first,
# and republish the trait atlas (flopo2.saudi.build + tools/deploy_atlas.sh) after each flora
# completes (docs/full-flora-run-plan.md).
#
#   tmux new -d -s flopo-floras 'tools/run_floras_full.sh'
#   WORKERS=4 tools/run_floras_full.sh            # default: 4 concurrent Qwen requests
#   tools/run_floras_full.sh --status             # what is done, running, failed
#
# A flora is "done" when local-corpora/run-logs/done/<source> exists; delete that file to rerun it.
# Every Qwen answer is cached per flora, so stopping and restarting the script resumes.
set -uo pipefail
cd "$(dirname "$0")/.."
export WORKERS="${WORKERS:-4}" LIMIT=0
PY=${PY:-$HOME/.cache/flopo-venv/bin/python}
LOGS=local-corpora/run-logs
DONE=$LOGS/done
RELEASES=local-corpora/saudi-flora/releases
mkdir -p "$DONE"

# Ascending by number of species treatments (flopo2.ingest.external stats, 2026-11-08).
ORDER=(
  powo-tong eflora-andes eflora-fom powo-grassbase powo-fiq powo-cate korup-flora powo-cayman
  silvics-na powo-fsom phytokeys powo-fwta powo-kew powo-ildis plants-tibet plazi africa-tree-db
  usda-plants powo-fz powo-ftea feis-plants flora-guianas illinois-wildflowers smithsonian-botany
  eflora-mfoc flora-malesiana flora-gabon flora-zimbabwe eflora-fop eflora-other powo-neotropical
  fdac nybg-naf eflora-fna kew-african eflora-foc wfo
)

log() { echo "== $(date -Is) $*" | tee -a "$LOGS/driver.log" >&2; }

if [[ ${1:-} == --status ]]; then
  for src in "${ORDER[@]}"; do
    if [[ -f $DONE/$src ]]; then echo "done     $src  ($(cat "$DONE/$src"))"
    elif [[ -f $LOGS/$src.failed ]]; then echo "FAILED   $src"
    elif [[ -f $LOGS/$src.log ]]; then echo "running  $src  ($(tail -c 300 "$LOGS/$src.log" | tr '\n' ' ' | tail -c 160))"
    else echo "pending  $src"; fi
  done
  exit 0
fi

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

publish() {  # source
  local alog=$LOGS/atlas-$1.log stamp
  stamp=$(date +%Y%m%d-%H%M)-$1
  log "atlas build after $1 -> $alog"
  if ! "$PY" -m flopo2.saudi.build >> "$alog" 2>&1; then log "ATLAS BUILD FAILED after $1 (see $alog)"; return 1; fi
  log "atlas deploy $stamp"
  if ! tools/deploy_atlas.sh --stamp "$stamp" >> "$alog" 2>&1; then log "ATLAS DEPLOY FAILED after $1 (see $alog)"; return 1; fi
  log "atlas live: $stamp"
  prune_releases >> "$alog" 2>&1 || true
}

log "driver start: WORKERS=$WORKERS, ${#ORDER[@]} floras"
for src in "${ORDER[@]}"; do
  [[ -f $DONE/$src ]] && continue
  rm -f "$LOGS/$src.failed"
  ok=0
  for attempt in 1 2 3; do
    log "$src attempt $attempt (WORKERS=$WORKERS)"
    if tools/build_flora.sh "$src" >> "$LOGS/$src.log" 2>&1; then ok=1; break; fi
    log "$src attempt $attempt failed; waiting 10 min before retrying"
    sleep 600
  done
  if [[ $ok == 0 ]]; then
    log "$src FAILED three times; moving on (tail of $LOGS/$src.log follows)"
    tail -5 "$LOGS/$src.log" >> "$LOGS/driver.log"
    touch "$LOGS/$src.failed"
    continue
  fi
  date -Is > "$DONE/$src"
  log "$src complete"
  publish "$src" || true
done
log "driver finished; failed: $(ls "$LOGS"/*.failed 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/.failed//' | tr '\n' ' ')"
