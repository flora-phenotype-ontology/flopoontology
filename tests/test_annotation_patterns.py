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


def test_a_count_without_a_number_is_presence_with_a_count_word(res):
    text = "Inflorescences few-flowered; seeds numerous."
    (flowers, seeds), _ = annotate(
        res, text,
        {"entity_en": "inflorescence", "quality_en": "few-flowered", "source_en": "Inflorescences few-flowered"},
        {"entity_en": "seed", "quality_en": "numerous", "source_en": "seeds numerous"},
    )
    assert (flowers["po_id"], flowers["pato_id"], flowers["bearer_container"]) == ("PO_0009046", "PATO_0000467", "PO_0009049")
    assert flowers["count_word"]["amount"] == "few"
    assert text[flowers["count_word"]["start"]:flowers["count_word"]["end"]] == "few-flowered"
    assert (seeds["po_id"], seeds["pato_id"], seeds["count_word"]["amount"]) == ("PO_0009010", "PATO_0000467", "many")
    assert flowers.get("phenotype_class_iri") and issues(flowers, text) == [] and issues(seeds, text) == []
    assert "count_word_with_number" in issues({**seeds, "value_low": 20.0}, text)
    assert "count_word_without_presence" in issues({**seeds, "pato_id": "PATO_0000070"}, text)
    assert "count_word_text_not_verbatim" in issues({**seeds, "count_word": {**seeds["count_word"], "start": 0}}, text)


def test_a_count_on_each_side_has_its_position_and_no_phenotype_class(res):
    text = "Leaf blade with 3-10 lobes on each side."
    (a,), _ = annotate(res, text, {"entity_en": "leaf blade", "quality_en": "number of lobes", "value_low": 3,
                                   "value_high": 10, "unit": "lobes", "source_en": "with 3-10 lobes on each side"})
    assert (a["po_id"], a["pato_id"], a["value_low"], a["value_high"]) == ("PO_0025517", "PATO_0000070", 3.0, 10.0)
    assert a["bearer_container"] == "PO_0020039" and a["count_position"]["kind"] == "each_side"
    assert text[a["count_position"]["start"]:a["count_position"]["end"]] == "on each side"
    assert not a.get("phenotype_class_iri") and issues(a, text) == []
    assert "count_position_with_phenotype_class" in issues({**a, "phenotype_class_iri": "http://example.org/c"}, text)
    assert "count_position_without_count" in issues({**a, "value_low": None, "value_high": None}, text)
    from flopo2.owl.assertions import _strict

    assert _strict({**a, "gate": {"status": "accepted"}}, True) is False


def test_two_numbers_joined_by_or_are_a_range(res):
    text = "Stems with 4 or 5 leaves."
    (a,), _ = annotate(res, text, {"entity_en": "stem", "quality_en": "number of leaves", "value_low": 4,
                                   "value_high": 5, "unit": "leaves", "source_en": "with 4 or 5 leaves"})
    assert (a["po_id"], a["value_low"], a["value_high"], a["unit"]) == ("PO_0025034", 4.0, 5.0, "count")
    # one number only in the transcription: the choice between two numbers stays unresolved
    rows, _ = annotate(res, text, {"entity_en": "stem", "quality_en": "number of leaves", "value_low": 4,
                                   "value_high": 4, "unit": "leaves", "source_en": "with 4 or 5 leaves"})
    assert rows == []


def test_or_nearly_so_is_an_approximation_cue(res):
    text = "Stems glabrous or nearly so."
    (a,), _ = annotate(res, text, {"entity_en": "stem", "quality_en": "glabrous", "source_en": "Stems glabrous or nearly so"})
    assert a["pato_id"] == "PATO_0000453" and a["value_qualifier"] == "approximately"
    assert text[a["modality_start"]:a["modality_end"]] == "or nearly so"


