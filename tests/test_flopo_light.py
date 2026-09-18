from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, Literal, URIRef

from flopo2.owl.light import (
    ANATOMICAL_ENTITY_PHENOTYPE,
    FULL_ONTOLOGY,
    HAS_PART,
    LIGHT_ONTOLOGY,
    ROOT_CLASS,
    build_light_ontology,
)
from tools.build_flopo_pubescent_migration import (
    BOTANICAL_PUBESCENCE,
    PUBESCENCE_PHENOTYPE,
    equivalent_class_uses_quality,
)


OBO = "http://purl.obolibrary.org/obo/"
CONTINUANT = URIRef(OBO + "FLOPO_0980417")
OCCURRENT = URIRef(OBO + "FLOPO_0980422")


def _write_fixture(tmp_path: Path, classified_version: str = "2026-08-02"):
    source = Graph()
    source.add((FULL_ONTOLOGY, RDF.type, OWL.Ontology))
    source.add((FULL_ONTOLOGY, OWL.versionInfo, Literal("2026-08-02")))

    leaf_phenotype = URIRef(OBO + "FLOPO_0000004")
    leaf_pubescent = URIRef(OBO + "FLOPO_0000818")
    support_quality = URIRef(OBO + "FLOPO_0980106")
    obsolete = URIRef(OBO + "FLOPO_0000009")
    classes = {
        ROOT_CLASS: "flora phenotype",
        CONTINUANT: "plant continuant-target phenotype",
        OCCURRENT: "plant occurrent-target phenotype",
        ANATOMICAL_ENTITY_PHENOTYPE: "plant anatomical entity phenotype",
        PUBESCENCE_PHENOTYPE: "pubescence phenotype",
        leaf_phenotype: "leaf phenotype",
        leaf_pubescent: "leaf pubescent",
        support_quality: "crimson",
        obsolete: "obsolete old phenotype",
    }
    for cls, label in classes.items():
        source.add((cls, RDF.type, OWL.Class))
        source.add((cls, RDFS.label, Literal(label, lang="en")))
        source.add((cls, DCTERMS.source, URIRef("https://example.org/source")))
    source.add((obsolete, OWL.deprecated, Literal(True)))
    source.add((CONTINUANT, RDFS.subClassOf, ROOT_CLASS))
    source.add((OCCURRENT, RDFS.subClassOf, ROOT_CLASS))
    source.add((ANATOMICAL_ENTITY_PHENOTYPE, RDFS.subClassOf, CONTINUANT))
    source.add((PUBESCENCE_PHENOTYPE, RDFS.subClassOf, ANATOMICAL_ENTITY_PHENOTYPE))
    source.add((leaf_phenotype, RDFS.subClassOf, ROOT_CLASS))
    source.add((leaf_pubescent, RDFS.subClassOf, PUBESCENCE_PHENOTYPE))
    source.add((leaf_pubescent, RDFS.subClassOf, leaf_phenotype))
    source.add((support_quality, RDFS.subClassOf, URIRef(OBO + "PATO_0000001")))
    restriction = BNode()
    source.add((leaf_pubescent, OWL.equivalentClass, restriction))
    source.add((restriction, RDF.type, OWL.Restriction))
    source.add((restriction, OWL.onProperty, HAS_PART))
    source.add((restriction, OWL.someValuesFrom, URIRef(OBO + "PO_0025034")))

    classified = Graph()
    classified.add((FULL_ONTOLOGY, RDF.type, OWL.Ontology))
    classified.add((FULL_ONTOLOGY, OWL.versionInfo, Literal(classified_version)))
    for cls in classes:
        classified.add((cls, RDF.type, OWL.Class))
    classified.add((CONTINUANT, RDFS.subClassOf, ROOT_CLASS))
    classified.add((OCCURRENT, RDFS.subClassOf, ROOT_CLASS))
    classified.add((ANATOMICAL_ENTITY_PHENOTYPE, RDFS.subClassOf, CONTINUANT))
    classified.add((PUBESCENCE_PHENOTYPE, RDFS.subClassOf, ANATOMICAL_ENTITY_PHENOTYPE))
    classified.add((leaf_phenotype, RDFS.subClassOf, ANATOMICAL_ENTITY_PHENOTYPE))
    classified.add((leaf_pubescent, RDFS.subClassOf, PUBESCENCE_PHENOTYPE))
    classified.add((leaf_pubescent, RDFS.subClassOf, leaf_phenotype))

    source_path = tmp_path / "flopo.owl"
    classified_path = tmp_path / "flopo-inferred.owl"
    source.serialize(source_path, format="xml")
    classified.serialize(classified_path, format="xml")
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        f"{leaf_phenotype}\t4\tleaf phenotype\tPHENO|PO_0025034\t0\n"
        f"{leaf_pubescent}\t818\tleaf pubescent\tEQ|PO_0025034|PATO_0001320\t0\n"
    )
    return source_path, classified_path, registry, leaf_phenotype, leaf_pubescent


