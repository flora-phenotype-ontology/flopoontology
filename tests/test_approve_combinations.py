from __future__ import annotations

import csv

import pytest


REVIEW_HEADER = (
    "po_id\tpo_label\tpato_id\tpato_label\tproposed_label\treview_status\t"
    "reviewer\treview_date\treview_notes\n"
)


def _rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_approve_review_records_provenance_and_updates_whitelist_idempotently(tmp_path):
    from flopo2.verify.approve_combinations import approve_review

    review = tmp_path / "review.tsv"
    review.write_text(
        REVIEW_HEADER
        + "PO_0000001\tleaf\tPATO_0000001\tgreen\tleaf green\tpending\t\t\t\n"
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0000002\tPATO_0000002\tallowed\tseed\tpetal red\n"
    )
    approved = tmp_path / "approved.tsv"
    kwargs = {
        "review_path": review,
        "combinations_path": combinations,
        "approved_review_path": approved,
        "reviewer": "https://orcid.org/0000-0001-8149-5890",
        "review_date": "2026-07-17",
        "source": "curator_review_2026-07-17",
        "note": "Approved as reusable.",
    }
    first = approve_review(**kwargs)
    second = approve_review(**kwargs)

    assert first["added"] == 1
    assert second["added"] == 0
    assert second["already_allowed"] == 1
    assert len(_rows(combinations)) == 2
    row = _rows(approved)[0]
    assert row["review_status"] == "approved"
    assert row["reviewer"].endswith("0000-0001-8149-5890")
    assert row["review_notes"] == "Approved as reusable."


def test_approve_review_refuses_a_blocked_pair(tmp_path):
    from flopo2.verify.approve_combinations import approve_review

    review = tmp_path / "review.tsv"
    review.write_text(
        REVIEW_HEADER
        + "PO_0000001\tleaf\tPATO_0000001\tgreen\tleaf green\tpending\t\t\t\n"
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0000001\tPATO_0000001\tblocked\tcuration\tbad pair\n"
    )
    with pytest.raises(ValueError, match="conflicts with blocked"):
        approve_review(
            review,
            combinations,
            tmp_path / "approved.tsv",
            "reviewer",
            "2026-07-17",
            "curator_review_2026-07-17",
        )


def test_approve_review_allows_a_flopo_local_anatomy_bearer(tmp_path):
    from flopo2.verify.approve_combinations import approve_review

    review = tmp_path / "review.tsv"
    review.write_text(
        REVIEW_HEADER
        + "FLOPO_1234567\torchid labellum\tPATO_0000323\twhite\t"
        "orchid labellum white\tpending\t\t\t\n"
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text("po_id\tpato_id\tstatus\tsource\texample_label\n")

    result = approve_review(
        review,
        combinations,
        tmp_path / "approved.tsv",
        "https://orcid.org/0000-0001-8149-5890",
        "2026-07-18",
        "curator_review_2026-07-18",
    )

    assert result["added"] == 1
    assert _rows(combinations)[0]["po_id"] == "FLOPO_1234567"