def test_place_words_of_the_second_model_review(res):
    text = "Leaf blades ovate, apex acute. Upper leaves sessile. Leaves pubescent on both surfaces."
    apex, upper, both = annotate(
        res, text,
        {"entity_en": "leaf blade", "quality_en": "acute", "source_en": "apex acute", "stage": "apex"},
        {"entity_en": "leaf", "quality_en": "sessile", "source_en": "Upper leaves sessile", "stage": "upper"},
        {"entity_en": "leaf", "quality_en": "pubescent", "source_en": "Leaves pubescent on both surfaces",
         "stage": "on both surfaces"},
    )[0]
    assert apex["po_id"] == "PO_0025589" and apex["value_terms"] == ["FLOPO_0991095"]  # leaf lamina tip, acute
    assert upper["bearer_context_qualities"] == ["FLOPO_0991376"]                    # the upper leaves
    assert both["po_id"] == "PO_0025034" and not both.get("bearer_scope")            # the leaf as a whole
    assert all(a["gate"]["status"] == "accepted" for a in (apex, upper, both))


def test_a_part_with_its_whole_by_a_reviewed_rule(res):
    text = "Bract lobes acute."
    (a,), _ = annotate(res, text, {"entity_en": "bract lobe", "quality_en": "acute", "source_en": "Bract lobes acute"})
    # "bract lobe": a lobe (phyllome lamina lobe) that is part of a bract
    assert (a["po_id"], a["bearer_container"]) == ("PO_0025514", "PO_0009055")
    assert issues(a, text) == []


def test_lengths_in_feet_inches_and_decimetres_are_converted_to_si(res):
    text = "Trees 15 to 30 feet tall; stems (2-)3-6(-7) dm."
    tree, stem = annotate(
        res, text,
        {"entity_en": "whole plant", "quality_en": "height", "value_low": 15, "value_high": 30, "unit": "ft",
         "source_en": "Trees 15 to 30 feet tall"},
        {"entity_en": "stem", "quality_en": "length", "value_low": 3, "value_high": 6, "unit": "dm",
         "source_en": "stems (2-)3-6(-7) dm"},
    )[0]
    assert (tree["value_low"], tree["value_high"], tree["unit"]) == (4.572, 9.144, "m")
    assert (tree["source_unit"], tree["unit_conversion_factor"]) == ("ft", 0.3048)
    assert (stem["value_low"], stem["value_high"], stem["unit"]) == (30.0, 60.0, "cm")
    assert (stem["value_min_extreme"], stem["value_max_extreme"]) == (20.0, 70.0)
    assert issues(tree, text) == [] and issues(stem, text) == []


def test_a_list_of_alternatives_stays_with_the_rows_it_lists(res):
    from dataclasses import replace

    sentence = "Erect, ascending or rarely procumbent perennial shrub"
    chain = {"values": [{"text": "Erect", "term": "erect"}, {"text": "ascending", "term": "ascending"},
                        {"text": "rarely procumbent", "term": "procumbent"}],
             "connectors": [{"text": ",", "interpretation": "taxon_level_alternatives"},
                            {"text": "or", "interpretation": "taxon_level_alternatives"}], "model": "test"}
    rows = [{"entity_en": "whole plant", "quality_en": q, "source_en": sentence} for q in ("erect", "perennial")]
    rec = flora_annotate.to_ncvc_record(
        {"source_id": "test:taxon#p1", "taxon": "Testus exemplaris", "segment_text": sentence + ".",
         "phenotypes": [{"value_low": None, "value_high": None, "unit": "",
                         "qualifiers": {"negated": False, "stage": "", "frequency": "", "alternatives": []}, **r}
                        for r in rows]}, "test")
    flora_annotate.prepare(rec)
    key = na.ncvc_guide._source_id(rec)
    with_chain = replace(res, llm_relation_chains={(key, 0): chain, (key, 1): chain})
    segments, _ = na.annotate_record(rec, with_chain)
    found = next(s for s in segments if s["language"] == "en" and s["organ"] == "description")["assertions"]
    perennial = [a for a in found if a["pato_id"] == "PATO_0104361"]
    assert len(perennial) == 1 and not perennial[0].get("qualitative_value_relation")
    assert perennial[0]["source_text"] == "perennial"
    assert sum(1 for a in found if a.get("qualitative_value_relation")) == 2  # erect-ascending, ascending-procumbent


