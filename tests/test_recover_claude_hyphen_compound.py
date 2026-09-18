import json
import re

import pytest

from flopo2.verify import recover_claude_hyphen_compound as hc
from flopo2.verify.data_model import validate_jsonl


REASON = "hyphenated_or_slash_compound"


@pytest.fixture(scope="module")
def resources() -> hc.Resources:
    return hc.Resources()


def _record(text: str, cues: list[tuple[str, str]], *, organ="description", language="en"):
    """Build a segment with one withheld hyphen span per ``(surface, pato_id)`` cue."""

    spans = []
    cursor = 0
    for surface, pato_id in cues:
        start = text.index(surface, cursor)
        cursor = start + len(surface)
        spans.append(
            {
                "start": start,
                "end": start + len(surface),
                "surface_form": surface,
                "reason": REASON,
                "candidate_pato_id": pato_id,
                "extractor": "deterministic_baseline",
            }
        )
    return {
        "source": "kew-african",
        "source_id": "test-1",
        "taxon": "Testia exempla L.",
        "organ": organ,
        "language": language,
        "char_start": 0,
        "char_end": len(text),
        "source_segment_index": 0,
        "text": text,
        "assertions": [],
        "source_statements": [],
        "term_mentions": [],
        "unresolved_spans": spans,
    }


def test_clause_initial_shape_continuum_is_recovered(resources):
    record = _record(
        "Leaves membranous, oblong-lanceolate, 10-30 by 2.5-7.5 cm, base attenuate.",
        [("oblong", "PATO_0000946"), ("lanceolate", "PATO_0001877")],
    )
    delta, outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None
    (assertion,) = delta["add_assertions"]
    relation = assertion["qualitative_value_relation"]
    assert assertion["po_id"] == "PO_0009025"
    assert assertion["pato_id"] == hc.SHAPE_ATTRIBUTE
    assert (relation["interpretation"], relation["from_value"], relation["to_value"]) == (
        "continuum",
        "PATO_0000946",
        "PATO_0001877",
    )
    assert record["text"][relation["connector_start"] : relation["connector_end"]] == "-"
    assert assertion["raw_entity_text"] == "Leaves" and assertion["bearer_start"] == 0
    assert assertion["gate"]["status"] == "accepted"
    assert assertion["extractor"] == hc.EXTRACTOR
    assert len(delta["remove_unresolved"]) == 2
    assert outcomes["shape:resolved_spans"] == 2
    statement_ids = {row["statement_id"] for row in delta["add_source_statements"]}
    assert assertion["source_statement_id"] in statement_ids


@pytest.mark.parametrize(
    "text",
    [
        "Leaves ovate to oblong-lanceolate, 3-5 cm long.",  # range with a third value
        "Leaves ± oblong-lanceolate, 3-5 cm long.",  # approximation is not an E2 degree
        "Leaves pale oblong-lanceolate, 3-5 cm long.",  # unmodelled pre-modifier
        "Leaves oblong-lanceolate or elliptic, 3-5 cm long.",  # alternative
        "Leaves oblong-lanceolate, sometimes elliptic, 3-5 cm long.",  # other value in clause
        "Lateral sepals oblong-lanceolate, 3 mm long.",  # subset bearer
        "Leaves pinnate, pinnae 5 pairs, oblong-lanceolate.",  # nested noun
        "Female flowers sessile; sepals 3, oblong-lanceolate, 1 mm long.",  # sex category
        "Stipules present, oblong-lanceolate, or absent.",  # absence alternative
        "Leaves oblong-lanceolate when young, 3 cm long.",  # developmental context
    ],
)
def test_unsafe_shape_contexts_stay_unresolved(resources, text):
    record = _record(text, [("oblong", "PATO_0000946"), ("lanceolate", "PATO_0001877")])
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is None


