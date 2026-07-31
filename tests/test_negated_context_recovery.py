"""Tests for the ledger-driven negated-context recovery module.

The module materializes reviewed universal phenotype negation and negated upper bounds from an
audited row ledger, re-verifying every offset against the pinned record text, and rewrites each
record non-destructively.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from flopo2.extract import negated_context_recovery as ncr


# --- ledger fixtures ----------------------------------------------------------------------------

_LEDGER_COLUMNS = [
    "stage11_sha256", "stage10_sha256", "source", "source_id", "source_segment_index", "taxon",
    "record_organ", "language", "span_id", "span_start", "span_end", "span_surface",
    "assertion_index_within_span", "kind", "current_promoted", "recommended_promote",
    "current_po_id", "recommended_po_id", "pato_id", "negated", "value_low", "value_high", "unit",
    "value_low_inclusive", "value_high_inclusive", "logical_cue_text", "logical_cue_start",
    "logical_cue_end", "current_frequency_qualifier", "recommended_frequency_qualifier",
    "current_epistemic_modality", "recommended_epistemic_modality", "recommended_modality_text",
    "modality_start", "modality_end", "bearer_context_quality_ids", "bearer_context_text",
    "bearer_context_start", "bearer_context_end", "developmental_stage_term",
    "developmental_stage_text", "developmental_stage_start", "developmental_stage_end",
    "bearer_surface", "bearer_start", "bearer_end", "bearer_evidence_basis", "current_source_text",
    "current_source_start", "current_source_end", "current_raw_entity_text",
    "current_raw_quality_text", "assertion_evidence_text", "assertion_evidence_start",
    "assertion_evidence_end", "source_statement_text", "source_statement_start",
    "source_statement_end", "required_relational_context_text",
    "required_relational_context_start", "required_relational_context_end",
    "current_source_statement_id", "defect_codes", "hold_reason",
    "semantic_clean_if_all_listed_corrections_applied", "current_release_ready", "notes",
]

_TRANCHE_COLUMNS = [
    "source", "source_id", "source_segment_index", "span_start", "span_end", "span_surface",
    "pato_id", "value_high", "unit", "value_high_inclusive", "comparator_cue", "cue_start",
    "cue_end", "bearer_surface", "bearer_start", "bearer_end", "standard_po_bearer_ids",
    "flopo_local_bearer_needed", "disposition", "assertion_evidence_text",
    "assertion_evidence_start", "assertion_evidence_end", "source_statement_text",
    "source_statement_start", "source_statement_end", "required_residual_reason", "notes",
]


def _row(**over) -> dict:
    row = {c: "" for c in _LEDGER_COLUMNS}
    row["recommended_promote"] = "true"
    row["assertion_index_within_span"] = "0"
    row["bearer_evidence_basis"] = "verbatim_local_bearer"
    row["recommended_frequency_qualifier"] = "unspecified"
    row["recommended_epistemic_modality"] = "asserted"
    row.update(over)
    return row


def _write_ledger(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_LEDGER_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return path


def _write_tranche(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=_TRANCHE_COLUMNS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in _TRANCHE_COLUMNS})
    return path


# Record: the 900280-style leaflet quality negation ("... non acuminé ...").
QUALITY_TEXT = "à limbe obovale, parfois à peine apiculé mais non acuminé, assez coriaces"
QUALITY_ROW = _row(
    source="fdac", source_id="900280", source_segment_index="1", record_organ="feuilles",
    span_start="50", span_end="57", span_surface="acuminé", kind="quality",
    recommended_po_id="PO_0020049", pato_id="PATO_0002228", negated="true",
    logical_cue_text="non", logical_cue_start="46", logical_cue_end="49",
    bearer_surface="limbe", bearer_start="2", bearer_end="7",
    current_raw_quality_text="acuminé",
    assertion_evidence_text="non acuminé", assertion_evidence_start="46", assertion_evidence_end="57",
    source_statement_text=QUALITY_TEXT, source_statement_start="0",
    source_statement_end=str(len(QUALITY_TEXT)),
)


def _quality_record() -> dict:
    return {
        "source": "fdac", "source_id": "900280", "source_segment_index": 1,
        "taxon": "Test sp.", "taxon_family": "Fabaceae", "organ": "feuilles", "language": "fr",
        "char_start": 100, "char_end": 100 + len(QUALITY_TEXT),
        "source_statements": [], "term_mentions": [], "text": QUALITY_TEXT,
        "assertions": [{"po_id": "PO_0009025", "pato_id": "PATO_0000000", "negated": False,
                        "source_text": "obovale", "source_start": 8, "source_end": 15}],
        "unresolved_spans": [
            {"start": 50, "end": 57, "surface_form": "acuminé", "reason": "negated_context",
             "candidate_pato_id": "PATO_0002228", "extractor": "deterministic_baseline"},
            {"start": 8, "end": 15, "surface_form": "obovale", "reason": "missing_or_unsupported_bearer"},
        ],
    }


NUM_TEXT = "à tiges grêles, n'atteignant pas 0,5 mm de diamètre"
NUM_ROW = _row(
    source="fdac", source_id="904975", source_segment_index="0", record_organ="herbe",
    span_start="33", span_end="51", span_surface="0,5 mm de diamètre", kind="numeric",
    recommended_po_id="PO_0009047", pato_id="PATO_0001334", negated="false",
    value_high="0.5", unit="mm", value_low_inclusive="true", value_high_inclusive="false",
    logical_cue_text="n'atteignant pas", logical_cue_start="16", logical_cue_end="32",
    bearer_surface="tiges", bearer_start="2", bearer_end="7",
    current_raw_quality_text="0,5 mm de diamètre",
    assertion_evidence_text="n'atteignant pas 0,5 mm de diamètre",
    assertion_evidence_start="16", assertion_evidence_end="51",
    source_statement_text=NUM_TEXT, source_statement_start="0",
    source_statement_end=str(len(NUM_TEXT)),
)


def _numeric_record() -> dict:
    return {
        "source": "fdac", "source_id": "904975", "source_segment_index": 0,
        "taxon": "Test herb", "organ": "herbe", "language": "fr",
        "char_start": 0, "char_end": len(NUM_TEXT),
        "source_statements": [], "term_mentions": [], "text": NUM_TEXT, "assertions": [],
        "unresolved_spans": [
            {"start": 33, "end": 51, "surface_form": "0,5 mm de diamètre", "reason": "negated_context",
             "candidate_pato_id": "PATO_0001334", "extractor": "deterministic_baseline"},
        ],
    }


# --- tests --------------------------------------------------------------------------------------

def test_quality_negation_materializes_with_exact_statement_and_cue(tmp_path):
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [QUALITY_ROW]))
    rec = _quality_record()
    row = ledger[("fdac", "900280", 1, 50, 57)][0]
    a = ncr.materialize_assertion(rec, row)
    assert a["negated"] is True and a["negation_scope"] == "quality"
    assert a["po_id"] == "PO_0020049" and a["pato_id"] == "PATO_0002228"
    assert a["source_text"] == "non acuminé"
    assert rec["text"][a["source_start"]:a["source_end"]] == a["source_text"]
    assert "non" in a["source_text"]
    assert rec["text"][a["bearer_start"]:a["bearer_end"]] == "limbe"
    assert a["raw_entity_text"] == "limbe"
    assert a["raw_quality_text"] == "acuminé"
    assert a["value_high"] is None
    assert "composition" not in a and "gate" not in a and "phenotype_class_iri" not in a


def test_numeric_strict_bound_is_exclusive_upper_bound(tmp_path):
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [NUM_ROW]))
    row = ledger[("fdac", "904975", 0, 33, 51)][0]
    a = ncr.materialize_assertion(_numeric_record(), row)
    assert a["value_low"] is None
    assert a["value_high"] == 0.5
    assert a["value_high_inclusive"] is False
    assert a["value_low_inclusive"] is True
    assert a["unit"] == "mm"
    assert a["negated"] is False and "negation_scope" not in a


def test_numeric_inclusive_default(tmp_path):
    text = "x, xx ne dépassant pas 5 mm"
    row = _row(
        source="s", source_id="i", source_segment_index="0", span_start="0", span_end="1",
        kind="numeric", recommended_po_id="PO_0009043", pato_id="PATO_0000122", negated="false",
        value_high="5.0", unit="mm", value_high_inclusive="true",
        logical_cue_text="ne dépassant pas", logical_cue_start="6", logical_cue_end="22",
        bearer_surface="x", bearer_start="0", bearer_end="1",
        current_raw_quality_text="5 mm",
        assertion_evidence_text="ne dépassant pas 5 mm",
        assertion_evidence_start="6", assertion_evidence_end=str(len(text)),
        source_statement_text=text, source_statement_start="0", source_statement_end=str(len(text)),
    )
    rec = {"source": "s", "source_id": "i", "source_segment_index": 0, "organ": "o",
           "text": text, "assertions": [], "unresolved_spans": []}
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [row]))
    a = ncr.materialize_assertion(rec, ledger[("s", "i", 0, 0, 1)][0])
    assert a["value_high"] == 5.0 and a["value_high_inclusive"] is True


def test_offset_mismatch_raises(tmp_path):
    bad = dict(QUALITY_ROW)
    bad["bearer_start"] = "0"  # text[0:7] != "limbe"
    bad["bearer_end"] = "7"
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [bad]))
    row = ledger[("fdac", "900280", 1, 50, 57)][0]
    with pytest.raises(ncr.LedgerOffsetError):
        ncr.materialize_assertion(_quality_record(), row)


def test_record_organ_basis_emits_no_bearer_offsets(tmp_path):
    text = "(peu) non ramifiées, atteignant"
    row = _row(
        source="fdac", source_id="895166", source_segment_index="1", record_organ="tiges",
        span_start="10", span_end="19", kind="quality", recommended_po_id="PO_0009047",
        pato_id="PATO_0000402", negated="true", logical_cue_text="non", logical_cue_start="6",
        logical_cue_end="9", bearer_surface="tiges",
        bearer_evidence_basis="record_organ_field_nonverbatim",
        current_raw_quality_text="ramifiées",
        assertion_evidence_text="non ramifiées", assertion_evidence_start="6",
        assertion_evidence_end="19",
        source_statement_text=text, source_statement_start="0", source_statement_end=str(len(text)),
    )
    rec = {"source": "fdac", "source_id": "895166", "source_segment_index": 1, "organ": "tiges",
           "text": text, "assertions": [], "unresolved_spans": []}
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [row]))
    a = ncr.materialize_assertion(rec, ledger[("fdac", "895166", 1, 10, 19)][0])
    assert "bearer_start" not in a and "bearer_end" not in a
    assert a["raw_entity_text"] == "tiges"


def test_non_destructive_record_rewrite_and_span_removed_once(tmp_path):
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [QUALITY_ROW]))
    rec = _quality_record()
    original_existing = [dict(a) for a in rec["assertions"]]
    out, audit, proposals = ncr.recover_negation_record(rec, ledger)
    assert out["assertions"][: len(original_existing)] == original_existing
    assert len(out["assertions"]) == len(original_existing) + 1
    reasons = [s["reason"] for s in out["unresolved_spans"]]
    assert "negated_context" not in reasons
    assert "missing_or_unsupported_bearer" in reasons
    for k in ("source", "source_id", "source_segment_index", "text", "taxon"):
        assert out[k] == rec[k]
    assert len(proposals) == 1


def test_held_span_is_retained_with_reason(tmp_path):
    held = dict(QUALITY_ROW)
    held["recommended_promote"] = "false"
    held["hold_reason"] = "OCR ambiguous"
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [held]))
    out, audit, proposals = ncr.recover_negation_record(_quality_record(), ledger)
    assert proposals == []
    assert any(s["reason"] == "negated_context" for s in out["unresolved_spans"])
    assert any(a["disposition"] == "held" and a["reason"] == "OCR ambiguous" for a in audit)


def test_coordinated_split_one_span_two_assertions(tmp_path):
    text = "bractées et bractéoles, ne dépassant pas en général 5 mm de long"
    stmt_end = str(len(text))
    common = dict(
        source="fg", source_id="v13", source_segment_index="116", span_start="0", span_end="8",
        span_surface="bractées", kind="numeric", negated="false", value_high="5.0", unit="mm",
        value_high_inclusive="true", logical_cue_text="ne dépassant pas", logical_cue_start="24",
        logical_cue_end="40", recommended_frequency_qualifier="usually",
        recommended_modality_text="en général", modality_start="41", modality_end="51",
        current_raw_quality_text="5 mm de long",
        assertion_evidence_text=text[24:], assertion_evidence_start="24",
        assertion_evidence_end=stmt_end,
        source_statement_text=text, source_statement_start="0", source_statement_end=stmt_end,
    )
    r0 = _row(assertion_index_within_span="0", recommended_po_id="PO_0009055", pato_id="PATO_0000122",
              bearer_surface="bractées", bearer_start="0", bearer_end="8", **common)
    r1 = _row(assertion_index_within_span="1", recommended_po_id="PO_0009043", pato_id="PATO_0000122",
              bearer_surface="bractéoles", bearer_start="12", bearer_end="22", **common)
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [r0, r1]))
    rec = {"source": "fg", "source_id": "v13", "source_segment_index": 116, "organ": "inflorescences",
           "text": text, "assertions": [],
           "unresolved_spans": [{"start": 0, "end": 8, "surface_form": "bractées",
                                 "reason": "negated_context"}]}
    out, audit, proposals = ncr.recover_negation_record(rec, ledger)
    assert len(out["assertions"]) == 2
    assert {a["po_id"] for a in out["assertions"]} == {"PO_0009055", "PO_0009043"}
    assert out["unresolved_spans"] == []
    assert sum(1 for a in audit if a["disposition"] == "recovered") == 2


def test_modality_and_context_and_stage_retained(tmp_path):
    text = "feuilles jeunes, en général ne dépassant pas 5 mm, à l'anthèse non ramifiées"

    def span(sub):
        start = text.index(sub)
        return str(start), str(start + len(sub))

    cue_s, cue_e = span("non")
    mod_s, mod_e = span("en général")
    ctx_s, ctx_e = span("jeunes")
    stg_s, stg_e = span("à l'anthèse")
    bear_s, bear_e = span("feuilles")
    quality_s, quality_e = span("ramifiées")
    row = _row(
        source="s", source_id="i", source_segment_index="0",
        span_start=quality_s, span_end=quality_e,
        span_surface="ramifiées", kind="quality", recommended_po_id="PO_0025073",
        pato_id="PATO_0000402", negated="true", logical_cue_text="non", logical_cue_start=cue_s,
        logical_cue_end=cue_e, recommended_frequency_qualifier="usually",
        recommended_modality_text="en général", modality_start=mod_s, modality_end=mod_e,
        bearer_context_quality_ids="PATO_0000309", bearer_context_text="jeunes",
        bearer_context_start=ctx_s, bearer_context_end=ctx_e,
        developmental_stage_term="PO_0007616", developmental_stage_text="à l'anthèse",
        developmental_stage_start=stg_s, developmental_stage_end=stg_e,
        bearer_surface="feuilles", bearer_start=bear_s, bearer_end=bear_e,
        current_raw_quality_text="ramifiées",
        assertion_evidence_text="non ramifiées", assertion_evidence_start=cue_s,
        assertion_evidence_end=quality_e,
        source_statement_text=text, source_statement_start="0", source_statement_end=str(len(text)),
    )
    rec = {"source": "s", "source_id": "i", "source_segment_index": 0, "organ": "feuilles",
           "text": text, "assertions": [],
           "unresolved_spans": [{"start": int(quality_s), "end": int(quality_e),
                                 "surface_form": "ramifiées", "reason": "negated_context"}]}
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [row]))
    a = ncr.materialize_assertion(rec, ledger[("s", "i", 0, int(quality_s), int(quality_e))][0])
    assert a["frequency_qualifier"] == "usually"
    assert a["modality_text"] == "en général"
    assert rec["text"][a["modality_start"]:a["modality_end"]] == "en général"
    assert a["bearer_context_qualities"] == ["PATO_0000309"]
    stage = a["developmental_stage_contexts"][0]
    assert stage["stage_term"] == "PO_0007616"
    assert rec["text"][stage["start"]:stage["end"]] == "à l'anthèse"


def test_load_ledger_groups_split_span_sorted(tmp_path):
    text = "bractées et bractéoles ne dépassant pas 5 mm"
    r0 = _row(source="fg", source_id="v13", source_segment_index="116", span_start="0", span_end="8",
              assertion_index_within_span="0", kind="numeric", recommended_po_id="PO_0009055",
              pato_id="PATO_0000122", value_high="5.0", unit="mm",
              logical_cue_text="ne", logical_cue_start="23", logical_cue_end="25",
              bearer_surface="b", bearer_start="0", bearer_end="1",
              source_statement_text=text, source_statement_start="0", source_statement_end=str(len(text)))
    r1 = dict(r0)
    r1["assertion_index_within_span"] = "1"
    r1["recommended_po_id"] = "PO_0009043"
    ledger = ncr.load_ledger(_write_ledger(tmp_path / "l.tsv", [r1, r0]))  # out of order on disk
    rows = ledger[("fg", "v13", 116, 0, 8)]
    assert [r.assertion_index for r in rows] == [0, 1]


def test_tranche_coordinated_bearer_mints_one_row_per_po_id(tmp_path):
    text = "lobes and pinnae not over 4 mm wide"
    tranche = _write_tranche(
        tmp_path / "tranche.tsv",
        [
            {
                "source": "fm",
                "source_id": "fbec7",
                "source_segment_index": "0",
                "span_start": "26",
                "span_end": str(len(text)),
                "span_surface": "4 mm wide",
                "pato_id": "PATO_0000921",
                "value_high": "4",
                "unit": "mm",
                "value_high_inclusive": "true",
                "comparator_cue": "not over",
                "cue_start": "17",
                "cue_end": "25",
                "bearer_surface": "lobes and pinnae",
                "bearer_start": "0",
                "bearer_end": "16",
                "standard_po_bearer_ids": "PO_0025517|PO_0020049",
                "disposition": "promote_standard_po_next",
                "assertion_evidence_text": "not over 4 mm wide",
                "assertion_evidence_start": "17",
                "assertion_evidence_end": str(len(text)),
                "source_statement_text": text,
                "source_statement_start": "0",
                "source_statement_end": str(len(text)),
                "required_residual_reason": "numeric_bound_standard_po_ready",
            }
        ],
    )
    rows = ncr.load_tranche(tranche)[("fm", "fbec7", 0, 26, len(text))]
    assert [(row.po_id, row.bearer_surface) for row in rows] == [
        ("PO_0025517", "lobes"),
        ("PO_0020049", "pinnae"),
    ]
    assert [(row.bearer_start, row.bearer_end) for row in rows] == [(0, 5), (10, 16)]


def test_partial_local_bearer_is_retained_after_standard_po_promotion(tmp_path):
    text = "each wing not over 5 mm wide"
    tranche = _write_tranche(
        tmp_path / "tranche.tsv",
        [
            {
                "source": "fg",
                "source_id": "efd415",
                "source_segment_index": "0",
                "span_start": "19",
                "span_end": str(len(text)),
                "span_surface": "5 mm wide",
                "pato_id": "PATO_0000921",
                "value_high": "5",
                "unit": "mm",
                "value_high_inclusive": "true",
                "comparator_cue": "not over",
                "cue_start": "10",
                "cue_end": "18",
                "bearer_surface": "each wing",
                "bearer_start": "0",
                "bearer_end": "9",
                "standard_po_bearer_ids": "PO_0025129",
                "flopo_local_bearer_needed": "leaf rachis wing",
                "disposition": "split_promote_standard_po_and_hold_local_bearer",
                "assertion_evidence_text": "not over 5 mm wide",
                "assertion_evidence_start": "10",
                "assertion_evidence_end": str(len(text)),
                "source_statement_text": text,
                "source_statement_start": "0",
                "source_statement_end": str(len(text)),
                "required_residual_reason": (
                    "numeric_bound_standard_po_ready_with_local_split"
                ),
            }
        ],
    )
    ledger = ncr.load_tranche(tranche)
    record = {
        "source": "fg",
        "source_id": "efd415",
        "source_segment_index": 0,
        "organ": "leaf",
        "text": text,
        "assertions": [],
        "source_statements": [],
        "unresolved_spans": [
            {
                "start": 19,
                "end": len(text),
                "surface_form": "5 mm wide",
                "reason": "negated_context",
            }
        ],
    }
    out, audit, proposals = ncr.recover_negation_record(record, ledger)
    assert len(proposals) == 1
    assert out["assertions"][0]["po_id"] == "PO_0025129"
    assert len(out["unresolved_spans"]) == 1
    residual = out["unresolved_spans"][0]
    assert residual["reason"] == "missing_or_unsupported_bearer"
    assert residual["original_reason"] == "negated_context"
    assert residual["pending_bearer"] == "leaf rachis wing"
    assert residual["promoted_po_ids"] == ["PO_0025129"]
    assert any(row["disposition"] == "retained_partial_bearer" for row in audit)
