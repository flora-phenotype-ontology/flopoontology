"""Surface-scope re-admission (schema extension E3)."""

from __future__ import annotations

import json

import pytest

from flopo2.verify.recover_surface_scope import (
    attach_surface_cue,
    build,
    clause_subject_ok,
    contradicting_same_side,
    rebear,
)

LABELS = {"PATO_0000453": "glabrous", "PATO_0001320": "pubescent", "PATO_0000320": "green"}


def _span(text: str, value: str, occurrence: int = 0) -> tuple[int, int]:
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(value, start + 1)
    return start, start + len(value)


def _record(text: str) -> dict:
    return {
        "source": "flora-test",
        "source_id": "t.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplar",
        "organ": "feuilles",
        "char_start": 0,
        "char_end": len(text),
        "language": "fr",
        "text": text,
        "source_statements": [],
        "assertions": [],
        "unresolved_spans": [],
    }


def _original(text: str, value: str, po_id: str, pato_id: str) -> dict:
    start, end = _span(text, value)
    return {
        "po_id": po_id,
        "pato_id": pato_id,
        "value_operator": "atomic",
        "value_terms": [],
        "source_text": text[start:end],
        "source_start": start,
        "source_end": end,
        "raw_entity_text": "Limbe",
        "bearer_start": 0,
        "bearer_end": 5,
        "negated": False,
        "extractor": "deterministic_baseline",
        "mapping_provenance": [],
        "composition": {"status": "accept"},
    }


@pytest.mark.parametrize(
    ("text", "value", "expected"),
    [
        ("Limbe glabre en dessus, pubescent en dessous.", "glabre", "adaxial"),
        ("Limbe glabre en dessus, pubescent en dessous.", "pubescent", "abaxial"),
        ("Leaves dark green above, paler beneath.", "green", "adaxial"),
        ("Limbe glabre sur les deux faces.", "glabre", "both"),
        ("Leaves hairy on both surfaces.", "hairy", "both"),
        ("Leaves glabrous except sparsely hairy above.", "glabrous", "temporal_exception_or_region_in_member"),
        ("Limbe d'abord pubescent dessous puis glabre.", "glabre", "temporal_exception_or_region_in_member"),
        ("Bractées vertes en bas et grisâtres au-dessus.", "vertes", "temporal_exception_or_region_in_member"),
        ("Limbe, nervures pubescentes en dessous.", "pubescentes", "other_lamina_part_in_member"),
        ("Leaves dark green and paler beneath.", "green", "comparative_between_value_and_cue"),
        ("Limbe glabre parfois scabre dessus.", "glabre", "hedge_between_value_and_cue"),
    ],
)
def test_cue_attachment(text, value, expected):
    start, end = _span(text, value)
    result = attach_surface_cue(text, start, end)
    side = result[0] if isinstance(result, tuple) else result
    assert side == expected


def test_clause_subject_must_be_the_outer_organ():
    text = "Leaf-rhachis slightly pubescent above; Leaves: rhachis densely pubescent above."
    assert not clause_subject_ok(text, text.index("slightly"), "PO_0009025")
    assert not clause_subject_ok(text, text.index("densely"), "PO_0009025")
    text = "Pétioles canaliculés et pubescents dessus. Limbe glabre dessus."
    assert not clause_subject_ok(text, text.index("pubescents"), "PO_0009025")
    assert clause_subject_ok(text, text.index("glabre"), "PO_0020039")
    text = "Sépales d'env. 2 mm, à 5 lobes pubescents dessus."
    assert not clause_subject_ok(text, text.index("pubescents"), "PO_0009031")


def test_contradicting_same_side_members_block():
    text = "Feuilles brun foncé et glabres en dessous, velues-cotonneuses argentées en dessous."
    start, end = _span(text, "glabres")
    cue = attach_surface_cue(text, start, end)
    assert contradicting_same_side(text, start, end, cue, "pilosity")
    text = "Limbe glabre dessus, pubescent dessous, marron vert dessus, vert grisâtre dessous."
    start, end = _span(text, "glabre")
    cue = attach_surface_cue(text, start, end)
    assert not contradicting_same_side(text, start, end, cue, "pilosity")


