"""The release asserts its classified hierarchy (BioPortal shows asserted axioms only)."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Graph, URIRef

from tools.update_flopo_bearer_parents import BEGIN_MARKER as BEARER_BEGIN
from tools.update_flopo_inferred_parents import BEGIN_MARKER as INFERRED_BEGIN

ROOT = Path(__file__).resolve().parents[1]
OBO = "http://purl.obolibrary.org/obo/"
FLORA_PHENOTYPE = URIRef(OBO + "FLOPO_0000000")
LEGACY_PREFIX = OBO + "flopo.owl#"  # 2019 malformed IRIs, obsoleted 2026-10-13


@pytest.fixture(scope="module")
def release() -> Graph:
    return Graph().parse((ROOT / "ontology/flopo.owl").as_posix())


def test_release_carries_the_materialized_block_only():
    text = (ROOT / "ontology/flopo.owl").read_text(encoding="utf-8")
    assert text.count(INFERRED_BEGIN) == 1
    assert BEARER_BEGIN not in text  # superseded by the materialized superclasses


def test_every_live_class_has_an_asserted_named_parent(release):
    orphans = []
    for cls in set(release.subjects(RDF.type, OWL.Class)):
        if not isinstance(cls, URIRef) or "FLOPO_" not in str(cls) or cls == FLORA_PHENOTYPE:
            continue
        if (cls, OWL.deprecated, None) in release:
            continue
        if not any(isinstance(o, URIRef) for o in release.objects(cls, RDFS.subClassOf)):
            orphans.append(str(cls))
    assert not orphans, orphans[:10]


@pytest.mark.parametrize(
    "child, parent",
    [
        ("FLOPO_0015820", "FLOPO_0012025"),  # androecium absent < androecium amount
    ],
)
def test_examples_are_placed(release, child, parent):
    assert (URIRef(OBO + child), RDFS.subClassOf, URIRef(OBO + parent)) in release


def test_legacy_iris_are_obsolete_and_replaced(release):
    legacy = {c for c in release.subjects(RDF.type, OWL.Class) if str(c).startswith(LEGACY_PREFIX)}
    assert len(legacy) == 4
    for cls in legacy:
        assert (cls, OWL.deprecated, None) in release
        replacement = release.value(cls, URIRef(OBO + "IAO_0100001"))
        assert replacement is not None and str(replacement).startswith(OBO + "FLOPO_0992")
        assert (replacement, RDF.type, OWL.Class) in release
