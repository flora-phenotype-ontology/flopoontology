#!/usr/bin/env bash
# End-to-end build for any flora in flopo2.ingest.external.FLORA_SOURCES.
# Usage:
#   tools/build_flora.sh powo-fiq powo-cayman
#   LIMIT=200 tools/build_flora.sh eflora-fna eflora-foc
# Endpoint: LLM_BASE_URL, LLM_MODEL, LLM_KEY_FILE override the unimatrix defaults of the LLM stages
# (another endpoint, e.g. for a manual run against an ORIX job).
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

EXTRA=()
[ -n "${LLM_BASE_URL:-}" ] && EXTRA+=(--base-url "$LLM_BASE_URL")
[ -n "${LLM_MODEL:-}" ] && EXTRA+=(--model "$LLM_MODEL")
[ -n "${LLM_KEY_FILE:-}" ] && EXTRA+=(--key-file "$LLM_KEY_FILE")

"$PYTHON" -m flopo2.ingest.pipeline "$@" --workers "$WORKERS" --limit "$LIMIT" ${EXTRA[@]+"${EXTRA[@]}"}
