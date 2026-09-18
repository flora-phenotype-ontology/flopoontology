"""Tests for the deterministic continuum/transition recovery of residual alternative spans."""

from __future__ import annotations

import json

import pytest

from flopo2.annotation.qualitative import validate_qualitative_value_relation
from flopo2.verify import recover_claude_alternatives_transitions as rec


TARGET = "unsupported_alternative_or_transition"


@pytest.fixture(scope="module")
def catalogs() -> rec.Catalogs:
    return rec.Catalogs.load()


def _span(text: str, word: str, pato_id: str, *, occurrence: int = 0, reason: str = TARGET) -> dict:
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(word, start + 1)
    return {
        "start": start,
        "end": start + len(word),
        "surface_form": word,
        "reason": reason,
        "candidate_pato_id": pato_id,
        "extractor": "deterministic_baseline",
    }


def _record(text: str, spans: list[dict], *, organ: str = "description", language: str = "en") -> dict:
    return {
        "source": "test",
        "source_id": "doc-1",
        "source_segment_index": 0,
        "taxon": "Testus exemplaris",
        "organ": organ,
        "language": language,
        "char_start": 100,
        "char_end": 100 + len(text),
        "text": text,
        "assertions": [],
        "source_statements": [],
        "unresolved_spans": spans,
    }


def test_english_shape_continuum_is_recovered_with_verbatim_evidence(catalogs):
    text = "Leaves elliptic to lanceolate, 3–5 cm long."
    record = _record(
        text,
        [
            _span(text, "elliptic", "PATO_0000947"),
            _span(text, "lanceolate", "PATO_0001877"),
        ],
    )
    delta, _ = rec.recover_record(record, catalogs)
    assert delta is not None
    [assertion] = delta["add_assertions"]
    relation = assertion["qualitative_value_relation"]
    assert assertion["po_id"] == "PO_0009025"
    assert assertion["pato_id"] == "PATO_0000052"
    assert relation["interpretation"] == "continuum"
    assert (relation["from_value"], relation["to_value"]) == ("PATO_0000947", "PATO_0001877")
    for prefix in ("from", "connector", "to"):
        assert text[relation[f"{prefix}_start"] : relation[f"{prefix}_end"]] == relation[
            f"{prefix}_text"
        ]
    assert assertion["source_text"] == "Leaves elliptic to lanceolate"
    assert assertion["raw_entity_text"] == "Leaves"
    assert "phenotype_class_iri" not in assertion
    assert not validate_qualitative_value_relation(assertion, text)
    [statement] = delta["add_source_statements"]
    assert statement["statement_id"] == assertion["source_statement_id"]
    assert statement["document_start"] == 100 + statement["start"]
    assert len(delta["remove_unresolved"]) == 2


def test_hold_for_review_is_the_default_and_admit_keeps_the_gate(catalogs):
    text = "Petals white to yellow."
    spans = [_span(text, "white", "PATO_0000323"), _span(text, "yellow", "PATO_0000324")]
    held, _ = rec.recover_record(_record(text, spans), catalogs)
    admitted, _ = rec.recover_record(_record(text, spans), catalogs, hold_for_review=False)
    assert held["add_assertions"][0]["gate"]["status"] == "review"
    assert rec.HOLD_REASON in held["add_assertions"][0]["gate"]["reasons"]
    assert admitted["add_assertions"][0]["gate"]["status"] == "accepted"
    assert admitted["add_assertions"][0]["gate"]["flopo_status"] == "structured_annotation_only"


def test_french_endpoint_is_grounded_through_english_exact_label(catalogs):
    text = "pétiole de 2 cm; limbe elliptique à obovale, de 4–6 cm de long."
    record = _record(text, [_span(text, "elliptique", "PATO_0000947")], language="fr")
    delta, _ = rec.recover_record(record, catalogs)
    assert delta is not None
    relation = delta["add_assertions"][0]["qualitative_value_relation"]
    assert delta["add_assertions"][0]["po_id"] == "PO_0020039"
    assert relation["to_value"] == "PATO_0001936"
    assert relation["connector_text"] == "à"


def test_temporal_transition_is_recovered(catalogs):
    text = "Fruit green becoming red."
    record = _record(
        text, [_span(text, "green", "PATO_0000320"), _span(text, "red", "PATO_0000322")]
    )
    delta, _ = rec.recover_record(record, catalogs)
    assert delta is not None
    relation = delta["add_assertions"][0]["qualitative_value_relation"]
    assert relation["interpretation"] == "temporal_transition"
    assert relation["connector_text"] == "becoming"


