"""Context, part-of and comparison patterns of the flora annotator
(docs/annotation-context-patterns.md)."""

from __future__ import annotations

import pytest
from rdflib import OWL, RDF, Graph, URIRef

from flopo2.ingest import ncvc_annotate as na

OBO = "http://purl.obolibrary.org/obo/"


@pytest.fixture(scope="module")
def res():
    resources = na.load_resources()
    na.enable_atlas_options(resources)
    return resources


def test_stage_and_state_words_are_read_from_the_reviewed_table(res):
    text = "Calyx 6-8 mm long in fruit; leaves pubescent when young."
    reading, start, end = na.stage_context(res, "in fruit", text, 0, 16, ["calyx"])
    assert (reading["kind"], reading["target"], text[start:end]) == ("stage", "PO_0001002", "in fruit")
    reading, start, end = na.stage_context(res, "when young", text, 29, 45, ["leaf"])
    assert (reading["kind"], reading["target"]) == ("bearer_quality", "PATO_0000309")
    # the sex of a flower is not a quality of its calyx
    assert na.stage_context(res, "male", "male calyx 3 mm", 0, 10, ["calyx"]) is None
    # a word outside the clause of the span is no evidence
    assert na.stage_context(res, "in fruit", "Calyx green. Pedicel long in fruit.", 0, 11, ["calyx"]) is None


def test_above_is_a_side_of_a_leaf_and_the_upper_part_of_a_stem(res):
    leaf, _s, _e = na.stage_context(res, "above", "leaves glabrous above", 0, 21, ["leaf"])
    stem, _s, _e = na.stage_context(res, "above", "stem hairy above", 0, 16, ["stem"])
    assert (leaf["kind"], leaf["target"]) == ("surface", "adaxial")
    assert (stem["kind"], stem["target"]) == ("region", "distal")


def test_a_surface_is_the_po_epidermis_of_that_side(res):
    plan, why = na.plan_bearer_scope(res, "PO_0020039", "PATO_0000453", [], False, "surface", "abaxial", "beneath", 16, 23)
    assert not why
    assert plan["po_id"] == "PO_0000049"  # leaf lamina abaxial epidermis
    assert plan["bearer_scope"]["mode"] == "substituted_bearer"
    assert plan["bearer_scope"]["outer_bearer"] == "PO_0020039" and "part_restrictions" not in plan


def test_a_region_without_a_po_class_is_a_pinned_bspo_part_and_the_organ_keeps_the_attribute(res):
    # "filaments white at base": the stamen filament has no PO base class
    plan, why = na.plan_bearer_scope(res, "PO_0009067", "PATO_0000014", ["FLOPO_0988009"], False, "region", "base", "at base", 16, 23)
    assert not why and "po_id" not in plan
    assert plan["pato_id"] == "PATO_0000014" and plan["value_terms"] == []
    (part,) = plan["part_restrictions"]
    assert part["filler_class"] == "BSPO_0000074" and part["qualities"] == ["FLOPO_0988009"]
    assert plan["bearer_scope"]["mode"] == "part_restriction"
    # hairs on a region entail a hairy organ: the value stays at the top level
    plan, _ = na.plan_bearer_scope(res, "PO_0009047", "PATO_0000454", [], False, "region", "distal", "above", 11, 16)
    assert plan["pato_id"] == "PATO_0000454" and plan["part_restrictions"][0]["filler_class"] == "BSPO_0000078"


def test_scoped_measurements_and_other_value_families_are_left_alone(res):
    assert na.plan_bearer_scope(res, "PO_0020039", "PATO_0000122", [], True, "surface", "abaxial", "beneath", 0, 7)[0] is None
    # a shape is not stated of a surface
    assert na.plan_bearer_scope(res, "PO_0020039", "PATO_0000947", [], False, "surface", "abaxial", "beneath", 0, 7)[0] is None


def test_comparison_with_another_part(res):
    text = "Style slightly shorter than the stamens, glabrous."
    found = na.comparison(res, {"quality_en": "slightly shorter than the stamens"}, text, 6, 39, "PO_0009074")
    assert found["pato_id"] == "PATO_0000574" and found["target_term"] == "PO_0009029"
    assert text[found["start"]:found["end"]] == found["target_text"] == "stamens"
    assert found["comparison_text"] == "slightly shorter than"
    # no second part, a measurement, or the bearer itself: no comparison
    # the second part is read from the source span when the transcribed quality lacks it
    assert na.comparison(res, {"quality_en": "shorter"}, text, 6, 39, "PO_0009074")["target_term"] == "PO_0009029"
    assert na.comparison(res, {"quality_en": "shorter"}, "Style shorter, glabrous.", 6, 13, "PO_0009074") is None
    assert na.comparison(res, {"quality_en": "longer than 5 mm"}, "Style longer than 5 mm.", 6, 22, "PO_0009074") is None
    assert na.comparison(res, {"quality_en": "shorter than the style"}, "Style shorter than the style.", 6, 28, "PO_0009074") is None


def test_towards_compiles_to_a_relational_quality():
    from flopo2.owl import assertions

    graph = Graph()
    assertion = {"po_id": "PO_0009074", "pato_id": "PATO_0000574",
                 "towards": {"target_term": "PO_0009029", "target_text": "stamens"}}
    assertions._phenotype_expression(graph, assertions._Nodes(), assertion, set())
    towards = URIRef(OBO + "RO_0002503")
    (restriction,) = set(graph.subjects(OWL.onProperty, towards))
    assert (restriction, OWL.someValuesFrom, URIRef(OBO + "PO_0009029")) in graph
    assert (towards, RDF.type, OWL.ObjectProperty) in graph
    # without a target the expression is unchanged
    plain = Graph()
    assertions._phenotype_expression(plain, assertions._Nodes(), {"po_id": "PO_0009074", "pato_id": "PATO_0000574"}, set())
    assert not set(plain.subjects(OWL.onProperty, towards))


def test_the_signature_of_a_comparison_names_its_target():
    from flopo2.owl.annotation_class import canonical_signature_json as signature_of

    base = {"po_id": "PO_0009074", "pato_id": "PATO_0000574"}
    assert signature_of(base) != signature_of({**base, "towards": {"target_term": "PO_0009029", "target_text": "stamens"}})