@pytest.mark.parametrize("words, part, problem", [
    ("Petals absent", "petal", ""),
    ("without petals", "petal", ""),
    ("Absent", "stipule", ""),
    ("petals and disk absent", "petal", ""),
    ("auricles and oral setae absent", "leaf sheath auricle", ""),
    ("stipules usually absent", "stipule", ""),
    ("without simple hairs", "stem", "absence_of_another_part"),
    ("allomorphic pistillate flowers absent", "flower", "absence_of_a_kind_of_the_part"),
    ("basal leaves absent", "leaf", "absence_of_a_kind_of_the_part"),
    ("Corolla absent in female flowers", "corolla", "absence_in_some_members"),
    ("ray florets without pappus", "pappus", "absence_in_some_members"),
    ("Cypselae not seen", "fruit", "part_not_observed"),
])
def test_an_absence_is_taken_only_of_the_part_itself(words, part, problem):
    assert na.absence_scope_problem(words, [part]) == problem


def test_a_privative_word_is_an_absence_from_the_organ_described(res):
    text = "Peduncles ebracteate."
    (a,), _ = annotate(res, text, {"entity_en": "peduncle", "quality_en": "ebracteate", "source_en": "Peduncles ebracteate"})
    # no bract on the peduncle; the involucral bracts of the same plant are another matter
    assert (a["po_id"], a["negated"], a["bearer_container"]) == ("PO_0009055", True, "PO_0009053")


def test_a_reading_is_found_under_another_reviewed_wording(res):
    text = "Young branches pubescent."
    (a,), _ = annotate(res, text, {"entity_en": "branch", "quality_en": "pubescent", "source_en": "branches pubescent",
                                   "stage": "when young"})
    assert a["bearer_context_qualities"] == ["PATO_0000309"]  # young


def test_arrangement_is_a_quality_of_the_axis_and_fusion_of_the_whorl(res):
    text = "Leaves alternate. Sepals connate. Petals white."
    (leaves, sepals, petals), _ = annotate(
        res, text,
        {"entity_en": "leaf", "quality_en": "alternate", "source_en": "Leaves alternate"},
        {"entity_en": "sepal", "quality_en": "connate", "source_en": "Sepals connate"},
        {"entity_en": "petal", "quality_en": "white", "source_en": "Petals white"},
    )
    assert leaves["po_id"] in ("PO_0025034", "PO_0009025")  # the record keeps the part the flora names
    assert leaves["carrier"] == {"carrier_term": "PO_0025029", "kind": "arrangement"}
    assert (sepals["po_id"], sepals["carrier"]) == ("PO_0009031", {"carrier_term": "PO_0009060", "kind": "set"})
    assert not petals.get("carrier")
    assert issues(leaves, text) == [] and issues(sepals, text) == []
    assert "carrier_does_not_follow_from_part_and_value" in issues(
        {**leaves, "carrier": {"carrier_term": "PO_0009060", "kind": "set"}}, text)
    assert "carrier_is_the_part" in issues(
        {**leaves, "carrier": {"carrier_term": leaves["po_id"], "kind": "arrangement"}}, text)
    assert "carrier_with_number_negation_or_relation" in issues({**leaves, "negated": True}, text)
    from rdflib import Graph, URIRef

    from flopo2.owl import assertions
    from flopo2.owl.annotation_class import annotation_class_iri

    obo = "http://purl.obolibrary.org/obo/"
    graph = Graph()
    assertions._phenotype_expression(graph, assertions._Nodes(), leaves, set())
    # has part some (shoot axis and has characteristic some (alternate and towards some leaf))
    towards = next(graph.subjects(URIRef("http://www.w3.org/2002/07/owl#onProperty"), URIRef(obo + "RO_0002503")))
    target = graph.value(towards, URIRef("http://www.w3.org/2002/07/owl#someValuesFrom"))
    assert str(target) == obo + leaves["po_id"]
    whole = next(graph.subjects(URIRef("http://www.w3.org/2002/07/owl#onProperty"), URIRef(obo + "BFO_0000051")))
    members = set(graph.items(graph.value(graph.value(whole, URIRef("http://www.w3.org/2002/07/owl#someValuesFrom")),
                                          URIRef("http://www.w3.org/2002/07/owl#intersectionOf"))))
    assert URIRef(obo + "PO_0025029") in members and URIRef(obo + leaves["po_id"]) not in members
    assert annotation_class_iri(leaves) != annotation_class_iri({k: v for k, v in leaves.items() if k != "carrier"})
    assert leaves["phenotype_class_iri"] == annotation_class_iri(leaves)



