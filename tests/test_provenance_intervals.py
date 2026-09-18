from __future__ import annotations

import json
import sqlite3


def _lexicons(tmp_path):
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_0009025\tleaf\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\nPATO_0000320\tgreen\n")
    return po, pato


def _record(text: str, assertion: dict) -> dict:
    return {
        "source": "flora-test",
        "source_id": "volume.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplar",
        "language": "en",
        "text": text,
        "assertions": [assertion],
    }


def test_legacy_modifier_recovers_verbatim_cue_and_bearer_from_anchored_clause():
    from flopo2.annotation.provenance import ensure_source_statements

    text = "Leaves typically green."
    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000320",
        "source_text": "green",
        "source_start": text.index("green"),
        "source_end": text.index("green") + len("green"),
        "raw_entity_text": "leaves",
        "modifier": "usually",
        # This normalized spelling is legacy metadata, not source evidence.
        "modality_text": "usually",
    }

    normalized = ensure_source_statements(_record(text, assertion))
    actual = normalized["assertions"][0]
    statement = normalized["source_statements"][0]

    assert actual["frequency_qualifier"] == "usually"
    assert actual["modality_text"] == "typically"
    assert (actual["modality_start"], actual["modality_end"]) == (7, 16)
    assert actual["raw_entity_text"] == "Leaves"
    assert (actual["bearer_start"], actual["bearer_end"]) == (0, 6)
    assert statement["verbatim_text"] == "Leaves typically green"
    assert (statement["start"], statement["end"]) == (0, 22)


def test_provenance_never_widens_across_semicolon_for_repeated_cues_and_bearers():
    from flopo2.annotation.provenance import ensure_source_statements

    text = "Leaves typically green; leaves usually red."
    red = text.index("red")
    normalized = ensure_source_statements(
        _record(
            text,
            {
                "po_id": "PO_0009025",
                "pato_id": "PATO_0000320",
                "source_text": "red",
                "source_start": red,
                "source_end": red + len("red"),
                "raw_entity_text": "leaves",
                "modifier": "usually",
                "modality_text": "usually",
            },
        )
    )
    assertion = normalized["assertions"][0]
    statement = normalized["source_statements"][0]

    assert text[assertion["bearer_start"] : assertion["bearer_end"]] == "leaves"
    assert assertion["bearer_start"] == text.index("leaves")
    assert text[assertion["modality_start"] : assertion["modality_end"]] == "usually"
    assert statement["verbatim_text"] == "leaves usually red"
    assert ";" not in statement["verbatim_text"]
    assert statement["start"] > text.index(";")


def test_repeated_modality_cue_without_offsets_is_not_assigned_to_first_occurrence(tmp_path):
    from flopo2.annotation.provenance import ensure_source_statements
    from flopo2.verify.data_model import validate_jsonl

    text = "Leaves typically green, typically glabrous."
    green = text.index("green")
    normalized = ensure_source_statements(
        _record(
            text,
            {
                "po_id": "PO_0009025",
                "pato_id": "PATO_0000320",
                "source_text": "green",
                "source_start": green,
                "source_end": green + len("green"),
                "raw_entity_text": "Leaves",
                "modifier": "usually",
                "modality_text": "typically",
            },
        )
    )
    assertion = normalized["assertions"][0]
    assert assertion["modality_text"] == "typically"
    assert "modality_start" not in assertion
    assert "modality_end" not in assertion

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "repeated-cue.jsonl"
    path.write_text(json.dumps(normalized) + "\n")
    report = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        strict_source_statements=True,
    )
    assert report["errors_by_code"]["ambiguous_modality_evidence_without_offsets"] == 1


def test_existing_narrow_statement_disambiguates_repeated_cue_in_wider_clause():
    from flopo2.annotation.provenance import ensure_source_statements

    text = "very branched specimens and very narrow leaves"
    source_text = "very branched"
    source_start = text.index(source_text)
    source_end = source_start + len(source_text)
    record = _record(
        text,
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000320",
            "source_text": source_text,
            "source_start": source_start,
            "source_end": source_end,
            "source_statement_id": "statement-narrow",
            "degree_qualifier": "very",
            "modality_text": "very",
        },
    )
    record["source_statements"] = [
        {
            "statement_id": "statement-narrow",
            "verbatim_text": source_text,
            "start": source_start,
            "end": source_end,
        }
    ]

    normalized = ensure_source_statements(record)
    assertion = normalized["assertions"][0]
    assert assertion["modality_text"] == "very"
    assert (assertion["modality_start"], assertion["modality_end"]) == (0, 4)


def test_unique_quality_disambiguates_its_nearest_approximation_cue():
    from flopo2.annotation.provenance import ensure_source_statements

    text = "lamina ± obovate, rounded to acute and ± acuminate at apex"
    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000320",
        "source_text": text,
        "source_start": 0,
        "source_end": len(text),
        "raw_quality_text": "acuminate",
        "value_qualifier": "approximately",
        "modality_text": "±",
    }

    normalized = ensure_source_statements(_record(text, assertion))
    actual = normalized["assertions"][0]
    expected = text.rindex("±")
    assert (actual["modality_start"], actual["modality_end"]) == (expected, expected + 1)


