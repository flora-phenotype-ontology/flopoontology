"""Pattern 18: the position of the bearer has its own relation, and frequent positioned parts a name."""

from __future__ import annotations

from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.collection import Collection

from flopo2.owl import assertions, position

OBO = "http://purl.obolibrary.org/obo/"


def _restrictions(graph: Graph) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for node in graph.subjects(RDF.type, OWL.Restriction):
        found.setdefault(str(graph.value(node, OWL.onProperty)), set()).add(str(graph.value(node, OWL.someValuesFrom)))
    return found


def test_a_position_is_written_with_has_position_and_a_state_with_has_characteristic():
    from flopo2.verify import gates

    attributes = gates.load_pato_attribute_terms(Path("config/pato_lexicon.tsv"))
    graph = Graph()
    record = {"po_id": "PO_0025034", "pato_id": "PATO_0000453", "value_terms": [], "value_operator": "atomic",
              "negated": False, "bearer_context_qualities": ["FLOPO_0991002", "PATO_0000309"]}
    assertions.defining_property(graph, assertions._Nodes(), record, attributes)
    by_property = _restrictions(graph)
    assert by_property[str(position.HAS_POSITION)] == {OBO + "FLOPO_0991002"}
    assert {OBO + "PATO_0000309", OBO + "PATO_0000453"} <= by_property[str(position.HAS_CHARACTERISTIC)]
    assert (position.HAS_POSITION, RDFS.subPropertyOf, position.HAS_CHARACTERISTIC) in graph


def test_the_class_identifier_does_not_depend_on_the_relation():
    from flopo2.owl.annotation_class import annotation_class_iri

    record = {"po_id": "PO_0025034", "pato_id": "PATO_0000453", "value_terms": [], "value_operator": "atomic",
              "negated": False, "bearer_context_qualities": ["FLOPO_0991002"]}
    assert annotation_class_iri(record).startswith("http://phenomebrowser.net/flopo/annotation-class/FAC_")
    assert position.is_position("FLOPO:0991002") and not position.is_position("PATO_0000309")


def test_the_release_names_the_frequent_positioned_parts():
    graph = Graph().parse("ontology/flopo.owl")
    assert (position.HAS_POSITION, RDFS.subPropertyOf, position.HAS_CHARACTERISTIC) in graph
    parts = position.positioned_parts()
    assert len(parts) >= 40 and len({identifier for identifier, _ in parts.values()}) == len(parts)
    for (part, value), (identifier, label) in parts.items():
        cls = URIRef(OBO + identifier)
        expressions = [e for e in graph.objects(cls, OWL.equivalentClass) if graph.value(e, OWL.intersectionOf)]
        members = [list(Collection(graph, graph.value(e, OWL.intersectionOf))) for e in expressions]
        matching = [m for m in members if URIRef(OBO + part) in m and any(
            (r, OWL.onProperty, position.HAS_POSITION) in graph and (r, OWL.someValuesFrom, URIRef(OBO + value)) in graph
            for r in m)]
        assert matching, f"{identifier} {label} is not defined by 'has position'"
        if identifier.startswith("FLOPO_"):
            assert str(graph.value(cls, RDFS.label)) == label
            assert (cls, RDFS.subClassOf, URIRef(OBO + part)) in graph
