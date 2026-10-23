#!/usr/bin/env bash
# Deploy the Saudi Flora Trait Atlas on ws with a QLever endpoint (docs/atlas-deploy.md).
#
#   tools/deploy_atlas.sh [--stamp S] [--skip-tests]   build, index, check on staging, switch, check live
#   tools/deploy_atlas.sh --rollback                     make the previous release live again
#   tools/deploy_atlas.sh --monitor                      check the live site (for cron)
#   tools/deploy_atlas.sh --status                       show what is live
#
# Set PUBLIC_URL (default http://phenomebrowser.net/flopo/) to also check the public address after
# the switch; PUBLIC_URL= skips that check. The script stops at the first failed check; a failure
# after the switch restores the previous release.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-$HOME/.cache/flopo-venv/bin/python}
REPO=$PWD
RELEASES=$REPO/local-corpora/saudi-flora/releases
STATE=$RELEASES/state
QLEVER_IMAGE=adfreiburg/qlever@sha256:73935fe83e361f01f64c85563d479dc279d168996adaac8d2531b1db11179e64
NGINX_IMAGE=nginx@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
NGINX=flopo-atlas-nginx
LIVE_URL=http://127.0.0.1:8778/
STAGING_URL=http://127.0.0.1:8779/
PUBLIC_URL=${PUBLIC_URL-http://phenomebrowser.net/flopo/}
declare -A PORT=([blue]=7001 [green]=7002)

log() { echo "== $(date +%T) $*" >&2; }
die() { echo "deploy_atlas: $*" >&2; exit 1; }
checks() { "$PY" -m tools.atlas_checks "$@"; }

mkdir -p "$STATE"
LIVE_STAMP="" LIVE_COLOUR="" PREV_STAMP="" PREV_COLOUR=""
[[ -f $STATE/live.env ]] && source "$STATE/live.env"

write_conf() {  # name stamp colour
  cat > "$STATE/$1.conf" <<EOF
set \$atlas_root /srv/atlas/$2/web;
set \$atlas_qlever 127.0.0.1:${PORT[$3]};
set \$atlas_release $2;
EOF
}

write_env() {
  cat > "$STATE/live.env" <<EOF
LIVE_STAMP=$LIVE_STAMP
LIVE_COLOUR=$LIVE_COLOUR
PREV_STAMP=$PREV_STAMP
PREV_COLOUR=$PREV_COLOUR
EOF
}

reload_nginx() {
  if [[ -z $(docker ps -q --filter "name=^$NGINX$") ]]; then
    docker rm -f "$NGINX" >/dev/null 2>&1 || true
    docker run -d --name "$NGINX" --restart unless-stopped --network host \
      -v "$REPO/deploy/atlas/nginx:/etc/nginx/conf.d:ro" -v "$RELEASES:/srv/atlas:ro" "$NGINX_IMAGE" >/dev/null
    sleep 2
  fi
  docker exec "$NGINX" nginx -t -q && docker exec "$NGINX" nginx -s reload
  sleep 1
}

start_qlever() {  # colour stamp
  local name=flopo-atlas-qlever-$1 port=${PORT[$1]}
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --restart unless-stopped -u "$(id -u):$(id -g)" \
    -p "127.0.0.1:$port:$port" -v "$RELEASES/$2/index:/data" -w /data \
    --entrypoint /qlever/qlever-server "$QLEVER_IMAGE" \
    -i atlas -p "$port" -j 8 -m 8G -c 4G -s 30s --index-description "Saudi Flora Trait Atlas $2" >/dev/null
  for _ in $(seq 120); do
    curl -sf "http://127.0.0.1:$port/?query=ASK%7B%3Fs%20%3Fp%20%3Fo%7D" -H 'Accept: application/sparql-results+json' \
      | grep -q true && return 0
    sleep 1
  done
  docker logs --tail 20 "$name" >&2
  die "QLever $name did not come up"
}

rollback() {
  [[ -n $PREV_STAMP ]] || die "no previous release to roll back to"
  [[ -n $(docker ps -q --filter "name=^flopo-atlas-qlever-$PREV_COLOUR$") ]] || start_qlever "$PREV_COLOUR" "$PREV_STAMP"
  log "rolling back: $LIVE_STAMP ($LIVE_COLOUR) -> $PREV_STAMP ($PREV_COLOUR)"
  write_conf live "$PREV_STAMP" "$PREV_COLOUR"
  local s=$LIVE_STAMP c=$LIVE_COLOUR
  LIVE_STAMP=$PREV_STAMP LIVE_COLOUR=$PREV_COLOUR PREV_STAMP=$s PREV_COLOUR=$c
  write_env
  reload_nginx
  checks smoke "$LIVE_URL" --release "$RELEASES/$LIVE_STAMP" --stage rollback
}

case "${1:-}" in
  --status)
    echo "live: ${LIVE_STAMP:-none} (${LIVE_COLOUR:-}), previous: ${PREV_STAMP:-none} (${PREV_COLOUR:-})"
    docker ps --filter name=flopo-atlas --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
    exit 0 ;;
  --rollback) rollback; exit $? ;;
  --monitor)
    [[ -n $LIVE_STAMP ]] || die "nothing is live"
    status=0
    checks smoke "$LIVE_URL" --release "$RELEASES/$LIVE_STAMP" --report "$STATE/monitor-last.json" --stage monitor || status=1
    if [[ -n $PUBLIC_URL ]]; then
      checks smoke "$PUBLIC_URL" --release "$RELEASES/$LIVE_STAMP" --report "$STATE/monitor-last.json" --stage monitor-public || status=1
    fi
    echo "$(date -Is) monitor $([[ $status == 0 ]] && echo ok || echo FAILED) $LIVE_STAMP" >> "$STATE/monitor.log"
    exit $status ;;
