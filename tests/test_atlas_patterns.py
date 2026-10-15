from flopo2.ingest.ncvc_annotate import (
    alternatives_as_union,
    count_from_text,
    normalize_counts,
    split_inline_alternatives,
)
from flopo2.extract.measurement import is_supported_count


def _row(entity, quality, low=None, high=None, unit=""):
    return {"entity_en": entity, "quality_en": quality, "value_low": low, "value_high": high, "unit": unit,
            "source_en": "", "qualifiers": {}}


def test_counts_name_the_counted_part():
    rec = {"phenotypes": [
        _row("seed", "count per fruit", 1, 1),
        _row("inflorescence", "number of flowers", 4, 5, "flowers"),
        _row("fruit", "has number of seed", 1, 1, "seed"),
        _row("fruit locule", "number (three-celled)", 3, 3, "locules"),
        _row("leaflet", "amount", 11, 15, "pairs"),
        _row("leaf", "length", 2, 3, "cm"),
    ]}
    normalize_counts(rec)
    seen = [(p["entity_en"], p["quality_en"], p["unit"], p.get("count_container", "")) for p in rec["phenotypes"]]
    assert seen[:4] == [
        ("seed", "amount", "count", "fruit"),
        ("flower", "amount", "count", "inflorescence"),
        ("seed", "amount", "count", "fruit"),
        ("fruit locule", "amount", "count", ""),
    ]
    assert seen[4][1:3] == ("amount", "count") and rec["phenotypes"][4]["count_collection_size"] == 2
    assert seen[5][1:3] == ("length", "cm")


def test_count_phrases_and_unit():
    assert count_from_text("four petals") == (4.0, 4.0, "petal")
    assert count_from_text("containing 2 to 3 seeds") == (2.0, 3.0, "seed")
    assert count_from_text("a single seed") == (1.0, 1.0, "seed")
    assert count_from_text("five-parted") is None
    assert is_supported_count("count", "PATO_0000070")
    assert not is_supported_count("count", "PATO_0000122")


def test_inline_alternatives_are_split():
    rec = {"phenotypes": [_row("whole plant", "shrub or small tree"), _row("fruit", "ovate to subglobose"),
                          _row("leaf", "linear, ovate or lanceolate"), _row("leaf", "dark green")]}
    split_inline_alternatives(rec)
    assert [(p["quality_en"], p["qualifiers"].get("alternatives")) for p in rec["phenotypes"]] == [
        ("shrub", ["small tree"]), ("ovate", ["subglobose"]), ("linear", ["ovate", "lanceolate"]), ("dark green", None)]


def _relation(interpretation, connector, a, b, pato="PATO_0000052"):
    return {"pato_id": pato, "relation": {"interpretation": interpretation, "connector_text": connector,
                                          "from_value": a, "to_value": b, "from_start": 0, "to_end": 10}}


def test_only_or_alternatives_become_unions():
    union = alternatives_as_union(_relation("taxon_level_alternatives", " or ", "A", "B"), [])
    assert union["values"] == ["A", "B"]
    chain = alternatives_as_union(_relation("taxon_level_alternatives", ", ", "A", "B"),
                                  [_relation("taxon_level_alternatives", " or ", "B", "C")])
    assert chain["values"] == ["A", "B", "C"]
    assert alternatives_as_union(_relation("taxon_level_alternatives", " and ", "A", "B"), []) is None
    assert alternatives_as_union(_relation("continuum", " to ", "A", "B"), []) is None
    assert alternatives_as_union(_relation("taxon_level_alternatives", " or ", "A", "B"),
                                 [_relation("taxon_level_alternatives", " or ", "B", "C", "PATO_0000014")]) is None


def test_count_containers_and_pairs():
    rec = {"phenotypes": [
        _row("seed", "count per fruit", 1, 1),
        _row("leaflet", "amount", 11, 15, "pairs"),
        _row("leaf", "amount of pinna pairs", 1, 2, "pairs"),
        _row("fruit", "number per leaf axil", 1, 3, "fruits"),
    ]}
    rec["phenotypes"][1]["source_en"] = "11-15 pairs of leaflets per pinna"
    normalize_counts(rec)
    got = [(p["entity_en"], p["count_container"], p["count_collection_size"]) for p in rec["phenotypes"]]
    assert got == [("seed", "fruit", None), ("leaflet", "pinna", 2), ("pinna", "leaf", 2), ("fruit", "leaf axil", None)]


