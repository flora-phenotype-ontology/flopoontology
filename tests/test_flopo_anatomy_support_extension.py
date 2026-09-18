from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.compare import isomorphic

from flopo2.verify.local_bearer_table import (
    CONTEXTUAL_PO,
    EXISTING_PO,
    FLOPO_LOCAL,
    load_reviewed_bearers,
)
from tools.build_flopo_anatomy_support_extension import (
    HAS_PART,
    OBO,
    OIO,
    PART_OF,
    build_module,
    live_po_ids,
    load_allocations,
)
from tools.update_flopo_anatomy_support_release import BEGIN_MARKER, update_release


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ontology" / "flopo-anatomy-support-extension.ttl"
REGISTRY = ROOT / "config" / "flopo_anatomy_support_id_registry.tsv"
SPEC = ROOT / "curation" / "flopo_anatomy_support_classes_20260918.tsv"
BEARERS = ROOT / "config" / "reviewed_local_bearers.tsv"
PO_OBO = ROOT / "ont" / "plant_ontology.obo"
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
EXPECTED = {
    "FLOPO_0986000": ("leaflet apex", "PO_0025001", "PO_0020049"),
    "FLOPO_0986001": ("leaflet base", "PO_0025001", "PO_0020049"),
    "FLOPO_0986002": ("leaflet lamina", "PO_0025513", "PO_0020049"),
    "FLOPO_0986003": ("indumentum", "PO_0009011", "PO_0005679"),
    "FLOPO_0986004": ("perianth lobe", "PO_0025001", "PO_0009058"),
    "FLOPO_0986005": ("calyx lobe", "FLOPO_0986004", "PO_0009060"),
    "FLOPO_0986006": ("corolla lobe", "FLOPO_0986004", "PO_0009059"),
}


def _tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _module() -> Graph:
    return Graph().parse(MODULE_PATH)


def _some(graph: Graph, cls: URIRef, prop: URIRef) -> set:
    return {
        next(graph.objects(parent, OWL.someValuesFrom))
        for parent in graph.objects(cls, RDFS.subClassOf)
        if isinstance(parent, BNode) and (parent, OWL.onProperty, prop) in graph
    }


def test_registry_block_is_reserved_and_disjoint_from_every_other_allocation():
    allocations = load_allocations(REGISTRY)
    assert sorted(allocations.values()) == sorted(EXPECTED)
    ours = set(allocations.values())
    for path in sorted((ROOT / "config").glob("*registry*.tsv")):
        # flopo_id_registry.tsv is the release-wide index of every released FLOPO class, so it
        # legitimately lists this block once the module has been released.
        if path in (REGISTRY, ROOT / "config" / "flopo_id_registry.tsv"):
            continue
        text = path.read_text(encoding="utf-8")
        assert not {flopo_id for flopo_id in ours if flopo_id in text}, path.name
    for path in sorted((ROOT / "ontology").glob("*.ttl")):
        if path == MODULE_PATH:
            continue
        assert not re.search(r"FLOPO_0986\d{3}", path.read_text(encoding="utf-8")), path.name


def test_committed_module_matches_the_builder():
    assert isomorphic(build_module(SPEC, REGISTRY), _module())


def test_classes_are_provisional_po_parented_and_carry_provenance():
    graph = _module()
    live = live_po_ids(PO_OBO)
    declared = {str(cls) for cls in graph.subjects(RDF.type, OWL.Class)}
    assert declared == {OBO + flopo_id for flopo_id in EXPECTED}
    for flopo_id, (label, parent, part_of) in EXPECTED.items():
        cls = URIRef(OBO + flopo_id)
        assert (cls, RDFS.label, Literal(label, lang="en")) in graph
        definition = str(next(graph.objects(cls, IAO_DEFINITION)))
        assert definition.startswith("A ")
        note = str(next(graph.objects(cls, IAO_EDITOR_NOTE)))
        assert "provisional flopo bearer; po submission pending" in note.lower()
        assert (cls, DCTERMS.contributor, CONTRIBUTOR) in graph
        assert (cls, RDFS.subClassOf, URIRef(OBO + parent)) in graph
        assert parent in live or parent in EXPECTED
        assert _some(graph, cls, PART_OF) == {URIRef(OBO + part_of)}
        assert part_of in live
        languages = {lit.language for lit in graph.objects(cls, OIO.hasExactSynonym)}
        assert languages == {"en", "fr"}
    indumentum = URIRef(OBO + "FLOPO_0986003")
    assert _some(graph, indumentum, HAS_PART) == {URIRef(OBO + "PO_0000282")}


