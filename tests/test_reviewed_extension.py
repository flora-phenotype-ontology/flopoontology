from __future__ import annotations

import csv
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, URIRef

from flopo2.ids.registry import load_registry
from flopo2.owl.assertions import FLOPOANN
from flopo2.owl.build import FLOPO_SUPPORT_COUNT
from flopo2.owl.reviewed_extension import FLOPO_ROOT, MODULE, build_reviewed_extension
from flopo2.owl.top_level import PLANT_STRUCTURE
from tools.update_flopo_reviewed_release import BEGIN_MARKER, update_release

OBO = "http://purl.obolibrary.org/obo/"
ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
ASSERTION = URIRef("https://w3id.org/flopo/flora-assertion/example")


def _write_registry(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["flopo_iri", "flopo_num", "label", "signature", "deprecated"])
        writer.writerow([OBO + "FLOPO_0000000", 0, "flora phenotype", "OTHER", 0])


def _write_approval(path: Path, pato_id: str = "PATO_0000320") -> None:
    fields = [
        "po_id",
        "pato_id",
        "review_status",
        "reviewer",
        "review_date",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "po_id": "PO_0025034",
                "pato_id": pato_id,
                "review_status": "approved",
                "reviewer": str(CONTRIBUTOR),
                "review_date": "2026-07-17",
            }
        )


def _write_candidate(path: Path, *, include_unapproved: bool = False) -> None:
    extra = """
obo:FLOPO_0000003 a owl:Class ;
    rdfs:label "leaf red"@en ;
    rdfs:subClassOf obo:FLOPO_0000001 ;
    owl:equivalentClass [ a owl:Restriction ;
        owl:onProperty obo:BFO_0000051 ;
        owl:someValuesFrom [ owl:intersectionOf (
            obo:PO_0025034
            [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ;
              owl:someValuesFrom obo:PATO_0000322 ]
        ) ]
    ] .
""" if include_unapproved else ""
    path.write_text(
        """@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix flopoann: <https://w3id.org/flopo/annotation/> .

obo:flopo.owl a owl:Ontology .
obo:FLOPO_0000000 a owl:Class ; rdfs:label "flora phenotype"@en .
obo:FLOPO_0000001 a owl:Class ;
    rdfs:label "leaf phenotype"@en ;
    rdfs:subClassOf obo:FLOPO_0000000 ;
    owl:equivalentClass [ a owl:Restriction ;
        owl:onProperty obo:BFO_0000051 ;
        owl:someValuesFrom [ owl:intersectionOf (
            [ a owl:Restriction ; owl:onProperty obo:BFO_0000050 ;
              owl:someValuesFrom obo:PO_0025034 ]
            [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ;
              owl:someValuesFrom obo:PATO_0000001 ]
        ) ]
    ] .
obo:FLOPO_0000002 a owl:Class ;
    rdfs:label "leaf green"@en ;
    rdfs:subClassOf obo:FLOPO_0000001 ;
    obo:FLOPO_supporting_assertion_count 4 ;
    flopoann:supported_by_assertion <https://w3id.org/flopo/flora-assertion/example> ;
    owl:equivalentClass [ a owl:Restriction ;
        owl:onProperty obo:BFO_0000051 ;
        owl:someValuesFrom [ owl:intersectionOf (
            obo:PO_0025034
            [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ;
              owl:someValuesFrom obo:PATO_0000320 ]
        ) ]
    ] .
"""
        + extra,
        encoding="utf-8",
    )


def _inputs(tmp_path: Path, *, include_unapproved: bool = False) -> tuple[Path, Path, Path]:
    candidate = tmp_path / "candidate.ttl"
    registry = tmp_path / "registry.tsv"
    approvals = tmp_path / "approvals.tsv"
    _write_candidate(candidate, include_unapproved=include_unapproved)
    _write_registry(registry)
    _write_approval(approvals)
    return candidate, registry, approvals


def test_reviewed_module_copies_only_new_approved_classes_and_axiom_closure(tmp_path):
    candidate, registry, approvals = _inputs(tmp_path)
    output = tmp_path / "reviewed.ttl"
    reservations = tmp_path / "reservations.tsv"

    stats = build_reviewed_extension(
        candidate,
        registry,
        approvals,
        output,
        "2026-07-17",
        reservations_path=reservations,
        expected_approved=1,
        expected_new_eq=1,
        expected_new_pheno=1,
    )
    graph = Graph().parse(output)
    pheno = URIRef(OBO + "FLOPO_0000001")
    eq = URIRef(OBO + "FLOPO_0000002")

    assert stats["total_new"] == 2
    assert set(
        cls
        for cls in graph.subjects(DCTERMS.source, None)
        if str(cls).startswith(OBO + "FLOPO_")
    ) == {pheno, eq}
    assert (eq, DCTERMS.contributor, CONTRIBUTOR) in graph
    assert (eq, FLOPO_SUPPORT_COUNT, None) in graph
    assert (eq, FLOPOANN.supported_by_assertion, ASSERTION) in graph
    assert (pheno, RDFS.subClassOf, URIRef(OBO + PLANT_STRUCTURE)) in graph
    assert (pheno, RDFS.subClassOf, FLOPO_ROOT) not in graph
    expression = next(graph.objects(eq, OWL.equivalentClass))
    assert isinstance(expression, BNode)
    assert (expression, RDF.type, OWL.Restriction) in graph
    assert (MODULE, RDF.type, OWL.Ontology) in graph
    reserved = load_registry(reservations)
    assert {entry.iri for entry in reserved} == {str(pheno), str(eq)}
    assert stats["reservations"] == str(reservations)