def test_french_agreement_blocks_nested_attachment(resources):
    text = "Rhizome épais, hérissé de paillettes, linéaires-lancéolées, ciliées."
    record = _record(
        text,
        [("linéaires", "PATO_0001199"), ("lancéolées", "PATO_0001877")],
        organ="rhizome",
        language="fr",
    )
    assert hc.recover_record(record, resources)[0] is None
    agreeing = _record(
        "Feuilles alternes, oblongues-lancéolées, de 3 cm de long.",
        [("oblongues", "PATO_0000946"), ("lancéolées", "PATO_0001877")],
        organ="feuilles",
        language="fr",
    )
    delta, _outcomes, _audit = hc.recover_record(agreeing, resources)
    assert delta is not None
    assert delta["add_assertions"][0]["po_id"] == "PO_0009025"
    mismatched = _record(
        "Limbe oblongues-lancéolées, de 3 cm de long.",
        [("oblongues", "PATO_0000946"), ("lancéolées", "PATO_0001877")],
        organ="feuilles",
        language="fr",
    )
    assert hc.recover_record(mismatched, resources)[0] is None


def test_exact_pato_colour_compound_is_atomic(resources):
    record = _record(
        "Seeds reddish-brown, globose, 5 mm long.",
        [("brown", "PATO_0000952")],
    )
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None
    (assertion,) = delta["add_assertions"]
    assert (assertion["po_id"], assertion["pato_id"]) == ("PO_0009010", "PATO_0001287")
    assert assertion["value_terms"] == []
    assert "qualitative_value_relation" not in assertion
    assert assertion["phenotype_class_iri"].startswith("https://w3id.org/flopo/annotation-class/FAC_")


def test_colour_blend_without_ontology_class_is_left(resources):
    record = _record("Seeds grey-brown, globose.", [("brown", "PATO_0000952")])
    assert hc.recover_record(record, resources)[0] is None


def test_prefix_modifier_and_numeric_prefix_are_out_of_scope(resources):
    for text, cue in (
        ("Leaves long-acuminate, 3 cm long.", ("acuminate", "PATO_0002228")),
        ("Stems much-branched, 3 m tall.", ("branched", "PATO_0000402")),
        ("Fruit 10-ridged, 3 cm long.", ("ridged", "PATO_0002358")),
    ):
        _delta, outcomes, _audit = hc.recover_record(_record(text, [cue]), resources)
        assert outcomes["span:out_of_scope_token"] == 1


def test_apply_delta_and_gated_validation(resources, tmp_path):
    record = _record(
        "Petals 5, glabrous, linear-oblong, 4 mm long. Seeds reddish-brown.",
        [
            ("linear", "PATO_0001199"),
            ("oblong", "PATO_0000946"),
            ("brown", "PATO_0000952"),
        ],
    )
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None and len(delta["add_assertions"]) == 2
    source = tmp_path / "in.jsonl"
    deltas = tmp_path / "delta.jsonl"
    patched = tmp_path / "out.jsonl"
    source.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    deltas.write_text(json.dumps(delta, ensure_ascii=False) + "\n", encoding="utf-8")
    assert hc.apply_delta(source, deltas, patched) == {"applied_segments": 1}
    out = json.loads(patched.read_text(encoding="utf-8"))
    assert out["unresolved_spans"] == []
    report = validate_jsonl(patched, stage="gated", strict_source_statements=True)
    assert report["errors"] == 0, report["error_examples"]

    stale = dict(delta, remove_unresolved=[{**delta["remove_unresolved"][0], "start": 0}])
    with pytest.raises(ValueError, match="absent"):
        hc.apply_delta_record(record, stale)


def test_right_boundary_regex_accepts_measurements_only():
    assert hc._RIGHT_BOUNDARY.match(", 3 cm long")
    assert hc._RIGHT_BOUNDARY.match(" in outline, 5 cm")
    assert hc._RIGHT_BOUNDARY.match(" de 3 mm de long")
    assert not hc._RIGHT_BOUNDARY.match(" to elliptic")
    assert not hc._RIGHT_BOUNDARY.match(" leaves")
    assert not re.match(hc._SHAPE_TOKEN, "ovale-lanceolee")


