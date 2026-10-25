"""The flora corrections module: plane vs solid ovate, length synonyms, disjoint values."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from rdflib import OWL, RDFS, Graph, Literal, URIRef, XSD

from tools.build_flopo_flora_corrections import (
    FLAT_BEARERS,
    OIO,
    PLANE_OVATE,
    SOLID_OVATE,
    eq_parts,
)

ROOT = Path(__file__).resolve().parents[1]
OBO = "http://purl.obolibrary.org/obo/"


@pytest.fixture(scope="module")
def module() -> Graph:
    return Graph().parse((ROOT / "ontology/flopo-flora-corrections.ttl").as_posix())


@pytest.fixture(scope="module")
def registry() -> list[dict[str, str]]:
    with (ROOT / "config/flopo_id_registry.tsv").open(encoding="utf-8", newline="") as handle:
        return [r for r in csv.DictReader(handle, delimiter="\t") if r["deprecated"] == "0"]


def test_flat_organs_use_plane_ovate_and_others_are_ovoid(module, registry):
    seen = {"plane": 0, "solid": 0}
    for cls in module.subjects(OWL.equivalentClass, None):
        entity, quality = eq_parts(module, cls)
        label = str(module.value(cls, RDFS.label))
        if str(entity).rsplit("/", 1)[-1] in FLAT_BEARERS:
            assert quality == PLANE_OVATE and label.endswith(" ovate")
            seen["plane"] += 1
        else:
            assert quality == SOLID_OVATE and label.endswith(" ovoid")
            seen["solid"] += 1
    expected = {"plane": 0, "solid": 0}
    for row in registry:
        parts = row["signature"].split("|")
        if len(parts) != 3 or parts[0] != "EQ":
            continue
        _, entity, quality = parts
        if quality == "PATO_0001891":
            expected["plane" if entity in FLAT_BEARERS else "solid"] += 1
        elif quality == "FLOPO_0991024" and entity in FLAT_BEARERS:
            expected["plane"] += 1
    assert seen == expected
    assert seen["plane"] >= 30 and seen["solid"] >= 120
    leaf = URIRef(OBO + "FLOPO_0000286")
    assert eq_parts(module, leaf) == (URIRef(OBO + "PO_0025034"), PLANE_OVATE)
    assert str(module.value(URIRef(OBO + "FLOPO_0003805"), RDFS.label)) == "seed ovoid"


def test_new_eq_definition_uses_solid_ovoid_wording_without_changing_quality():
    from tools.build_flopo_flora_corrections import DEFINITION, ovate_classes
    from flopo2.verify.eq_release import eq_axioms

    graph, out = Graph(), Graph()
    cls = eq_axioms(graph, OBO + "FLOPO_9999998", OBO + "PO_0009072",
                    str(SOLID_OVATE), "plant ovary ovate", "")
    graph.add((cls, DEFINITION, Literal("A flora phenotype in which a plant ovary exhibits ovate.", lang="en")))
    ovate_classes(graph, out)
    assert str(out.value(cls, RDFS.label)) == "plant ovary ovoid"
    assert str(out.value(cls, DEFINITION)).endswith("exhibits ovoid.")
    assert eq_parts(out, cls)[1] == SOLID_OVATE


def test_registry_keeps_the_identifiers(registry):
    signatures = {r["flopo_iri"].rsplit("/", 1)[-1]: r["signature"] for r in registry}
    assert signatures["FLOPO_0000286"] == "EQ|PO_0025034|FLOPO_0991024"
    assert signatures["FLOPO_0003805"] == "EQ|PO_0009010|PATO_0001891"


def test_length_classes_have_long_and_short_synonyms(module, registry):
    length = [r for r in registry if r["signature"].endswith(("|PATO_0000573", "|PATO_0000574"))]
    assert length
    for row in length:
        word = "long" if row["signature"].endswith("0573") else "short"
        bearer = row["label"].rsplit(" ", 2)[0]
        synonym = Literal(f"{bearer} {word}", datatype=XSD.string)
        assert (URIRef(row["flopo_iri"]), OIO.hasExactSynonym, synonym) in module


def test_disjoint_values_are_stated_per_bearer(module):
    with (ROOT / "config/flopo_disjoint_values.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    pairs = set()
    for a, b in module.subject_objects(OWL.disjointWith):
        qa = [module.value(i, OWL.someValuesFrom) for i in module.items(module.value(a, OWL.intersectionOf))]
        qb = [module.value(i, OWL.someValuesFrom) for i in module.items(module.value(b, OWL.intersectionOf))]
        pairs.add((str(qa[1]).rsplit("/", 1)[-1], str(qb[1]).rsplit("/", 1)[-1]))
    assert pairs == {(r["value_a"], r["value_b"]) for r in rows}
    # Hairiness changes over an organ's life (glabrescent), so it is not declared disjoint.
    assert not any(r["group"] == "pubescence" for r in rows)
