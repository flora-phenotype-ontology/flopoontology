from __future__ import annotations

import json
import sqlite3


def _lexicons(tmp_path):
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_0009025\tleaf\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\nPATO_0000122\tlength\nPATO_0000320\tgreen\n")
    return po, pato


def test_real_wire_record_validates_against_linkml_contract(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "traits.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "volume.xml",
                "taxon": "Planta exemplar",
                "organ": "leaves",
                "language": "en",
                "text": "Leaves 3-7 cm long and green.",
                "assertions": [
                    {
                        "po_id": "PO_0009025",
                        "pato_id": "PATO_0000122",
                        "source_text": "3-7 cm long",
                        "source_start": 7,
                        "source_end": 18,
                        "extractor": "test",
                        "value_low": 3,
                        "value_high": 7,
                        "unit": "cm",
                        "composition": {"status": "accept"},
                        "gate": {"status": "review"},
                    },
                    {
                        "po_id": "PO_0009025",
                        "pato_id": "PATO_0000320",
                        "source_text": "green",
                        "source_start": 23,
                        "source_end": 28,
                        "extractor": "test",
                        "composition": {"status": "accept"},
                        "gate": {"status": "accepted"},
                    },
                ],
            }
        )
        + "\n"
    )
    report = validate_jsonl(path, stage="gated", po_lexicon=po, pato_lexicon=pato)
    assert report["ok"]
    assert report["assertions"] == 2
    assert report["gate_statuses"] == {"accepted": 1, "review": 1}


def test_validator_accepts_reviewed_flopo_local_anatomy_bearer(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    registry = tmp_path / "flopo.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_1234567\t1234567\t"
        "orchid labellum\tOTHER\t0\n"
    )
    path = tmp_path / "local-bearer.jsonl"
    record = {
        "source": "flora-test",
        "source_id": "volume.xml",
        "text": "Labellum green.",
        "assertions": [
            {
                "po_id": "FLOPO_1234567",
                "pato_id": "PATO_0000320",
                "source_text": "green",
                "source_start": 9,
                "source_end": 14,
            }
        ],
    }
    path.write_text(json.dumps(record) + "\n")

    report = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
    )
    assert report["ok"]

    record["assertions"][0]["po_id"] = "FLOPO_7654321"
    path.write_text(json.dumps(record) + "\n")
    report = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
    )
    assert report["errors_by_code"] == {"unknown_flopo_bearer_id": 1}


def test_validator_accepts_scoped_negation_and_po_stage_context(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    po.write_text(po.read_text() + "PO_0007016\twhole plant flowering stage\n")
    text = "Leaves not green at flowering."
    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000320",
        "negated": True,
        "negation_scope": "quality",
        "developmental_stage_contexts": [
            {
                "stage_term": "PO_0007016",
                "stage_text": "flowering",
                "start": text.index("flowering"),
                "end": text.index("flowering") + len("flowering"),
            }
        ],
        "source_text": "not green at flowering",
        "source_start": text.index("not"),
        "source_end": text.index("flowering") + len("flowering"),
        "extractor": "test",
        "composition": {"status": "accept"},
        "gate": {"status": "accepted"},
    }
    path = tmp_path / "scoped.jsonl"
    record = {
        "source": "flora-test",
        "source_id": "stage.xml",
        "taxon": "Planta exemplar",
        "text": text,
        "assertions": [assertion],
    }
    path.write_text(json.dumps(record) + "\n")
    report = validate_jsonl(path, stage="gated", po_lexicon=po, pato_lexicon=pato)
    assert report["ok"], report

    assertion.pop("negation_scope")
    path.write_text(json.dumps(record) + "\n")
    report = validate_jsonl(path, stage="gated", po_lexicon=po, pato_lexicon=pato)
    assert report["errors_by_code"] == {"negated_assertion_missing_scope": 1}


