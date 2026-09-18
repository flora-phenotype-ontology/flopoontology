from __future__ import annotations

import json

import pytest

from flopo2.verify import recover_claude_explicit_disjunction as rec


def _record(text: str, *surfaces: str, organ: str = "description", source: str = "kew-african",
            family: str = "Rubiaceae", language: str = "en") -> dict:
    spans = []
    for surface in surfaces:
        start = text.index(surface)
        spans.append(
            {
                "start": start,
                "end": start + len(surface),
                "surface_form": surface,
                "reason": rec.TARGET_REASON,
                "candidate_pato_id": "PATO_0000000",
                "extractor": "deterministic_baseline",
            }
        )
    return {
        "source": source,
        "source_id": "1",
        "source_segment_index": 0,
        "taxon": "Genus species",
        "taxon_family": family,
        "organ": organ,
        "language": language,
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "assertions": [],
        "source_statements": [],
        "unresolved_spans": spans,
    }


def _find(text: str, surface: str, **kwargs):
    record = _record(text, surface, **kwargs)
    span = record["unresolved_spans"][0]
    return rec.find_candidate(record, span["start"], span["end"])


@pytest.fixture(scope="module")
def gate_context():
    return rec.GateContext.load()


def test_head_noun_colour_union():
    candidate, reason = _find("Petals 5, 4–5 mm. long, white or pink. Stamens 5.", "white")
    assert reason == ""
    assert candidate.bearer_po == "PO_0009032"
    assert [op.pato_id for op in candidate.operands] == ["PATO_0000323", "PATO_0000954"]
    assert candidate.subfamily == "colour"


def test_french_comma_list_union():
    candidate, reason = _find(
        "corolle rose, rouge ou pourpre; étendard obovale.", "rouge", source="fdac",
        language="fr", organ="fleurs",
    )
    assert reason == ""
    assert candidate.bearer_po == "PO_0009059"
    assert [op.pato_id for op in candidate.operands] == [
        "PATO_0000954", "PATO_0000322", "PATO_0000951",
    ]


def test_ungrounded_partner_stays_residual():
    _candidate, reason = _find("Ovary glabrous or puberulous.", "glabrous")
    assert reason == "ungrounded_or_modified_operand"


def test_apex_shape_not_handled():
    _candidate, reason = _find("Leaves elliptic, apex obtuse or acute.", "obtuse")
    assert reason == "ungrounded_or_modified_operand"


def test_nonexhaustive_list_blocked():
    # ``whitish`` is a same-family alternative outside the table: never drop it.
    _candidate, reason = _find("Petals whitish, white or pink.", "white")
    assert reason in {"unsafe_gap_between_head_and_union", "unsupported_same_family_cue_in_clause"}
    _candidate, reason = _find("Bark ashy-brown, brown or grey, smooth.", "brown")
    assert reason in {"unsafe_gap_between_head_and_union", "other_same_family_value_in_clause"}


def test_developmental_context_blocked():
    _candidate, reason = _find("Fruit green or yellow, becoming black.", "green")
    assert reason == "clause_scope_or_context_cue"


def test_trailing_scope_blocks_operand():
    _candidate, reason = _find("Leaves glabrous or pubescent beneath.", "glabrous")
    assert reason == "ungrounded_or_modified_operand"


def test_nested_bearer_in_gap_blocked():
    _candidate, reason = _find("Leaves 3 cm long, lower surface glabrous or pubescent.", "glabrous")
    assert reason == "ungrounded_or_modified_operand"
    _candidate, reason = _find("Leaves of short shoots, glabrous or pubescent.", "glabrous")
    assert reason == "unsafe_gap_between_head_and_union"
    _candidate, reason = _find(
        "Pétales glabres extérieurement, roses ou blancs.", "blancs", source="fdac", language="fr"
    )
    assert reason == "unsafe_gap_between_head_and_union"


def test_mixed_dimension_shapes_blocked():
    _candidate, reason = _find("Leaves ovate or elliptic.", "elliptic")
    assert reason == "mixed_pato_shape_dimensions"


def test_entailing_modifier_and_hedge():
    candidate, reason = _find("Ovary glabrous or rarely sparsely pubescent.", "glabrous")
    assert reason == ""
    assert [op.pato_id for op in candidate.operands] == ["PATO_0000453", "PATO_0001320"]
    assert candidate.operands[1].hedge == "rarely"
    assert candidate.operands[1].modifier == "sparsely"


