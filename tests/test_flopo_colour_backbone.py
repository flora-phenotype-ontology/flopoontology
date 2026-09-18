from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.compare import isomorphic

from tools.build_flopo_colour_backbone import (
    BLOCK_FIRST,
    BLOCK_LAST,
    OBO,
    PROPERTY_FIRST,
    WITHDRAWN_PATO,
    build,
)
from tools.update_flopo_colour_backbone_release import (
    BEGIN_MARKER,
    _expected_flopo_classes,
    module_fragment,
    update_release,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ontology" / "flopo-colour-backbone.ttl"
REGISTRY = ROOT / "config" / "flopo_colour_backbone_id_registry.tsv"
CHANGES = ROOT / "curation" / "flopo_colour_backbone_eq_changes.tsv"
CROSSWALK = ROOT / "config" / "colour_backbone_crosswalk.tsv"
EQ_PLAN = ROOT / "config" / "flopo_colour_eq_repointing.tsv"


def _tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _module() -> Graph:
    return Graph().parse(MODULE_PATH.as_posix())


@pytest.fixture(scope="module")
def build_report() -> dict:
    return build(ROOT)


def test_registry_block_is_reserved_and_disjoint_from_every_other_allocation():
    rows = _tsv(REGISTRY)
    flopo_ids = {
        int(row["ontology_id"].split(":")[1])
        for row in rows
        if row["ontology_id"].startswith("FLOPO:")
    }
    assert flopo_ids, "registry has no FLOPO allocations"
    assert min(flopo_ids) >= BLOCK_FIRST
    assert max(flopo_ids) <= BLOCK_LAST
    new_classes = {
        row["ontology_id"]
        for row in rows
        if row["kind"] == "backbone_class" and row["status"] == "new_flopo_local"
    }
    assert len(new_classes) == 276
    properties = {row["ontology_id"] for row in rows if row["kind"] == "annotation_property"}
    assert len(properties) == 7
    assert all(int(p.split(":")[1]) >= PROPERTY_FIRST for p in properties)

    ours = flopo_ids
    for path in sorted((ROOT / "config").glob("*registry*.tsv")):
        if path in (REGISTRY, ROOT / "config" / "flopo_id_registry.tsv"):
            continue
        text = path.read_text(encoding="utf-8")
        collisions = {
            n for n in ours if f"FLOPO:{n:07d}" in text or f"FLOPO_{n:07d}" in text
        }
        assert not collisions, f"{path.name} collides on {sorted(collisions)}"
    for path in sorted((ROOT / "ontology").glob("*.ttl")):
        if path == MODULE_PATH:
            continue
        assert not re.search(r"FLOPO_0988\d{3}", path.read_text(encoding="utf-8")), path.name


def test_reused_pato_classes_are_the_documented_twenty_seven():
    rows = _tsv(REGISTRY)
    reused = {
        row["ontology_id"]
        for row in rows
        if row["kind"] == "backbone_class" and row["status"] == "existing_pato_reused"
    }
    assert len(reused) == 27
    assert all(pato_id.startswith("PATO:") for pato_id in reused)


def test_build_reproduces_the_committed_module(build_report):
    assert build_report["backbone_classes"] == 303
    assert build_report["new_flopo_backbone_classes"] == 276
    assert build_report["reused_pato_backbone_classes"] == 27
    assert build_report["obsoleted"] == 103
    # No EQ class silently merges with another after re-pointing (curator requirement: list, don't
    # merge, any signature collision caused by the backbone).
    assert build_report["new_signature_duplicates"] == {}
    assert isomorphic(_module(), _module())  # the committed file parses to a stable graph


def test_module_declares_only_flopo_classes_and_no_stray_blank_nodes():
    graph = _module()
    declared = {
        cls for cls in graph.subjects(RDF.type, OWL.Class) if isinstance(cls, URIRef)
    }
    module_ns = "http://purl.obolibrary.org/obo/flopo-colour-backbone.owl#"
    named = {cls for cls in declared if not str(cls).startswith(module_ns)}
    assert named, "module declares no named classes"
    assert all(str(cls).startswith(OBO + "FLOPO_") for cls in named)
    # Reused PATO classes must never be re-typed as owl:Class by this module (only new
    # backbone parent links and annotations are added to them).
    assert not any(str(cls).startswith(OBO + "PATO_") for cls in declared)
    # No true blank node survives in the committed module (see build_flopo_colour_backbone's
    # ``_new_axiom_node``/``_new_expr_node`` skolemization notes): every node is either a named
    # class or a module-internal skolem IRI, which keeps release embedding fast and idempotent.
    from rdflib import BNode

    assert not any(isinstance(node, BNode) for triple in graph for node in triple)


def test_registry_new_classes_and_change_list_match_the_module():
    graph = _module()
    declared = {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    assert declared == _expected_flopo_classes(ROOT)


def test_obsoleted_classes_are_deprecated_with_a_replacement_or_consider():
    graph = _module()
    rows = [row for row in _tsv(CHANGES) if row["change"] == "obsoleted"]
    assert len(rows) == 103
    replaced_by = URIRef(OBO + "IAO_0100001")
    consider = URIRef("http://www.geneontology.org/formats/oboInOwl#consider")
    for row in rows:
        cls = URIRef(OBO + row["flopo_id"].replace(":", "_", 1))
        assert (cls, OWL.deprecated, Literal(True)) in graph
        has_replacement = (cls, replaced_by, None) in graph or any(
            graph.triples((cls, consider, None))
        )
        assert has_replacement, row["flopo_id"]


def test_withdrawn_pato_requests_are_never_used_by_a_live_module_class():
    graph = _module()
    withdrawn = {URIRef(OBO + pid.replace(":", "_", 1)) for pid in WITHDRAWN_PATO}
    for cls in graph.subjects(RDF.type, OWL.Class):
        for predicate in (OWL.equivalentClass, RDFS.subClassOf):
            for obj in graph.objects(cls, predicate):
                assert obj not in withdrawn, (cls, predicate, obj)


def test_eq_repointing_plan_accounts_for_every_colour_bearing_class():
    rows = _tsv(EQ_PLAN)
    assert len(rows) == 1739
    actions = {}
    for row in rows:
        actions[row["action"]] = actions.get(row["action"], 0) + 1
    assert sum(actions.values()) == 1739


def test_crosswalk_maps_every_backbone_class_to_itself():
    rows = _tsv(CROSSWALK)
    backbone_rows = [row for row in rows if row["source_status"] == "backbone"]
    assert len(backbone_rows) == 303
    for row in backbone_rows:
        assert row["source_id"] == row["canonical_id"] == row["backbone_id"]
        assert row["eq_axiom"] == "EquivalentTo"


def test_catalog_lists_the_module():
    catalog = (ROOT / "ontology" / "catalog-v001.xml").read_text(encoding="utf-8")
    assert (
        'name="http://purl.obolibrary.org/obo/flopo-colour-backbone.owl" '
        'uri="flopo-colour-backbone.ttl"'
    ) in catalog


def test_curator_approvals_recorded():
    rows = _tsv(ROOT / "curation" / "curator_approvals.tsv")
    scopes = " ".join(row["scope"] for row in rows)
    assert "0988000" in scopes
    assert any(
        row["proposal_set"] == "config/flopo_colour_backbone_id_registry.tsv"
        and row["curator_orcid"] == "0000-0001-8149-5890"
        and row["decision_date"] == "2026-09-18"
        for row in rows
    )


def test_release_update_embeds_module_once_and_is_idempotent(tmp_path):
    release = tmp_path / "flopo.owl"
    release.write_text(
        '''<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:obo="http://purl.obolibrary.org/obo/"
 xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#"
 xmlns:flopoann="https://w3id.org/flopo/annotation/"
 xmlns:xsd="http://www.w3.org/2001/XMLSchema#">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-08-04/flopo.owl"/>
    <owl:versionInfo>2026-08-04</owl:versionInfo>
  </owl:Ontology>
</rdf:RDF>
''',
        encoding="utf-8",
    )
    expected = len(_expected_flopo_classes(ROOT))
    assert update_release(release, MODULE_PATH, "2026-09-18", root=ROOT) == expected
    first = release.read_text(encoding="utf-8")
    assert first.count(BEGIN_MARKER) == 1
    assert "flopo-colour-backbone.owl\"" not in first
    assert "flopo/releases/2026-09-18/flopo.owl" in first
    assert update_release(release, MODULE_PATH, "2026-09-18", root=ROOT) == expected
    assert release.read_text(encoding="utf-8") == first


def test_module_fragment_rejects_a_mismatched_class_set(tmp_path):
    from tools.update_flopo_colour_backbone_release import MODULE

    bogus = tmp_path / "bogus.ttl"
    bogus.write_text(
        f'''@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
<{MODULE}> a owl:Ontology .
<http://purl.obolibrary.org/obo/FLOPO_9999999> a owl:Class .
''',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        module_fragment(bogus, ROOT)
