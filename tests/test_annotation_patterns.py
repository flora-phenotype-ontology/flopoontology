"""The annotation design patterns of docs/odp/: each test annotates one flora sentence end to end
and checks the record the pattern document describes, then the data-model rules of the pattern."""

from __future__ import annotations

import json

import pytest

from flopo2.ingest import flora_annotate
from flopo2.ingest import ncvc_annotate as na
from flopo2.verify import data_model as dm


@pytest.fixture(scope="module")
def res():
    """The resources of a flora run (flopo2.ingest.flora_annotate.run), without per-flora caches."""

    from dataclasses import replace

    resources = na.load_resources()
    resources.holds = []
    tables = flora_annotate.RULE_TABLES
    rules = na.merge_rules(resources.rules, [p for p in tables[2:] if p.exists()], tables[:2])
    na.enable_atlas_options(resources)
    resources.rereads, resources.llm_relations, resources.llm_relation_chains = {}, {}, {}
    return replace(resources, rules=rules)


def annotate(res, text: str, *rows: dict) -> tuple[list[dict], list]:
    phenotypes = []
    for row in rows:
        qualifiers = {"negated": False, "stage": row.pop("stage", ""), "frequency": row.pop("frequency", ""),
                      "alternatives": row.pop("alternatives", [])}
        phenotypes.append({"value_low": None, "value_high": None, "unit": "", "qualifiers": qualifiers, **row})
    rec = flora_annotate.to_ncvc_record(
        {"source_id": "test:taxon#p1", "taxon": "Testus exemplaris", "segment_text": text, "phenotypes": phenotypes},
        "test",
    )
    flora_annotate.prepare(rec)
    segments, dispositions = na.annotate_record(rec, res)
    english = next(s for s in segments if s["language"] == "en" and s["organ"] == "description")
    return english["assertions"], dispositions


def issues(assertion: dict, text: str) -> list[str]:
    parsed = dm._pydantic_assertion(assertion)
    return [code for code, _ in dm.pattern_issues(parsed, text, set(), set(), set(), set())]


def test_plus_minus_is_an_approximation_cue(res):
    text = "Stems ± erect."
    (a,), _ = annotate(res, text, {"entity_en": "stem", "quality_en": "± erect", "source_en": "Stems ± erect"})
    assert a["pato_id"] == "PATO_0000622" and a["value_qualifier"] == "approximately"
    assert text[a["modality_start"]:a["modality_end"]] == "±"


def test_less_than_is_a_strict_upper_bound(res):
    text = "Sepals less than 1 mm long."
    (a,), _ = annotate(res, text, {"entity_en": "sepal", "quality_en": "length", "source_en": "Sepals less than 1 mm long",
                                   "value_high": 1, "unit": "mm"})
    assert (a["value_low"], a["value_high"], a["value_high_inclusive"]) == (None, 1.0, False)
    # "rarely less than" is not an upper bound
    got, dispositions = annotate(res, "Sepals rarely less than 7 mm long.", {
        "entity_en": "sepal", "quality_en": "length", "source_en": "Sepals rarely less than 7 mm long",
        "value_high": 7, "unit": "mm"})
    assert not got and dispositions[0].reason == "upper_bound_cue_not_supported"


def test_a_counted_part_in_the_word(res):
    text = "Leaves 3-5-foliolate."
    (a,), _ = annotate(res, text, {"entity_en": "leaf", "quality_en": "3-5-foliolate", "source_en": "Leaves 3-5-foliolate"})
    assert (a["pato_id"], a["value_low"], a["value_high"], a["unit"]) == ("PATO_0000070", 3.0, 5.0, "count")
    assert a["po_id"] == "PO_0020049" and a["bearer_container"] == "PO_0025034"  # leaflets of a leaf


def test_a_member_of_a_series_is_a_position_of_the_bearer(res):
    text = "Basal leaves glabrous."
    (a,), _ = annotate(res, text, {"entity_en": "leaf", "quality_en": "glabrous", "source_en": "leaves glabrous",
                                   "stage": "basal"})
    assert a["bearer_context_qualities"] == ["FLOPO_0991002"]


