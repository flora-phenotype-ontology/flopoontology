"""Sanity tests for the assembled silver standard (skipped if it hasn't been generated)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SILVER = Path("gold/silver_standard.jsonl")
pytestmark = pytest.mark.skipif(not SILVER.exists(), reason="silver standard not generated")


def _rows():
    return [json.loads(line) for line in SILVER.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_silver_is_well_formed():
    rows = _rows()
    assert len(rows) == 400
    for r in rows:
        assert {"source", "taxon", "organ", "language", "text", "assertions"} <= r.keys()
        for a in r["assertions"]:
            assert a["po_id"].startswith("PO_")
            assert a["pato_id"].startswith("PATO_")
            assert a.get("source_text")  # provenance present
            assert "source_verbatim" in a  # validation flag applied


def test_silver_loads_via_eval_harness():
    from flopo2.eval.gold import load_gold

    pairs = list(load_gold(SILVER))
    assert len(pairs) == 400
    total = sum(len(assertions) for _, assertions in pairs)
    assert total > 1000  # ~2.5k assertions expected


def test_silver_ids_are_grounded_to_lexicons():
    import csv

    def ids(path):
        with open(path, newline="") as fh:
            return {row["id"] for row in csv.DictReader(fh, delimiter="\t")}

    po = ids("config/po_lexicon.tsv")
    pato = ids("config/pato_lexicon.tsv")
    for r in _rows():
        for a in r["assertions"]:
            assert a["po_id"] in po
            assert a["pato_id"] in pato
