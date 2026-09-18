"""Tests for the clause-scope developmental-stage recovery (claude campaign 2026-09-18).

The positive cases lock the two routes (S1 stage-bound value, S2 stage provably out of scope);
the negative cases lock the error classes found during the precision review: alternative value
series, transitions, same-family contrast, compound/modified shapes, comparatives, sub-regional
scope, and French agreement mismatches.  Every recovery must be gate-accepted and source-bound.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pytest

from flopo2.extract.baseline import extract_segment_with_unresolved
from flopo2.verify import recover_claude_developmental_stage as mod

REASON = mod.TARGET_REASON


@lru_cache(maxsize=1)
def _resources() -> mod.Resources:
    return mod.load_resources()


def _record(text: str, *, organ: str = "description", language: str = "en") -> dict:
    assertions, unresolved = extract_segment_with_unresolved(
        {"text": text, "organ": organ, "language": language}
    )
    return {
        "source": "flora-test",
        "source_id": "one.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplar",
        "organ": organ,
        "language": language,
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "assertions": assertions,
        "source_statements": [],
        "unresolved_spans": unresolved,
    }


def _run(text: str, **kwargs) -> tuple[dict | None, list[dict]]:
    return mod.recover_record(_record(text, **kwargs), _resources())


def _recovered(audit: list[dict]) -> dict[str, dict]:
    return {row["surface_form"]: row for row in audit if row["outcome"] == "recovered"}


def _assertion(delta: dict, surface: str) -> dict:
    return next(a for a in delta["add_assertions"] if a["raw_quality_text"] == surface)


def test_input_spans_are_developmental_residuals() -> None:
    record = _record("Leaves elliptic, 5–12 cm long, pubescent when young")
    assert any(span["reason"] == REASON for span in record["unresolved_spans"])


def test_s2_value_out_of_scope_of_postposed_stage() -> None:
    delta, audit = _run("Leaves elliptic, 5–12 cm long, pubescent when young")
    recovered = _recovered(audit)
    assert recovered["elliptic"]["route"] == "S2"
    assertion = _assertion(delta, "elliptic")
    assert assertion["po_id"] == "PO_0009025"
    assert assertion["pato_id"] == "PATO_0000947"
    assert assertion["bearer_context_qualities"] == []
    assert assertion["normalization_status"] == "context_override"
    assert assertion["extractor"] == mod.EXTRACTOR
    assert assertion["gate"]["status"] == "accepted"
    assert any(p.startswith("dev_stage_scope_route:S2") for p in assertion["mapping_provenance"])


def test_s1_own_member_predicate_adds_stage_quality() -> None:
    delta, audit = _run("Leaves elliptic, 5–12 cm long, pubescent when young")
    assert _recovered(audit)["pubescent"]["route"] == "S1"
    assertion = _assertion(delta, "pubescent")
    assert assertion["bearer_context_qualities"] == ["PATO_0000309"]
    assert assertion["normalization_status"] == "compositional"
    assert "when young" in assertion["source_text"]


def test_s1_subject_adjective_binds_every_plain_member() -> None:
    delta, audit = _run("Young branches ridged, glabrous")
    recovered = _recovered(audit)
    assert set(recovered) == {"ridged", "glabrous"}
    for surface in recovered:
        assert _assertion(delta, surface)["bearer_context_qualities"] == ["PATO_0000309"]
        assert _assertion(delta, surface)["po_id"] == "PO_0025073"


def test_french_predicate_stage_and_subject() -> None:
    delta, audit = _run("rameaux brunâtres, lenticellés, pubescents à l'état jeune", language="fr")
    row = _recovered(audit)["pubescents"]
    assert row["stage"] == "young"
    assert _assertion(delta, "pubescents")["po_id"] == "PO_0025073"


def test_same_family_value_contrasting_with_stage_is_retained() -> None:
    _delta, audit = _run("Fruit green, globose, red at maturity")
    recovered = _recovered(audit)
    assert "green" not in recovered  # implicitly the immature colour
    assert recovered["globose"]["route"] == "S2"
    assert recovered["red"]["stage"] == "mature"


def test_transition_source_is_retained() -> None:
    _delta, audit = _run("Twigs terete, pubescent, becoming glabrous, lenticellate when old")
    assert "pubescent" not in _recovered(audit)


@pytest.mark.parametrize(
    "text, surface, language",
    [
        (
            "Leaves chartaceous, elliptic, subobovate, or oblanceolate, pubescent when young",
            "elliptic",
            "en",
        ),
        ("limbe ovale, elliptique, oblong, glabre à l'état adulte", "elliptique", "fr"),
        ("Fruit ellipsoid, glabrous, sometimes pubescent, black at maturity", "glabrous", "en"),
        ("receptacle (sub)globose, 1 cm diam. when dry", "globose", "en"),
        ("réceptacle souvent globuleux ± déprimé, ridé sur le sec", "globuleux", "fr"),
        ("blade elliptic oblong, 6-19 cm long, pubescent when young", "elliptic", "en"),
        ("Feuilles un peu plus coriaces, vertes à sec", "coriaces", "fr"),
        (
            "bracteoles pale brown when dry, narrowly triangular, pubescent outside",
            "pubescent",
            "en",
        ),
        ("Juvenile leaves linear, adult lanceolate, 5–15 cm long", "lanceolate", "en"),
    ],
)
def test_reviewed_error_classes_are_retained(text: str, surface: str, language: str) -> None:
    _delta, audit = _run(text, language=language)
    assert surface not in _recovered(audit)


def test_whole_plant_diameter_is_not_asserted() -> None:
    _delta, audit = _run(
        "Arbre de 3 à 20 m, atteignant 30 cm de diamètre, à écorce lisse, "
        "les jeunes rameaux pubescents",
        organ="habit",
        language="fr",
    )
    assert not any(
        row["po_id"] == "PO_0000003" and "diam" in row["surface_form"]
        for row in _recovered(audit).values()
    )


def test_french_number_agreement_blocks_subject_shift() -> None:
    _delta, audit = _run(
        "rameaux anguleux, à écorce abondamment lenticellée, grisâtre, glabres même à l'état jeune",
        language="fr",
    )
    assert not any(row["po_id"] == "PO_0004518" for row in _recovered(audit).values())


def test_delta_references_statements_and_applies(tmp_path: Path) -> None:
    record = _record("Leaves elliptic, 5–12 cm long, pubescent when young")
    delta, _audit = mod.recover_record(record, _resources())
    assert delta is not None
    assert set(delta["key"]) == {
        "source",
        "source_id",
        "source_segment_index",
        "taxon",
        "organ",
        "char_start",
        "char_end",
    }
    statement_ids = {s["statement_id"] for s in delta["add_source_statements"]}
    for assertion in delta["add_assertions"]:
        assert assertion["source_statement_id"] in statement_ids
        statement = next(
            s
            for s in delta["add_source_statements"]
            if s["statement_id"] == assertion["source_statement_id"]
        )
        assert (
            statement["start"] <= assertion["source_start"]
            and assertion["source_end"] <= statement["end"]
        )
        text = record["text"]
        assert text[assertion["source_start"] : assertion["source_end"]] == assertion["source_text"]
    corpus = tmp_path / "in.jsonl"
    corpus.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    delta_path = tmp_path / "delta.jsonl"
    delta_path.write_text(json.dumps(delta, ensure_ascii=False) + "\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    assert mod.apply_delta(corpus, delta_path, out) == {"segments_patched": 1}
    patched = json.loads(out.read_text(encoding="utf-8"))
    removed = {(r["start"], r["end"]) for r in delta["remove_unresolved"]}
    assert not any((s["start"], s["end"]) in removed for s in patched["unresolved_spans"])
    assert len(patched["assertions"]) == len(record["assertions"]) + len(delta["add_assertions"])
    with pytest.raises(ValueError):
        mod.apply_delta(corpus, delta_path, corpus)


def test_apply_rejects_unknown_statement() -> None:
    record = _record("Leaves elliptic, 5–12 cm long, pubescent when young")
    delta, _audit = mod.recover_record(record, _resources())
    assert delta is not None
    broken = {**delta, "add_source_statements": []}
    with pytest.raises(ValueError):
        mod.apply_delta_record(record, broken)


# --- v3: E3 positional scope (surface, region, indumentum) -------------------------------------


def test_surface_cue_substitutes_po_epidermis_with_bearer_scope() -> None:
    text = "Limbe glabre dessus, finement velu dessous, brun à sec, elliptique."
    delta, audit = _run(text, language="fr", organ="feuilles")
    assertion = _assertion(delta, "glabre")
    assert assertion["po_id"] == "PO_0000050"
    scope = assertion["bearer_scope"]
    assert scope["outer_bearer"] == "PO_0020039"
    assert scope["mode"] == "substituted_bearer"
    assert text[scope["scope_start"] : scope["scope_end"]] == scope["scope_text"] == "dessus"
    assert "bearer_scope:E3" in assertion["mapping_provenance"]
    assert assertion["phenotype_class_iri"].startswith("https://w3id.org/flopo/annotation-class/")


def test_region_cue_uses_po_region_class_when_po_places_it() -> None:
    delta, _ = _run("Leaves ovate, 2.5–9 cm. long, acuminate at the apex, pubescent when young.")
    assertion = _assertion(delta, "acuminate")
    assert assertion["po_id"] == "PO_0020137"
    assert assertion["bearer_scope"]["outer_bearer"] == "PO_0009025"
    assert not assertion.get("part_restrictions")


def test_region_cue_falls_back_to_pinned_bspo_part_on_lamina() -> None:
    text = (
        "Feuilles opposées; limbe ovale-elliptique, atténué-cunéé à la base, acuminé au sommet, "
        "de 12–20 cm de long, pubescent à l'état jeune."
    )
    delta, _ = _run(text, language="fr", organ="feuilles")
    assertion = _assertion(delta, "acuminé")
    assert assertion["po_id"] == "PO_0020039"
    assert assertion["pato_id"] == "PATO_0000052"  # shape attribute: the lamina is not acuminate
    part = assertion["part_restrictions"][0]
    assert part["filler_class"] == "BSPO_0000073"
    assert part["qualities"] == ["PATO_0002228"]
    assert text[part["part_start"] : part["part_end"]] == part["part_text"] == "au sommet"
    assert assertion["bearer_scope"]["mode"] == "part_restriction"


def test_leaflet_context_lamina_region_is_borne_by_leaflet_lamina() -> None:
    text = (
        "Feuilles composées; folioles à pétiolule de 4–20 mm de long; limbes ovales à obovales, "
        "acuminés au sommet, pubescents à l'état jeune."
    )
    delta, _ = _run(text, language="fr", organ="feuilles")
    assertion = _assertion(delta, "acuminés")
    assert assertion["po_id"] == "FLOPO_0986002"
    assert assertion["part_restrictions"][0]["filler_class"] == "BSPO_0000073"


def test_indumentum_colour_is_a_trichome_quality() -> None:
    delta, _ = _run("Tree up to 16 m high; young branchlets densely brown hairy.")
    assertion = _assertion(delta, "brown")
    assert assertion["pato_id"] == "PATO_0000454"  # the branchlets are hairy, not brown
    part = assertion["part_restrictions"][0]
    assert (part["filler_class"], part["qualities"]) == ("PO_0000282", ["PATO_0000952"])
    assert part["part_text"] == "hairy"
    assert assertion["bearer_context_qualities"] == ["PATO_0000309"]


def test_dried_colour_on_other_surface_is_not_recovered() -> None:
    text = (
        "Limbe subcoriace [à coriace], elliptique, de 7-14 x 3-5 cm, grisâtre foncé dessus à sec, "
        "brun dessous; base obtuse à arrondie."
    )
    _, audit = _run(text, language="fr", organ="feuilles")
    assert "brun" not in _recovered(audit)


def test_bare_side_cue_is_not_a_surface_on_bracts() -> None:
    text = "bracts green below."
    cue = mod.ScopeCue("surface", "abaxial", 13, 18, 13, 18)
    assertion = {
        "po_id": "PO_0009055",
        "pato_id": "PATO_0000320",
        "source_start": 0,
        "source_end": 12,
        "mapping_provenance": [],
    }
    scoped, reason = mod._apply_scope({"text": text}, assertion, cue)
    assert scoped is None and reason.startswith("bare_side_cue_on_non_leaf")
