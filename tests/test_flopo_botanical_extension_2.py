from __future__ import annotations

import csv
from pathlib import Path

import pytest
from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection

from tools.build_flopo_botanical_extension_2 import (
    HAS_CHARACTERISTIC,
    HAS_PART,
    IN_PLACE,
    OBO,
    OIO,
    PART_OF,
    _live_obo_ids,
    build_module,
)
from tools.update_flopo_botanical_extension_2_release import BEGIN_MARKER, update_release


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ontology" / "flopo-botanical-extension-2.ttl"
REGISTRY = ROOT / "config" / "flopo_botanical_concept_id_registry.tsv"
PROPOSALS = ROOT / "curation" / "botanical_concept_proposals.tsv"
APPROVALS = ROOT / "curation" / "curator_approvals.tsv"
CATALOG = ROOT / "ontology" / "catalog-v001.xml"
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
COLOUR_ROOT = URIRef(OBO + "PATO_0000014")
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")


def _tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _module() -> Graph:
    return Graph().parse(MODULE_PATH)


def _c(curie: str) -> URIRef:
    return URIRef(OBO + curie.replace(":", "_"))


def _intersection(graph: Graph, node) -> set:
    return set(Collection(graph, next(graph.objects(node, OWL.intersectionOf))))


def _some(graph: Graph, cls: URIRef, prop: URIRef) -> list:
    return [
        next(graph.objects(parent, OWL.someValuesFrom))
        for parent in graph.objects(cls, RDFS.subClassOf)
        if isinstance(parent, BNode) and (parent, OWL.onProperty, prop) in graph
    ]


def test_registry_block_is_reserved_unique_and_disjoint_from_other_allocations():
    rows = _tsv(REGISTRY)
    ids = [row["flopo_id"] for row in rows]
    assert len(rows) == 38
    assert ids == [f"FLOPO_{n:07d}" for n in range(985000, 985038)]

    other: set[str] = set()
    for path, column in (
        (ROOT / "config" / "flopo_botanical_id_registry.tsv", "flopo_id"),
        (ROOT / "config" / "flopo_value_id_registry.tsv", "flopo_id"),
        (ROOT / "config" / "flopo_machine_support_id_registry.tsv", "flopo_id"),
    ):
        other.update(row[column] for row in _tsv(path))
    assert not set(ids) & other

    # After a release the global registry is re-synced from flopo.owl and then lists these
    # classes too; any shared identifier must denote the same class (label and parent-free).
    labels = {row["flopo_id"]: row["label"] for row in rows}
    for row in _tsv(ROOT / "config" / "flopo_id_registry.tsv"):
        flopo_id = row["flopo_iri"].rsplit("/", 1)[1]
        if flopo_id in labels:
            assert row["label"] == labels[flopo_id]
        else:
            other.add(flopo_id)
    # Other blocks reserved before or after this one (e.g. the 2026-09-18 anatomy support block
    # FLOPO_0986000-0986999, the colour backbone block FLOPO_0988000-0988999, or whatever the
    # global registry has picked up from later releases) are checked by their own tests. What
    # matters here is only that none of them lands inside *this* block, so check that directly
    # instead of asserting an upper bound that a later, unrelated block would keep invalidating.
    ours = set(range(985000, 985038))
    theirs = {int(value.removeprefix("FLOPO_")) for value in other}
    assert not (ours & theirs)


def test_registry_rows_are_curator_accepted_and_materialized_with_provenance():
    proposals = {row["proposal_id"]: row for row in _tsv(PROPOSALS)}
    graph = _module()
    for row in _tsv(REGISTRY):
        proposal = proposals[row["proposal_key"]]
        assert proposal["curator_decision"] in {"accept", "accept_with_revision"}
        assert proposal["preferred_label"] == row["label"]
        assert "2026-09-18" in proposal["curator_notes"]
        cls = URIRef(OBO + row["flopo_id"])
        assert (cls, RDF.type, OWL.Class) in graph
        assert (cls, RDFS.label, Literal(row["label"], lang="en")) in graph
        assert (cls, IAO_DEFINITION, None) in graph
        assert (cls, DCTERMS.contributor, CONTRIBUTOR) in graph
        assert (cls, DCTERMS.created, None) in graph

    for key, curie in IN_PLACE.items():
        assert proposals[key]["curator_decision"] in {"accept", "accept_with_revision"}
        cls = URIRef(OBO + curie)
        assert (cls, DCTERMS.modified, None) in graph
        assert len(list(graph.objects(cls, IAO_DEFINITION))) == 1
        assert len(list(graph.objects(cls, RDFS.label))) == 1

    approvals = _tsv(APPROVALS)
    assert any(
        row["proposal_set"] == "curation/botanical_concept_proposals.tsv"
        and row["decision"] == "accept_with_revision"
        and row["curator_orcid"] == "0000-0001-8149-5890"
        and row["decision_date"] == "2026-09-18"
        for row in approvals
    )
    assert "flopo-botanical-extension-2.ttl" in CATALOG.read_text(encoding="utf-8")


