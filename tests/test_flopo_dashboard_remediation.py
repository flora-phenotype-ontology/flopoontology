from __future__ import annotations

import shutil
from hashlib import sha256
from pathlib import Path

from rdflib import OWL, RDFS, XSD, Graph, Literal, URIRef

from tools.update_flopo_dashboard_remediation import (
    BEGIN_MARKER,
    EXPECTED_REPLACEMENTS,
    GO_IMPORT,
    IAO_DEFINITION,
    OBO,
    TERM_REPLACED_BY,
    update_release,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ontology" / "flopo-dashboard-remediation.ttl"
RELEASE = ROOT / "ontology" / "flopo.owl"
EXACT_SYNONYM = URIRef("http://www.geneontology.org/formats/oboInOwl#hasExactSynonym")


def test_remediation_module_preserves_distinctions_and_replacement_history():
    graph = Graph().parse(MODULE.as_posix())

    for old, replacement in EXPECTED_REPLACEMENTS.items():
        old_iri = URIRef(old)
        assert (old_iri, OWL.deprecated, Literal(True, datatype=XSD.boolean)) in graph
        assert (old_iri, TERM_REPLACED_BY, URIRef(replacement)) in graph
        assert (old_iri, OWL.equivalentClass, None) not in graph
        assert str(next(graph.objects(old_iri, RDFS.label))).startswith("obsolete ")

    assert {
        str(value)
        for value in graph.objects(URIRef(OBO + "FLOPO_0002893"), EXACT_SYNONYM)
    } == {"sepal round", "sepal rounded"}
    assert {
        str(value)
        for value in graph.objects(URIRef(OBO + "FLOPO_0001692"), EXACT_SYNONYM)
    } == {"petal round", "petal rounded"}

    apiculate = URIRef(OBO + "FLOPO_0980063")
    assert (apiculate, RDFS.subClassOf, URIRef(OBO + "FLOPO_0015223")) in graph
    assert (apiculate, OWL.equivalentClass, None) not in graph
    assert "small, abrupt point" in str(next(graph.objects(apiculate, IAO_DEFINITION)))

    secretory_parent = URIRef(OBO + "FLOPO_0000467")
    for child_id in ("FLOPO_0900054", "FLOPO_0900055", "FLOPO_0900056"):
        child = URIRef(OBO + child_id)
        assert (child, RDFS.subClassOf, secretory_parent) in graph
        assert (child, IAO_DEFINITION, None) in graph


def test_release_update_is_idempotent_and_removes_dashboard_errors(tmp_path):
    candidate = tmp_path / "flopo.owl"
    shutil.copyfile(RELEASE, candidate)

    assert update_release(candidate, MODULE, "2026-07-16") == 10
    first = sha256(candidate.read_bytes()).digest()
    assert update_release(candidate, MODULE, "2026-07-16") == 10
    assert sha256(candidate.read_bytes()).digest() == first
    text = candidate.read_text(encoding="utf-8")
    assert text.count(BEGIN_MARKER) == 1
    assert GO_IMPORT in text