def test_reviewed_module_rejects_any_unapproved_new_eq_class(tmp_path):
    candidate, registry, approvals = _inputs(tmp_path, include_unapproved=True)
    with pytest.raises(ValueError, match="unapproved new EQ"):
        build_reviewed_extension(
            candidate, registry, approvals, tmp_path / "out.ttl", "2026-07-17"
        )


def test_reviewed_release_embedding_is_idempotent_and_keeps_evidence(tmp_path):
    candidate, registry, approvals = _inputs(tmp_path)
    module = tmp_path / "reviewed.ttl"
    build_reviewed_extension(
        candidate, registry, approvals, module, "2026-07-17"
    )
    release = tmp_path / "flopo.owl"
    release.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:obo="http://purl.obolibrary.org/obo/">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-07-16/flopo.owl"/>
    <owl:versionInfo>2026-07-16</owl:versionInfo>
  </owl:Ontology>
</rdf:RDF>
''',
        encoding="utf-8",
    )

    assert update_release(release, module, "2026-07-17") == 2
    first = release.read_text(encoding="utf-8")
    assert update_release(release, module, "2026-07-17") == 2
    assert release.read_text(encoding="utf-8") == first
    assert first.count(BEGIN_MARKER) == 1
    assert 'xmlns:flopoann="https://w3id.org/flopo/annotation/"' in first
    graph = Graph().parse(release)
    eq = URIRef(OBO + "FLOPO_0000002")
    assert (eq, FLOPOANN.supported_by_assertion, ASSERTION) in graph
    assert (MODULE, RDF.type, OWL.Ontology) not in graph


def test_real_reviewed_module_preserves_released_upper_level(tmp_path):
    module_path = ROOT / "ontology" / "flopo-reviewed-combinations.ttl"
    module = Graph().parse(module_path.as_posix())
    plant_structure = URIRef(OBO + PLANT_STRUCTURE)
    promoted = {
        cls
        for cls in module.subjects(DCTERMS.source, None)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    new_pheno = {
        cls for cls in promoted if (cls, RDFS.subClassOf, plant_structure) in module
    }

    assert len(promoted) == 366
    assert len(new_pheno) == 16
    assert not any((cls, RDFS.subClassOf, FLOPO_ROOT) in module for cls in promoted)

    candidate = tmp_path / "flopo.owl"
    shutil.copyfile(ROOT / "ontology" / "flopo.owl", candidate)
    assert update_release(candidate, module_path, "2026-07-31") == 366
    graph = Graph().parse(candidate.as_posix())
    direct_children = {
        child
        for child in graph.subjects(RDFS.subClassOf, FLOPO_ROOT)
        if isinstance(child, URIRef) and str(child).startswith(OBO + "FLOPO_")
    }
    flopo_classes = {
        cls
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }

    assert direct_children == {
        URIRef(OBO + "FLOPO_0980417"),
        URIRef(OBO + "FLOPO_0980422"),
    }
    assert len(flopo_classes) == 25_055


def test_real_reviewed_ids_are_reserved_and_catalog_target_exists():
    reservations = load_registry(
        ROOT / "config" / "flopo_reviewed_id_reservations.tsv"
    )
    module = Graph().parse(
        (ROOT / "ontology" / "flopo-reviewed-combinations.ttl").as_posix()
    )
    promoted = {
        str(cls)
        for cls in module.subjects(DCTERMS.source, None)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    released = {entry.iri for entry in load_registry(ROOT / "config" / "flopo_id_registry.tsv")}

    assert len(reservations) == 366
    assert [entry.flopo_num for entry in reservations] == list(range(980611, 980977))
    assert {entry.iri for entry in reservations} == promoted
    assert not (promoted & released)
    assert all(entry.signature != "OTHER" for entry in reservations)

    namespace = {"c": "urn:oasis:names:tc:entity:xmlns:xml:catalog"}
    catalog = ET.parse(ROOT / "ontology" / "catalog-v001.xml").getroot()
    mapping = next(
        row.attrib["uri"]
        for row in catalog.findall(".//c:uri", namespace)
        if row.attrib["name"]
        == "http://purl.obolibrary.org/obo/flopo-reviewed-combinations.owl"
    )
    assert (ROOT / "ontology" / mapping).is_file()
