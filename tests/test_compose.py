from __future__ import annotations

import json

import pytest

from flopo2.eval.scoring import Assertion
from flopo2.extract.ground import Lexicon


def _lexicons(tmp_path):
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\tnamespace\n"
        "PO_0009046\tflower\tflowers|bloom\tplant_anatomy\n"
        "PO_0009025\tleaf\tleaves\tplant_anatomy\n"
    )
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_0000322\tred\tcrimson\t\n"
        "PATO_0000386\tgreen\t\t\n"
    )
    return Lexicon.load(po), Lexicon.load(pato)


def test_compose_accepts_verbatim_visible_binding(tmp_path):
    from flopo2.extract.compose import check_assertion

    po_lex, pato_lex = _lexicons(tmp_path)
    assertion = Assertion(
        po_id="PO_0009046",
        pato_id="PATO_0000322",
        source_text="flowers red",
    )
    decision = check_assertion("leaves green; flowers red.", assertion, po_lex, pato_lex)
    assert decision.accepted
    assert decision.confidence >= 0.75


def test_compose_reviews_nonverbatim_span(tmp_path):
    from flopo2.extract.compose import check_assertion

    po_lex, pato_lex = _lexicons(tmp_path)
    assertion = Assertion(
        po_id="PO_0009046",
        pato_id="PATO_0000322",
        source_text="petals red",
    )
    decision = check_assertion("leaves green; flowers red.", assertion, po_lex, pato_lex)
    assert not decision.accepted
    assert "source_span_not_verbatim" in decision.reasons


def test_compose_parser_disagreement_routes_to_review(tmp_path):
    from flopo2.extract.compose import check_assertion

    po_lex, pato_lex = _lexicons(tmp_path)
    assertion = Assertion(
        po_id="PO_0009046",
        pato_id="PATO_0000322",
        source_text="flowers red",
    )
    decision = check_assertion(
        "leaves green; flowers red.",
        assertion,
        po_lex,
        pato_lex,
        parser_check=lambda clause, entity, quality: False,
    )
    assert not decision.accepted
    assert "dependency_binding_disagrees" in decision.reasons


def test_compose_reviews_related_part_conflict(monkeypatch, tmp_path):
    from flopo2.extract import compose

    po_lex, pato_lex = _lexicons(tmp_path)
    monkeypatch.setattr(compose, "load_lexicons", lambda: (po_lex, pato_lex))
    assertions = [
        Assertion(po_id="PO_0009046", pato_id="PATO_0000322", source_text="yellow leaves"),
        Assertion(po_id="PO_0009025", pato_id="PATO_0000322", source_text="yellow leaves"),
    ]
    decisions = compose.check_segment(
        "flowers red with yellow leaves.",
        assertions,
        auto_parser=False,
    )
    assert not decisions[0].accepted
    assert "source_span_mentions_different_entity" in decisions[0].reasons
    assert decisions[1].accepted


def test_run_file_returns_summary(monkeypatch, tmp_path):
    from flopo2.extract import compose

    po_lex, pato_lex = _lexicons(tmp_path)
    monkeypatch.setattr(compose, "load_lexicons", lambda: (po_lex, pato_lex))
    src = tmp_path / "preds.jsonl"
    src.write_text(
        '{"language":"en","text":"flowers red",'
        '"assertions":[{"po_id":"PO_0009046","pato_id":"PATO_0000322",'
        '"source_text":"flowers red"}]}\n'
    )
    out = tmp_path / "checks.jsonl"
    summary = compose.run_file(src, out, parser_mode="off")
    assert summary["segments"] == 1
    assert summary["statuses"] == {"accept": 1}
    assert out.exists()


def test_run_file_splits_accepted_and_review(monkeypatch, tmp_path):
    from flopo2.extract import compose

    po_lex, pato_lex = _lexicons(tmp_path)
    monkeypatch.setattr(compose, "load_lexicons", lambda: (po_lex, pato_lex))
    src = tmp_path / "preds.jsonl"
    src.write_text(
        '{"language":"en","text":"flowers red; leaves green",'
        '"predictions":['
        '{"po_id":"PO_0009046","pato_id":"PATO_0000322","source_text":"flowers red"},'
        '{"po_id":"PO_0009046","pato_id":"PATO_0000386","source_text":"leaves green"}'
        ']}\n'
    )
    checks = tmp_path / "checks.jsonl"
    accepted = tmp_path / "accepted.jsonl"
    review = tmp_path / "review.jsonl"
    summary = compose.run_file(
        src,
        checks,
        parser_mode="off",
        accepted_out=accepted,
        review_out=review,
    )
    assert summary["statuses"] == {"accept": 1, "review": 1}
    accepted_obj = json.loads(accepted.read_text())
    review_obj = json.loads(review.read_text())
    assert accepted_obj["assertions"][0]["composition"]["status"] == "accept"
    assert review_obj["assertions"][0]["composition"]["status"] == "review"
    assert "source_span_mentions_different_entity" in review_obj["assertions"][0]["composition"]["reasons"]


def test_clause_selection_uses_assertion_offsets_for_repeated_spans(tmp_path):
    from flopo2.extract.compose import check_assertion

    po_lex, pato_lex = _lexicons(tmp_path)
    text = "leaves green; flowers red; leaves green"
    start = text.rindex("green")
    assertion = Assertion(
        po_id="PO_0009025",
        pato_id="PATO_0000386",
        source_text="green",
        source_start=start,
        source_end=start + len("green"),
    )
    decision = check_assertion(text, assertion, po_lex, pato_lex)
    assert decision.clause == "leaves green"


