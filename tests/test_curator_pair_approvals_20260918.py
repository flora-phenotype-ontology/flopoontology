from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVALS = ROOT / "curation" / "curator-2026-09-18-po-pato-approvals.tsv"
COMBINATIONS = ROOT / "config" / "valid_combinations.tsv"
SOURCE = "curator_review_2026-09-18"
# PATO homonym traps and abnormal-sense (relative to a reference) terms screened out on 2026-09-18.
FORBIDDEN_PATO = {
    "PATO_0000455",  # pubescent = puberty
    "PATO_0002352",  # herbaceous = die-back
    "PATO_0000587",  # decreased size
    "PATO_0000574",  # decreased length
    "PATO_0000599",  # decreased width
    "PATO_0000586",  # increased size
    "PATO_0000470",  # increased amount
    "PATO_0000969",  # dwarf-like
    "PATO_0001227",  # variant
}


def _tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_every_approved_pair_is_allowed_with_curator_source():
    combos = {(row["po_id"], row["pato_id"]): row for row in _tsv(COMBINATIONS)}
    approvals = _tsv(APPROVALS)
    assert len(approvals) == 379
    for row in approvals:
        assert row["review_status"] == "approved"
        assert row["reviewer"] == "https://orcid.org/0000-0001-8149-5890"
        assert row["review_date"] == "2026-09-18"
        combo = combos[(row["po_id"], row["pato_id"])]
        assert combo["status"] == "allowed"
        assert combo["source"] == SOURCE


def test_curator_source_is_recognised_by_the_gate():
    from flopo2.verify.gates import load_combinations

    combos = load_combinations(COMBINATIONS)
    phyllary_length = combos[("PO_0009045", "PATO_0000122")]
    assert phyllary_length.curator_reviewed and phyllary_length.review_satisfied


def test_screened_out_pairs_were_not_added():
    added = [row for row in _tsv(COMBINATIONS) if row["source"] == SOURCE]
    assert not {row["pato_id"] for row in added} & FORBIDDEN_PATO
    assert ("PO_0030121", "PATO_0001874") not in {
        (row["po_id"], row["pato_id"]) for row in added
    }  # "discoid head" homonym
