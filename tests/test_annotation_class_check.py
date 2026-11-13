"""The ELK check of annotation classes (flopo2.verify.annotation_class_check)."""

from __future__ import annotations

import json
import shutil

import pytest

from flopo2.verify import annotation_class_check as acc


def _assertion(pato: str, text: str) -> dict:
    from flopo2.owl.annotation_class import ensure_annotation_class_iri

    assertion = {"po_id": "PO_0025034", "pato_id": pato, "value_terms": [], "value_operator": "atomic",
                 "negated": False, "source_text": text, "gate": {"status": "accepted", "reasons": []},
                 "composition": {"entity_label": "leaf", "quality_label": text}}
    ensure_annotation_class_iri(assertion)
    return assertion


def test_demote_marks_accepted_assertions_once(tmp_path):
    good, bad = _assertion("PATO_0000453", "glabrous"), _assertion("PATO_0000389", "acute")
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"source_id": "x:1", "assertions": [good, bad]}) + "\n", encoding="utf-8")
    assert acc.demote(path, {bad["phenotype_class_iri"]}) == 1
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["assertions"][0]["gate"] == {"status": "accepted", "reasons": []}
    assert record["assertions"][1]["gate"] == {"status": "review", "reasons": [acc.REASON]}
    assert acc.demote(path, {bad["phenotype_class_iri"]}) == 0  # nothing left to mark


def test_definitions_are_written_once_per_class(tmp_path):
    good = _assertion("PATO_0000453", "glabrous")
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"source_id": "x:1", "assertions": [good, dict(good)]}) + "\n", encoding="utf-8")
    classes = acc.write_class_definitions(path, tmp_path / "definitions.ttl")
    assert classes[good["phenotype_class_iri"]]["statements"] == 2
    assert (tmp_path / "definitions.ttl").read_text(encoding="utf-8").count("owl#equivalentClass") == 1


@pytest.mark.skipif(shutil.which("java") is None, reason="needs Java for ROBOT/ELK")
def test_a_process_quality_on_a_plant_part_is_unsatisfiable(tmp_path):
    good, bad = _assertion("PATO_0000453", "glabrous"), _assertion("PATO_0000389", "acute")
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"source_id": "x:1", "assertions": [good, bad]}) + "\n", encoding="utf-8")
    result = acc.check("x", path, tmp_path)
    assert (result["classes"], result["unsatisfiable"], result["marked"]) == (2, 1, 1)
    report = (tmp_path / "x-unsatisfiable.tsv").read_text(encoding="utf-8")
    assert bad["phenotype_class_iri"] in report and good["phenotype_class_iri"] not in report
