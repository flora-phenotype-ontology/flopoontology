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


def _absent(text: str) -> dict:
    from flopo2.owl.annotation_class import ensure_annotation_class_iri

    assertion = {"po_id": "PO_0025034", "pato_id": "PATO_0000467", "value_terms": [], "value_operator": "atomic",
                 "negated": True, "negation_scope": "absence", "source_text": text,
                 "gate": {"status": "accepted", "reasons": []},
                 "composition": {"entity_label": "leaf", "quality_label": "present"}}
    ensure_annotation_class_iri(assertion)
    return assertion


def test_taxon_statements_leave_out_frequencies_and_unaccepted(tmp_path):
    glabrous, absent = _assertion("PATO_0000453", "glabrous"), _absent("leaves absent")
    rarely = {**_absent("rarely leafless"), "frequency_qualifier": "rarely"}
    review = {**_assertion("PATO_0000453", "glabrous?"), "gate": {"status": "review", "reasons": []}}
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"taxon": "A b", "assertions": [glabrous, absent]}) + "\n"
                    + json.dumps({"taxon": "C d", "assertions": [rarely, review]}) + "\n", encoding="utf-8")
    taxa, absences = {}, {}
    acc.write_class_definitions(path, tmp_path / "definitions.ttl", taxa=taxa, absences=absences)
    assert taxa == {"A b": {"present": {glabrous["phenotype_class_iri"]: "glabrous"},
                            "absent": {absent["phenotype_class_iri"]: "leaves absent"}}}
    assert list(absences) == [absent["phenotype_class_iri"]]
    taxon_classes = acc.write_taxon_classes(taxa, absences, tmp_path / "taxa.ttl")
    assert list(taxon_classes.values()) == ["A b"]
    assert "owl#disjointWith" in (tmp_path / "taxa.ttl").read_text(encoding="utf-8")


def test_demote_in_one_taxon_only(tmp_path):
    glabrous = _assertion("PATO_0000453", "glabrous")
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"taxon": "A b", "assertions": [glabrous]}) + "\n"
                    + json.dumps({"taxon": "C d", "assertions": [dict(glabrous)]}) + "\n", encoding="utf-8")
    iri = glabrous["phenotype_class_iri"]
    assert acc.demote(path, {iri}, acc.TAXON_REASON, {"A b": {iri}}) == 1
    first, second = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert first["assertions"][0]["gate"] == {"status": "review", "reasons": [acc.TAXON_REASON]}
    assert second["assertions"][0]["gate"] == {"status": "accepted", "reasons": []}


@pytest.mark.skipif(shutil.which("java") is None, reason="needs Java for ROBOT/ELK")
def test_absent_and_described_in_one_taxon_is_a_contradiction(tmp_path):
    glabrous, absent = _assertion("PATO_0000453", "leaves glabrous"), _absent("leaves absent")
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"taxon": "A b", "assertions": [glabrous, absent]}) + "\n"
                    + json.dumps({"taxon": "C d", "assertions": [dict(glabrous)]}) + "\n"
                    + json.dumps({"taxon": "E f", "assertions": [dict(absent)]}) + "\n", encoding="utf-8")
    result = acc.check("x", path, tmp_path)
    assert (result["unsatisfiable"], result["taxa_checked"], result["taxon_contradictions"],
            result["taxon_statements_marked"]) == (0, 1, 1, 2)
    report = (tmp_path / "x-taxon-contradictions.tsv").read_text(encoding="utf-8").splitlines()
    assert len(report) == 2 and report[1].startswith("A b\t")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [a["gate"]["status"] for r in records for a in r["assertions"]] == ["review", "review", "accepted", "accepted"]


def _part(po: str, label: str, pato: str, text: str) -> dict:
    from flopo2.owl.annotation_class import ensure_annotation_class_iri

    assertion = {"po_id": po, "pato_id": pato, "value_terms": [], "value_operator": "atomic",
                 "negated": False, "source_text": text, "gate": {"status": "accepted", "reasons": []},
                 "composition": {"entity_label": label, "quality_label": text}}
    ensure_annotation_class_iri(assertion)
    return assertion


def test_absence_of_a_part_is_written_with_part_of():
    """not (has part some (part of some leaf)): Gkoutos, Schofield and Hoehndorf 2018."""
    from rdflib import OWL, Graph, URIRef

    from flopo2.owl import assertions

    graph = Graph()
    assertions._phenotype_expression(graph, assertions._Nodes(), _absent("leaves absent"), set())
    (negated,) = graph.objects(None, OWL.complementOf)
    assert graph.value(negated, OWL.onProperty) == assertions.HAS_PART
    inner = graph.value(negated, OWL.someValuesFrom)
    assert graph.value(inner, OWL.onProperty) == assertions.PART_OF
    assert graph.value(inner, OWL.someValuesFrom) == URIRef(acc.OBO + "PO_0025034")
    assert URIRef(acc.OBO + "PATO_0000467") not in set(graph.all_nodes())
    # a part that lacks a quality keeps the form "no part with that quality"
    lacking = {**_assertion("PATO_0000453", "not glabrous"), "negated": True, "negation_scope": "absence"}
    assert not assertions.is_absence_of_part(lacking)