def test_range_with_extremes(res):
    text = "Leaves (2-)3-8(-11) cm long."
    (a,), _ = annotate(res, text, {"entity_en": "leaf", "quality_en": "length", "source_en": "(2-)3-8(-11) cm long",
                                   "value_low": 8, "value_high": 11, "unit": "cm"})  # the transcriber folded the extreme in
    assert (a["value_min_extreme"], a["value_low"], a["value_high"], a["value_max_extreme"]) == (2.0, 3.0, 8.0, 11.0)
    assert issues(a, text) == []
    assert "extreme_not_outside_usual_range" in issues({**a, "value_max_extreme": 7.0}, text)
    assert "extreme_not_in_parentheses_in_source" in issues({**a, "value_max_extreme": 12.0}, text)
    assert "extreme_without_usual_bound" in issues({**a, "value_low": None}, text)
    assert na.range_extremes("(6-)12(-26) x (19-)21-24(-42) mm", 21, 24)["max_extreme"] == 42.0
    assert na.range_extremes("3-8 cm", 3, 8) is None


def test_specimen_condition_has_no_phenotype_class(res):
    text = "Leaves black when dry."
    (a,), _ = annotate(res, text, {"entity_en": "leaf", "quality_en": "black", "source_en": "Leaves black",
                                   "stage": "when dry"})
    assert a["specimen_condition"]["condition"] == "dried"
    assert text[a["specimen_condition"]["start"]:a["specimen_condition"]["end"]] == "when dry"
    assert not a.get("phenotype_class_iri")
    assert issues(a, text) == []
    assert "specimen_condition_with_phenotype_class" in issues({**a, "phenotype_class_iri": "http://example.org/c"}, text)
    from flopo2.owl.assertions import _strict

    assert _strict({**a, "gate": {"status": "accepted"}}, True) is False


def test_alternatives_of_one_attribute_stay_the_primary_pattern(res):
    text = "Flowers white or pink."
    (a,), _ = annotate(res, text, {"entity_en": "flower", "quality_en": "white", "source_en": "Flowers white or pink",
                                   "alternatives": ["pink"]})
    assert a["value_operator"] == "one_of" and a.get("value_union_scope", "same_attribute") == "same_attribute"
    assert a["pato_id"] == "PATO_0000014"


def test_alternatives_across_attributes_need_a_reviewed_pair(res):
    text = "Stem simple or branched."
    (a,), _ = annotate(res, text, {"entity_en": "stem", "quality_en": "simple", "source_en": "Stem simple or branched",
                                   "alternatives": ["branched"]})
    assert a["value_union_scope"] == "across_attributes" and a["pato_id"] == "PATO_0000001"
    assert sorted(a["value_terms"]) == ["PATO_0000402", "PATO_0001503"]
    assert [o["text"] for o in a["value_operands"]] == ["simple", "branched"]
    assert issues(a, text) == []
    # rules of the pattern
    assert "across_attributes_pair_not_reviewed" in issues({**a, "value_terms": ["PATO_0001503", "PATO_0000014"],
        "value_operands": [a["value_operands"][0], {**a["value_operands"][1], "value": "PATO_0000014"}]}, text)
    assert "across_attributes_without_or" in issues(a, "Stem simple to branched.")
    assert "across_attributes_top_level_not_quality" in issues({**a, "pato_id": "PATO_0000051"}, text)
    assert "union_under_quality_root_without_scope" in issues({**a, "value_union_scope": "same_attribute"}, text)
    # a pair that was not reviewed stays unresolved and names the pair
    got, dispositions = annotate(res, "Stem simple or yellow.", {
        "entity_en": "stem", "quality_en": "simple", "source_en": "Stem simple or yellow", "alternatives": ["yellow"]})
    assert not got and dispositions[0].reason.startswith("alternatives_across_attributes_unreviewed:")


def test_an_alternative_with_its_own_frequency(res):
    text = "Fruit curved or rarely straight."
    (a,), _ = annotate(res, text, {"entity_en": "fruit", "quality_en": "curved", "source_en": "Fruit curved or rarely straight",
                                   "alternatives": ["straight"], "frequency": "rarely"})
    assert a["value_operator"] == "one_of"
    assert [(o["text"], o["frequency_qualifier"]) for o in a["value_operands"]] == [
        ("curved", "unspecified"), ("rarely straight", "rarely")]
    assert a.get("frequency_qualifier", "unspecified") == "unspecified"  # not a frequency of the statement