def test_leaflet_lamina_is_not_borne_on_leaf_lamina(resources):
    """``folioles …; limbe oblong-lancéolé`` describes the leaflet lamina (FLOPO_0986002)."""

    leaflet = "folioles 5; pétiolule de 5 mm de long; limbe oblong-lancéolé, de 5–9 cm de long."
    cues = [("oblong", "PATO_0000946"), ("lancéolé", "PATO_0001877")]
    delta, outcomes, _audit = hc.recover_record(
        _record(leaflet, cues, organ="feuilles", language="fr"), resources
    )
    borne = [row["po_id"] for row in (delta or {}).get("add_assertions", [])]
    assert "PO_0020039" not in borne
    # Without an approved leaflet-lamina x shape pair the gate holds the re-borne assertion.
    if not borne:
        assert outcomes["shape:gate_held"] == 2
    else:
        assert borne == ["FLOPO_0986002"]
    # Simple-leaf control: the same clause without the leaflet prefix stays leaf lamina.
    control = "limbe oblong-lancéolé, de 5–9 cm de long."
    delta, _outcomes, _audit = hc.recover_record(
        _record(control, cues, organ="feuilles", language="fr"), resources
    )
    assert delta is not None and delta["add_assertions"][0]["po_id"] == "PO_0020039"


def test_reviewed_local_bearer_phrase_is_the_bearer(resources):
    """``Calyx lobes`` resolves to the FLOPO calyx lobe (config/reviewed_local_bearers.tsv)."""

    assert hc._bearer_at("Calyx lobes oblong-lanceolate")[:3] == ("FLOPO_0986005", 11, "Calyx lobes")
    record = _record(
        "Calyx lobes oblong-lanceolate, 3 mm long.",
        [("oblong", "PATO_0000946"), ("lanceolate", "PATO_0001877")],
    )
    delta, outcomes, _audit = hc.recover_record(record, resources)
    borne = [row["po_id"] for row in (delta or {}).get("add_assertions", [])]
    assert "PO_0009060" not in borne
    assert borne in ([], ["FLOPO_0986005"])


@pytest.mark.parametrize(
    ("text", "cue", "degree", "language"),
    [
        ("Leaves narrowly oblong-lanceolate, 3-5 cm long.", "narrowly", "narrowly", "en"),
        ("Leaves petiolate, very narrowly oblong-lanceolate, 3 cm long.", "very narrowly", "narrowly", "en"),
        ("Feuilles alternes, largement oblongues-lancéolées, de 3 cm de long.", "largement", "broadly", "fr"),
    ],
)
def test_width_degree_cue_is_an_assertion_level_qualifier(resources, text, cue, degree, language):
    """E2: a closed width-degree cue before the compound qualifies the whole continuum."""

    left, right = ("oblong", "lanceolate") if language == "en" else ("oblongues", "lancéolées")
    record = _record(
        text, [(left, "PATO_0000946"), (right, "PATO_0001877")], language=language
    )
    delta, outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None
    (assertion,) = delta["add_assertions"]
    start = text.index(cue)
    assert assertion["degree_qualifier"] == degree
    assert (assertion["modality_text"], assertion["modality_start"], assertion["modality_end"]) == (
        cue,
        start,
        start + len(cue),
    )
    assert assertion["source_start"] <= start
    assert "compound_degree_qualifier:E2" in assertion["mapping_provenance"]
    relation = assertion["qualitative_value_relation"]
    assert relation["from_text"] == left and "from_operand" not in relation
    assert assertion["extractor"] == hc.EXTRACTOR
    assert outcomes[f"shape:degree:{degree}"] == 1


def test_degree_compound_validates_in_gated_stage(resources, tmp_path):
    record = _record(
        "Leaves narrowly elliptic-oblong, 3-5 cm long.",
        [("elliptic", "PATO_0000947"), ("oblong", "PATO_0000946")],
    )
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None
    source = tmp_path / "in.jsonl"
    deltas = tmp_path / "delta.jsonl"
    patched = tmp_path / "out.jsonl"
    source.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    deltas.write_text(json.dumps(delta, ensure_ascii=False) + "\n", encoding="utf-8")
    hc.apply_delta(source, deltas, patched)
    report = validate_jsonl(patched, stage="gated", strict_source_statements=True)
    assert report["errors"] == 0, report["error_examples"]


def test_colour_compound_ignores_width_degree(resources):
    record = _record("Seeds broadly reddish-brown, 3 mm long.", [("brown", "PATO_0000952")])
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is None or all(
        a["degree_qualifier"] == "unmodified" for a in delta["add_assertions"]
    )


# --- E3: indumentum parts and surface scope -------------------------------------------------


