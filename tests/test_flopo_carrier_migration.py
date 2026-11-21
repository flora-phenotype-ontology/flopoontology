"""The named FLOPO classes of arrangements and whorl relations are defined on the structure that
carries the parts (tools/update_flopo_carrier_release.py, docs/odp/16-...), and keep their
identifier, label and registry signature."""

from __future__ import annotations

from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.collection import Collection

from flopo2.ids.registry import _signature_of
from flopo2.owl import carrier

OBO = "http://purl.obolibrary.org/obo/"
MODULE = Path("ontology/flopo-carrier-migration.ttl")
HAS_PART, HAS_CHARACTERISTIC, TOWARDS = (URIRef(OBO + i) for i in ("BFO_0000051", "RO_0000053", "RO_0002503"))


def _filler(graph, node, prop):
    assert graph.value(node, OWL.onProperty) == prop
    return graph.value(node, OWL.someValuesFrom)


def _members(graph, node):
    return list(Collection(graph, graph.value(node, OWL.intersectionOf)))


def test_each_class_has_one_definition_on_its_carrier_and_keeps_its_signature():
    graph = Graph().parse(MODULE.as_posix())
    classes = [c for c in graph.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef) and "FLOPO_" in str(c)]
    assert len(classes) >= 50
    for cls in classes:
        (definition,) = graph.objects(cls, OWL.equivalentClass)
        whole, bears = _members(graph, _filler(graph, definition, HAS_PART))
        value, towards = _members(graph, _filler(graph, bears, HAS_CHARACTERISTIC))
        part = _filler(graph, towards, TOWARDS)
        local = lambda iri: str(iri).removeprefix(OBO)  # noqa: E731
        slot = carrier.expected(local(part), local(value))
        assert slot is not None and slot["carrier_term"] == local(whole), cls
        assert _signature_of(graph, cls) == f"EQ|{local(part)}|{local(value)}"
        assert graph.value(cls, RDFS.label)
        text = str(graph.value(cls, URIRef(OBO + "IAO_0000115")))
        assert text.startswith("A flora phenotype in which") and "http" not in text
        parents = [p for p in graph.objects(cls, RDFS.subClassOf) if "FLOPO_" in str(p)]
        assert len(parents) == 1  # the phenotype class of the carrier


def test_leaf_alternate_placement_is_a_quality_of_the_shoot_axis():
    graph = Graph().parse(MODULE.as_posix())
    cls = URIRef(OBO + "FLOPO_0001032")
    assert str(graph.value(cls, RDFS.label)) == "leaf alternate placement"
    assert str(graph.value(cls, URIRef(OBO + "IAO_0000115"))) == (
        "A flora phenotype in which a shoot axis bears its leaves in an alternate arrangement.")
    assert (cls, RDFS.subClassOf, URIRef(OBO + "FLOPO_0008318")) in graph  # shoot axis phenotype


def test_a_plain_part_and_quality_class_keeps_its_plain_signature():
    graph = Graph().parse(data="""
@prefix obo: <http://purl.obolibrary.org/obo/> . @prefix owl: <http://www.w3.org/2002/07/owl#> .
obo:FLOPO_1 a owl:Class ; owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
  owl:someValuesFrom [ a owl:Class ; owl:intersectionOf ( obo:PO_0025034 [ a owl:Restriction ;
    owl:onProperty obo:RO_0000053 ; owl:someValuesFrom obo:PATO_0000320 ] ) ] ] .
obo:FLOPO_2 a owl:Class ; owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
  owl:someValuesFrom [ a owl:Class ; owl:intersectionOf ( obo:PO_0009047 [ a owl:Restriction ;
    owl:onProperty obo:RO_0000053 ; owl:someValuesFrom [ a owl:Class ; owl:intersectionOf ( obo:PATO_0001932
      [ a owl:Restriction ; owl:onProperty obo:RO_0002503 ; owl:someValuesFrom obo:PO_0025034 ] ) ] ] ) ] ] .
""", format="turtle")
    assert _signature_of(graph, URIRef(OBO + "FLOPO_1")) == "EQ|PO_0025034|PATO_0000320"
    # the stem is not the carrier the tables give for leaves: not a class of the pattern
    assert _signature_of(graph, URIRef(OBO + "FLOPO_2")) == "OTHER"
