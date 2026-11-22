"""Phenotype classes as phenes (flopo2/owl/phene.py, tools/update_flopo_phene_form.py).

    P EquivalentTo: 'flora phenotype' and 'phenotype of' some <defining property>

Hoehndorf, Oellrich and Rebholz-Schuhmann 2010 (doi:10.1093/bioinformatics/btq578); the quality
reading of Gkoutos, Schofield and Hoehndorf 2018 (doi:10.1093/bib/bbx035).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, BNode, Graph, URIRef
from rdflib.compare import isomorphic

from flopo2.owl import phene
from tools import update_flopo_phene_form as form

OBO = "http://purl.obolibrary.org/obo/"
RELEASE = Path("ontology/flopo.owl")

SMALL = f"""<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF
  xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
  xmlns:owl="http://www.w3.org/2002/07/owl#"
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
>
  <owl:Ontology rdf:about="{OBO}flopo.owl">
    <owl:versionIRI rdf:resource="{OBO}flopo/releases/2026-11-21/flopo.owl"/>
    <owl:versionInfo>2026-11-21</owl:versionInfo>
  </owl:Ontology>
  <!-- BEGIN GENERATED SOMETHING -->
  <owl:Class rdf:about="{OBO}FLOPO_0000000"><rdfs:label xml:lang="en">flora phenotype</rdfs:label></owl:Class>
  <owl:Class rdf:about="{OBO}FLOPO_0000010">
    <rdfs:label>leaf glabrous</rdfs:label>
    <owl:equivalentClass>
      <owl:Restriction rdf:nodeID="A1">
        <owl:onProperty rdf:resource="{OBO}BFO_0000051"/>
        <owl:someValuesFrom>
          <owl:Class rdf:nodeID="A2">
            <owl:intersectionOf rdf:parseType="Collection">
              <rdf:Description rdf:about="{OBO}PO_0025034"/>
              <owl:Restriction rdf:nodeID="A3">
                <owl:onProperty rdf:resource="{OBO}RO_0000053"/>
                <owl:someValuesFrom rdf:resource="{OBO}PATO_0000453"/>
              </owl:Restriction>
            </owl:intersectionOf>
          </owl:Class>
        </owl:someValuesFrom>
      </owl:Restriction>
    </owl:equivalentClass>
  </owl:Class>
  <!-- END GENERATED SOMETHING -->
  <rdf:Description rdf:about="{OBO}FLOPO_0000011">
    <rdf:type rdf:resource="http://www.w3.org/2002/07/owl#Class"/>
    <rdfs:label>leaf phenotype</rdfs:label>
    <owl:equivalentClass rdf:nodeID="B1"/>
  </rdf:Description>
  <owl:Restriction rdf:nodeID="B1">
    <owl:onProperty rdf:resource="{OBO}BFO_0000051"/>
    <owl:someValuesFrom>
      <owl:Restriction rdf:nodeID="B2">
        <owl:onProperty rdf:resource="{OBO}BFO_0000050"/>
        <owl:someValuesFrom rdf:resource="{OBO}PO_0025034"/>
      </owl:Restriction>
    </owl:someValuesFrom>
  </owl:Restriction>
  <rdf:Description rdf:about="{OBO}FLOPO_0000012">
    <rdfs:label>whole plant arborescent</rdfs:label>
    <rdfs:subClassOf rdf:resource="{OBO}FLOPO_0000000"/>
    <rdfs:subClassOf>
      <owl:Restriction rdf:nodeID="C1">
        <owl:onProperty rdf:resource="{OBO}BFO_0000051"/>
        <owl:someValuesFrom rdf:resource="{OBO}FLOPO_0985025"/>
      </owl:Restriction>
    </rdfs:subClassOf>
  </rdf:Description>
  <rdf:Description rdf:about="{OBO}FLOPO_0985029">
    <rdfs:label>cyathium</rdfs:label>
    <rdfs:subClassOf rdf:resource="{OBO}PO_0009049"/>
    <rdfs:subClassOf>
      <owl:Restriction rdf:nodeID="D1">
        <owl:onProperty rdf:resource="{OBO}BFO_0000051"/>
        <owl:someValuesFrom rdf:resource="{OBO}PO_0009046"/>
      </owl:Restriction>
    </rdfs:subClassOf>
  </rdf:Description>
  <owl:Restriction rdf:nodeID="G1">
    <owl:onProperty rdf:resource="{OBO}BFO_0000051"/>
    <owl:someValuesFrom>
      <owl:Restriction rdf:nodeID="G2">
        <owl:onProperty rdf:resource="{OBO}RO_0000053"/>
        <owl:someValuesFrom rdf:resource="{OBO}PATO_0000370"/>
      </owl:Restriction>
    </owl:someValuesFrom>
    <rdfs:subClassOf rdf:resource="http://www.w3.org/2002/07/owl#Nothing"/>
  </owl:Restriction>
