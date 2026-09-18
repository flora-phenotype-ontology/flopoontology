from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest


INPUT_DIR = Path(
    "scratchpad/flopo-semantic-v2-20260718/unresolved-recovery/logical/exact-pato-compounds"
)


def test_resolved_finding_inventory_is_bounded_and_complete():
    from flopo2.verify.audit_exact_pato_promotions import (
        CURRENT_RETAIN_REVIEWS,
        REQUIRED_FINAL_SAFE_KEYS,
        RESOLVED_PRIOR_FINDINGS,
    )

    assert CURRENT_RETAIN_REVIEWS == {}
    assert len(RESOLVED_PRIOR_FINDINGS) == 6
    assert {key[0] for key in RESOLVED_PRIOR_FINDINGS} == {"kew"}
    assert {key[2] for key in RESOLVED_PRIOR_FINDINGS} == {
        "84806",
        "102815",
        "106937",
        "108633",
        "110000",
        "113322",
    }
    assert Counter(review.issue_category for review in RESOLVED_PRIOR_FINDINGS.values()) == {
        "attribution_modality_unmodeled": 1,
        "part_vs_whole_wrong_bearer": 1,
        "wrong_po_bearer": 1,
        "state_context_unmodeled": 1,
        "unmodeled_colour_modifier": 2,
    }
    assert all(review.notes.strip() for review in RESOLVED_PRIOR_FINDINGS.values())
    assert {key[2] for key in REQUIRED_FINAL_SAFE_KEYS} == {"101232", "106937"}


@pytest.mark.skipif(
    not all(
        (INPUT_DIR / f"{flora}-recovered-baseline.jsonl").exists()
        for flora in ("fdac", "gabon", "kew", "malesiana")
    ),
    reason="full exact-compound recovery snapshots are not present",
)
def test_exhaustive_audit_reconciles_every_promotion_without_mutating_inputs(tmp_path):
    from flopo2.verify.audit_exact_pato_promotions import (
        EXPECTED_SHA256,
        REVIEW_DIMENSIONS,
        audit_exact_pato_promotions,
    )

    output_tsv = tmp_path / "all-occurrences.tsv"
    report_json = tmp_path / "report.json"
    markdown = tmp_path / "REPORT.md"
    report = audit_exact_pato_promotions(
        INPUT_DIR,
        output_tsv,
        report_json,
        markdown_report=markdown,
    )

    assert report["result"] == "pass"
    assert all(report["invariants"].values())
    assert report["counts"] == {
        "reviewed": 338,
        "pass": 338,
        "retain": 0,
        "duplicate_groups": 116,
    }
    assert report["by_flora_and_decision"] == {
        "kew:pass": 297,
        "malesiana:pass": 41,
    }
    assert all(
        details["sha256_before"] == EXPECTED_SHA256[flora]
        and details["sha256_after"] == EXPECTED_SHA256[flora]
        for flora, details in report["inputs"].items()
    )

    with output_tsv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 338
    assert Counter(row["decision"] for row in rows) == {"pass": 338}
    assert all(row["decision"] in {"pass", "retain"} for row in rows)
    assert all(row["issue_category"] and row["notes"] for row in rows)
    assert all(row["review_status"] == "manual_complete" for row in rows)
    assert all(row["review_dimensions"] == "|".join(REVIEW_DIMENSIONS) for row in rows)
    assert all(row["po_label"] and row["pato_label"] for row in rows)
    assert len({row["duplicate_group_id"] for row in rows}) == 116
    assert all(row["decision"] == "pass" for row in rows if row["input_flora"] == "malesiana")
    assert report["retained_cases"] == []
    assert len(report["resolved_prior_findings"]) == 6
    assert report_json.exists() and markdown.exists()
