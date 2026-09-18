from __future__ import annotations

import csv
import json

import pytest

from flopo2.verify.bearer_occurrences import build_occurrence_ledger, stable_occurrence_id


def _lexicons(tmp_path):
    po_obo = tmp_path / "po.obo"
    po_obo.write_text(
        """format-version: 1.2

[Term]
id: PO:0000282
name: trichome
namespace: plant_anatomy
def: "A plant hair." [TEST:1]
is_a: PO:0009011 ! plant structure
relationship: part_of PO:0005679 ! epidermis
synonym: "hair" EXACT []
""",
        encoding="utf-8",
    )
    po_lexicon = tmp_path / "po.tsv"
    with po_lexicon.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("id", "label", "synonyms", "namespace"), delimiter="\t"
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "PO_0000282",
                "label": "trichome",
                "synonyms": "hair",
                "namespace": "plant_anatomy",
            }
        )
    pato_lexicon = tmp_path / "pato.tsv"
    pato_lexicon.write_text(
        "id\tlabel\tsynonyms\tslim\nPATO_0000323\twhite\t\tcolour\n",
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed.tsv"
    reviewed.write_text("surface_form\tpo_id\treview_status\n", encoding="utf-8")
    return po_obo, po_lexicon, pato_lexicon, reviewed


def _record(text: str, source_id: str, index: int, span: dict) -> dict:
    return {
        "source": "flora",
        "source_id": source_id,
        "source_segment_index": index,
        "char_start": index * 100,
        "char_end": index * 100 + len(text),
        "taxon": "Planta exemplar",
        "organ": "description",
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": [span],
    }


def test_ledger_is_occurrence_level_lossless_and_reconciles_vocabulary(tmp_path):
    po_obo, po_lexicon, pato_lexicon, reviewed = _lexicons(tmp_path)
    first_text = "Hair white."
    first_start = first_text.index("white")
    first_span = {
        "start": first_start,
        "end": first_start + len("white"),
        "surface_form": "white",
        "reason": "missing_or_unsupported_bearer",
        "candidate_pato_id": "PATO_0000323",
        "extractor": "test",
    }
    second_text = "No explicit bearer; white."
    second_start = second_text.index("white")
    second_span = {
        **first_span,
        "start": second_start,
        "end": second_start + len("white"),
    }
    records = [
        _record(first_text, "doc", 1, first_span),
        _record(second_text, "doc", 2, second_span),
    ]
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    summary_path = tmp_path / "summary.json"

    summary = build_occurrence_ledger(
        source,
        ledger,
        summary_path,
        po_obo=po_obo,
        po_lexicon=po_lexicon,
        pato_lexicon=pato_lexicon,
        reviewed_bearers=reviewed,
    )

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert summary["counts"]["original_missing_spans"] == 2
    assert summary["counts"].get("recovered_missing_spans", 0) == 0
    assert summary["counts"]["retained_missing_spans"] == 2
    assert len(rows) == 2
    # Root's conservative recovery audit identifies the same PO bearer but retains the span.
    # The occurrence ledger records that vocabulary agreement without promoting the assertion.
    assert rows[0]["review"]["terminal_state"] == "pending_review"
    assert rows[0]["review"]["family"] == "accepted_existing_po"
    assert rows[0]["review"]["authoritative_po_id"] == "PO_0000282"
    assert rows[0]["review"]["decision"] is None
    row = rows[1]
    assert row["text"][row["quality"]["start"] : row["quality"]["end"]] == "white"
    assert row["quality"]["candidate_pato_label"] == "white"
    assert row["previous_segment"]["text"] == first_text
    assert row["next_segment"] is None
    assert row["review"]["family"] == "unresolved_contextual_bearer"
    assert row["review"]["decision"] is None
    assert summary_path.exists()


def test_occurrence_id_is_source_scoped_and_coordinate_only():
    span = {
        "start": 0,
        "end": 3,
        "surface_form": "red",
        "reason": "missing_or_unsupported_bearer",
        "candidate_pato_id": "PATO_1",
        "extractor": "test",
    }
    left = _record("red", "one", 0, span)
    right = _record("red", "two", 0, span)
    assert stable_occurrence_id(left, span) != stable_occurrence_id(right, span)
    assert stable_occurrence_id(left, span) == stable_occurrence_id(
        left, {**span, "candidate_pato_id": "PATO_2"}
    )


def test_ledger_rejects_nonverbatim_spans_and_count_mismatches(tmp_path):
    po_obo, po_lexicon, pato_lexicon, reviewed = _lexicons(tmp_path)
    span = {
        "start": 0,
        "end": 3,
        "surface_form": "blue",
        "reason": "missing_or_unsupported_bearer",
        "candidate_pato_id": "PATO_0000323",
        "extractor": "test",
    }
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps(_record("red", "doc", 0, span)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-verbatim"):
        build_occurrence_ledger(
            source,
            tmp_path / "ledger.jsonl",
            tmp_path / "summary.json",
            po_obo=po_obo,
            po_lexicon=po_lexicon,
            pato_lexicon=pato_lexicon,
            reviewed_bearers=reviewed,
        )

    valid_span = {**span, "surface_form": "red"}
    source.write_text(json.dumps(_record("red", "doc", 0, valid_span)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical occurrence expectations failed"):
        build_occurrence_ledger(
            source,
            tmp_path / "other-ledger.jsonl",
            tmp_path / "other-summary.json",
            po_obo=po_obo,
            po_lexicon=po_lexicon,
            pato_lexicon=pato_lexicon,
            reviewed_bearers=reviewed,
            expected={"retained_missing_spans": 99},
        )


def test_ledger_refuses_to_overwrite_input_or_summary(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="must all be distinct"):
        build_occurrence_ledger(source, source, tmp_path / "summary.json")


def test_ledger_never_populates_a_curation_decision(tmp_path):
    po_obo, po_lexicon, pato_lexicon, reviewed = _lexicons(tmp_path)
    text = "No explicit bearer; white."
    start = text.index("white")
    span = {
        "start": start,
        "end": start + len("white"),
        "surface_form": "white",
        "reason": "missing_or_unsupported_bearer",
        "candidate_pato_id": "PATO_0000323",
        "extractor": "test",
    }
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps(_record(text, "doc", 0, span)) + "\n", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"

    build_occurrence_ledger(
        source,
        ledger,
        tmp_path / "summary.json",
        po_obo=po_obo,
        po_lexicon=po_lexicon,
        pato_lexicon=pato_lexicon,
        reviewed_bearers=reviewed,
    )

    row = json.loads(ledger.read_text(encoding="utf-8"))
    assert row["review"]["terminal_state"] == "pending_review"
    assert row["review"]["decision"] is None