def test_attachment_to_another_part(res):
    text = "Stamens adnate to the petals."
    (a,), _ = annotate(res, text, {"entity_en": "stamen", "quality_en": "adnate to the petals",
                                   "source_en": "Stamens adnate to the petals"})
    assert a["towards"]["target_term"] == "PO_0009032" and a["towards"]["target_text"] == "petals"
    assert "PATO_0000642" in (a["pato_id"], *a["value_terms"]) or "FLOPO_0991129" in a["value_terms"]
    # "opposite cauline leaves" describes those leaves; "opposite the petals" is a relation
    assert na.comparison(res, {"quality_en": "opposite"}, "Leaves opposite cauline leaves.", 0, 30, "PO_0025034") is None
    assert na.comparison(res, {"quality_en": "opposite the petals"}, "Stamens opposite the petals.", 0, 27, "PO_0009029")["pato_id"] == "PATO_0001933"


def test_equal_length_and_ratio_to_another_part(res):
    text = "Petals as long as the sepals. Filaments 2-3 times as long as the anthers."
    equal, ratio = annotate(
        res, text,
        {"entity_en": "petal", "quality_en": "as long as the sepals", "source_en": "Petals as long as the sepals"},
        {"entity_en": "filament", "quality_en": "2-3 times as long as the anthers",
         "source_en": "Filaments 2-3 times as long as the anthers"},
    )[0]
    assert (equal["pato_id"], equal["towards"]["ratio_low"], equal["towards"]["ratio_high"]) == ("PATO_0000122", 1.0, 1.0)
    assert (ratio["pato_id"], ratio["towards"]["ratio_low"], ratio["towards"]["ratio_high"]) == ("PATO_0000573", 2.0, 3.0)
    assert issues(ratio, text) == []
    assert "invalid_ratio_bounds" in issues({**ratio, "towards": {**ratio["towards"], "ratio_low": 4.0}}, text)
    # a multiple the reader does not know is not read as "as long as"
    odd = "Petals five sevenths as long as the sepals."
    assert na.comparison(res, {"quality_en": "five sevenths as long as the sepals"}, odd, 0, 42, "PO_0009032") is None


def test_ratio_of_two_dimensions(res):
    text = "Leaves 2-3 times as long as wide."
    (a,), _ = annotate(res, text, {"entity_en": "leaf", "quality_en": "2-3 times as long as wide",
                                   "source_en": "Leaves 2-3 times as long as wide"})
    assert (a["pato_id"], a["value_low"], a["value_high"], a["unit"]) == ("PATO_0001470", 2.0, 3.0, "ratio")
    assert (a["ratio_numerator"], a["ratio_denominator"]) == ("PATO_0000122", "PATO_0000921")
    assert issues(a, text) == []
    assert "ratio_of_one_dimension" in issues({**a, "ratio_denominator": "PATO_0000122"}, text)
    assert na.self_ratio({"quality_en": "longer than broad"}, "")["low_inclusive"] is False


def test_part_of_a_qualified_whole(res):
    text = "Calyx hairy in male flowers."
    (a,), _ = annotate(res, text, {"entity_en": "calyx", "quality_en": "hairy", "source_en": "Calyx hairy",
                                   "stage": "in male flowers"})
    whole = a["bearer_whole"]
    assert (whole["whole_term"], whole["qualities"], whole["whole_text"]) == ("PO_0009046", ["PATO_0000384"], "in male flowers")
    assert issues(a, text) == []
    assert "whole_is_the_bearer" in issues({**a, "po_id": "PO_0009046"}, text)
    assert "whole_text_not_verbatim" in issues({**a, "bearer_whole": {**whole, "start": 0, "end": 5}}, text)
    from rdflib import Graph

    from flopo2.owl import assertions

    graph = Graph()
    assertions._phenotype_expression(graph, assertions._Nodes(), a, set())
    turtle = graph.serialize(format="nt")
    assert "PO_0009046" in turtle and "PATO_0000384" in turtle and "BFO_0000050" in turtle
    from flopo2.owl.annotation_class import annotation_class_iri

    assert annotation_class_iri(a) != annotation_class_iri({k: v for k, v in a.items() if k != "bearer_whole"})
