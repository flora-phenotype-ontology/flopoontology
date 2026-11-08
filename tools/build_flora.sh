#!/usr/bin/env bash
# End-to-end build for any flora in flopo2.ingest.external.FLORA_SOURCES.
# Usage:
#   tools/build_flora.sh powo-fiq powo-cayman
#   LIMIT=200 tools/build_flora.sh eflora-fna eflora-foc
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-.}"

PYTHON="${PYTHON:-$HOME/.cache/flopo-venv/bin/python}"
WORKERS="${WORKERS:-16}"
LIMIT="${LIMIT:-0}"

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <flora-source> [<flora-source> ...]" >&2
  exit 1
fi

"$PYTHON" -m flopo2.ingest.pipeline "$@" --workers "$WORKERS" --limit "$LIMIT"
