from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest


DATA_ROOT = Path("scratchpad/flopo-semantic-v2-20260718")
COMPOUND_SPANS = DATA_ROOT / "claude-fanout/compounds/compound_spans.jsonl"
CANONICAL = DATA_ROOT / "disjunction-recovery/four-flora-gated-all-annotated.jsonl"


def test_manual_review_inventory_is_complete_and_conservative():
    from flopo2.verify.audit_exact_noncolour_pato import REVIEWS

    assert len(REVIEWS) == 28
    assert Counter(key[0] for key in REVIEWS) == {
        "lanceolate-triangular": 19,
        "semi-erect": 9,
    }
    safe = [(key, review) for key, review in REVIEWS.items() if review.disposition == "safe_atomic"]
    assert len(safe) == 5
    assert {key[0] for key, _ in safe} == {"lanceolate-triangular"}
    assert {review.po_id for _, review in safe} == {
        "PO_0009031",
        "PO_0009055",
        "PO_0020041",
    }
    assert all(not review.context_flags for _, review in safe)
    assert all(
        review.bearer_relation in {"exact_lexical_bearer", "sound_is_a_superclass"}
        for _, review in safe
    )
    assert sum(
        review.bearer_relation == "sound_is_a_superclass" for _, review in safe
    ) == 1
    assert all(
        review.disposition == "reject"
        for key, review in REVIEWS.items()
        if key[0] == "semi-erect"
    )
    assert any(
        review.bearer_relation == "part_of_not_generalizable"
        for review in REVIEWS.values()
    )


@pytest.mark.skipif(
    not (COMPOUND_SPANS.exists() and CANONICAL.exists()),
    reason="full manually reviewed flora corpus is not present",
)
def test_full_audit_preserves_canonical_and_emits_only_five_safe_proposals(tmp_path):
    from flopo2.verify.audit_exact_noncolour_pato import audit_exact_noncolour_pato

    before = CANONICAL.read_bytes()
    decisions = tmp_path / "decisions.tsv"
    proposals = tmp_path / "proposals.jsonl"
    report_path = tmp_path / "report.json"
    markdown = tmp_path / "REPORT.md"
    report = audit_exact_noncolour_pato(
        COMPOUND_SPANS,
        CANONICAL,
        decisions,
        proposals,
        report_path,
        markdown_report=markdown,
    )

    assert report["result"] == "pass"
    assert all(report["invariants"].values())
    assert report["counts"]["reviewed"] == 28
    assert report["counts"]["safe_atomic"] == 5
    assert report["counts"]["rejected"] == 23
    assert report["counts"]["safe_unique_expressions"] == 3
    assert report["by_form_and_disposition"] == {
        "lanceolate-triangular:reject": 14,
        "lanceolate-triangular:safe_atomic": 5,
        "semi-erect:reject": 9,
    }
    assert CANONICAL.read_bytes() == before

    with decisions.open(encoding="utf-8", newline="") as handle:
        decision_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(decision_rows) == 28
    assert all(row["manual_review"] == "reviewed" for row in decision_rows)
    assert all(row["token_text"] == row["compound"] for row in decision_rows)
    assert sum(row["disposition"] == "safe_atomic" for row in decision_rows) == 5
    assert sum(row["integration_disposition"] == "safe_for_applier" for row in decision_rows) == 5
    assert sum(row["requires_applier"] == "true" for row in decision_rows) == 5
    assert report["integration"] == {
        "canonical_mutated": False,
        "safe_rows_require_applier": True,
        "safe_rows_applied": 0,
        "safe_rows_waiting_for_applier": 5,
        "rejected_rows_must_not_be_applied": 23,
    }

    proposal_rows = [json.loads(line) for line in proposals.read_text(encoding="utf-8").splitlines()]
    assert len(proposal_rows) == 5
    assert all(row["assertion"]["value_operator"] == "atomic" for row in proposal_rows)
    assert all(row["assertion"]["normalization_status"] == "reviewed" for row in proposal_rows)
    assert all(
        all(isinstance(value, str) for value in row["assertion"]["mapping_provenance"])
        for row in proposal_rows
    )
    from flopo2.verify.data_model import _pydantic_assertion

    assert all(_pydantic_assertion(row["assertion"]) for row in proposal_rows)
    assert all(row["assertion"]["pato_id"] == "PATO_0002338" for row in proposal_rows)
    assert all(
        row["assertion"]["phenotype_class_iri"].startswith(
            "https://w3id.org/flopo/annotation-class/FAC_"
        )
        for row in proposal_rows
    )
    assert not any(
        "FLOPO_" in row["assertion"]["phenotype_class_iri"] for row in proposal_rows
    )
    assert {
        row["flopo_signature"] for row in proposal_rows if not row["existing_flopo_iri"]
    } == {
        "EQ|PO_0009031|PATO_0002338",
        "EQ|PO_0020041|PATO_0002338",
    }