</rdf:RDF>
"""


def _class(local: str) -> URIRef:
    return URIRef(OBO + local)


def test_definitions_and_necessary_conditions_of_phenotype_classes_become_phenes():
    text, counts = form.wrap_text(SMALL)
    assert counts == {"equivalent": 2, "subclass": 1, "already": 0}
    graph = Graph().parse(data=text, format="xml")
    for local in ("FLOPO_0000010", "FLOPO_0000011"):
        (expression,) = graph.objects(_class(local), OWL.equivalentClass)
        members = list(graph.items(graph.value(expression, OWL.intersectionOf)))
        assert members[0] == phene.PHENOTYPE and len(members) == 2
        assert graph.value(members[1], OWL.onProperty) == phene.PHENOTYPE_OF
        body = graph.value(members[1], OWL.someValuesFrom)
        assert graph.value(body, OWL.onProperty) == phene.HAS_PART  # the defining property, untouched
    (condition,) = [o for o in graph.objects(_class("FLOPO_0000012"), RDFS.subClassOf) if isinstance(o, BNode)]
    assert graph.value(condition, OWL.onProperty) == phene.PHENOTYPE_OF
    assert graph.value(graph.value(condition, OWL.someValuesFrom), OWL.someValuesFrom) == _class("FLOPO_0985025")


def test_axioms_about_plants_are_left_alone():
    graph = Graph().parse(data=form.wrap_text(SMALL)[0], format="xml")
    # an anatomy class (beneath a Plant Ontology class) keeps its parts
    (parts,) = [o for o in graph.objects(_class("FLOPO_0985029"), RDFS.subClassOf) if isinstance(o, BNode)]
    assert graph.value(parts, OWL.onProperty) == phene.HAS_PART
    # the general class axiom that rules out a process quality on a plant part is about plants
    (general,) = [s for s in graph.subjects(RDFS.subClassOf, OWL.Nothing)]
    assert graph.value(general, OWL.onProperty) == phene.HAS_PART


def test_the_pass_is_idempotent_and_keeps_the_layout_of_the_file():
    once, _ = form.wrap_text(SMALL)
    twice, counts = form.wrap_text(once)
    assert twice == once and counts == {"equivalent": 0, "subclass": 0, "already": 3}
    assert once.startswith(SMALL[: SMALL.index(">", SMALL.index("<rdf:RDF")) + 1])  # header as written
    for marker in ("<!-- BEGIN GENERATED SOMETHING -->", "<!-- END GENERATED SOMETHING -->",
                   form.BEGIN_MARKER, form.END_MARKER):
        assert once.count(marker) == 1
    assert once.rstrip().endswith("</rdf:RDF>")


def test_the_relations_are_declared_with_the_axioms_the_form_rests_on():
    graph = Graph().parse(data=form.wrap_text(SMALL)[0], format="xml")
    assert (phene.PHENOTYPE_OF, RDF.type, OWL.FunctionalProperty) in graph
    assert (phene.HAS_PHENOTYPE, OWL.inverseOf, phene.PHENOTYPE_OF) in graph
    assert str(phene.PHENOTYPE_OF) == OBO + "RO_0002201" and str(phene.HAS_PHENOTYPE) == OBO + "RO_0002200"


def test_the_defining_view_gives_back_the_classes_as_they_were_written():
    """Code that analyses defining properties (registry, text definitions, trait or value) reads
    the release through this view: it must be the graph before the pass, nothing lost or left."""

    before = Graph().parse(data=SMALL, format="xml")
    view = phene.defining_view(Graph().parse(data=form.wrap_text(SMALL)[0], format="xml"))
    for triple in list(view.triples((phene.PHENOTYPE_OF, None, None))) + list(view.triples((phene.HAS_PHENOTYPE, None, None))):
        view.remove(triple)
    assert isomorphic(before, view)


def test_phene_body_and_phene_are_inverse_and_allow_a_season_beside():
    graph = Graph()
    body = BNode()
    graph.add((body, RDF.type, OWL.Restriction))
    graph.add((body, OWL.onProperty, phene.HAS_PART))
    graph.add((body, OWL.someValuesFrom, _class("PO_0025034")))
    assert phene.phene_body(graph, phene.phene(graph, body)) == body
    assert phene.phene_body(graph, body) is None  # a property of the plant is not a phene
    from flopo2.owl import assertions

    seasonal = {"po_id": "PO_0009046", "pato_id": "PATO_0000323", "value_terms": [], "season_ids": ["ENVO_01000775"]}
    expression = assertions._phenotype_expression(graph, assertions._Nodes(), seasonal, set())[0]
    inner = phene.phene_body(graph, expression)
    assert inner is not None and graph.value(inner, OWL.onProperty) == phene.HAS_PART


def test_bearer_axioms_state_the_step_from_the_phene_to_the_plant():
    graph = Graph().parse(data=form.wrap_text(SMALL)[0], format="xml")
    classes = phene.phene_classes(graph)
    assert {str(c).rsplit("_", 1)[1] for c in classes} == {"0000010", "0000011", "0000012"}
    axioms = phene.bearer_axioms(graph)
    assert len(list(axioms.subject_objects(RDFS.subClassOf))) == 3
    for bearer, body in axioms.subject_objects(RDFS.subClassOf):
        assert axioms.value(bearer, OWL.onProperty) == phene.HAS_PHENOTYPE
        cls = axioms.value(bearer, OWL.someValuesFrom)
        assert body in classes[cls]


# --- the release ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def release() -> Graph:
    return Graph().parse(RELEASE.as_posix())


def test_every_phenotype_class_of_the_release_is_a_phene(release):
    assert form.unwrapped(release) == []
    phenes = phene.phene_classes(release)
    assert len(phenes) > 25000
    assert all(str(cls).startswith(OBO + "FLOPO_") for cls in phenes)
    assert (phene.PHENOTYPE_OF, RDF.type, OWL.FunctionalProperty) in release
    assert (phene.HAS_PHENOTYPE, OWL.inverseOf, phene.PHENOTYPE_OF) in release


def test_no_class_of_the_release_is_defined_as_a_class_of_plants(release):
    """The two readings are not mixed: no FLOPO class is equivalent to a 'has part' expression,
    and the general class axioms about plants have no FLOPO class in them."""

    for cls, expression in release.subject_objects(OWL.equivalentClass):
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_"):
            assert (expression, OWL.onProperty, phene.HAS_PART) not in release, cls


def test_the_registry_reads_the_same_signatures_through_the_defining_view():
    import csv

    from flopo2.ids.registry import build_registry

    with Path("config/flopo_id_registry.tsv").open(encoding="utf-8", newline="") as handle:
        stored = {row["flopo_iri"]: row["signature"] for row in csv.DictReader(handle, delimiter="\t")}
    built = {entry.iri: entry.signature for entry in build_registry(RELEASE)}
    assert built == stored
    assert sum(1 for s in built.values() if s.startswith("EQ|")) > 25000


# --- the ELK check of the bearers ------------------------------------------------------------

CONTRADICTING = f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo: <{OBO}> .
<urn:test> a owl:Ontology .
obo:BFO_0000051 a owl:ObjectProperty . obo:RO_0000053 a owl:ObjectProperty .
obo:RO_0002201 a owl:ObjectProperty . obo:RO_0002200 a owl:ObjectProperty .
obo:PO_1 a owl:Class . obo:PATO_1 a owl:Class . obo:PATO_2 a owl:Class .
obo:FLOPO_0000000 a owl:Class .
# a leaf with quality 1, a leaf with quality 2; no plant has both kinds of leaf
obo:FLOPO_0000001 a owl:Class ; owl:equivalentClass [ owl:intersectionOf ( obo:FLOPO_0000000
    [ a owl:Restriction ; owl:onProperty obo:RO_0002201 ; owl:someValuesFrom _:one ] ) ] .
obo:FLOPO_0000002 a owl:Class ; owl:equivalentClass [ owl:intersectionOf ( obo:FLOPO_0000000
    [ a owl:Restriction ; owl:onProperty obo:RO_0002201 ; owl:someValuesFrom _:two ] ) ] .
_:one a owl:Restriction ; owl:onProperty obo:BFO_0000051 ; owl:someValuesFrom [ owl:intersectionOf ( obo:PO_1
    [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ; owl:someValuesFrom obo:PATO_1 ] ) ] .
_:two a owl:Restriction ; owl:onProperty obo:BFO_0000051 ; owl:someValuesFrom [ owl:intersectionOf ( obo:PO_1
    [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ; owl:someValuesFrom obo:PATO_2 ] ) ] .
obo:PlantOne a owl:Class ; owl:equivalentClass _:one .
obo:PlantTwo a owl:Class ; owl:equivalentClass _:two ; owl:disjointWith obo:PlantOne .
# asserted, not entailed: the phene of one kind of leaf placed under the phene of the other
obo:FLOPO_0000001 rdfs:subClassOf obo:FLOPO_0000002 .
"""