esac

STAMP=$(date +%Y%m%d-%H%M) SKIP_TESTS=0
while [[ $# -gt 0 ]]; do
  case $1 in
    --stamp) STAMP=$2; shift 2 ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    *) die "unknown option $1" ;;
  esac
done
REL=$RELEASES/$STAMP
COLOUR=blue; [[ $LIVE_COLOUR == blue ]] && COLOUR=green

# Stage 1: build and pre-flight.
if [[ $SKIP_TESTS == 0 ]]; then
  log "C1 tests"
  "$PY" -m pytest -q tests/test_atlas_patterns.py tests/test_saudi_flora.py tests/test_ncvc_annotate.py \
    || die "C1 tests failed"
fi
log "release $STAMP"
"$PY" -m tools.atlas_release --stamp "$STAMP"
checks preflight "$REL" ${LIVE_STAMP:+--previous "$RELEASES/$LIVE_STAMP"} || die "pre-flight checks failed"

# Stage 2: QLever index, candidate endpoint on the idle colour, staging checks and parity.
log "QLever index"
mkdir -p "$REL/index"
files=(); for f in "$REL"/rdf/*.nq; do files+=(-f "rdf/$(basename "$f")"); done
docker run --rm -u "$(id -u):$(id -g)" -v "$REL:/data" -w /data --entrypoint /qlever/qlever-index "$QLEVER_IMAGE" \
  -i index/atlas "${files[@]}" -F nq > "$REL/index.log" 2>&1 || { tail -20 "$REL/index.log"; die "index build failed"; }
log "QLever $COLOUR on port ${PORT[$COLOUR]}"
start_qlever "$COLOUR" "$STAMP"
write_conf staging "$STAMP" "$COLOUR"
[[ -f $STATE/live.conf ]] || write_conf live "$STAMP" "$COLOUR"   # first deployment: nothing live yet
reload_nginx
log "staging checks"
checks smoke "$STAGING_URL" --release "$REL" --stage staging || die "staging checks failed; live is unchanged"
checks crawl "$STAGING_URL" --out "$REL/queries.jsonl" --release "$REL" || die "browser checks failed; live is unchanged"
checks parity "$REL" --qlever "http://127.0.0.1:${PORT[$COLOUR]}/" --queries "$REL/queries.jsonl" \
  || die "parity checks failed; live is unchanged"

# Stage 3: switch.
log "switch live to $STAMP ($COLOUR)"
PREV_STAMP=$LIVE_STAMP PREV_COLOUR=$LIVE_COLOUR LIVE_STAMP=$STAMP LIVE_COLOUR=$COLOUR
write_conf live "$STAMP" "$COLOUR"
write_env
reload_nginx

# Stage 4: checks on the live addresses; restore the previous release on failure.
ok=1
checks smoke "$LIVE_URL" --release "$REL" --stage live || ok=0
if [[ $ok == 1 && -n $PUBLIC_URL ]]; then
  checks smoke "$PUBLIC_URL" --release "$REL" --stage public || ok=0
fi
if [[ $ok == 0 ]]; then
  if [[ -n $PREV_STAMP ]]; then rollback; else log "no previous release; leaving $STAMP live"; fi
  die "live checks failed"
fi
log "deployed $STAMP; previous ${PREV_STAMP:-none} stays on ${PREV_COLOUR:-none} for --rollback"
