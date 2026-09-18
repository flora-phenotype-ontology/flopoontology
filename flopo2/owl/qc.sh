#!/usr/bin/env bash
set -euo pipefail

OWL="${1:-ontology/flopo-v2-candidate.ttl}"
GATED="${2:-}"
PYTHON_BIN="${PYTHON:-python3}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROBOT_BIN="${ROBOT:-}"
if [[ -z "$ROBOT_BIN" && -x "$ROOT/bin/robot" ]]; then
  ROBOT_BIN="$ROOT/bin/robot"
fi
if [[ -z "$ROBOT_BIN" ]] && command -v robot >/dev/null 2>&1; then
  ROBOT_BIN="$(command -v robot)"
fi

if [[ -n "$GATED" ]]; then
  "$PYTHON_BIN" -m flopo2.owl.qc "$OWL" --gated "$GATED"
else
  "$PYTHON_BIN" -m flopo2.owl.qc "$OWL"
fi

if [[ -n "$ROBOT_BIN" ]]; then
  "$ROBOT_BIN" reason --reasoner ELK --input "$OWL" --output /tmp/flopo-v2-reasoned.owl
  "$ROBOT_BIN" report --input /tmp/flopo-v2-reasoned.owl --output /tmp/flopo-v2-report.tsv
else
  echo "robot not found; skipped ROBOT/ELK release QC" >&2
fi