# --- patterns 19 to 25 (second-model review of 2026-11-23) ---------------------------------------


def test_to_more_than_is_a_lower_bound_on_the_maximum_without_range_or_class(res):
    text = "Subshrubs to more than 1.5 m high."
    (a,), _ = annotate(res, text, {"entity_en": "whole plant", "quality_en": "height", "value_high": 1.5, "unit": "m",
                                   "source_en": "Subshrubs to more than 1.5 m high"})
    bound = a["maximum_at_least"]
    assert (a["po_id"], a["pato_id"], bound["value"], bound["unit"], bound["inclusive"]) == ("PO_0000003", "PATO_0000119", 1.5, "m", False)
    assert text[bound["start"]:bound["end"]] == "to more than"
    assert a.get("value_low") is None and a.get("value_high") is None and not a.get("phenotype_class_iri")
    assert issues(a, text) == []
    assert "maximum_at_least_with_range" in issues({**a, "value_high": 1.5}, text)
    assert "maximum_at_least_with_phenotype_class" in issues({**a, "phenotype_class_iri": "http://example.org/c"}, text)
    from flopo2.owl.assertions import _strict

    assert _strict({**a, "gate": {"status": "accepted"}}, True) is False


def test_or_longer_after_a_number_is_the_same_bound_and_at_least_is_inclusive(res):
    (a,), _ = annotate(res, "Petioles up to 4 cm long or longer.", {
        "entity_en": "petiole", "quality_en": "length", "value_high": 4, "unit": "cm", "source_en": "Petioles up to 4 cm long or longer"})
    assert a["maximum_at_least"]["value"] == 4.0 and a["maximum_at_least"]["inclusive"] is True
    (b,), _ = annotate(res, "Tuber to at least 6 cm diam.", {
        "entity_en": "tuber", "quality_en": "diameter", "value_high": 6, "unit": "cm", "source_en": "Tuber to at least 6 cm diam"})
    assert b["maximum_at_least"]["inclusive"] is True


def test_a_rare_exceedance_is_not_a_bound_on_the_maximum(res):
    assertions, dispositions = annotate(res, "Plants rarely to more than 1 m high.", {
        "entity_en": "whole plant", "quality_en": "height", "value_high": 1, "unit": "m", "source_en": "rarely to more than 1 m high"})
    assert not any(a.get("maximum_at_least") for a in assertions)


def test_a_number_beside_a_state_is_its_extent_and_the_class_is_that_of_the_state(res):
    text = "Filaments exserted 5.5-6.5 mm."
    (a,), _ = annotate(res, text, {"entity_en": "filament", "quality_en": "exserted", "value_low": 5.5, "value_high": 6.5,
                                   "unit": "mm", "source_en": "exserted 5.5-6.5 mm"})
    assert (a["po_id"], a["pato_id"]) == ("PO_0009067", "PATO_0000623")
    assert a["extent"] == {"quality": "PATO_0000623", "value_low": 5.5, "value_high": 6.5, "unit": "mm"}
    assert a.get("value_low") is None and a.get("value_high") is None
    (plain,), _ = annotate(res, "Filaments exserted.", {"entity_en": "filament", "quality_en": "exserted", "source_en": "Filaments exserted"})
    assert a["phenotype_class_iri"] == plain["phenotype_class_iri"] and issues(a, text) == []
    assert "extent_with_measurement" in issues({**a, "value_low": 5.5}, text)
    assert "extent_of_another_quality" in issues({**a, "extent": {**a["extent"], "quality": "PATO_0000122"}}, text)