def test_rebear_substitutes_surface_bearer_and_records_scope():
    text = "Limbe coriace, glabre en dessus, pubescent en dessous."
    record = _record(text)
    original = _original(text, "glabre", "PO_0020039", "PATO_0000453")
    span = {"start": original["source_start"], "end": original["source_end"],
            "reason": "missing_or_unsupported_bearer", "surface_form": "glabre"}
    results, reason = rebear(record, original, span, "surface_restriction_correction", "", LABELS)
    assert reason == ""
    assertion, statement = results[0]
    assert assertion["po_id"] == "PO_0000050"
    scope = assertion["bearer_scope"]
    assert (scope["outer_bearer"], scope["mode"], scope["scope_text"]) == (
        "PO_0020039", "substituted_bearer", "en dessus",
    )
    assert text[scope["scope_start"] : scope["scope_end"]] == "en dessus"
    assert assertion["source_text"] == "glabre en dessus"
    assert statement["start"] == 0 and statement["end"] >= scope["scope_end"]
    assert "surface_scope:E3" in assertion["mapping_provenance"]
    # Leaflet lamina values are borne on the leaf's adaxial epidermis.
    results, _ = rebear(
        record, original, span, "leaflet_bearer_correction", "FLOPO_0986002", LABELS
    )
    assertion, _statement = results[0]
    assert assertion["po_id"] == "PO_0006018"
    assert assertion["bearer_scope"]["outer_bearer"] == "FLOPO_0986002"


def test_rebear_rejects_non_surface_values_and_unreviewed_organs():
    text = "Limbe ovale en dessus."
    record = _record(text)
    original = _original(text, "ovale", "PO_0020039", "PATO_0000953")
    span = {"start": 6, "end": 11, "reason": "missing_or_unsupported_bearer", "surface_form": "ovale"}
    assert rebear(record, original, span, "x", "", LABELS)[1] == "not_a_surface_value"
    text = "Stipules pubescentes en dessous."
    record = _record(text)
    original = _original(text, "pubescentes", "PO_0020041", "PATO_0001320")
    span = {"start": 9, "end": 20, "reason": "missing_or_unsupported_bearer", "surface_form": "pubescentes"}
    assert rebear(record, original, span, "x", "", LABELS)[1].startswith("no_reviewed_scope")


def test_rebear_both_surfaces_yields_two_side_scoped_assertions():
    """Curator decision 2026-09-18 (c): "both surfaces" cues re-bear as two assertions."""

    text = "Limbe coriace, pubescent sur les deux faces."
    record = _record(text)
    original = _original(text, "pubescent", "PO_0020039", "PATO_0001320")
    span = {"start": original["source_start"], "end": original["source_end"],
            "reason": "missing_or_unsupported_bearer", "surface_form": "pubescent"}
    results, reason = rebear(record, original, span, "surface_restriction_correction", "", LABELS)
    assert reason == ""
    assert len(results) == 2
    po_ids = {assertion["po_id"] for assertion, _statement in results}
    assert po_ids == {"PO_0000050", "PO_0000049"}
    scopes = {assertion["po_id"]: assertion["bearer_scope"] for assertion, _statement in results}
    adaxial = scopes["PO_0000050"]
    abaxial = scopes["PO_0000049"]
    assert adaxial["outer_bearer"] == abaxial["outer_bearer"] == "PO_0020039"
    # Both assertions share the same "both surfaces" cue span but are two distinct assertions.
    assert adaxial["scope_text"] == abaxial["scope_text"] == "deux faces"
    assert adaxial["scope_start"] == abaxial["scope_start"]
    assert adaxial["scope_end"] == abaxial["scope_end"]
    for assertion, _statement in results:
        assert "surface_scope:both_surfaces_split" in assertion["mapping_provenance"]
    # English cue.
    text = "Leaves hairy on both surfaces."
    record = _record(text)
    original = _original(text, "hairy", "PO_0020039", "PATO_0001320")
    span = {"start": original["source_start"], "end": original["source_end"],
            "reason": "missing_or_unsupported_bearer", "surface_form": "hairy"}
    results, reason = rebear(record, original, span, "surface_restriction_correction", "", LABELS)
    assert reason == ""
    assert len(results) == 2
    assert {assertion["po_id"] for assertion, _statement in results} == {"PO_0000050", "PO_0000049"}