def test_validator_requires_retained_statement_to_cover_all_assertion_evidence(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    po.write_text(po.read_text() + "PO_0007016\twhole plant flowering stage\n")
    text = "Leaflets normally not green at flowering."
    statement_text = "not green"
    statement_start = text.index(statement_text)
    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000320",
        "source_text": statement_text,
        "source_start": statement_start,
        "source_end": statement_start + len(statement_text),
        "source_statement_id": "statement-narrow",
        "raw_entity_text": "Leaflets",
        "frequency_qualifier": "usually",
        "modality_text": "normally",
        "developmental_stage_contexts": [
            {
                "stage_term": "PO_0007016",
                "stage_text": "flowering",
                "start": text.index("flowering"),
                "end": text.index("flowering") + len("flowering"),
            }
        ],
    }
    record = {
        "source": "flora-test",
        "source_id": "statement.xml",
        "text": text,
        "source_statements": [
            {
                "statement_id": "statement-narrow",
                "verbatim_text": statement_text,
                "start": statement_start,
                "end": statement_start + len(statement_text),
            }
        ],
        "assertions": [assertion],
    }
    path = tmp_path / "statement-support.jsonl"
    path.write_text(json.dumps(record) + "\n")

    report = validate_jsonl(path, po_lexicon=po, pato_lexicon=pato)
    # Interval-aware coverage: the bearer and modality cues carry no offsets and are absent from
    # the narrow statement text, so they are reported as omitted; the developmental-stage context
    # carries exact offsets that fall outside the statement interval, so it is reported precisely
    # as outside the interval rather than as a generic substring omission.
    assert set(report["errors_by_code"]) == {
        "source_statement_omits_bearer_evidence",
        "developmental_stage_outside_statement_interval",
        "source_statement_omits_modality_cue",
    }


def test_validator_requires_upper_bound_cue_in_source_span(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    text = "Leaves 5 mm long."
    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000122",
        "source_text": "5 mm long",
        "source_start": 7,
        "source_end": 16,
        "extractor": "test",
        "value_high": 5,
        "unit": "mm",
    }
    record = {
        "source": "flora-test",
        "source_id": "bounds.xml",
        "text": text,
        "assertions": [assertion],
    }
    path = tmp_path / "upper-bound.jsonl"
    path.write_text(json.dumps(record) + "\n")
    report = validate_jsonl(path, po_lexicon=po, pato_lexicon=pato)
    assert report["errors_by_code"] == {"upper_bound_cue_not_in_source_span": 1}

    record["text"] = "Leaves up to 5 mm long."
    assertion["source_text"] = "up to 5 mm long"
    assertion["source_start"] = 7
    assertion["source_end"] = 22
    path.write_text(json.dumps(record) + "\n")
    report = validate_jsonl(path, po_lexicon=po, pato_lexicon=pato)
    assert report["ok"], report


def test_validator_rejects_accepted_atomic_trait_with_local_disjunction(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "truncated-disjunction.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "1",
                "text": "Leaves green or yellow.",
                "assertions": [{
                    "po_id": "PO_0009025",
                    "pato_id": "PATO_0000320",
                    "source_text": "Leaves green",
                    "source_start": 0,
                    "source_end": 12,
                    "extractor": "test",
                    "composition": {"status": "accept"},
                    "gate": {"status": "accepted"},
                }],
            }
        ) + "\n"
    )
    report = validate_jsonl(path, stage="gated", po_lexicon=po, pato_lexicon=pato)
    assert not report["ok"]
    assert report["errors_by_code"] == {"accepted_atomic_clause_contains_disjunction": 1}


def test_validator_finds_provenance_identifier_and_value_errors(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "1",
                "text": "Leaves green.",
                "assertions": [
                    {
                        "po_id": "PO_9999999",
                        "pato_id": "PATO_0000320",
                        "source_text": "blue",
                        "value_operator": "one_of",
                        "value_terms": ["PATO_0000320"],
                        "value_low": 7,
                        "value_high": 3,
                        "unit": "cm",
                        "composition": {"status": "review"},
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )
    report = validate_jsonl(path, stage="gated", po_lexicon=po, pato_lexicon=pato)
    assert not report["ok"]
    assert set(report["errors_by_code"]) >= {
        "unknown_po_id",
        "source_span_not_verbatim",
        "logical_value_missing_components",
        "reversed_measurement_range",
        "accepted_without_composition",
    }


def test_validator_checks_mention_offsets_and_references(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "mentions.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "1",
                "text": "Leaves green.",
                "term_mentions": [
                    {
                        "mention_id": "m1",
                        "start": 7,
                        "end": 12,
                        "surface_form": "blue",
                        "normalized_form": "blue",
                    }
                ],
                "assertions": [
                    {
                        "po_id": "PO_0009025",
                        "pato_id": "PATO_0000320",
                        "source_text": "green",
                        "quality_mention_ids": ["missing"],
                    }
                ],
            }
        )
        + "\n"
    )
    report = validate_jsonl(path, po_lexicon=po, pato_lexicon=pato)
    assert report["errors_by_code"] == {
        "mention_not_verbatim": 1,
        "unknown_mention_reference": 1,
    }