@pytest.mark.skipif(shutil.which("java") is None, reason="needs Java for ROBOT/ELK")
def test_absent_whole_contradicts_a_described_part(tmp_path):
    """Leaves absent, leaf lamina ovate: the lamina (PO:0020039) is part of a leaf."""
    lamina = _part("PO_0020039", "leaf lamina", "PATO_0001891", "leaf blades ovoid")
    stem = _part("PO_0009047", "stem", "PATO_0000453", "stems glabrous")
    absent = _absent("leaves absent")
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"taxon": "A b", "assertions": [lamina, absent]}) + "\n"
                    + json.dumps({"taxon": "C d", "assertions": [stem, dict(absent)]}) + "\n", encoding="utf-8")
    result = acc.check("x", path, tmp_path)
    assert (result["unsatisfiable"], result["taxa_checked"], result["taxon_contradictions"],
            result["taxon_statements_marked"]) == (0, 2, 1, 2)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [a["gate"]["status"] for r in records for a in r["assertions"]] == ["review", "review", "accepted", "accepted"]


def test_classes_are_phenes_and_the_bearer_axiom_is_only_in_the_check(tmp_path):
    """C = 'flora phenotype' and 'phenotype of' some Y; for ELK, 'has phenotype' some C SubClassOf Y."""
    from rdflib import OWL, RDFS, Graph, URIRef

    from flopo2.owl import phene

    glabrous, absent = _assertion("PATO_0000453", "leaves glabrous"), _absent("leaves absent")
    path = tmp_path / "x-annotated.jsonl"
    path.write_text(json.dumps({"taxon": "A b", "assertions": [glabrous, absent]}) + "\n", encoding="utf-8")
    acc.write_class_definitions(path, tmp_path / "published.ttl", bearers=False)
    published = Graph().parse(tmp_path / "published.ttl", format="nt")
    for assertion in (glabrous, absent):
        (expression,) = published.objects(URIRef(assertion["phenotype_class_iri"]), OWL.equivalentClass)
        assert phene.phene_body(published, expression) is not None
    assert (None, OWL.onProperty, phene.HAS_PHENOTYPE) not in published
    acc.write_class_definitions(path, tmp_path / "check.ttl")
    checked = Graph().parse(tmp_path / "check.ttl", format="nt")
    bearers = [(s, o) for s, o in checked.subject_objects(RDFS.subClassOf)
               if (s, OWL.onProperty, phene.HAS_PHENOTYPE) in checked]
    assert len(bearers) == 1  # the positive class; an absence gets its marker in the taxon check
    bearer, body = bearers[0]
    assert checked.value(bearer, OWL.someValuesFrom) == URIRef(glabrous["phenotype_class_iri"])
    (expression,) = checked.objects(URIRef(glabrous["phenotype_class_iri"]), OWL.equivalentClass)
    assert body == phene.phene_body(checked, expression)


@pytest.mark.skipif(shutil.which("java") is None, reason="needs Java for HermiT and ROBOT/ELK")
def test_hermit_on_the_published_axioms_agrees_with_the_elk_check(tmp_path):
    """The same taxa asked twice: of HermiT with the functional 'phenotype of' and the definitions
    as published, and of ELK with the bearer axioms and markers. Both find the taxon with leaves
    absent and a leaf blade described, and the one with leaves absent and glabrous; neither the
    taxon whose stems are glabrous nor the one that only lacks leaves."""

    lamina = _part("PO_0020039", "leaf lamina", "PATO_0001891", "leaf blades ovoid")
    stem = _part("PO_0009047", "stem", "PATO_0000453", "stems glabrous")
    glabrous, absent = _assertion("PATO_0000453", "leaves glabrous"), _absent("leaves absent")
    path = tmp_path / "x-annotated.jsonl"
    taxa = {"A b": [lamina, absent], "C d": [stem, dict(absent)], "E f": [glabrous, dict(absent)],
            "G h": [dict(absent)], "I j": [dict(glabrous), dict(stem), dict(lamina)]}
    path.write_text("".join(json.dumps({"taxon": name, "assertions": items}) + "\n" for name, items in taxa.items()),
                    encoding="utf-8")
    work = tmp_path / "hermit"
    work.mkdir()
    found, note = acc.complete_taxon_check(path, work)
    assert found is not None, note
    assert {name: row["status"] for name, row in found.items()} == {
        "A b": "inconsistent", "C d": "consistent", "E f": "inconsistent", "G h": "consistent", "I j": "consistent"}
    assert set(found["A b"]["conflict"]) == {lamina["phenotype_class_iri"], absent["phenotype_class_iri"]}
    assert set(found["E f"]["conflict"]) == {glabrous["phenotype_class_iri"], absent["phenotype_class_iri"]}

    result = acc.check("x", path, tmp_path)
    assert (result["unsatisfiable"], result["taxon_contradictions"]) == (0, 2)
    rows = (tmp_path / "x-taxon-contradictions.tsv").read_text(encoding="utf-8").splitlines()[1:]
    assert {row.split("\t")[0] for row in rows} == {name for name, row in found.items() if row["status"] == "inconsistent"}