def test_a_number_beside_a_value_that_takes_no_extent_stays_unresolved(res):
    assertions, dispositions = annotate(res, "Leaves glabrous 3 mm.", {
        "entity_en": "leaf", "quality_en": "glabrous", "value_low": 3, "value_high": 3, "unit": "mm", "source_en": "glabrous 3 mm"})
    assert assertions == [] and dispositions[0].reason == "numeric_quality_not_pato_attribute"


def test_a_growth_form_noun_states_the_habit_of_the_whole_plant(res):
    (liana,), _ = annotate(res, "Lianas to 12 m.", {"entity_en": "whole plant", "quality_en": "liana", "source_en": "Lianas"})
    assert (liana["po_id"], liana["value_terms"]) == ("PO_0000003", ["FLOPO_0991412"]) and liana.get("phenotype_class_iri")
    (twiner,), _ = annotate(res, "Deciduous twining shrubs.", {"entity_en": "whole plant", "quality_en": "twining", "source_en": "twining"})
    assert twiner["value_terms"] == ["FLOPO_0991411"]
    (vine,), _ = annotate(res, "Vines woody.", {"entity_en": "whole plant", "quality_en": "vine", "source_en": "Vines"})
    assert vine["value_terms"] == ["FLOPO_0991108"]


def test_rooting_at_the_nodes_is_a_root_present_at_the_node(res):
    (a,), _ = annotate(res, "Stems creeping, rooting at the nodes.", {
        "entity_en": "stem", "quality_en": "rooting at the nodes", "source_en": "rooting at the nodes"})
    assert (a["po_id"], a["pato_id"], a["bearer_container"]) == ("PO_0000042", "PATO_0000467", "PO_0020141")
    assert not a.get("negated") and a.get("phenotype_class_iri")


def test_with_or_without_a_part_is_variable_presence_without_a_class(res):
    text = "Plants with or without stolons."
    (a,), _ = annotate(res, text, {"entity_en": "stolon", "quality_en": "present", "source_en": "with or without stolons"})
    cue = a["presence_variable"]
    assert (a["po_id"], a["pato_id"], a.get("negated", False)) == ("PO_0003024", "PATO_0000467", False)
    assert text[cue["start"]:cue["end"]] == "with or without" and not a.get("phenotype_class_iri")
    assert a["gate"]["status"] == "accepted" and issues(a, text) == []
    assert "presence_variable_with_phenotype_class" in issues({**a, "phenotype_class_iri": "http://example.org/c"}, text)
    assert "presence_variable_without_presence" in issues({**a, "negated": True, "negation_scope": "absence"}, text)


def test_absent_or_with_a_measurement_is_variable_presence(res):
    text = "Pedicels absent or to 0.5 mm."
    (a,), _ = annotate(res, text, {"entity_en": "pedicel", "quality_en": "absent", "source_en": "Pedicels absent or to 0.5 mm"})
    assert a["pato_id"] == "PATO_0000467" and not a.get("negated") and a["presence_variable"]["cue_text"] == "absent or"