def test_contextual_simple_means_unbranched():
    candidate, reason = _find("Stems simple or branched, glabrous.", "branched")
    assert reason == ""
    assert [op.pato_id for op in candidate.operands] == ["PATO_0000414", "PATO_0000402"]
    _candidate, reason = _find("Leaves simple or glabrous.", "glabrous")
    assert reason != ""


def test_banner_petal_requires_papilionoid_family():
    _candidate, reason = _find("Standard yellow or orange.", "yellow", family="Balsaminaceae")
    assert reason == "no_clause_head_bearer"
    candidate, reason = _find("Standard yellow or orange.", "yellow", family="Leguminosae")
    assert reason == "" and candidate.bearer_po == "PO_0025324"


def test_growth_form_tail_bearer():
    candidate, reason = _find("Erect or decumbent annual herb, 30 cm tall.", "Erect")
    assert reason == ""
    assert candidate.bearer_po == "PO_0000003"
    assert candidate.bearer_method == "post_union_growth_form"


def test_organ_heading_first_clause_only():
    text = "roses ou blanches, à pédicelle de 2 mm de long; sépales verts."
    candidate, reason = _find(text, "blanches", source="fdac", organ="fleurs", language="fr")
    assert reason == ""
    assert candidate.bearer_method == "organ_heading"
    assert candidate.bearer_po == "PO_0009046"
    _candidate, reason = _find(text, "blanches", source="kew-african", organ="description")
    assert reason == "no_clause_head_bearer"