def test_rebear_both_surfaces_no_reviewed_scope_yields_no_results():
    text = "Stipules pubescentes sur les deux faces."
    record = _record(text)
    original = _original(text, "pubescentes", "PO_0020041", "PATO_0001320")
    span = {"start": original["source_start"], "end": original["source_end"],
            "reason": "missing_or_unsupported_bearer", "surface_form": "pubescentes"}
    results, reason = rebear(record, original, span, "x", "", LABELS)
    assert results == []
    assert reason.startswith("no_reviewed_scope")


def test_build_writes_correction_delta(tmp_path):
    text = "Limbe coriace, glabre en dessus, pubescent en dessous."
    record = _record(text)
    original = _original(text, "glabre", "PO_0020039", "PATO_0000453")
    original["source_statement_id"] = "s0"
    record["assertions"] = [original]
    record["source_statements"] = [
        {"statement_id": "s0", "verbatim_text": "glabre", "start": 15, "end": 21}
    ]
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    key = {name: record[name] for name in (
        "source", "source_id", "source_segment_index", "taxon", "organ", "char_start", "char_end")}
    removal = {name: original.get(name) for name in (
        "source_statement_id", "po_id", "pato_id", "source_start", "source_end")}
    span = {"start": 15, "end": 21, "reason": "missing_or_unsupported_bearer", "surface_form": "glabre"}
    candidates = {tuple(key.values()): {"key": key, "items": [("surface_restriction_correction", "", removal, span)]}}
    report = build(base, tmp_path / "out", sample_size=5, candidates=candidates)
    assert report["counts"]["readmitted"] == 1
    line = json.loads((tmp_path / "out" / "surface-scope-delta.jsonl").read_text(encoding="utf-8"))
    assert line["remove_unresolved"] == [span]
    added = line["add_assertions"][0]
    assert added["po_id"] == "PO_0000050"
    assert added["gate"]["status"] in {"accepted", "review"}
    assert added["phenotype_class_iri"].startswith("https://w3id.org/flopo/annotation-class/FAC_")
    assert line["add_source_statements"][0]["statement_id"] == added["source_statement_id"]


def test_build_writes_two_assertions_for_both_surfaces(tmp_path):
    """Curator decision 2026-09-18 (c): one held "both surfaces" span clears to two assertions."""

    text = "Limbe coriace, pubescent sur les deux faces."
    record = _record(text)
    original = _original(text, "pubescent", "PO_0020039", "PATO_0001320")
    original["source_statement_id"] = "s0"
    record["assertions"] = [original]
    start, end = original["source_start"], original["source_end"]
    record["source_statements"] = [
        {"statement_id": "s0", "verbatim_text": text[start:end], "start": start, "end": end}
    ]
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    key = {name: record[name] for name in (
        "source", "source_id", "source_segment_index", "taxon", "organ", "char_start", "char_end")}
    removal = {name: original.get(name) for name in (
        "source_statement_id", "po_id", "pato_id", "source_start", "source_end")}
    span = {"start": start, "end": end, "reason": "missing_or_unsupported_bearer", "surface_form": "pubescent"}
    candidates = {tuple(key.values()): {"key": key, "items": [("surface_restriction_correction", "", removal, span)]}}
    report = build(base, tmp_path / "out", sample_size=5, candidates=candidates)
    assert report["counts"]["readmitted"] == 2
    line = json.loads((tmp_path / "out" / "surface-scope-delta.jsonl").read_text(encoding="utf-8"))
    # One span cleared, even though it produced two assertions.
    assert line["remove_unresolved"] == [span]
    assert len(line["add_assertions"]) == 2
    assert {a["po_id"] for a in line["add_assertions"]} == {"PO_0000050", "PO_0000049"}
