from rdflib import Graph, OWL, Literal
from flopo2.owl.trait_phenotype import (
    OBO,
    quality_role,
    build_annotations,
    PROPERTY,
)
from flopo2.verify.eq_release import eq_axioms


def test_attribute_vs_value_and_local_value():
    tags = {"attribute": {"attribute_slim"}, "value": {"value_slim"}}
    assert quality_role("attribute", tags, {}, set())[0] == "trait"
    assert quality_role("value", tags, {}, set())[0] == "phenotype"
    assert quality_role("local", tags, {"local": {"attribute"}}, {"local"})[0] == "phenotype"
    assert not quality_role("untagged", tags, {"untagged": {"attribute"}}, set())[0]


def test_conflicting_tags_are_not_silently_forced_to_a_category():
    assert not quality_role("q", {"q": {"attribute_slim", "value_slim"}}, {}, set())[0]


def test_eq_annotations_preserve_trait_subsumption_semantics():
    g = Graph()
    e = OBO + "PO_0025034"
    a = OBO + "PATO_0000014"
    v = OBO + "PATO_0000322"
    trait = eq_axioms(g, OBO + "FLOPO_1", e, a, "leaf colour", "")
    pheno = eq_axioms(g, OBO + "FLOPO_2", e, v, "leaf red", str(trait))
    tags = {a: {"attribute_slim"}, v: {"value_slim"}}
    out, rows = build_annotations(g, tags, {}, set())
    assert (trait, PROPERTY, Literal("trait")) in out
    assert (pheno, PROPERTY, Literal("phenotype")) in out
    assert not list(out.triples((None, OWL.disjointWith, None)))
    assert len(rows) == 2


def test_colour_backbone_local_values_are_not_mistaken_for_attributes():
    from pathlib import Path
    from flopo2.owl.trait_phenotype import local_value_ids

    values = local_value_ids(Path(__file__).resolve().parents[1])
    assert OBO + "FLOPO_0988000" in values
    assert (
        quality_role(
            OBO + "FLOPO_0988000", {}, {OBO + "FLOPO_0988000": {OBO + "PATO_0000014"}}, values
        )[0]
        == "phenotype"
    )


def test_union_of_attributes_is_not_misclassified_as_a_value():
    from rdflib import URIRef
    from flopo2.owl.build import HAS_PART, HAS_QUALITY, _intersection, _restriction, _union
    from flopo2.owl.trait_phenotype import classification

    graph = Graph()
    cls = URIRef(OBO + "FLOPO_3")
    length, width = URIRef(OBO + "PATO_0000122"), URIRef(OBO + "PATO_0000921")
    filler = _union(graph, [length, width])
    bearer = _intersection(
        graph, [URIRef(OBO + "PO_0025034"), _restriction(graph, HAS_QUALITY, filler)]
    )
    graph.add((cls, OWL.equivalentClass, _restriction(graph, HAS_PART, bearer)))
    tags = {str(length): {"attribute_slim"}, str(width): {"attribute_slim"}}
    assert classification(graph, cls, tags, {}, set())[0] == "trait"
    tags[str(width)] = {"value_slim"}
    assert classification(graph, cls, tags, {}, set())[0] == ""
    tags[str(length)] = {"value_slim"}
    assert classification(graph, cls, tags, {}, set())[0] == "phenotype"