def test_container_and_collection_in_owl_and_signature():
    from rdflib import Graph, URIRef
    from flopo2.owl import assertions as owl
    from flopo2.owl.annotation_class import annotation_class_iri
    from flopo2.verify.gates import assertion_signature

    base = {"po_id": "PO_0020049", "pato_id": "PATO_0000070", "value_terms": [], "value_low": 11,
            "value_high": 15, "unit": "count"}
    pairs = {**base, "bearer_collection_size": 2, "bearer_container": "PO_0020050"}
    graph = Graph()
    owl._phenotype_expression(graph, owl._Nodes(), pairs, {"PATO_0000070"})
    assert (None, owl.OWL.onClass, URIRef(owl.OBO + "PO_0020049")) in graph
    assert (None, owl.OWL.someValuesFrom, URIRef(owl.OBO + "PO_0020050")) in graph
    assert len({annotation_class_iri(base), annotation_class_iri(pairs),
                annotation_class_iri({**base, "bearer_container": "PO_0020050"})}) == 3
    assert assertion_signature(pairs) == "EQC|PO_0020049|2|PATO_0000070"


def test_groups_are_collections():
    rec = {"phenotypes": [_row("flower", "number", 4, 6), _row("seed", "number", 2, 2, "seeds")]}
    rec["phenotypes"][0]["source_en"] = "flowers in groups of 4–6"
    rec["phenotypes"][1].update(entity_en="fruit (seed cone)", source_en="containing two seeds")
    normalize_counts(rec)
    group, seeds = rec["phenotypes"]
    assert (group["count_of"], group["count_container"], group["count_collection"]) == ("flower", "", True)
    assert (seeds["count_of"], seeds["count_container"], seeds["count_collection"]) == ("seed", "fruit", False)

    from rdflib import Graph, URIRef
    from flopo2.owl import assertions as owl
    graph = Graph()
    owl._phenotype_expression(graph, owl._Nodes(), {"po_id": "PO_0009046", "pato_id": "PATO_0000070", "value_terms": [],
                                                     "value_low": 4, "value_high": 6, "unit": "count", "bearer_collection": True},
                              {"PATO_0000070"})
    assert (None, owl.OWL.onProperty, owl.HAS_MEMBER) in graph
    assert (None, owl.OWL.someValuesFrom, URIRef(owl.OBO + "PO_0009046")) in graph


def test_comma_lists_are_conjunctions_and_tending_to_is_a_connector():
    rec = {"phenotypes": [_row("exocarp", "thin, leathery"), _row("fruit", "red tending to purple")]}
    split_inline_alternatives(rec)
    got = [(p["quality_en"], p["qualifiers"].get("alternatives")) for p in rec["phenotypes"]]
    assert got == [("thin", None), ("red", ["purple"]), ("leathery", None)]


def test_measurement_in_quality():
    from flopo2.ingest.ncvc_annotate import measurements_from_quality

    rec = {"phenotypes": [_row("spine", "2-5 cm long"), _row("stem", "60 cm tall"), _row("leaf", "linear")]}
    measurements_from_quality(rec)
    got = [(p["quality_en"], p["value_low"], p["value_high"], p["unit"]) for p in rec["phenotypes"]]
    assert got == [("length", 2.0, 5.0, "cm"), ("height", 60.0, 60.0, "cm"), ("linear", None, None, "")]


def test_compound_shapes_are_read_as_continua():
    from pathlib import Path

    from flopo2.ingest import ncvc_annotate as na

    res = na.load_resources()
    res.rules = na.merge_rules(res.rules, [], [Path("flopo2/ingest/flora_value_term_rules.tsv"),
                                               Path("flopo2/ingest/collenette_normalization.tsv")])
    chain = na.chain_from_phrase(res, "ovate to elongate-linear", ["leaf"])
    assert [v["term"] for v in chain["values"]] == ["ovate", "linear"]
    chain = na.chain_from_phrase(res, "pods linear-lanceolate to oblong-ovate in shape", ["fruit"])
    assert [v["term"] for v in chain["values"]] == ["linear", "lanceolate", "oblong", "ovate"]
    assert {c["interpretation"] for c in chain["connectors"]} == {"continuum"}
    chain = na.chain_from_phrase(res, "linear, ovate or lanceolate", ["leaf"])
    assert {c["interpretation"] for c in chain["connectors"]} == {"taxon_level_alternatives"}
    assert na.chain_from_phrase(res, "divided into linear-lanceolate [segments]", ["leaf"])["values"][1]["term"] == "lanceolate"
