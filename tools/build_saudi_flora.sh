#!/usr/bin/env bash
# Rebuild the Saudi-flora annotation corpora and RDF dataset (see flopo2/saudi/build.py).
# The LLM steps (flopo2.ingest.collenette_llm, flopo2.ingest.llm_term_rules) are cached and only
# call the model for new entries/words.  Run from the repository root.
set -euo pipefail
PY=${PY:-$HOME/.cache/flopo-venv/bin/python}
NCVC=local-corpora/saudi-ncvc-guide
COLL=local-corpora/saudi-collenette
# The atlas reads an NCVC run that also applies the Collenette and LLM-proposed rules; the default
# derived/ corpus keeps to the reviewed NCVC rules (tests/test_ncvc_eq_extension.py).
ATLAS_NCVC=local-corpora/saudi-flora/ncvc-derived
OVERRIDE="flopo2/ingest/flora_value_term_rules.tsv flopo2/ingest/collenette_normalization.tsv"
EXTRA="flopo2/ingest/llm_term_rules.tsv"

$PY -m flopo2.ingest.collenette_llm --workers "${WORKERS:-12}"
$PY -m flopo2.ingest.collenette_annotate > /dev/null
$PY -m flopo2.ingest.ncvc_annotate $NCVC > /dev/null
$PY -m flopo2.ingest.ncvc_annotate $NCVC -o $ATLAS_NCVC --extra-rules $EXTRA --override-rules $OVERRIDE --atlas > /dev/null
$PY -m flopo2.ingest.llm_term_rules $COLL/derived/collenette-saudi-dispositions.tsv \
    $NCVC/derived/ncvc-saudi-phenotype-dispositions.tsv
# Qwen locates the endpoints of alternatives/continua that the deterministic matcher missed
$PY -m flopo2.ingest.llm_relations $ATLAS_NCVC/ncvc-saudi-annotated.jsonl $ATLAS_NCVC/ncvc-saudi-phenotype-dispositions.tsv \
    $COLL/derived/collenette-saudi-annotated.jsonl $COLL/derived/collenette-saudi-dispositions.tsv
# second pass with the (possibly extended) LLM rules and located relations
$PY -m flopo2.ingest.collenette_annotate > /dev/null
$PY -m flopo2.ingest.ncvc_annotate $NCVC > /dev/null
$PY -m flopo2.ingest.ncvc_annotate $NCVC -o $ATLAS_NCVC --extra-rules $EXTRA --override-rules $OVERRIDE --atlas > /dev/null
for corpus in $ATLAS_NCVC/ncvc-saudi-annotated $COLL/derived/collenette-saudi-annotated; do
  $PY -m flopo2.verify.data_model $corpus.jsonl --stage gated > $corpus.validation.json || true
done
$PY -m flopo2.saudi.taxa
$PY -m flopo2.saudi.build "$@"