@pytest.mark.parametrize(
    ("text", "word", "pato_id", "reason"),
    [
        # A degree outside the closed family cues (E2 admits "narrowly"): no relation proposed.
        ("Leaves ovate to deeply lanceolate.", "ovate", "PATO_0001891", None),
        (
            "Leaves oblong to elliptic to lanceolate.",
            "oblong",
            "PATO_0000946",
            "chained_or_mixed_connector_after",
        ),
        (
            "Corolla white to pink, yellowish, bluish.",
            "white",
            "PATO_0000323",
            "following_same_family_value",
        ),
        (
            "Flowers yellow-green, green to brown.",
            "brown",
            "PATO_0000952",
            "preceding_same_family_value",
        ),
        (
            "Accrescent, in fruit orange to red.",
            "red",
            "PATO_0000322",
            "stage_or_relational_phrase_bearer",
        ),
        (
            "Leaves obtuse to acuminate, 3 cm long.",
            "obtuse",
            "PATO_0001935",
            "terminal_shape_endpoint_on_leaf_bearer",
        ),
        ("Leaves not elliptic to lanceolate.", "elliptic", "PATO_0000947", "negated_context"),
        (
            "Anthers green to yellow, turning black with age.",
            "green",
            "PATO_0000320",
            "temporal_cue_in_clause",
        ),
        (
            "Leaves glabrous to pubescent at apex.",
            "glabrous",
            "PATO_0000453",
            "bearer_unresolved_for_an_endpoint",
        ),
    ],
)
def test_unsafe_constructions_stay_unresolved(catalogs, text, word, pato_id, reason):
    record = _record(text, [_span(text, word, pato_id)])
    delta, outcomes = rec.recover_record(record, catalogs)
    assert delta is None
    assert all(outcome.status == "retained" for outcome in outcomes)
    if reason is None:
        assert outcomes == []
    else:
        assert reason in {outcome.reason for outcome in outcomes}


def test_statement_with_disjunction_is_not_recorded_as_atomic(catalogs):
    text = "folioles 1-21, ovées ou obovées, glabres à pubescentes."
    record = _record(text, [_span(text, "glabres", "PATO_0000453")], language="fr")
    delta, outcomes = rec.recover_record(record, catalogs)
    assert delta is None
    assert any(outcome.reason == "disjunction_inside_statement" for outcome in outcomes)


def test_unrelated_unresolved_span_inside_relation_blocks(catalogs):
    text = "Leaves elliptic to lanceolate."
    spans = [
        _span(text, "elliptic", "PATO_0000947"),
        {**_span(text, "lanceolate", "PATO_0001877"), "reason": "explicit_disjunction"},
    ]
    delta, outcomes = rec.recover_record(_record(text, spans), catalogs)
    assert delta is None
    assert outcomes[0].reason == "unrelated_unresolved_span_in_relation"


def test_apply_delta_round_trip_and_fail_closed(tmp_path, catalogs):
    text = "Stems glabrous to tomentose."
    record = _record(
        text, [_span(text, "glabrous", "PATO_0000453"), _span(text, "tomentose", "PATO_0002341")]
    )
    delta, _ = rec.recover_record(record, catalogs)
    patched = rec.apply_delta_to_record(record, delta)
    assert patched["unresolved_spans"] == []
    assert len(patched["assertions"]) == 1
    assert patched["assertions"][0]["source_statement_id"] in {
        row["statement_id"] for row in patched["source_statements"]
    }

    source = tmp_path / "in.jsonl"
    delta_path = tmp_path / "delta.jsonl"
    output = tmp_path / "out.jsonl"
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    delta_path.write_text(json.dumps(delta) + "\n", encoding="utf-8")
    assert rec.apply_delta(source, delta_path, output) == {"delta_lines": 1, "applied": 1}

    broken = dict(delta)
    broken["remove_unresolved"] = [
        {"start": 0, "end": 5, "reason": TARGET, "surface_form": "Stems"}
    ]
    with pytest.raises(ValueError):
        rec.apply_delta_to_record(record, broken)


def test_wilson_interval():
    low, high = rec.wilson_interval(160, 160)
    assert 0.976 < low < 0.978
    assert high == pytest.approx(1.0)
    assert rec.wilson_interval(0, 0) == (0.0, 0.0)


def test_leaflet_lamina_range_is_not_borne_on_leaf_lamina(catalogs):
    """``folioles …; limbe elliptique à obovale`` is the leaflet lamina (FLOPO_0986002)."""

    def run(text: str) -> tuple[dict | None, dict]:
        record = _record(
            text,
            [
                _span(text, "elliptique", "PATO_0000947"),
                _span(text, "obovale", "PATO_0001936"),
            ],
            organ="feuilles",
            language="fr",
        )
        return rec.recover_record(record, catalogs)

    delta, _ = run("folioles 9–15, à pétiolule de 1–5 mm de long; limbe elliptique à obovale, de 3 cm de long.")
    borne = [row["po_id"] for row in (delta or {}).get("add_assertions", [])]
    assert "PO_0020039" not in borne
    assert borne in ([], ["FLOPO_0986002"])
    # Simple-leaf control keeps the leaf lamina.
    delta, _ = run("limbe elliptique à obovale, de 3 cm de long.")
    assert delta is not None and delta["add_assertions"][0]["po_id"] == "PO_0020039"