def test_validator_checks_unresolved_span_schema_offsets_and_catalog(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "unresolved.jsonl"
    path.write_text(json.dumps({
        "source": "flora-test",
        "source_id": "1",
        "text": "Leaves green.",
        "unresolved_spans": [{
            "start": 7,
            "end": 12,
            "surface_form": "blue",
            "reason": "unsupported_composition",
            "candidate_pato_id": "PATO_9999999",
            "extractor": "test",
        }],
        "assertions": [],
    }) + "\n")
    report = validate_jsonl(path, po_lexicon=po, pato_lexicon=pato)
    assert report["unresolved_spans"] == 1
    assert report["errors_by_code"] == {
        "unknown_unresolved_pato_id": 1,
        "unresolved_span_not_verbatim": 1,
    }


def test_sqlite_validation_checks_integrity_and_counts(tmp_path):
    from flopo2.db.load import init_db
    from flopo2.owl.annotation_class import (
        annotation_class_digest,
        annotation_class_iri,
        canonical_signature_json,
    )
    from flopo2.verify.data_model import validate_sqlite

    db = tmp_path / "traits.sqlite"
    init_db(db)
    assertion = {"po_id": "PO_0009025", "pato_id": "PATO_0000320"}
    class_iri = annotation_class_iri(assertion)
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            INSERT INTO text_segment(
              segment_id, source, source_id, taxon, organ, language, char_start, char_end, text
            ) VALUES (1, 'flora-test', '1', 'Planta exemplar', 'leaf', 'en', 0, 12,
                      'leaves green');
            INSERT INTO source_statement(
              statement_id, segment_id, char_start, char_end, verbatim_text, language
            ) VALUES ('statement-1', 1, 7, 12, 'green', 'en');
            """
        )
        conn.execute(
            """
            INSERT INTO annotation_class(
              phenotype_class_iri, annotation_class_id, expression_sha256,
              canonical_expression_signature
            ) VALUES (?, ?, ?, ?)
            """,
            (
                class_iri,
                class_iri.rsplit("/", 1)[-1],
                annotation_class_digest(assertion),
                canonical_signature_json(assertion),
            ),
        )
        conn.execute(
            """
            INSERT INTO trait_assertion(
              assertion_id, segment_id, source_statement_id, phenotype_class_iri, po_id,
              pato_id, gate_status, source_text, source_start, source_end, extractor
            ) VALUES (1, 1, 'statement-1', ?, 'PO_0009025', 'PATO_0000320',
                      'accepted', 'green', 7, 12, 'test')
            """,
            (class_iri,),
        )
    report = validate_sqlite(db, {"segments": 1, "assertions": 1, "unresolved_spans": 0})
    assert report["ok"]
    assert report["accepted_assertions"] == 1


def test_database_does_not_merge_identical_text_from_different_taxa(tmp_path):
    from flopo2.db.load import load_jsonl
    from flopo2.verify.data_model import validate_sqlite

    gated = tmp_path / "gated.jsonl"
    records = []
    for taxon in ("Planta alpha", "Planta beta"):
        records.append(
            {
                "source": "flora-test",
                "source_id": "volume.xml",
                "taxon": taxon,
                "organ": "leaves",
                "language": "en",
                "char_start": 10,
                "char_end": 23,
                "text": "Leaves green.",
                "assertions": [
                    {
                        "po_id": "PO_0009025",
                            "pato_id": "PATO_0000320",
                            "source_text": "green",
                            "source_start": 7,
                            "source_end": 12,
                            "extractor": "test",
                            "composition": {"status": "accept"},
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
    gated.write_text("".join(json.dumps(record) + "\n" for record in records))
    db = tmp_path / "traits.sqlite"
    loaded = load_jsonl(db, gated)
    report = validate_sqlite(db, {"segments": 2, "assertions": 2})

    assert loaded == {
        "segments": 2,
        "assertions": 2,
        "source_statements": 2,
        "unresolved_spans": 0,
        "annotation_classes": 1,
        "db": str(db),
    }
    assert report["ok"]
    with sqlite3.connect(db) as conn:
        taxa = conn.execute("SELECT taxon FROM text_segment ORDER BY taxon").fetchall()
    assert taxa == [("Planta alpha",), ("Planta beta",)]


def test_validator_requires_and_verifies_materialized_annotation_class_iri(tmp_path):
    from flopo2.owl.annotation_class import annotation_class_iri
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000320",
        "source_text": "green",
        "source_start": 7,
        "source_end": 12,
    }
    record = {
        "source": "flora-test",
        "source_id": "one.xml",
        "text": "Leaves green.",
        "assertions": [assertion],
    }
    path = tmp_path / "annotation.jsonl"
    path.write_text(json.dumps(record) + "\n")
    missing = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        require_annotation_class=True,
    )
    assert missing["errors_by_code"] == {"missing_phenotype_class_iri": 1}

    assertion["phenotype_class_iri"] = annotation_class_iri(assertion)
    path.write_text(json.dumps(record) + "\n")
    assert validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        require_annotation_class=True,
    )["ok"]

    assertion["phenotype_class_iri"] = (
        "https://w3id.org/flopo/annotation-class/FAC_00000000000000000000000000000000"
    )
    path.write_text(json.dumps(record) + "\n")
    mismatch = validate_jsonl(
        path,
        po_lexicon=po,
        pato_lexicon=pato,
        require_annotation_class=True,
    )
    assert mismatch["errors_by_code"] == {"phenotype_class_iri_mismatch": 1}


def test_composition_preserves_segment_identity_fields(tmp_path, monkeypatch):
    from flopo2.extract import compose
    from flopo2.extract.ground import Lexicon

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009025\tleaf\tleaves\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tsynonyms\nPATO_0000320\tgreen\t\n")
    monkeypatch.setattr(compose, "load_lexicons", lambda: (Lexicon.load(po), Lexicon.load(pato)))
    source = tmp_path / "extracted.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "volume.xml",
                "taxon": "Planta alpha",
                "taxon_family": "Plantaceae",
                "taxon_rank": "species",
                "organ": "leaves",
                "language": "en",
                "char_start": 21,
                "char_end": 34,
                "source_segment_index": 7,
                "text": "Leaves green.",
                "assertions": [
                    {
                        "po_id": "PO_0009025",
                        "pato_id": "PATO_0000320",
                        "source_text": "Leaves green",
                        "extractor": "deterministic_baseline",
                    }
                ],
            }
        )
        + "\n"
    )
    checks = tmp_path / "checks.jsonl"
    accepted = tmp_path / "accepted.jsonl"
    compose.run_file(source, checks, parser_mode="off", accepted_out=accepted)
    row = json.loads(accepted.read_text())

    assert row["taxon_family"] == "Plantaceae"
    assert row["taxon_rank"] == "species"
    assert row["source_segment_index"] == 7
    assert (row["char_start"], row["char_end"]) == (21, 34)
    assertion = row["assertions"][0]
    assert assertion["extractor"] == "deterministic_baseline"
    assert (assertion["source_start"], assertion["source_end"]) == (0, 12)


def test_validator_rejects_ambiguous_accepted_span_without_offsets(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "ambiguous.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "1",
                "taxon": "Planta exemplar",
                "text": "green leaves; green stems",
                "assertions": [
                    {
                        "po_id": "PO_0009025",
                        "pato_id": "PATO_0000320",
                        "source_text": "green",
                        "extractor": "test",
                        "composition": {"status": "accept"},
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )
    report = validate_jsonl(path, stage="gated", po_lexicon=po, pato_lexicon=pato)
    assert report["errors_by_code"] == {"ambiguous_source_span_without_offsets": 1}


def test_validator_rejects_duplicate_source_segment_indices(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "duplicate-segments.jsonl"
    row = {
        "source": "flora-test",
        "source_id": "volume.xml",
        "source_segment_index": 4,
        "text": "Leaves green.",
        "assertions": [],
    }
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    report = validate_jsonl(path, po_lexicon=po, pato_lexicon=pato)
    assert report["errors_by_code"] == {"duplicate_source_segment_index": 1}


def test_validator_rejects_arbitrary_measurement_unit_and_missing_provenance(tmp_path):
    from flopo2.verify.data_model import validate_jsonl

    po, pato = _lexicons(tmp_path)
    path = tmp_path / "bad-unit.jsonl"
    path.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "1",
                "taxon": "",
                "text": "aiguillons vers la 5e feuille",
                "assertions": [
                    {
                        "po_id": "PO_0009025",
                        "pato_id": "PATO_0000122",
                        "source_text": "5e feuille",
                        "source_start": 18,
                        "source_end": 28,
                        "value_low": 5,
                        "value_high": 5,
                        "unit": "leaf",
                        "composition": {"status": "accept"},
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )
    report = validate_jsonl(path, stage="gated", po_lexicon=po, pato_lexicon=pato)
    assert set(report["errors_by_code"]) >= {
        "unsupported_measurement_unit",
        "missing_extractor_provenance",
        "accepted_without_taxon_provenance",
    }


def test_loader_rejects_old_database_that_can_conflate_taxa(tmp_path):
    import pytest

    from flopo2.db.load import init_db

    db = tmp_path / "old.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE text_segment(
              segment_id INTEGER PRIMARY KEY,
              source TEXT, source_id TEXT, taxon TEXT, organ TEXT, language TEXT, text TEXT,
              UNIQUE(source, source_id, organ, text)
            )
            """
        )
    with pytest.raises(RuntimeError, match="pre-provenance schema"):
        init_db(db)