def test_organ_heading_is_context_not_invented_local_bearer_evidence(tmp_path):
    from flopo2.annotation.provenance import ensure_source_statements
    from flopo2.verify.data_model import validate_jsonl

    text = "Fruits similar, red at maturity."
    predicate = "red at maturity"
    start = text.index(predicate)
    record = _record(
        text,
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000320",
            "source_text": predicate,
            "source_start": start,
            "source_end": start + len(predicate),
            "source_statement_id": "statement-predicate",
            "raw_entity_text": "fruits",
            "mapping_provenance": ["bearer:organ_heading"],
        },
    )
    record["source_statements"] = [
        {
            "statement_id": "statement-predicate",
            "verbatim_text": predicate,
            "start": start,
            "end": start + len(predicate),
        }
    ]

    normalized = ensure_source_statements(record)
    assertion = normalized["assertions"][0]
    assert "bearer_start" not in assertion and "bearer_end" not in assertion

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "organ-heading.jsonl"
    path.write_text(json.dumps(normalized) + "\n")
    report = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        strict_source_statements=True,
    )
    assert report["errors_by_code"] == {}


def test_repeated_bearer_without_offsets_is_not_guessed(tmp_path):
    from flopo2.annotation.provenance import ensure_source_statements
    from flopo2.verify.data_model import validate_jsonl

    text = "Leaves green and leaves red."
    red = text.index("red")
    normalized = ensure_source_statements(
        _record(
            text,
            {
                "po_id": "PO_0009025",
                "pato_id": "PATO_0000320",
                "source_text": "red",
                "source_start": red,
                "source_end": red + len("red"),
                "raw_entity_text": "leaves",
            },
        )
    )
    assertion = normalized["assertions"][0]
    assert "bearer_start" not in assertion
    assert "bearer_end" not in assertion

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "repeated-bearer.jsonl"
    path.write_text(json.dumps(normalized) + "\n")
    report = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        strict_source_statements=True,
    )
    assert report["errors_by_code"]["ambiguous_bearer_evidence_without_offsets"] == 1


def test_exact_modality_interval_outside_statement_is_not_rescued_by_duplicate_inside(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    text = "typically green; typically red"
    second_cue = text.rindex("typically")
    red = text.index("red")
    statement_text = text[second_cue : red + len("red")]
    record = _record(
        text,
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000320",
            "source_text": "red",
            "source_start": red,
            "source_end": red + len("red"),
            "source_statement_id": "statement-second",
            "frequency_qualifier": "usually",
            "modality_text": "typically",
            # Deliberately selects the first cue; identical wording occurs in the statement too.
            "modality_start": 0,
            "modality_end": len("typically"),
        },
    )
    record["source_statements"] = [
        {
            "statement_id": "statement-second",
            "verbatim_text": statement_text,
            "start": second_cue,
            "end": red + len("red"),
        }
    ]
    po, pato = _lexicons(tmp_path)
    path = tmp_path / "outside.jsonl"
    path.write_text(json.dumps(record) + "\n")
    report = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        strict_source_statements=True,
    )
    assert report["errors_by_code"] == {"modality_cue_outside_statement_interval": 1}


def test_strict_mode_requires_retained_source_statement(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    text = "Leaves green."
    green = text.index("green")
    record = _record(
        text,
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000320",
            "source_text": "green",
            "source_start": green,
            "source_end": green + len("green"),
        },
    )
    po, pato = _lexicons(tmp_path)
    path = tmp_path / "missing-statement.jsonl"
    path.write_text(json.dumps(record) + "\n")
    report = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        strict_source_statements=True,
    )
    assert report["errors_by_code"] == {"missing_source_statement_reference": 1}


def test_sqlite_roundtrips_evidence_offsets_and_negation_residual_metadata(tmp_path):
    from flopo2.db.load import load_jsonl
    from flopo2.verify.data_model import validate_sqlite

    text = "Leaves typically green."
    green = text.index("green")
    record = _record(
        text,
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000320",
            "source_text": "green",
            "source_start": green,
            "source_end": green + len("green"),
            "raw_entity_text": "Leaves",
            "modifier": "usually",
            "modality_text": "typically",
        },
    )
    record["unresolved_spans"] = [
        {
            "start": 0,
            "end": 6,
            "surface_form": "Leaves",
            "reason": "negated_context_partial_promotion",
            "candidate_pato_id": "PATO_0000320",
            "original_reason": "negated_context",
            "negation_residual_reason": "pending_local_bearer",
            "negation_residual_detail": "rachis wing still needs a reviewed bearer",
            "partial_promotion": True,
            "pending_bearer": "rachis wing",
            "promoted_po_ids": ["PO_0009025"],
            "extractor": "negated_context_recovery_v3",
        }
    ]
    source = tmp_path / "roundtrip.jsonl"
    source.write_text(json.dumps(record) + "\n")
    db = tmp_path / "roundtrip.sqlite"
    loaded = load_jsonl(db, source)
    report = validate_sqlite(db, loaded)
    assert report["ok"], report

    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT bearer_start, bearer_end, modality_start, modality_end "
            "FROM trait_assertion"
        ).fetchone() == (0, 6, 7, 16)
        residual = connection.execute(
            "SELECT original_reason, negation_residual_reason, negation_residual_detail, "
            "partial_promotion, pending_bearer, promoted_po_ids FROM unresolved_span"
        ).fetchone()
    assert residual == (
        "negated_context",
        "pending_local_bearer",
        "rachis wing still needs a reviewed bearer",
        1,
        "rachis wing",
        '["PO_0009025"]',
    )
