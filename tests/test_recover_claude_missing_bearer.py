"""Tests for the deterministic missing-bearer recovery (clause heads, headings, trichomes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flopo2.extract import baseline
from flopo2.extract.measurement import parse_measurements
from flopo2.verify.data_model import validate_jsonl
from flopo2.verify.recover_claude_missing_bearer import (
    DEFAULT_TABLE,
    TARGET_REASON,
    Recoverer,
    apply_record_delta,
    load_head_table,
    recover_record,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def recoverer() -> Recoverer:
    return Recoverer.from_config(
        ROOT / DEFAULT_TABLE,
        po_lexicon=ROOT / "config/po_lexicon.tsv",
        pato_lexicon=ROOT / "config/pato_lexicon.tsv",
        registry_path=ROOT / "config/flopo_id_registry.tsv",
        combinations_path=ROOT / "config/valid_combinations.tsv",
    )


def _span(text: str, language: str, surface: str, occurrence: int = 0) -> dict:
    """Build an unresolved span exactly as the baseline would for ``surface``."""

    for measurement in parse_measurements(text, language):
        if measurement.source_text.strip() == surface:
            return {
                "start": measurement.start,
                "end": measurement.end,
                "surface_form": measurement.source_text,
                "reason": TARGET_REASON,
                "candidate_pato_id": measurement.attribute_id,
                "extractor": "deterministic_baseline",
            }
    found = []
    for cue in baseline.QUALITY_PATTERNS:
        for match in cue.pattern.finditer(text):
            if match.group(0).strip() == surface:
                found.append((match.start(), match.end(), cue.pato_id))
    start, end, pato_id = sorted(found)[occurrence]
    return {
        "start": start,
        "end": end,
        "surface_form": text[start:end],
        "reason": TARGET_REASON,
        "candidate_pato_id": pato_id,
        "extractor": "deterministic_baseline",
    }


def _record(text: str, *surfaces: str, language: str = "en", organ: str = "description",
            family: str = "Compositae") -> dict:
    return {
        "source": "test",
        "source_id": "doc-1",
        "source_segment_index": 0,
        "taxon": "Testia testii",
        "taxon_family": family,
        "organ": organ,
        "language": language,
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "source_statements": [],
        "assertions": [],
        "term_mentions": [],
        "unresolved_spans": [_span(text, language, surface) for surface in surfaces],
    }


def _recovered(delta: dict | None) -> list[tuple[str, str, str]]:
    if delta is None:
        return []
    return [
        (row["po_id"], row["pato_id"], row["source_text"].strip())
        for row in delta["add_assertions"]
    ]


def test_table_ids_exist_in_catalogs(recoverer: Recoverer) -> None:
    table = load_head_table(ROOT / DEFAULT_TABLE)
    assert table, "reviewed head table must not be empty"
    for entry in table:
        assert entry.po_id in recoverer.po_ids or entry.po_id in recoverer.flopo_ids


def test_clause_head_measurement_is_recovered(recoverer: Recoverer) -> None:
    text = "Capitula discoid; involucre cylindrical, 7–9 mm long, 3 mm in diameter."
    delta, decisions = recover_record(_record(text, "7–9 mm long"), recoverer)
    assert _recovered(delta) == [("PO_0009100", "PATO_0000122", "7–9 mm long")]
    assertion = delta["add_assertions"][0]
    assert assertion["raw_entity_text"] == "involucre"
    assert text[assertion["bearer_start"] : assertion["bearer_end"]] == "involucre"
    assert assertion["gate"]["status"] == "accepted"
    assert assertion["phenotype_class_iri"].startswith("https://w3id.org/flopo/annotation-class/")
    assert decisions[0]["rule"] == "clause_head"


def test_nested_noun_blocks_clause_head(recoverer: Recoverer) -> None:
    text = "Involucre cylindrical, with appendages 7–9 mm long."
    delta, decisions = recover_record(_record(text, "7–9 mm long"), recoverer)
    assert delta is None
    assert decisions[0]["reason"] == "unwhitelisted_head_to_span_filler"


def test_locative_right_context_blocks(recoverer: Recoverer) -> None:
    text = "Pistil glabrous above, 2 mm long."
    delta, decisions = recover_record(
        _record(text, "glabrous", family="Rubiaceae"), recoverer
    )
    assert delta is None
    # E3: "above" is now read as a surface cue, but a pistil has no reviewed surface class.
    assert decisions[0]["reason"] == "gate_scope"
    assert decisions[0]["gate_reasons"].startswith("surface_scope_unmapped_bearer:")


def test_restricting_member_blocks(recoverer: Recoverer) -> None:
    text = "Pistil glabrous, except for the style base."
    delta, decisions = recover_record(_record(text, "glabrous"), recoverer)
    assert delta is None
    assert decisions[0]["reason"] == "restricting_member_after_value"


def test_record_heading_with_value_only_prefix(recoverer: Recoverer) -> None:
    text = "Glabre, long de 2 mm."
    record = _record(text, "long de 2 mm", language="fr", organ="pistil", family="")
    delta, decisions = recover_record(record, recoverer)
    assert _recovered(delta) == [("PO_0009062", "PATO_0000122", "long de 2 mm")]
    assertion = delta["add_assertions"][0]
    assert "bearer_basis:record_organ_field_nonverbatim" in assertion["mapping_provenance"]
    assert assertion["bearer_start"] is None


def test_adjacent_trichome_orientation_but_not_pilosity(recoverer: Recoverer) -> None:
    text = "Ovaire globuleux, à poils courts dressés; style glabre."
    delta, _ = recover_record(_record(text, "dressés", language="fr"), recoverer)
    assert _recovered(delta) == [("PO_0000282", "PATO_0000622", "dressés")]
    text = "Leaves with hairs pubescent."
    delta, _ = recover_record(_record(text, "pubescent"), recoverer)
    assert delta is None


def test_family_restricted_head_needs_family(recoverer: Recoverer) -> None:
    text = "Pods oblong, 3 cm long."
    delta, decisions = recover_record(
        _record(text, "3 cm long", family="Rosaceae"), recoverer
    )
    assert delta is None and decisions[0]["head_id"] != "pod_en"
    _delta, decisions = recover_record(
        _record(text, "3 cm long", family="LEGUMINOSAE"), recoverer
    )
    # The legume head is selected (case-insensitive family). Whether the legume-fruit length
    # pair is then emitted or held depends on config/valid_combinations.tsv (curator-approved
    # 2026-09-18), so only the family-restricted head selection is asserted here.
    assert decisions[0]["head_id"] == "pod_en"


def test_member_initial_french_noun_like_word_blocks_carry_over(recoverer: Recoverer) -> None:
    text = "Pétales 5, oblongs; épichile de 4 mm de long, lisse."
    delta, _ = recover_record(_record(text, "lisse", language="fr"), recoverer)
    assert delta is None


def test_positional_substantive_blocks(recoverer: Recoverer) -> None:
    text = "Sporophylls dimorphic; dorsal green, 2.5 mm long."
    delta, _ = recover_record(_record(text, "2.5 mm long", family=""), recoverer)
    assert delta is None


def test_semicolon_carry_over(recoverer: Recoverer) -> None:
    text = "Feuilles alternes, simples; assez coriaces, discolores."
    delta, decisions = recover_record(_record(text, "coriaces", language="fr"), recoverer)
    assert _recovered(delta) and _recovered(delta)[0][0] == "PO_0009025"
    assertion = delta["add_assertions"][0]
    assert assertion["source_text"].startswith("Feuilles")
    assert decisions[0]["rule"] == "semicolon_carry_over"


def test_delta_applies_and_validates(recoverer: Recoverer, tmp_path: Path) -> None:
    text = "Capitula discoid; involucre cylindrical, 7–9 mm long, 3 mm in diameter."
    record = _record(text, "7–9 mm long")
    delta, _ = recover_record(record, recoverer)
    patched = apply_record_delta(record, delta)
    assert patched["unresolved_spans"] == []
    statement_ids = {row["statement_id"] for row in patched["source_statements"]}
    assert all(row["source_statement_id"] in statement_ids for row in patched["assertions"])
    path = tmp_path / "patched.jsonl"
    path.write_text(json.dumps(patched, ensure_ascii=False) + "\n", encoding="utf-8")
    report = validate_jsonl(
        path,
        stage="gated",
        po_lexicon=ROOT / "config/po_lexicon.tsv",
        pato_lexicon=ROOT / "config/pato_lexicon.tsv",
        flopo_registry=ROOT / "config/flopo_id_registry.tsv",
        strict_source_statements=True,
    )
    assert report["errors"] == 0, report["error_examples"]


def test_apply_rejects_unknown_unresolved_target(recoverer: Recoverer) -> None:
    text = "Capitula discoid; involucre cylindrical, 7–9 mm long."
    record = _record(text, "7–9 mm long")
    delta, _ = recover_record(record, recoverer)
    delta["remove_unresolved"][0]["start"] += 1
    with pytest.raises(ValueError):
        apply_record_delta(record, delta)


def test_reviewed_local_bearer_phrase_is_a_head(recoverer: Recoverer) -> None:
    """Exact aliases from config/reviewed_local_bearers.tsv are clause heads; the gate decides."""

    for text, po_id in (
        ("Upper leaf surface 3 mm long.", "PO_0000050"),
        ("Pappus bristles 3 mm long.", "PO_0025394"),
        ("Calyx lobes 3 mm long.", "FLOPO_0986005"),
    ):
        _delta, decisions = recover_record(_record(text, "3 mm long"), recoverer)
        assert decisions[0]["po_id"] == po_id
        assert decisions[0]["head_id"].startswith("reviewed_local_bearer:en:")


def test_contextual_reviewed_bearers_are_not_heads(recoverer: Recoverer) -> None:
    heads = {entry.head_id for entry in recoverer.heads}
    assert not any(head.endswith((":scale", ":bristles", ":upper surface")) for head in heads)
    assert any(head.endswith(":leaflet lamina") for head in heads)


def test_leaflet_lamina_is_not_borne_on_leaf_lamina(recoverer: Recoverer) -> None:
    """``folioles …; limbe coriace`` is the leaflet lamina (FLOPO_0986002), not PO leaf lamina."""

    text = "Folioles 5, à pétiolule de 5 mm de long; limbe coriace, de 5 cm de long."
    record = _record(text, "coriace", language="fr", organ="feuilles", family="Sapindaceae")
    delta, _decisions = recover_record(record, recoverer)
    borne = [row[0] for row in _recovered(delta)]
    assert "PO_0020039" not in borne
    assert borne in ([], ["FLOPO_0986002"])
    control = _record("Limbe coriace, de 5 cm de long.", "coriace", language="fr",
                      organ="feuilles", family="Sapindaceae")
    delta, _decisions = recover_record(control, recoverer)
    assert [row[0] for row in _recovered(delta)] == ["PO_0020039"]


@pytest.mark.parametrize(
    ("text", "surface", "language", "reason"),
    [
        ("Pod practically sessile, 5 mm long.", "sessile", "en", "non_entailing_hedge_before_value"),
        ("Rachis foliaire atteignant 85 cm de longueur.", "85 cm de longueur", "fr",
         "bound_cue_before_value"),
        ("Ray florets 11–15, to 10 mm long.", "10 mm long", "en", "bound_cue_before_value"),
        ("Blades obtuse, firmly chartaceous to thinly coriaceous, nerves 5 pairs.", "coriaceous",
         "en", "range_or_alternative_before_value"),
    ],
)
def test_hedge_or_bound_before_value_blocks(recoverer: Recoverer, text, surface, language, reason):
    delta, decisions = recover_record(
        _record(text, surface, language=language, family="Fabaceae"), recoverer
    )
    assert delta is None
    assert decisions[0]["reason"] == reason


# ------------------------------------------------------------------ E3 surface/sub-part scope
def _scoped(delta: dict | None) -> list[tuple[str, str, str, str, str]]:
    if delta is None:
        return []
    return [
        (
            row["po_id"],
            row["pato_id"],
            row["bearer_scope"]["outer_bearer"],
            row["bearer_scope"]["mode"],
            row["bearer_scope"]["scope_text"],
        )
        for row in delta["add_assertions"]
        if row.get("bearer_scope")
    ]


def test_surface_cues_substitute_the_epidermis_bearer(recoverer: Recoverer) -> None:
    text = "Leaves ovate, 3 cm long, glabrous above, pubescent beneath."
    delta, _ = recover_record(_record(text, "glabrous", "pubescent"), recoverer)
    assert _scoped(delta) == [
        ("PO_0000050", "PATO_0000453", "PO_0009025", "substituted_bearer", "above"),
        ("PO_0000049", "PATO_0001320", "PO_0009025", "substituted_bearer", "beneath"),
    ]
    first = delta["add_assertions"][0]
    assert first["source_text"] == "glabrous above"
    assert "bearer_scope:E3:surface:adaxial->adaxial:PO_0009025->PO_0000050" in first[
        "mapping_provenance"
    ]


def test_french_surface_phrase_and_masked_connector(recoverer: Recoverer) -> None:
    text = "Feuilles ovales, glabres en dessus, pubescentes à la face inférieure."
    delta, _ = recover_record(
        _record(text, "glabres", "pubescentes", language="fr"), recoverer
    )
    assert [row[0] for row in _scoped(delta)] == ["PO_0000050", "PO_0000049"]
    assert _scoped(delta)[1][4] == "à la face inférieure"


def test_outside_maps_to_abaxial_only_for_perianth_members(recoverer: Recoverer) -> None:
    delta, _ = recover_record(_record("Sepals ovate, pubescent outside.", "pubescent"), recoverer)
    assert _scoped(delta) == [
        ("PO_0006054", "PATO_0001320", "PO_0009031", "substituted_bearer", "outside")
    ]
    delta, decisions = recover_record(
        _record("Stems pubescent beneath.", "pubescent"), recoverer
    )
    assert delta is None
    assert decisions[0]["reason"] == "gate_scope"


def test_region_without_po_part_uses_pinned_bspo(recoverer: Recoverer) -> None:
    delta, _ = recover_record(_record("Ovary ovoid, pubescent at the apex.", "pubescent"), recoverer)
    assertion = delta["add_assertions"][0]
    assert assertion["po_id"] == "PO_0009072"
    assert assertion["pato_id"] == "PATO_0001320"  # hairs at the apex: the ovary bears hairs
    part = assertion["part_restrictions"][0]
    assert (part["filler_class"], part["qualities"], part["part_text"]) == (
        "BSPO_0000073",
        ["PATO_0001320"],
        "at the apex",
    )
    assert assertion["bearer_scope"]["mode"] == "part_restriction"


def test_non_entailed_region_value_uses_family_attribute(recoverer: Recoverer) -> None:
    delta, _ = recover_record(_record("Phyllaries 8, green at base.", "green"), recoverer)
    assertion = delta["add_assertions"][0]
    assert assertion["pato_id"] == "PATO_0000014"
    assert assertion["part_restrictions"][0]["qualities"] == ["PATO_0000320"]


def test_region_with_po_part_substitutes(recoverer: Recoverer) -> None:
    delta, _ = recover_record(
        _record("Leaves ovate, 4 cm long, acuminate at the apex.", "acuminate"), recoverer
    )
    assert _scoped(delta)[0][:4] == (
        "PO_0020137",
        "PATO_0002228",
        "PO_0009025",
        "substituted_bearer",
    )


def test_surface_subject_clause_carries_lamina(recoverer: Recoverer) -> None:
    text = "Limbe elliptique, arrondi à la base, de 3 cm de long; face supérieure glabre."
    delta, decisions = recover_record(_record(text, "glabre", language="fr"), recoverer)
    assert _scoped(delta) == [
        ("PO_0000050", "PATO_0000453", "PO_0020039", "substituted_bearer", "face supérieure")
    ]
    assert decisions[0]["rule"] == "surface_subject_carry_over"
    subset = "Feuilles de l'extrémité des rameaux plus petites; face supérieure glabre."
    delta, _ = recover_record(_record(subset, "glabre", language="fr"), recoverer)
    assert delta is None


def test_hedged_alternative_after_scoped_value_blocks(recoverer: Recoverer) -> None:
    text = "Limbe elliptique, glabre en dessus, plus rarement pubescent."
    delta, decisions = recover_record(_record(text, "glabre", language="fr"), recoverer)
    assert delta is None
    assert decisions[0]["reason"] == "scoped_value_with_hedged_alternative_after"


def test_scoped_delta_validates(recoverer: Recoverer, tmp_path: Path) -> None:
    text = "Leaves ovate, glabrous above, pubescent beneath. Ovary ovoid, pubescent at the apex."
    record = _record(text, "glabrous", "pubescent", "pubescent")
    record["unresolved_spans"][2] = _span(text, "en", "pubescent", occurrence=1)
    delta, _ = recover_record(record, recoverer)
    assert len(delta["add_assertions"]) == 3
    path = tmp_path / "patched.jsonl"
    path.write_text(json.dumps(apply_record_delta(record, delta)) + "\n", encoding="utf-8")
    report = validate_jsonl(path, stage="gated", strict_source_statements=True)
    assert report["ok"], report["error_examples"]
