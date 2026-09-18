"""Operand enrichment for stage assertions whose degree cue the old enum could not hold (E2)."""

from __future__ import annotations

import json

from flopo2.owl.annotation_class import annotation_class_iri
from flopo2.verify.enrich_operand_qualifiers import enrich, run


def _assertion(text: str, cue: str, **extra) -> dict:
    start = text.index(cue)
    source_start = min(start, extra.pop("source_start", start))
    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0001320",
        "value_operator": "atomic",
        "value_terms": [],
        "source_start": source_start,
        "source_end": len(text),
        "source_text": text[source_start:],
        "modality_text": cue,
        "modality_start": start,
        "modality_end": start + len(cue),
        "source_statement_id": "s",
    }
    assertion.update(extra)
    return assertion


def test_density_degree_becomes_operand_and_keeps_fac():
    text = "Leaves ± densely pubescent"
    assertion = _assertion(text, "± densely", value_qualifier="approximately", source_start=7)
    operands, reason = enrich(assertion, text)
    assert reason == ""
    assert operands == [
        {
            "operand_index": 0, "value": "PATO_0001320", "text": "densely pubescent",
            "start": 9, "end": 26, "degree_qualifier": "densely", "value_qualifier": "exact",
            "frequency_qualifier": "unspecified", "qualifier_text": "densely",
            "qualifier_start": 9, "qualifier_end": 16,
        }
    ]
    assert annotation_class_iri(assertion) == annotation_class_iri({**assertion, "value_operands": operands})


def test_intensity_stays_in_cue_and_unions_are_split():
    text = "very sparsely pubescent or glabrous"
    assertion = _assertion(
        text, "very sparsely", value_operator="one_of", pato_id="PATO_0000066",
        value_terms=["PATO_0001320", "PATO_0000453"], degree_qualifier="very",
    )
    operands, reason = enrich(assertion, text)
    assert reason == ""
    assert [op["text"] for op in operands] == ["very sparsely pubescent", "glabrous"]
    assert operands[0]["qualifier_text"] == "very sparsely"
    assert operands[0]["degree_qualifier"] == "sparsely"
    assert operands[1]["degree_qualifier"] == "unmodified"


def test_density_on_colour_and_unverified_heads_are_not_enriched():
    text = "± densely brown"
    assertion = _assertion(text, "± densely", pato_id="PATO_0000952")
    assert enrich(assertion, text) == (None, "degree_density_on_colour_value")
    text = "densely tomentose"
    assertion = _assertion(text, "densely")  # value says pubescent, text says tomentose
    assert enrich(assertion, text) == (None, "operand_head_not_verified")


def test_run_writes_update_only_correction_and_skips_removed(tmp_path):
    text = "Leaves usually densely pubescent"
    assertion = _assertion(text, "usually densely", frequency_qualifier="usually", source_start=7)
    key = {"source": "s", "source_id": "1", "source_segment_index": 0, "taxon": "T",
           "organ": "leaf", "char_start": 0, "char_end": len(text)}
    base = tmp_path / "base.jsonl"
    base.write_text(json.dumps({**key, "text": text, "assertions": [assertion]}) + "\n")
    out = tmp_path / "delta.jsonl"
    report = run(base, out, [])
    line = json.loads(out.read_text())
    update = line["update_assertions"][0]
    assert update["set"]["value_operands"][0]["qualifier_text"] == "densely"
    assert report["counts"]["enriched"] == 1
    skip = tmp_path / "correction.jsonl"
    skip.write_text(json.dumps({"key": key, "remove_assertions": [
        {name: assertion[name] for name in ("source_statement_id", "po_id", "pato_id",
                                            "source_start", "source_end")}]}) + "\n")
    report = run(base, out, [skip])
    assert report["counts"]["skipped:removed_by_earlier_correction"] == 1
    assert out.read_text() == ""