def test_clause_selection_does_not_split_decimal_or_unit_abbreviation():
    from flopo2.extract.compose import _clause_around

    text = "Leaves 1.2 cm. long and green. Flowers red."
    start = text.index("green")
    assert _clause_around(text, "green", start, start + 5) == "Leaves 1.2 cm. long and green"


def test_composition_preserves_unresolved_and_optional_assertion_fields(monkeypatch, tmp_path):
    from flopo2.extract import compose

    po_lex, pato_lex = _lexicons(tmp_path)
    monkeypatch.setattr(compose, "load_lexicons", lambda: (po_lex, pato_lex))
    src = tmp_path / "preds.jsonl"
    src.write_text(json.dumps({
        "source": "s",
        "source_id": "1",
        "taxon": "Planta exemplar",
        "language": "en",
        "text": "flowers about 2 cm long; leaves green",
        "unresolved_spans": [{
            "start": 34,
            "end": 39,
            "surface_form": "green",
            "reason": "test_review",
            "candidate_pato_id": "PATO_0000386",
            "extractor": "test",
        }],
        "assertions": [{
            "po_id": "PO_0009046",
            "pato_id": "PATO_0000322",
            "negated": True,
            "negation_scope": "quality",
            "source_text": "flowers",
            "source_start": 0,
            "source_end": 7,
            "trait": "TO_1",
            "modifier": "approximately",
            "cardinality": "2",
            "confidence": 0.8,
            "developmental_stage_contexts": [{
                "stage_term": "PO_0007016",
                "stage_text": "long",
            }],
            "developmental_stage_operator": "atomic",
        }],
    }) + "\n")
    checks = tmp_path / "checks.jsonl"
    accepted = tmp_path / "accepted.jsonl"
    compose.run_file(src, checks, parser_mode="off", accepted_out=accepted)
    row = json.loads(accepted.read_text())
    assert row["unresolved_spans"][0]["reason"] == "test_review"
    assertion = row["assertions"][0]
    assert (
        assertion["trait"],
        assertion["modifier"],
        assertion["cardinality"],
        assertion["confidence"],
    ) == ("TO_1", "approximately", "2", 0.8)
    assert assertion["negation_scope"] == "quality"
    assert assertion["developmental_stage_contexts"] == [
        {"stage_term": "PO_0007016", "stage_text": "long"}
    ]
    assert assertion["developmental_stage_operator"] == "atomic"


def test_compose_roundtrips_source_bearer_and_modality_offsets(monkeypatch, tmp_path):
    from flopo2.extract import compose

    po_lex, pato_lex = _lexicons(tmp_path)
    monkeypatch.setattr(compose, "load_lexicons", lambda: (po_lex, pato_lex))
    text = "flowers usually red"
    source = tmp_path / "offsets.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "one.xml",
                "language": "en",
                "text": text,
                "assertions": [
                    {
                        "po_id": "PO_0009046",
                        "pato_id": "PATO_0000322",
                        "source_text": "red",
                        "source_start": 16,
                        "source_end": 19,
                        "raw_entity_text": "flowers",
                        "bearer_start": 0,
                        "bearer_end": 7,
                        "frequency_qualifier": "usually",
                        "modality_text": "usually",
                        "modality_start": 8,
                        "modality_end": 15,
                    }
                ],
            }
        )
        + "\n"
    )
    audit = tmp_path / "audit.jsonl"
    accepted = tmp_path / "accepted.jsonl"
    summary = compose.run_file(
        source,
        audit,
        parser_mode="off",
        accepted_out=accepted,
    )

    assert summary["statuses"] == {"accept": 1}
    audit_assertion = json.loads(audit.read_text())["decisions"][0]["assertion"]
    accepted_assertion = json.loads(accepted.read_text())["assertions"][0]
    expected_offsets = {
        "source_start": 16,
        "source_end": 19,
        "bearer_start": 0,
        "bearer_end": 7,
        "modality_start": 8,
        "modality_end": 15,
    }
    assert {key: audit_assertion[key] for key in expected_offsets} == expected_offsets
    assert {key: accepted_assertion[key] for key in expected_offsets} == expected_offsets


@pytest.mark.parametrize(
    ("identity_field", "identity"),
    [
        ("taxon_iri", "https://list.worldfloraonline.org/wfo-0000970690-2025-12"),
        ("taxon_id", "WFO:wfo-0000970690-2025-12"),
        ("taxon_curie", "NCBITaxon:58331"),
    ],
)
def test_segment_base_preserves_existing_taxon_identity(identity_field, identity):
    from flopo2.extract.compose import _segment_base

    source = {
        "source": "flora",
        "source_id": "treatment-1",
        "taxon": "Gambeya africana",
        "taxon_family": "Sapotaceae",
        "taxon_rank": "species",
        identity_field: identity,
        "text": "Flowers red.",
    }

    result = _segment_base(source)

    assert result[identity_field] == identity
    assert result["taxon"] == "Gambeya africana"
    assert result["taxon_family"] == "Sapotaceae"
    assert result["taxon_rank"] == "species"


def test_segment_base_does_not_invent_taxon_identity_for_name_only_record():
    from flopo2.extract.compose import _segment_base

    result = _segment_base({"taxon": "Gambeya africana", "text": "Flowers red."})

    assert result["taxon"] == "Gambeya africana"
    assert not {"taxon_iri", "taxon_id", "taxon_curie"}.intersection(result)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