def test_colour_range_after_indument_term_is_retained(catalogs):
    text = "Ovaire densément pubescent velouté, gris à brun."
    record = _record(
        text,
        [_span(text, "gris", "PATO_0000950"), _span(text, "brun", "PATO_0000952")],
        organ="ovary",
        language="fr",
    )
    delta, outcomes = rec.recover_record(record, catalogs)
    assert delta is None
    assert [o.reason for o in outcomes] == ["colour_after_indument_term"]


def test_colour_after_sparse_hairs_is_the_organ_colour(catalogs):
    text = "Fruit 4–6 mm long, sparsely hairy, yellow to orange."
    record = _record(text, [_span(text, "yellow", "PATO_0000324"), _span(text, "orange", "PATO_0000953")])
    delta, _outcomes = rec.recover_record(record, catalogs)
    assert delta is not None and delta["add_assertions"][0]["po_id"] == "PO_0009001"


# ---------------------------------------------------------------------------------------------
# E2: per-endpoint degree qualifiers


def _one(record, catalogs):
    delta, outcomes = rec.recover_record(record, catalogs)
    return delta, outcomes


def test_degree_modified_shape_endpoints_carry_operands(catalogs):
    from flopo2.annotation.operands import validate_value_operands

    text = "Leaves narrowly elliptic to broadly lanceolate, 3–5 cm long."
    record = _record(
        text,
        [_span(text, "elliptic", "PATO_0000947"), _span(text, "lanceolate", "PATO_0001877")],
    )
    delta, _ = _one(record, catalogs)
    assert delta is not None
    assertion = delta["add_assertions"][0]
    relation = assertion["qualitative_value_relation"]
    assert relation["from_text"] == "narrowly elliptic"
    assert relation["to_text"] == "broadly lanceolate"
    assert relation["from_operand"]["degree_qualifier"] == "narrowly"
    assert relation["from_operand"]["qualifier_text"] == "narrowly"
    assert relation["to_operand"]["degree_qualifier"] == "broadly"
    assert relation["to_operand"]["operand_index"] == 1
    assert "endpoint_qualifiers:E2" in assertion["mapping_provenance"]
    assert not validate_value_operands(assertion, text)
    assert not validate_qualitative_value_relation(assertion, text)


def test_french_pilosity_degree_endpoint(catalogs):
    text = "Pédicelle de 2 mm de long, éparsement pubescent à glabre."
    record = _record(
        text,
        [_span(text, "pubescent", "PATO_0001320"), _span(text, "glabre", "PATO_0000453")],
        language="fr",
        organ="fleurs",
    )
    delta, _ = _one(record, catalogs)
    assert delta is not None
    relation = delta["add_assertions"][0]["qualitative_value_relation"]
    assert relation["from_text"] == "éparsement pubescent"
    assert relation["from_operand"]["degree_qualifier"] == "sparsely"
    assert "to_operand" not in relation


def test_unmodified_relation_has_no_operands(catalogs):
    text = "Leaves elliptic to lanceolate, 3–5 cm long."
    record = _record(
        text,
        [_span(text, "elliptic", "PATO_0000947"), _span(text, "lanceolate", "PATO_0001877")],
    )
    delta, _ = _one(record, catalogs)
    relation = delta["add_assertions"][0]["qualitative_value_relation"]
    assert "from_operand" not in relation and "to_operand" not in relation


@pytest.mark.parametrize(
    ("text", "left", "right", "reason"),
    [
        # A density degree is not a shape degree.
        (
            "Leaves densely elliptic to lanceolate, 3 cm long.",
            ("elliptic", "PATO_0000947"),
            ("lanceolate", "PATO_0001877"),
            "modified_first_operand",
        ),
        # The pilosity belongs to the attributive pétiolule (masculine), not the folioles.
        (
            "Folioles à pétiolule de 1 mm de long, éparsement pubescent à glabre.",
            ("pubescent", "PATO_0001320"),
            ("glabre", "PATO_0000453"),
            "nested_attributive_part_before_relation",
        ),
        (
            "Stipe 3 cm, with long slender petioles, glabrous to densely pubescent; flowers red.",
            ("glabrous", "PATO_0000453"),
            ("pubescent", "PATO_0001320"),
            "bearer_is_with_complement",
        ),
        (
            "Inflorescences terminal panicles, up to 6 cm. long; branches glabrous to shortly "
            "pubescent; bracts subulate.",
            ("glabrous", "PATO_0000453"),
            ("pubescent", "PATO_0001320"),
            "branch_in_inflorescence_context",
        ),
    ],
)
def test_degree_endpoint_guards(catalogs, text, left, right, reason):
    record = _record(text, [_span(text, *left), _span(text, *right)])
    delta, outcomes = _one(record, catalogs)
    assert delta is None
    assert reason in {outcome.reason for outcome in outcomes}
