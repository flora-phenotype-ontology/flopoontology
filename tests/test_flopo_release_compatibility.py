from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "ontology" / "flopo.owl"
ARCHIVE = ROOT / "releases" / "2026-07-15"
CURRENT_ARCHIVE = ROOT / "releases" / "2026-07-31"
OBO = "http://purl.obolibrary.org/obo/"
FLOPO_ROOT = URIRef(OBO + "FLOPO_0000000")
REPLACED_BY = URIRef(OBO + "IAO_0100001")


def _graph() -> Graph:
    return Graph().parse(RELEASE.as_posix())


def _flopo_classes(graph: Graph) -> set[str]:
    return {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }


def _deprecated(graph: Graph) -> set[URIRef]:
    return {
        cls
        for cls, value in graph.subject_objects(OWL.deprecated)
        if isinstance(cls, URIRef)
        and str(cls).startswith(OBO + "FLOPO_")
        and isinstance(value, Literal)
        and str(value).casefold() == "true"
    }


def test_every_archived_public_identifier_is_preserved():
    graph = _graph()
    baseline = {
        line.strip()
        for line in (ARCHIVE / "flopo-class-iris.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    }
    current = _flopo_classes(graph)

    assert len(baseline) == 24689
    assert baseline <= current
    assert not (baseline - current)


def test_archive_manifest_records_the_exact_previous_public_release():
    manifest = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_commit"] == "f82bc9f6124c0f2cc22af2f19ac26d570d2a0f16"
    assert manifest["version_info"] == "2026-07-15"
    assert manifest["flopo_class_count"] == 24689
    assert manifest["deprecated_class_count"] == 1161
    assert (
        manifest["artifacts"]["flopo.owl"]["sha256"]
        == "a76bd4d1120ee9896ce396d4bb28558018c8dbedc77a4114223be7f9e3f24bc6"
    )


def test_current_manifest_matches_the_frozen_release_artifacts():
    manifest = json.loads(
        (CURRENT_ARCHIVE / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["source_commit"] == "f3e3029ce87edc43dfaf2c3a09a97958eda63c8f"
    assert manifest["version_info"] == "2026-07-31"
    assert manifest["flopo_class_count"] == 24689
    assert manifest["deprecated_class_count"] == 1166
    assert (
        sha256(RELEASE.read_bytes()).hexdigest()
        == manifest["artifacts"]["flopo.owl"]["sha256"]
    )
    assert (
        sha256((ROOT / "ontology" / "flopo-inferred.owl").read_bytes()).hexdigest()
        == manifest["artifacts"]["flopo-inferred.owl"]["sha256"]
    )
    assert set(
        (CURRENT_ARCHIVE / "flopo-class-iris.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == _flopo_classes(_graph())


def test_flora_phenotype_has_exactly_the_two_approved_upper_children():
    graph = _graph()
    children = {
        child
        for child in graph.subjects(RDFS.subClassOf, FLOPO_ROOT)
        if isinstance(child, URIRef) and str(child).startswith(OBO + "FLOPO_")
    }
    assert children == {
        URIRef(OBO + "FLOPO_0980417"),
        URIRef(OBO + "FLOPO_0980422"),
    }


def test_duplicate_upper_identifiers_are_annotation_only_obsolete_shells():
    graph = _graph()
    replacements = {
        URIRef(OBO + "FLOPO_0980419"): URIRef(OBO + "FLOPO_0018579"),
        URIRef(OBO + "FLOPO_0980420"): URIRef(OBO + "FLOPO_0017857"),
    }
    for duplicate, original in replacements.items():
        assert duplicate in _deprecated(graph)
        assert (duplicate, REPLACED_BY, original) in graph
        assert not set(graph.objects(duplicate, RDFS.subClassOf))
        assert not set(graph.objects(duplicate, OWL.equivalentClass))
        assert (original, OWL.deprecated, None) not in graph


def test_no_obsolete_flopo_class_retains_or_receives_logical_axioms():
    graph = _graph()
    deprecated = _deprecated(graph)
    logical_predicates = {
        RDFS.subClassOf,
        OWL.equivalentClass,
        OWL.disjointWith,
        OWL.disjointUnionOf,
    }
    for cls in deprecated:
        assert not any(
            predicate in logical_predicates
            for predicate, _obj in graph.predicate_objects(cls)
        )
        assert not any(
            predicate in logical_predicates or predicate == RDF.first
            for _subject, predicate in graph.subject_predicates(cls)
        )