def test_no_po_identifier_is_minted_and_mapped_bearers_create_no_class():
    graph = _module()
    live = live_po_ids(PO_OBO)
    for cls in graph.subjects(RDF.type, OWL.Class):
        assert str(cls).startswith(OBO + "FLOPO_0986")
    maps = [row for row in _tsv(SPEC) if row["action"] == "map_existing_po"]
    assert {row["target_id"] for row in maps} == {
        "PO_0025517",
        "PO_0000050",
        "PO_0000049",
        "PO_0025349",
        "PO_0000282",
    }
    assert all(row["target_id"] in live for row in maps)


def test_po_still_lacks_the_new_bearers():
    text = PO_OBO.read_text(encoding="utf-8").lower()
    for phrase in (
        "leaflet apex",
        "leaflet base",
        "leaflet lamina",
        "indumentum",
        "perianth lobe",
        "calyx lobe",
        "corolla lobe",
    ):
        assert f'name: {phrase}\n' not in text
        assert f'"{phrase}' not in text


def test_catalog_lists_the_module():
    catalog = (ROOT / "ontology" / "catalog-v001.xml").read_text(encoding="utf-8")
    assert (
        'name="http://purl.obolibrary.org/obo/flopo-anatomy-support-extension.owl" '
        'uri="flopo-anatomy-support-extension.ttl"'
    ) in catalog


def test_reviewed_bearer_rows_use_known_ids_and_statuses():
    rows = _tsv(BEARERS)
    ours = set(EXPECTED)
    live = live_po_ids(PO_OBO)
    for row in rows:
        assert row["review_status"] in {EXISTING_PO, FLOPO_LOCAL, CONTEXTUAL_PO}
        if row["review_status"] == FLOPO_LOCAL:
            assert row["po_id"] in ours
            assert row["po_label"] == EXPECTED[row["po_id"]][0]
        else:
            assert row["po_id"] in live
    local = {row["po_id"] for row in rows if row["review_status"] == FLOPO_LOCAL}
    assert local == ours
    assert {row["surface_form"] for row in rows if row["po_id"] == "FLOPO_0986005"} >= {
        "calyx lobes",
        "lobes du calice",
    }


def test_flopo_local_aliases_are_released_gated_and_contextual_rows_never_returned():
    staged = load_reviewed_bearers(BEARERS, released_ids=set())
    assert not {row["po_id"] for row in staged} & set(EXPECTED)
    released = load_reviewed_bearers(BEARERS, released_ids=set(EXPECTED))
    assert {row["po_id"] for row in released} >= set(EXPECTED)
    surfaces = {row["surface_form"] for row in released}
    assert "scales" not in surfaces and "upper surface" not in surfaces and "awn" not in surfaces
    assert "leaf lobes" in surfaces and "lower leaf surface" in surfaces


def test_unknown_review_status_is_rejected(tmp_path):
    table = tmp_path / "bearers.tsv"
    table.write_text(
        "surface_form\tlanguage\tpo_id\tpo_label\tmatch_scope\treview_status\tnote\n"
        "x\ten\tPO_0000001\tx\texact_noun\tmaybe\t\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_reviewed_bearers(table, released_ids=set())


def test_release_update_embeds_module_once_and_is_idempotent(tmp_path):
    release = tmp_path / "flopo.owl"
    release.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:obo="http://purl.obolibrary.org/obo/"
 xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-08-04/flopo.owl"/>
    <owl:versionInfo>2026-08-04</owl:versionInfo>
  </owl:Ontology>
</rdf:RDF>
''',
        encoding="utf-8",
    )
    assert update_release(release, MODULE_PATH, "2026-09-18") == len(EXPECTED)
    first = release.read_text(encoding="utf-8")
    assert first.count(BEGIN_MARKER) == 1
    assert "flopo-anatomy-support-extension.owl" not in first
    assert "flopo/releases/2026-09-18/flopo.owl" in first
    assert update_release(release, MODULE_PATH, "2026-09-18") == len(EXPECTED)
    assert release.read_text(encoding="utf-8") == first