def test_every_curator_decision_is_recorded_and_colour_rows_are_not_materialized():
    proposals = _tsv(PROPOSALS)
    assert len(proposals) == 230
    assert all(
        row["curator_decision"] in {"accept", "accept_with_revision", "defer", "reject"}
        for row in proposals
    )
    colour_rows = [
        row for row in proposals if "implement via ISCC-NBS backbone" in row["curator_notes"]
    ]
    assert len(colour_rows) == 11

    graph = _module()
    for released_colour in ("FLOPO_0980092", "FLOPO_0980105", "FLOPO_0980106", "FLOPO_0980174"):
        assert (URIRef(OBO + released_colour), None, None) not in graph
    assert not list(graph.subjects(RDFS.subClassOf, COLOUR_ROOT))


def test_provisional_classes_sit_under_live_po_or_pato_parents_and_never_mint_their_ids():
    live = _live_obo_ids(ROOT / "ont" / "plant_ontology.obo", ROOT / "ont" / "quality.obo")
    graph = _module()
    declared = {s for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    assert all(str(cls).startswith(OBO + "FLOPO_") for cls in declared)

    for row in _tsv(REGISTRY):
        if row["provisional_for"] not in {"PO", "PATO"}:
            continue
        cls = URIRef(OBO + row["flopo_id"])
        named = [p for p in graph.objects(cls, RDFS.subClassOf) if isinstance(p, URIRef)]
        assert named, row
        for parent in named:
            local = str(parent).removeprefix(OBO)
            if local.startswith("FLOPO_"):
                assert row["provisional_for"] == "PO"  # corona subtypes under floral corona
                continue
            assert local.startswith(row["provisional_for"] + "_")
            assert local.replace("_", ":") in live


def test_anatomy_boundaries_follow_the_approved_counterexamples():
    graph = _module()
    pinna, pinnule = _c("FLOPO:0985027"), _c("FLOPO:0985028")
    leaflet = _c("PO:0020049")
    assert (pinna, RDFS.subClassOf, leaflet) not in graph
    assert (pinnule, RDFS.subClassOf, leaflet) not in graph
    assert set(_some(graph, pinnule, PART_OF)) == {pinna, _c("PO:0020043")}

    cyathium = _c("FLOPO:0985029")
    assert (cyathium, RDFS.subClassOf, _c("PO:0009049")) in graph
    assert (cyathium, RDFS.subClassOf, _c("PO:0030126")) not in graph
    assert set(_some(graph, cyathium, HAS_PART)) == {_c("PO:0025600"), _c("PO:0009100")}

    corona = _c("FLOPO:0985020")
    assert _some(graph, corona, PART_OF) == [_c("PO:0009046")]
    assert _some(graph, _c("FLOPO:0985021"), PART_OF) == [_c("PO:0009059")]
    assert _some(graph, _c("FLOPO:0985022"), PART_OF) == [_c("PO:0009061")]
    for subtype in ("FLOPO:0985021", "FLOPO:0985022"):
        assert (_c(subtype), RDFS.subClassOf, corona) in graph

    # Generic apex/base carry no parthood; the bearer-specific PO classes keep it.
    for generic in ("FLOPO:0985023", "FLOPO:0985024"):
        assert (_c(generic), RDFS.subClassOf, _c("PO:0025001")) in graph
        assert _some(graph, _c(generic), PART_OF) == []


def test_quality_parents_and_synonym_scopes_follow_the_approved_rows():
    graph = _module()
    assert (_c("FLOPO:0985005"), RDFS.subClassOf, _c("PATO:0002481")) in graph  # ascending
    assert (_c("FLOPO:0985012"), RDFS.subClassOf, _c("PATO:0001786")) in graph  # dissected
    assert (_c("FLOPO:0985009"), RDFS.subClassOf, _c("PATO:0001975")) in graph  # entire
    assert (_c("FLOPO:0985004"), RDFS.subClassOf, _c("PATO:0002358")) not in graph

    for cls, text in (
        ("FLOPO:0985007", "woolly"),
        ("FLOPO:0985008", "silky"),
        ("FLOPO:0985015", "pleated"),
    ):
        assert (_c(cls), OIO.hasRelatedSynonym, Literal(text, lang="en")) in graph
        assert (_c(cls), OIO.hasExactSynonym, Literal(text, lang="en")) not in graph
    assert (_c("FLOPO:0985013"), OIO.hasNarrowSynonym, Literal("amplexicaul", lang="en")) in graph

    definition = str(next(graph.objects(_c("FLOPO:0985001"), IAO_DEFINITION)))
    assert "terete" not in definition
    perennial = str(next(graph.objects(_c("FLOPO:0985011"), IAO_DEFINITION)))
    assert "more than two years" in perennial


def test_growth_forms_keep_referents_and_avoid_the_herbaceous_homonym():
    graph = _module()
    climber = _c("FLOPO:0985031")
    liana = _c("FLOPO:0900035")
    assert (climber, RDFS.subClassOf, _c("FLOPO:0900032")) in graph
    assert (liana, RDFS.subClassOf, climber) in graph
    assert (liana, RDFS.subClassOf, _c("FLOPO:0900032")) not in graph
    assert (liana, RDFS.label, Literal("whole plant lianescent", lang="en")) in graph
    assert (liana, OIO.hasExactSynonym, Literal("climber", lang="en")) not in graph
    assert (liana, OIO.hasExactSynonym, Literal("liana", lang="en")) in graph
    assert (climber, OIO.hasExactSynonym, Literal("climber", lang="en")) in graph

    for cls in ("FLOPO:0985032", "FLOPO:0985033", "FLOPO:0985034"):
        assert (_c(cls), RDFS.subClassOf, climber) in graph

    herbaceous = _c("PATO:0002352")
    vine = _c("FLOPO:0985032")
    assert not any(obj == herbaceous for _s, _p, obj in graph.triples((None, None, None))
                   if _s == vine)
    herb = _c("FLOPO:0022142")
    assert (herb, OIO.hasRelatedSynonym, Literal("herb", lang="en")) in graph
    assert (herb, OIO.hasExactSynonym, Literal("herb", lang="en")) not in graph
    assert "dying back" in str(next(graph.objects(herb, IAO_DEFINITION)))

    tree = _c("FLOPO:0900033")
    assert (tree, OIO.hasExactSynonym, Literal("tree", lang="en")) in graph

    leafless = _c("FLOPO:0985035")
    outer = _some(graph, leafless, HAS_PART)[0]
    members = _intersection(graph, outer)
    assert _c("PO:0000003") in members
    characteristic = next(
        m for m in members if isinstance(m, BNode) and (m, OWL.onProperty, HAS_CHARACTERISTIC) in graph
    )
    absence = next(graph.objects(characteristic, OWL.someValuesFrom))
    assert _c("PATO:0002000") in _intersection(graph, absence)


def test_builder_rejects_unaccepted_registry_rows(tmp_path):
    rows = _tsv(PROPOSALS)
    for row in rows:
        if row["proposal_id"] == "PATO-CAND:campanulate":
            row["curator_decision"] = "defer"
    proposals = tmp_path / "proposals.tsv"
    with proposals.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    release = tmp_path / "flopo.owl"
    release.write_text("<rdf:RDF></rdf:RDF>", encoding="utf-8")
    with pytest.raises(ValueError, match="not a curator-accepted proposal"):
        build_module(
            proposals,
            REGISTRY,
            ROOT / "curation" / "botanical_evidence.tsv",
            release,
            ROOT / "ont" / "plant_ontology.obo",
            ROOT / "ont" / "quality.obo",
            "2026-09-18",
        )


def test_release_update_replaces_revised_class_and_is_idempotent(tmp_path):
    release = tmp_path / "flopo.owl"
    release.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:dcterms="http://purl.org/dc/terms/">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-08-04/flopo.owl"/>
    <owl:versionInfo>2026-08-04</owl:versionInfo>
  </owl:Ontology>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0900035">
    <rdfs:label>old lianescent</rdfs:label>
  </owl:Class>
</rdf:RDF>
''',
        encoding="utf-8",
    )
    module = tmp_path / "module.ttl"
    module.write_text(
        '''@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
obo:flopo-botanical-extension-2.owl a owl:Ontology .
obo:FLOPO_0900035 a owl:Class ; rdfs:label "whole plant lianescent"@en .
obo:FLOPO_0985031 a owl:Class ; rdfs:label "whole plant climbing phenotype"@en .
''',
        encoding="utf-8",
    )

    assert update_release(release, module, "2026-09-18") == 2
    first = release.read_text(encoding="utf-8")
    assert "old lianescent" not in first
    assert first.count(BEGIN_MARKER) == 1
    assert "flopo/releases/2026-09-18/flopo.owl" in first
    assert "flopo-botanical-extension-2.owl" not in first

    assert update_release(release, module, "2026-09-18") == 2
    assert release.read_text(encoding="utf-8") == first
