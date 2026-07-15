from __future__ import annotations

import csv
import shutil
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, URIRef

from tools.build_flopo_pubescent_migration import (
    ANATOMICAL_ENTITY_PHENOTYPE,
    BOTANICAL_PUBESCENCE,
    HAS_CHARACTERISTIC,
    IAO_DEFINITION,
    TERM_REPLACED_BY,
)
from tools.update_flopo_pubescent_release import BEGIN_MARKER, update_release


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "curation" / "pubescent_migration.tsv"
MODULE = ROOT / "ontology" / "flopo-pubescent-migration.ttl"
RELEASE = ROOT / "ontology" / "flopo.owl"
OBO = "http://purl.obolibrary.org/obo/"
HUMAN_PUBERTY = URIRef(OBO + "PATO_0000455")


def _rows() -> list[dict[str, str]]:
    with MIGRATION.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_migration_module_has_all_approved_obsolete_replacement_pairs():
    rows = _rows()
    graph = Graph().parse(MODULE.as_posix())

    assert len(rows) == 154
    assert {
        int(row["replacement_flopo_id"].removeprefix("FLOPO_")) for row in rows
    } == set(range(980432, 980586))
    for row in rows:
        old = URIRef(OBO + row["old_flopo_id"])
        new = URIRef(OBO + row["replacement_flopo_id"])
        assert (old, RDF.type, OWL.Class) in graph
        assert (old, OWL.deprecated, Literal(True, datatype=XSD.boolean)) in graph
        assert (old, TERM_REPLACED_BY, new) in graph
        assert (old, OWL.equivalentClass, None) not in graph
        assert (new, RDF.type, OWL.Class) in graph
        assert (new, RDFS.subClassOf, ANATOMICAL_ENTITY_PHENOTYPE) in graph
        assert (new, OWL.equivalentClass, None) in graph
        definition = next(graph.objects(new, IAO_DEFINITION))
        assert "covered with short hairs or soft down" in str(definition)

    characteristic_restrictions = set(
        graph.subjects(OWL.onProperty, HAS_CHARACTERISTIC)
    ) & set(graph.subjects(OWL.someValuesFrom, BOTANICAL_PUBESCENCE))
    assert len(characteristic_restrictions) == 154
    assert (None, None, HUMAN_PUBERTY) not in graph


def test_release_update_is_idempotent_and_removes_all_human_puberty_logic(tmp_path):
    candidate = tmp_path / "flopo.owl"
    shutil.copyfile(RELEASE, candidate)

    assert update_release(candidate, MODULE, "2026-07-15") == 154
    first = candidate.read_bytes()
    assert update_release(candidate, MODULE, "2026-07-15") == 154
    second = candidate.read_bytes()

    assert first == second
    assert first.count(BEGIN_MARKER.encode()) == 1
    graph = Graph().parse(candidate.as_posix())
    assert (None, None, HUMAN_PUBERTY) not in graph