def test_recover_record_delta_and_apply(gate_context, tmp_path):
    record = _record("Petals white or pink. Sepals green.", "white", "pink")
    delta, outcomes, _audit = rec.recover_record(record, gate_context)
    assert outcomes["resolved_spans"] == 2
    assert delta is not None
    assertion = delta["add_assertions"][0]
    assert assertion["value_operator"] == "one_of"
    assert assertion["pato_id"] == "PATO_0000014"
    assert assertion["source_text"] == "Petals white or pink"
    assert assertion["phenotype_class_iri"].startswith(
        "https://w3id.org/flopo/annotation-class/FAC_"
    )
    statement_ids = {row["statement_id"] for row in delta["add_source_statements"]}
    assert assertion["source_statement_id"] in statement_ids
    patched = rec.apply_delta_to_record(record, delta)
    assert patched["unresolved_spans"] == []
    assert len(patched["assertions"]) == 1

    corpus = tmp_path / "in.jsonl"
    corpus.write_text(json.dumps(record) + "\n", encoding="utf-8")
    delta_path = tmp_path / "delta.jsonl"
    delta_path.write_text(json.dumps(delta) + "\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    assert rec.apply_delta_file(corpus, delta_path, out) == {"deltas": 1, "applied": 1}
    with pytest.raises(ValueError):
        rec.apply_delta_file(corpus, delta_path, corpus)


def test_existing_overlapping_assertion_blocks(gate_context):
    record = _record("Petals white or pink.", "white")
    record["assertions"] = [{"source_start": 0, "source_end": 12}]
    delta, outcomes, _audit = rec.recover_record(record, gate_context)
    assert delta is None
    assert outcomes["residual:overlaps_existing_assertion"] == 1


def test_value_table_ids_exist_in_pato_lexicon():
    import csv
    from pathlib import Path

    with Path("config/pato_lexicon.tsv").open(encoding="utf-8") as handle:
        ids = {row["id"] for row in csv.DictReader(handle, delimiter="\t")}
    assert {pato for pato, _family in rec.VALUE_TABLE.values()} <= ids
    assert set(rec.ATTRIBUTE_BY_SUBFAMILY.values()) <= ids


def test_released_flopo_local_alias_is_a_head():
    """Curator-approved FLOPO-local bearers (calyx lobe) come from config/reviewed_local_bearers.tsv."""

    candidate, reason = _find("Calyx lobes 5, white or pink. Stamens 5.", "white")
    assert reason == ""
    assert candidate.bearer_po == "FLOPO_0986005"


def test_leaflet_lamina_union_is_not_leaf_lamina(gate_context):
    text = "folioles 7, à pétiolule de 3 mm de long; limbe glabre ou pubescent, de 4 cm de long."
    record = _record(text, "glabre", organ="feuilles", source="fdac", language="fr")
    delta, _outcomes, _audit = rec.recover_record(record, gate_context)
    borne = [row["po_id"] for row in (delta or {}).get("add_assertions", [])]
    # Re-borne on the leaflet lamina; the novel pair is surfaced for curation (gate review).
    assert borne == ["FLOPO_0986002"]
    assert delta["add_assertions"][0]["gate"]["status"] == "review"
    control = "limbe glabre ou pubescent, de 4 cm de long."
    delta, _outcomes, _audit = rec.recover_record(
        _record(control, "glabre", organ="feuilles", source="fdac", language="fr"), gate_context
    )
    assert [row["po_id"] for row in delta["add_assertions"]] == ["PO_0020039"]


# --- v3: per-operand qualifiers (schema extension E2) -----------------------------------------


def _single_assertion(gate_context, text: str, surface: str, **kwargs) -> dict:
    record = _record(text, surface, **kwargs)
    delta, _outcomes, _audit = rec.recover_record(record, gate_context)
    assert delta is not None
    (assertion,) = delta["add_assertions"]
    return assertion


def test_operands_carry_degree_and_keep_fac_identity(gate_context):
    from flopo2.annotation.operands import validate_value_operands
    from flopo2.owl.annotation_class import annotation_class_iri

    text = "Ovary glabrous or very sparsely hairy. Style 2 mm."
    assertion = _single_assertion(gate_context, text, "glabrous")
    operands = assertion["value_operands"]
    assert [op["value"] for op in operands] == assertion["value_terms"]
    assert operands[0]["degree_qualifier"] == "unmodified"
    assert "qualifier_text" not in operands[0]
    assert operands[1]["text"] == "very sparsely hairy"
    assert operands[1]["degree_qualifier"] == "sparsely"
    assert operands[1]["qualifier_text"] == "very sparsely"
    assert text[operands[1]["qualifier_start"] : operands[1]["qualifier_end"]] == "very sparsely"
    assert not validate_value_operands(assertion, text)
    without = {k: v for k, v in assertion.items() if k not in {"value_operands", "phenotype_class_iri"}}
    assert assertion["phenotype_class_iri"] == annotation_class_iri(without)
    assert any(p.startswith("operand_qualifiers:E2:") for p in assertion["mapping_provenance"])


def test_frequency_hedge_becomes_operand_frequency(gate_context):
    text = "Calyx glabrous or rarely hairy. Petals 5."
    assertion = _single_assertion(gate_context, text, "glabrous")
    second = assertion["value_operands"][1]
    assert second["frequency_qualifier"] == "rarely"
    assert second["qualifier_text"] == "rarely"
    assert assertion["frequency_qualifier"] == "unspecified"
    assert not any("retained_in_source_only" in p for p in assertion["mapping_provenance"])


def test_french_degree_cues_map_to_operand_degree(gate_context):
    text = "Tige simple ou peu ramifiée, dressée. Feuilles 3 cm."
    assertion = _single_assertion(gate_context, text, "simple", language="fr")
    assert assertion["value_operands"][1]["degree_qualifier"] == "sparsely"
    assert assertion["value_operands"][1]["qualifier_text"] == "peu"


def test_unmapped_modifier_is_generalized_and_not_a_cue():
    text = "Seeds black or sometimes bright blue."
    ops = [
        rec.Operand(text.index("black"), text.index(" or"), "black", "PATO_0000317", "colour", "", "", text.index("black")),
        rec.Operand(
            text.index("blue"), text.index("."), "blue", "PATO_0000318", "colour",
            "sometimes", "bright", text.index("sometimes"),
        ),
    ]
    records, notes = rec.operand_records(text, ops)
    assert records[1]["qualifier_text"] == "sometimes"
    assert records[1]["frequency_qualifier"] == "sometimes"
    assert records[1]["degree_qualifier"] == "unmodified"
    assert records[1]["text"] == "sometimes bright blue"
    assert any("generalized:bright blue" in note for note in notes)


def test_operand_hedge_never_contradicts_assertion_frequency():
    text = "Leaves usually white or rarely pink."
    ops = [
        rec.Operand(text.index("white"), text.index(" or"), "white", "PATO_0000323", "colour", "", "", text.index("white")),
        rec.Operand(text.index("pink"), text.index("."), "pink", "PATO_0000954", "colour", "rarely", "", text.index("rarely")),
    ]
    records, notes = rec.operand_records(text, ops, "usually")
    assert records[1]["frequency_qualifier"] == "unspecified"
    assert any("conflicts_with_assertion_frequency" in note for note in notes)