def _elk_unsatisfiable(graph: Graph, work: Path) -> set[str]:
    from tools import classify_flopo_release as release_tools

    source = work / "input.owl"
    graph.serialize(source.as_posix(), format="xml")
    robot = release_tools._robot_command(Path(release_tools.__file__).resolve().parents[1])
    done = subprocess.run([*robot, "reason", "--reasoner", "ELK", "--input", str(source), "--output",
                           str(work / "out.ofn")], capture_output=True, text=True, check=False)
    import re

    return set(re.findall(r"unsatisfiable:\s*(\S+)", done.stdout + done.stderr))


@pytest.mark.skipif(shutil.which("java") is None, reason="needs Java for ROBOT/ELK")
def test_elk_finds_a_phenotype_no_plant_can_have_only_with_the_bearer_axioms(tmp_path):
    """FLOPO:1 is asserted under FLOPO:2, but no plant has both defining properties. As phenes
    the two classes are satisfiable for ELK (it does not read the functional property); with the
    bearer axioms the plant that has FLOPO:1 is unsatisfiable."""

    from tools import check_flopo_phene_bearers as check

    plain = Graph().parse(data=CONTRADICTING, format="turtle")
    assert _elk_unsatisfiable(plain, tmp_path) == set()
    graph = Graph().parse(data=CONTRADICTING, format="turtle")
    probes = check.with_bearers(graph)
    found = {probes[iri] for iri in _elk_unsatisfiable(graph, tmp_path) if iri in probes}
    assert found == {OBO + "FLOPO_0000001"}
