from __future__ import annotations

import csv
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, URIRef
from rdflib.collection import Collection

from tools.build_flopo_botanical_extension import (
    GO_BIOLOGICAL_PROCESS,
    HAS_CHARACTERISTIC,
    HAS_COMPONENT,
    HAS_MEMBER_PART,
    HAS_PART,
    IAO_REPLACED_BY,
    OBO,
    PARTICIPATES_IN,
    PATO_PROCESS_CHARACTERISTIC,
)
from tools.update_flopo_botanical_release import (
    BEGIN_MARKER,
    GO_MODULE,
    LEGACY_GO_MODULE,
    update_release,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ontology" / "flopo-botanical-extension.ttl"
ID_REGISTRY = ROOT / "config" / "flopo_botanical_id_registry.tsv"
APPROVALS = ROOT / "curation" / "curator_approvals.tsv"
REPARENTING = ROOT / "curation" / "flopo_top_level_reparenting.tsv"


def _restriction(graph: Graph, node, prop: URIRef):
    assert (node, RDF.type, OWL.Restriction) in graph
    assert (node, OWL.onProperty, prop) in graph
    return next(graph.objects(node, OWL.someValuesFrom), None)


def _intersection(graph: Graph, node) -> set:
    head = next(graph.objects(node, OWL.intersectionOf))
    return set(Collection(graph, head))


def test_botanical_module_has_stable_unique_approved_ids_and_provenance():
    with ID_REGISTRY.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    ids = [row["flopo_id"] for row in rows]

    assert len(rows) == 13
    assert len(ids) == len(set(ids))
    assert ids == [
        f"FLOPO_{number:07d}"
        for number in range(980417, 980432)
        if number not in {980419, 980420}
    ]

    graph = Graph().parse(MODULE_PATH)
    contributor = URIRef("https://orcid.org/0000-0001-8149-5890")
    for row in rows:
        cls = URIRef(OBO + row["flopo_id"])
        assert (cls, RDF.type, OWL.Class) in graph
        assert (cls, RDFS.label, None) in graph
        assert (cls, URIRef(OBO + "IAO_0000115"), None) in graph
        assert (cls, DCTERMS.contributor, contributor) in graph

    with APPROVALS.open(encoding="utf-8", newline="") as handle:
        approvals = list(csv.DictReader(handle, delimiter="\t"))
    assert any(
        row["proposal_set"].endswith(
            "flopo_top_level_and_local_extension_proposals.tsv"
        )
        and row["scope"] == "all rows"
        and row["decision"] == "accept"
        and row["curator_orcid"] == "0000-0001-8149-5890"
        for row in approvals
    )
    assert not any(
        (node, RDF.type, OWL.Class) not in graph
        for node in graph.subjects(OWL.intersectionOf, None)
    )


def test_original_upper_classes_are_active_and_new_duplicates_are_obsolete():
    graph = Graph().parse(MODULE_PATH)
    replacements = {
        "FLOPO_0980419": "FLOPO_0018579",
        "FLOPO_0980420": "FLOPO_0017857",
    }
    for duplicate_id, original_id in replacements.items():
        duplicate = URIRef(OBO + duplicate_id)
        original = URIRef(OBO + original_id)
        assert (original, RDF.type, OWL.Class) in graph
        assert (original, OWL.deprecated, None) not in graph
        assert (duplicate, OWL.deprecated, None) in graph
        assert (duplicate, IAO_REPLACED_BY, original) in graph
        assert str(next(graph.objects(duplicate, RDFS.label))).startswith("obsolete ")
        assert not set(graph.objects(duplicate, RDFS.subClassOf))
        assert not set(graph.objects(duplicate, OWL.equivalentClass))


def test_top_level_reparenting_ledger_is_complete_and_conservative():
    with REPARENTING.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 256
    assert len({row["flopo_id"] for row in rows}) == 256
    assert {row["review_status"] for row in rows} == {"deterministic", "approved"}

    category_counts: dict[str, int] = {}
    for row in rows:
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
    assert category_counts == {
        "anatomical_space": 9,
        "anatomical_space_root": 1,
        "manual_pedicel": 1,
        "plant_structure": 242,
        "plant_structure_root": 1,
        "plant_substance": 2,
    }

    graph = Graph().parse(MODULE_PATH)
    for row in rows:
        cls = URIRef(OBO + row["flopo_id"])
        parent = URIRef(OBO + row["new_parent"])
        if row["flopo_id"] == "FLOPO_0000467":
            dashboard = Graph().parse(
                ROOT / "ontology" / "flopo-dashboard-remediation.ttl"
            )
            assert (cls, RDFS.subClassOf, parent) in dashboard
            continue
        assert (cls, RDFS.subClassOf, parent) in graph
        assert (cls, RDFS.subClassOf, URIRef(OBO + "FLOPO_0000000")) not in graph


def test_process_phenotype_axiom_has_an_explicit_bearer_as_participant():
    graph = Graph().parse(MODULE_PATH)
    process_phenotype = URIRef(OBO + "FLOPO_0980423")
    expression = next(graph.objects(process_phenotype, OWL.equivalentClass))
    filler = _restriction(graph, expression, HAS_PART)
    members = _intersection(graph, filler)

    assert URIRef(OBO + "PO_0025131") in members
    participation = next(
        member
        for member in members
        if isinstance(member, BNode)
        and (member, OWL.onProperty, PARTICIPATES_IN) in graph
    )
    process = _restriction(graph, participation, PARTICIPATES_IN)
    process_members = _intersection(graph, process)
    assert GO_BIOLOGICAL_PROCESS in process_members
    process_characteristic = next(
        member
        for member in process_members
        if isinstance(member, BNode)
        and (member, OWL.onProperty, HAS_CHARACTERISTIC) in graph
    )
    assert (
        _restriction(graph, process_characteristic, HAS_CHARACTERISTIC)
        == PATO_PROCESS_CHARACTERISTIC
    )

    # Neither the process nor a process characteristic is a material part.
    assert not any(
        (restriction, OWL.onProperty, HAS_PART) in graph
        and (restriction, OWL.someValuesFrom, GO_BIOLOGICAL_PROCESS) in graph
        for restriction in graph.subjects(RDF.type, OWL.Restriction)
    )

    # The repaired impossibility GCI is restricted to a PO bearer; it no longer uses
    # owl:Thing, which made a reflexive has_part relation kill valid processes as well.
    constraints = set(graph.subjects(RDFS.subClassOf, OWL.Nothing))
    assert len(constraints) == 1
    invalid_filler = _restriction(graph, next(iter(constraints)), HAS_PART)
    invalid_members = _intersection(graph, invalid_filler)
    assert URIRef(OBO + "PO_0025131") in invalid_members
    assert OWL.Thing not in invalid_members
    assert not any(
        (restriction, OWL.onProperty, HAS_CHARACTERISTIC) in graph
        and (restriction, OWL.someValuesFrom, GO_BIOLOGICAL_PROCESS) in graph
        for restriction in graph.subjects(RDF.type, OWL.Restriction)
    )


def test_leaflet_cardinality_foliage_membership_and_local_parenting():
    graph = Graph().parse(MODULE_PATH)

    for class_id, cardinality in (("FLOPO_0900067", 3), ("FLOPO_0980426", 2)):
        cls = URIRef(OBO + class_id)
        expression = next(graph.objects(cls, OWL.equivalentClass))
        filler = _restriction(graph, expression, HAS_PART)
        members = _intersection(graph, filler)
        count = next(
            member
            for member in members
            if isinstance(member, BNode)
            and (member, OWL.qualifiedCardinality, None) in graph
        )
        assert int(next(graph.objects(count, OWL.qualifiedCardinality))) == cardinality
        assert (count, OWL.onProperty, HAS_COMPONENT) in graph
        assert (count, OWL.onClass, URIRef(OBO + "PO_0020049")) in graph

    assert not any(
        (restriction, OWL.onProperty, HAS_PART) in graph
        for predicate in (
            OWL.cardinality,
            OWL.minCardinality,
            OWL.maxCardinality,
            OWL.qualifiedCardinality,
            OWL.minQualifiedCardinality,
            OWL.maxQualifiedCardinality,
        )
        for restriction in graph.subjects(predicate, None)
    )

    foliage = URIRef(OBO + "FLOPO_0980429")
    foliage_restrictions = {
        parent
        for parent in graph.objects(foliage, RDFS.subClassOf)
        if isinstance(parent, BNode)
    }
    assert any(
        (node, OWL.onProperty, HAS_MEMBER_PART) in graph
        and (node, OWL.someValuesFrom, URIRef(OBO + "PO_0025034")) in graph
        for node in foliage_restrictions
    )
    assert any(
        (node, OWL.onProperty, HAS_MEMBER_PART) in graph
        and (node, OWL.allValuesFrom, URIRef(OBO + "PO_0025034")) in graph
        for node in foliage_restrictions
    )

    assert (
        URIRef(OBO + "FLOPO_0980424"),
        RDFS.subClassOf,
        URIRef(OBO + "PATO_0001555"),
    ) in graph
    assert (
        URIRef(OBO + "FLOPO_0980429"),
        RDFS.subClassOf,
        URIRef(OBO + "PO_0025131"),
    ) in graph


def test_botanical_release_update_replaces_existing_class_and_is_idempotent(tmp_path):
    release = tmp_path / "flopo.owl"
    release.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:dcterms="http://purl.org/dc/terms/">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
    <owl:imports rdf:resource="http://purl.obolibrary.org/obo/flopo/imports/go_import.owl"/>
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-07-13/flopo.owl"/>
    <owl:versionInfo>2026-07-13</owl:versionInfo>
  </owl:Ontology>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000000">
    <rdfs:label>old flora phenotype</rdfs:label>
  </owl:Class>
</rdf:RDF>
''',
        encoding="utf-8",
    )
    extension = tmp_path / "botanical.ttl"
    extension.write_text(
        '''@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
obo:flopo-botanical-extension.owl a owl:Ontology .
obo:FLOPO_0000000 a owl:Class ; rdfs:label "flora phenotype"@en .
obo:FLOPO_0980417 a owl:Class ; rdfs:label "plant continuant-target phenotype"@en .
''',
        encoding="utf-8",
    )

    assert update_release(release, extension, "2026-07-15") == 2
    first = release.read_text(encoding="utf-8")
    assert "old flora phenotype" not in first
    assert first.count(BEGIN_MARKER) == 1
    assert first.count(GO_MODULE) == 1
    assert LEGACY_GO_MODULE not in first
    assert "flopo/releases/2026-07-15/flopo.owl" in first

    assert update_release(release, extension, "2026-07-15") == 2
    assert release.read_text(encoding="utf-8") == first