def test_light_release_has_one_named_root_and_no_support_vocabulary(tmp_path):
    source, classified, registry, leaf_phenotype, leaf_pubescent = _write_fixture(tmp_path)
    output = tmp_path / "flopo-light.owl"

    stats = build_light_ontology(source, classified, registry, output)
    graph = Graph().parse(output)
    classes = set(graph.subjects(RDF.type, OWL.Class))
    roots = {
        cls
        for cls in classes
        if not any(parent in classes for parent in graph.objects(cls, RDFS.subClassOf))
    }

    assert roots == {ROOT_CLASS}
    assert set(graph.subjects(RDFS.subClassOf, ROOT_CLASS)) == {CONTINUANT, OCCURRENT}
    assert URIRef(OBO + "FLOPO_0980106") not in classes
    assert URIRef(OBO + "FLOPO_0000009") not in classes
    assert all(str(cls).startswith(OBO + "FLOPO_") for cls in classes)
    assert (leaf_phenotype, RDFS.subClassOf, ANATOMICAL_ENTITY_PHENOTYPE) in graph
    assert (leaf_phenotype, RDFS.subClassOf, ROOT_CLASS) not in graph
    assert (leaf_pubescent, RDFS.subClassOf, PUBESCENCE_PHENOTYPE) in graph
    assert (None, OWL.equivalentClass, None) not in graph
    assert (LIGHT_ONTOLOGY, OWL.imports, None) not in graph
    assert stats["direct_root_children"] == 2
    assert stats["omitted_active_support_classes"] == 1


def test_light_release_rejects_a_stale_classification(tmp_path):
    source, classified, registry, _leaf_phenotype, _leaf_pubescent = _write_fixture(
        tmp_path, classified_version="2026-08-01"
    )

    with pytest.raises(ValueError, match="classified ontology is stale"):
        build_light_ontology(source, classified, registry, tmp_path / "light.owl")


def test_light_release_serialization_is_byte_idempotent(tmp_path):
    source, classified, registry, _leaf_phenotype, _leaf_pubescent = _write_fixture(
        tmp_path
    )
    first = tmp_path / "first.owl"
    second = tmp_path / "second.owl"

    build_light_ontology(source, classified, registry, first)
    build_light_ontology(source, classified, registry, second)

    assert first.read_bytes() == second.read_bytes()


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "ontology" / "flopo.owl"
LIGHT_RELEASE = ROOT / "ontology" / "flopo-light.owl"


def test_materialized_light_release_is_a_single_rooted_pubescence_complete_view():
    source = Graph().parse(RELEASE.as_posix())
    light = Graph().parse(LIGHT_RELEASE.as_posix())
    classes = set(light.subjects(RDF.type, OWL.Class))
    roots = {
        cls
        for cls in classes
        if not any(parent in classes for parent in light.objects(cls, RDFS.subClassOf))
    }
    expected_pubescence = {
        cls
        for cls in source.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef)
        and str(cls).startswith(OBO + "FLOPO_")
        and cls != PUBESCENCE_PHENOTYPE
        and equivalent_class_uses_quality(source, cls, BOTANICAL_PUBESCENCE)
    }

    assert roots == {ROOT_CLASS}
    assert set(light.subjects(RDFS.subClassOf, ROOT_CLASS)) == {CONTINUANT, OCCURRENT}
    assert expected_pubescence
    children: dict[URIRef, set[URIRef]] = {}
    for child, parent in light.subject_objects(RDFS.subClassOf):
        children.setdefault(parent, set()).add(child)
    beneath_pubescence = {PUBESCENCE_PHENOTYPE}
    frontier = [PUBESCENCE_PHENOTYPE]
    while frontier:
        for child in children.get(frontier.pop(), set()):
            if child not in beneath_pubescence:
                beneath_pubescence.add(child)
                frontier.append(child)
    assert expected_pubescence <= beneath_pubescence
    assert all(str(cls).startswith(OBO + "FLOPO_") for cls in classes)
    assert (None, OWL.deprecated, Literal(True)) not in light
    assert (None, OWL.equivalentClass, None) not in light
    assert (LIGHT_ONTOLOGY, OWL.imports, None) not in light


def test_light_release_has_catalog_and_purl_routes():
    catalog = ET.parse(ROOT / "ontology" / "catalog-v001.xml")
    catalog_entries = {
        entry.attrib.get("name"): entry.attrib.get("uri")
        for entry in catalog.findall(".//{urn:oasis:names:tc:entity:xmlns:xml:catalog}uri")
    }
    products = yaml.safe_load((ROOT / "flopo.yml").read_text(encoding="utf-8"))[
        "products"
    ]

    assert catalog_entries[str(LIGHT_ONTOLOGY)] == "flopo-light.owl"
    assert any("flopo-light.owl" in product for product in products)