def test_indumentum_compound_puts_hair_quality_on_trichome_part(resources):
    record = _record("Petiole 3 mm long, stellate-pubescent.", [("pubescent", "PATO_0001320")])
    delta, outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None
    (assertion,) = delta["add_assertions"]
    assert assertion["pato_id"] == "PATO_0001320"
    (part,) = assertion["part_restrictions"]
    assert (part["filler_class"], part["qualities"]) == ("PO_0000282", ["PATO_0002065"])
    text = record["text"]
    assert text[part["part_start"] : part["part_end"]] == part["part_text"] == "stellate"
    assert "PATO_0002065" not in {assertion["pato_id"], *assertion["value_terms"]}
    assert "indumentum_part:E3" in assertion["mapping_provenance"]
    assert assertion["phenotype_class_iri"]
    assert outcomes["indumentum:assertions"] == 1


def test_french_head_first_indumentum_and_density_degree(resources):
    record = _record(
        "Pédoncules de 1–3 cm de long, densément tomenteux-bruns; bractées 13.",
        [("tomenteux", "PATO_0002341")],
        language="fr",
    )
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None
    (assertion,) = delta["add_assertions"]
    assert assertion["part_restrictions"][0]["qualities"] == ["PATO_0000952"]
    assert assertion["degree_qualifier"] == "densely"
    assert assertion["modality_text"] == "densément"


def test_surface_cue_substitutes_reviewed_surface_bearer(resources):
    record = _record(
        "Leaves ovate, apex acute, glabrous above, densely white-tomentose beneath.",
        [("tomentose", "PATO_0002341")],
    )
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None
    (assertion,) = delta["add_assertions"]
    scope = assertion["bearer_scope"]
    assert assertion["po_id"] == scope["scope_class"] == "PO_0000049"
    assert scope["outer_bearer"] == "PO_0009025" and scope["mode"] == "substituted_bearer"
    assert record["text"][scope["scope_start"] : scope["scope_end"]] == "beneath"
    assert "bearer_scope:E3" in assertion["mapping_provenance"]


@pytest.mark.parametrize(
    "text",
    [
        "Leaves ovate, stellate-pubescent, glabrous above.",  # other side named, no own cue
        "Leaves ovate, glabrous or stellate-pubescent, 3 cm long.",  # other pilosity value
        "Leaves ovate, lobes acute, white-tomentose beneath.",  # nested noun member
        "Stems terete, stellate-pubescent beneath.",  # surface cue on a non-laminar organ
        "Leaves ovate, densely to sparingly stellate-pubescent.",  # degree range
    ],
)
def test_unsafe_indumentum_contexts_stay_unresolved(resources, text):
    record = _record(text, [("pubescent" if "pubescent" in text else "tomentose", "PATO_0001320")])
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is None


def test_hair_colour_phrase_colours_trichomes_not_organ(resources):
    text = "Leaves ovate, with reddish-brown hairs, 3 cm long."
    record = _record(text, [("brown", "PATO_0000952")])
    compound = hc.match_compound(text, text.index("reddish"), text.index(" hairs"), resources)
    compound = hc.with_hair_context(text, compound, "en")
    assert compound.family == "hair_colour" and compound.pato_id == hc.HAIRY
    assert compound.part["filler_class"] == "PO_0000282"
    assert text[compound.expression_start : compound.expression_end] == "with reddish-brown hairs"
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    if delta is not None:
        (assertion,) = delta["add_assertions"]
        assert assertion["pato_id"] == hc.HAIRY
        assert assertion["part_restrictions"][0]["qualities"] != [assertion["pato_id"]]


def test_e3_assertions_validate_in_gated_stage(resources, tmp_path):
    record = _record(
        "Leaves ovate, glabrous above, stellate-pubescent beneath; petiole 3 mm, white-tomentose.",
        [("pubescent", "PATO_0001320"), ("tomentose", "PATO_0002341")],
    )
    delta, _outcomes, _audit = hc.recover_record(record, resources)
    assert delta is not None and len(delta["add_assertions"]) == 2
    source = tmp_path / "in.jsonl"
    deltas = tmp_path / "delta.jsonl"
    patched = tmp_path / "out.jsonl"
    source.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    deltas.write_text(json.dumps(delta, ensure_ascii=False) + "\n", encoding="utf-8")
    hc.apply_delta(source, deltas, patched)
    report = validate_jsonl(patched, stage="gated", strict_source_statements=True)
    assert report["errors"] == 0, report["error_examples"]