def test_after_a_stage_is_a_relation_of_its_own_and_another_class_than_at_the_stage(res):
    text = "Pedicels nodding after anthesis."
    (after,), _ = annotate(res, text, {"entity_en": "pedicel", "quality_en": "nodding", "stage": "after anthesis",
                                       "source_en": "nodding after anthesis"})
    context = after["developmental_stage_contexts"][0]
    assert (context["stage_term"], context["temporal_relation"]) == ("PO_0007616", "present_after")
    assert text[context["start"]:context["end"]] == "after anthesis" and issues(after, text) == []
    (during,), _ = annotate(res, "Pedicels nodding at anthesis.", {"entity_en": "pedicel", "quality_en": "nodding", "stage": "at anthesis",
                                                                    "source_en": "nodding at anthesis"})
    assert during["developmental_stage_contexts"][0]["temporal_relation"] == "present_during"
    assert after["phenotype_class_iri"] != during["phenotype_class_iri"]
    (before,), _ = annotate(res, "Leaves withered before flowering.", {"entity_en": "leaf", "quality_en": "withered", "stage": "before flowering",
                                                                        "source_en": "withered before flowering"})
    assert before["developmental_stage_contexts"][0]["temporal_relation"] == "present_before"


def test_the_stage_relation_is_written_in_owl_with_its_own_property():
    from rdflib import Graph

    from flopo2.owl import assertions as owl

    graph = Graph()
    owl._developmental_stage_restrictions(graph, owl._Nodes(), {"developmental_stage_contexts": [
        {"stage_term": "PO_0007616", "temporal_relation": "present_after", "stage_text": "after anthesis"}]})
    used = {str(o) for _, p, o in graph if str(p).endswith("onProperty")}
    assert used == {str(owl.FLOPOANN.present_after_developmental_stage)}


def test_paler_beneath_compares_the_two_sides_of_the_blade(res):
    text = "Leaf blades paler beneath."
    (a,), _ = annotate(res, text, {"entity_en": "leaf blade", "quality_en": "paler", "source_en": "paler beneath"})
    target = a["towards"]
    assert (a["po_id"], a["pato_id"], target["target_term"], target["implied"]) == ("PO_0000049", "PATO_0000328", "PO_0000050", True)
    assert text[target["start"]:target["end"]] == "beneath" and target["comparison_text"] == "paler"
    assert a.get("phenotype_class_iri") and issues(a, text) == []


def test_the_inner_smaller_compares_with_the_same_part_at_the_opposite_position(res):
    text = "Anthers 6, the inner smaller."
    (a,), _ = annotate(res, text, {"entity_en": "anther", "quality_en": "smaller", "source_en": "the inner smaller"})
    target = a["towards"]
    assert (a["po_id"], a["pato_id"], a["bearer_context_qualities"]) == ("PO_0009066", "PATO_0000587", ["FLOPO_0991378"])
    assert (target["target_term"], target["counterpart_position"], target["implied"]) == ("PO_0009066", "FLOPO_0991379", True)
    assert text[target["start"]:target["end"]] == "inner" and issues(a, text) == []
    assert "counterpart_is_another_part" in issues({**a, "towards": {**target, "target_term": "PO_0009029"}}, text)


def test_a_negated_or_placeless_comparison_stays_unresolved(res):
    for text, source in (("Leaf blade not paler beneath.", "not paler beneath"), ("Anthers smaller.", "Anthers smaller")):
        assertions, dispositions = annotate(res, text, {"entity_en": "leaf blade" if "Leaf" in text else "anther",
                                                         "quality_en": source.split()[-2] if "not" in source else "smaller",
                                                         "source_en": source})
        assert assertions == [] and dispositions[0].status == "unresolved"


def test_or_more_without_to_is_a_lower_bound_on_every_plant(res):
    (a,), _ = annotate(res, "Sori with 8 or more sporangia.", {
        "entity_en": "sporangium", "quality_en": "number", "value_low": 8, "value_high": 8, "unit": "count",
        "source_en": "Sori with 8 or more sporangia"})
    assert (a["value_low"], a.get("value_high")) == (8.0, None) and not a.get("maximum_at_least")
    assert a["gate"]["status"] == "accepted" and a.get("phenotype_class_iri")
    (b,), _ = annotate(res, "Trees to 25 m or more.", {
        "entity_en": "whole plant", "quality_en": "height", "value_high": 25, "unit": "m", "source_en": "Trees to 25 m or more"})
    assert b["maximum_at_least"]["value"] == 25.0 and b["gate"]["status"] == "accepted"
