"""Growth-form and life-span logical definitions (staged module, 2026-09-18)."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.compare import isomorphic

from tools.build_flopo_growth_form_extension import (
    ACCEPTED,
    FORBIDDEN_QUALITIES,
    HAS_CHARACTERISTIC,
    HAS_PART,
    IAO_DEFINITION,
    ID_BLOCK,
    OBO,
    build_module,
    live_obo_ids,
)
from tools.update_flopo_growth_form_release import (
    BEGIN_MARKER,
    QC_BEGIN,
    QC_END,
    _without_generated_block,
    update_release,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "curation" / "flopo_growth_form_logical_definitions_20260918.tsv"
REGISTRY = ROOT / "config" / "flopo_growth_form_id_registry.tsv"
EVIDENCE = ROOT / "curation" / "botanical_evidence.tsv"
FLOPO_REGISTRY = ROOT / "config" / "flopo_id_registry.tsv"
PO = ROOT / "ont" / "plant_ontology.obo"
PATO = ROOT / "ont" / "quality.obo"
MODULE_PATH = ROOT / "ontology" / "flopo-growth-form-extension.ttl"
WHOLE_PLANT = URIRef(OBO + "PO_0000003")
ROBOT_AVAILABLE = (ROOT / "tools" / "robot.jar").exists() and shutil.which("java") is not None

# Whole-plant classes that must receive the FLOPO EQ pattern, with their quality filler.
EXPECTED_EQ = {
    "FLOPO_0980070": ("PO_0000003", "PATO_0000050"),  # whole plant lifestyle
    "FLOPO_0980071": ("PO_0000003", "FLOPO_0985010"),  # annual (approved life span)
    "FLOPO_0980072": ("PO_0000003", "FLOPO_0987000"),  # biennial (proposed life span)
    "FLOPO_0980073": ("PO_0000003", "FLOPO_0985011"),  # perennial (approved life span)
    "FLOPO_0900033": ("PO_0000003", "FLOPO_0987001"),  # arborescent / tree
    "FLOPO_0900034": ("PO_0000003", "FLOPO_0987002"),  # frutescent / shrub
    "FLOPO_0987004": ("PO_0000003", "FLOPO_0987003"),  # suffrutescent / subshrub
    "FLOPO_0900039": ("PO_0025029", "PATO_0002348"),  # shoot axis ligneous
    "FLOPO_0900042": ("PO_0009007", "PATO_0104019"),  # tissue succulent
}

# Every named FLOPO ancestor that ELK newly infers for a released class after adding the staged module
# (ELK check of 2026-09-18 on a scratch copy). A change here is a reviewable event.
EXPECTED_NEW_ANCESTORS = {
    "FLOPO_0013842": {"FLOPO_0900038", "FLOPO_0900039"},
    "FLOPO_0900023": {"FLOPO_0980070", "FLOPO_0980071"},
    "FLOPO_0900028": {"FLOPO_0980070", "FLOPO_0980073"},
    "FLOPO_0900029": {"FLOPO_0980070", "FLOPO_0980073"},
    "FLOPO_0900033": {"FLOPO_0000451", "FLOPO_0980070", "FLOPO_0980073"},
    "FLOPO_0900034": {
        "FLOPO_0000451",
        "FLOPO_0001313",
        "FLOPO_0008318",
        "FLOPO_0900038",
        "FLOPO_0900039",
        "FLOPO_0980070",
        "FLOPO_0980073",
    },
    "FLOPO_0900035": {"FLOPO_0900038", "FLOPO_0900039", "FLOPO_0980070", "FLOPO_0980073"},
    "FLOPO_0980083": {"FLOPO_0000001", "FLOPO_0005913", "FLOPO_0005915"},
}


def _named_ancestors(path: Path) -> tuple[dict, set]:
    graph = Graph().parse(path)
    parents: dict[URIRef, set[URIRef]] = {}
    for predicate in (RDFS.subClassOf, OWL.equivalentClass):
        for subject, obj in graph.subject_objects(predicate):
            if isinstance(subject, URIRef) and isinstance(obj, URIRef):
                parents.setdefault(subject, set()).add(obj)
                if predicate == OWL.equivalentClass:
                    parents.setdefault(obj, set()).add(subject)
    memo: dict[URIRef, set[URIRef]] = {}

    def ancestors(cls: URIRef) -> set[URIRef]:
        if cls not in memo:
            memo[cls] = set()
            found: set[URIRef] = set()
            for parent in parents.get(cls, ()):
                found |= {parent} | ancestors(parent)
            memo[cls] = found
        return memo[cls]

    closure = {cls: ancestors(cls) for cls in parents if str(cls).startswith(OBO + "FLOPO_")}
    unsat = {str(cls) for cls, found in parents.items() if OWL.Nothing in found}
    return closure, unsat


def _inferred_diff(baseline: Path, module: Path) -> dict:
    old, _old_unsat = _named_ancestors(baseline)
    new, new_unsat = _named_ancestors(module)
    changes = []
    for cls in sorted(set(old) | set(new), key=str):
        added = new.get(cls, set()) - old.get(cls, set())
        lost = old.get(cls, set()) - new.get(cls, set())
        if added or lost:
            changes.append(
                {
                    "cls": str(cls),
                    "added": [(str(a), "") for a in sorted(added, key=str)],
                    "lost": [str(a) for a in sorted(lost, key=str)],
                }
            )
    return {"unsat_new": sorted(new_unsat), "changes": changes}


def _tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _build(include_pending: bool) -> Graph:
    return build_module(
        SPEC, REGISTRY, EVIDENCE, FLOPO_REGISTRY, PO, PATO, include_pending=include_pending
    )


def _eq_parts(graph: Graph, cls: URIRef) -> tuple[URIRef, URIRef]:
    (expression,) = list(graph.objects(cls, OWL.equivalentClass))
    assert (expression, OWL.onProperty, HAS_PART) in graph
    filler = next(graph.objects(expression, OWL.someValuesFrom))
    entity, characteristic = Collection(graph, next(graph.objects(filler, OWL.intersectionOf)))
    assert (characteristic, OWL.onProperty, HAS_CHARACTERISTIC) in graph
    return entity, next(graph.objects(characteristic, OWL.someValuesFrom))


def test_registry_block_is_reserved_unique_and_matches_the_specification():
    rows = _tsv(REGISTRY)
    ids = [row["flopo_id"] for row in rows]
    assert ids == [f"FLOPO_{n:07d}" for n in range(987000, 987005)]
    assert all(ID_BLOCK[0] <= int(value[6:]) <= ID_BLOCK[1] for value in ids)
    other: set[str] = set()
    for path in sorted((ROOT / "config").glob("flopo_*id_registry.tsv")):
        if path in {REGISTRY, FLOPO_REGISTRY}:
            continue
        other.update(row.get("flopo_id", "") for row in _tsv(path))
    assert not set(ids) & other
    released = {row["flopo_iri"].rsplit("/", 1)[1]: row["label"] for row in _tsv(FLOPO_REGISTRY)}
    for row in rows:
        # Before the release the IDs are unused; afterwards they must keep their labels.
        assert released.get(row["flopo_id"], row["label"]) == row["label"]
    new_rows = {
        row["target"]: row["label"]
        for row in _tsv(SPEC)
        if row["action"] in {"new_local_quality", "new_phenotype"}
    }
    assert new_rows == {row["proposal_key"]: row["label"] for row in rows}


def test_specification_references_live_terms_evidence_and_no_homonyms():
    live = live_obo_ids(PO, PATO)
    evidence = {row["evidence_id"] for row in _tsv(EVIDENCE)}
    released = {
        "FLOPO:" + row["flopo_iri"].rsplit("_", 1)[1]
        for row in _tsv(FLOPO_REGISTRY)
        if row["deprecated"] == "0"
    }
    for row in _tsv(SPEC):
        assert row["curator_decision"] in ACCEPTED | {"", "defer", "reject"}
        for token in (row["entity"], row["quality"], row["parent"]):
            if token.startswith(("PO:", "PATO:")):
                assert token in live, (row["row_id"], token)
                assert token not in FORBIDDEN_QUALITIES
            elif token.startswith("FLOPO:"):
                assert token in released, (row["row_id"], token)
        for token in filter(None, row["definition_sources"].split("|")):
            assert token in evidence, (row["row_id"], token)
        if row["action"] in {"new_local_quality", "new_phenotype", "revise_definition"}:
            assert row["definition"] and row["definition_sources"], row["row_id"]
        assert row["rationale"], row["row_id"]


def test_staged_module_is_current_and_nothing_is_releasable_before_review():
    module = Graph().parse(MODULE_PATH)
    staged = _build(include_pending=True)
    accepted = _build(include_pending=False)
    assert isomorphic(module, staged) or isomorphic(module, accepted)
    pending = [row for row in _tsv(SPEC) if row["curator_decision"] not in ACCEPTED]
    if pending:
        with pytest.raises(ValueError, match="accepted-only build"):
            update_release(ROOT / "does-not-exist.owl", MODULE_PATH, "2026-09-18")


def test_whole_plant_classes_get_the_eq_pattern_with_the_right_qualities():
    graph = _build(include_pending=True)
    for flopo_id, (entity, quality) in EXPECTED_EQ.items():
        found = _eq_parts(graph, URIRef(OBO + flopo_id))
        assert found == (URIRef(OBO + entity), URIRef(OBO + quality)), flopo_id
    for cls, _p, _o in graph.triples((None, OWL.equivalentClass, None)):
        assert str(cls).rsplit("/", 1)[1] in EXPECTED_EQ
    # Climbing, vine and epiphyte stay primitive; herbaceous keeps its released EQ.
    for flopo_id in ("FLOPO_0985031", "FLOPO_0985032", "FLOPO_0900030", "FLOPO_0022142"):
        assert (URIRef(OBO + flopo_id), None, None) not in graph


def test_local_qualities_sit_directly_under_live_pato_and_life_spans_are_disjoint():
    graph = _build(include_pending=True)
    parents = {
        "FLOPO_0987000": "PATO_0000050",
        "FLOPO_0987001": "PATO_0000051",
        "FLOPO_0987002": "PATO_0000051",
        "FLOPO_0987003": "PATO_0000051",
        "FLOPO_0987004": "FLOPO_0900032",
    }
    for flopo_id, parent in parents.items():
        cls = URIRef(OBO + flopo_id)
        named = {p for p in graph.objects(cls, RDFS.subClassOf) if isinstance(p, URIRef)}
        assert named == {URIRef(OBO + parent)}
        assert len(set(graph.objects(cls, IAO_DEFINITION))) == 1
        assert len(set(graph.objects(cls, RDFS.label))) == 1
    (disjoint,) = list(graph.subjects(RDF.type, OWL.AllDisjointClasses))
    members = set(Collection(graph, next(graph.objects(disjoint, OWL.members))))
    assert members == {URIRef(OBO + f) for f in ("FLOPO_0985010", "FLOPO_0987000", "FLOPO_0985011")}


def test_module_is_additive_for_released_classes():
    graph = _build(include_pending=True)
    new = {s for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    touched = {s for s in graph.subjects() if isinstance(s, URIRef) and str(s).startswith(OBO + "FLOPO_")}
    for cls in touched - new:
        assert (cls, RDFS.label, None) not in graph
        definitions = set(graph.objects(cls, IAO_DEFINITION))
        assert len(definitions) <= 1
    redefined = {s for s in touched - new if (s, IAO_DEFINITION, None) in graph}
    assert redefined == {URIRef(OBO + "FLOPO_0980072"), URIRef(OBO + "FLOPO_0980073")}
    # Necessary-only woody and perennial conditions are SubClassOf, never equivalences.
    frutescent = URIRef(OBO + "FLOPO_0900034")
    fillers = [
        next(graph.objects(parent, OWL.someValuesFrom))
        for parent in graph.objects(frutescent, RDFS.subClassOf)
        if isinstance(parent, BNode)
    ]
    qualities = set()
    for filler in fillers:
        for member in Collection(graph, next(graph.objects(filler, OWL.intersectionOf))):
            qualities.update(graph.objects(member, OWL.someValuesFrom))
    assert qualities == {URIRef(OBO + "PATO_0002348"), URIRef(OBO + "FLOPO_0985011")}


def _synthetic_release(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
 xmlns:owl="http://www.w3.org/2002/07/owl#"
 xmlns:obo="http://purl.obolibrary.org/obo/"
 xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#"
 xmlns:dcterms="http://purl.org/dc/terms/">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-08-04/flopo.owl"/>
    <owl:versionInfo>2026-08-04</owl:versionInfo>
  </owl:Ontology>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0980073">
    <rdfs:label xml:lang="en">whole plant perennial</rdfs:label>
  </owl:Class>
  <!-- BEGIN GENERATED FLOPO OBO QC DEFINITIONS -->
  <rdf:Description rdf:about="http://purl.obolibrary.org/obo/FLOPO_0980073">
    <obo:IAO_0000115 xml:lang="en">old text: more than one growing season.</obo:IAO_0000115>
    <dcterms:source rdf:resource="https://example.org/perennial"/>
  </rdf:Description>
  <!-- END GENERATED FLOPO OBO QC DEFINITIONS -->
</rdf:RDF>
""",
        encoding="utf-8",
    )


def _synthetic_module(path: Path) -> None:
    path.write_text(
        """@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
obo:flopo-growth-form-extension.owl a owl:Ontology ; dcterms:modified "2026-09-18"^^xsd:date .
obo:FLOPO_0980073 obo:IAO_0000115 "new text: more than two years."@en ;
    owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
        owl:someValuesFrom [ a owl:Class ; owl:intersectionOf ( obo:PO_0000003
            [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ;
              owl:someValuesFrom obo:FLOPO_0985011 ] ) ] ] .
obo:FLOPO_0987000 a owl:Class ; rdfs:label "biennial life span"@en ;
    obo:IAO_0000115 "A life span quality."@en ; rdfs:subClassOf obo:PATO_0000050 .
""",
        encoding="utf-8",
    )


def test_release_replaces_only_the_qc_definition_and_is_idempotent(tmp_path):
    release, module = tmp_path / "flopo.owl", tmp_path / "module.ttl"
    _synthetic_release(release)
    _synthetic_module(module)

    stats = update_release(release, module, "2026-09-18", allow_pending=True)
    assert stats == {"new_classes": 1, "redefined_classes": 1, "stripped_qc_definitions": 1}
    first = release.read_text(encoding="utf-8")
    assert "old text" not in first
    assert "https://example.org/perennial" in first
    assert first.count(BEGIN_MARKER) == 1
    assert "flopo/releases/2026-09-18/flopo.owl" in first
    graph = Graph().parse(release)
    perennial = URIRef(OBO + "FLOPO_0980073")
    assert set(graph.objects(perennial, IAO_DEFINITION)) == {
        Literal("new text: more than two years.", lang="en")
    }
    assert (perennial, OWL.equivalentClass, None) in graph

    update_release(release, module, "2026-09-18", allow_pending=True)
    assert release.read_text(encoding="utf-8") == first


def test_release_refuses_to_override_a_definition_owned_by_another_module(tmp_path):
    release, module = tmp_path / "flopo.owl", tmp_path / "module.ttl"
    _synthetic_release(release)
    text = release.read_text(encoding="utf-8").replace(
        '<rdfs:label xml:lang="en">whole plant perennial</rdfs:label>',
        '<rdfs:label xml:lang="en">whole plant perennial</rdfs:label>\n'
        '    <obo:IAO_0000115 xml:lang="en">curated elsewhere</obo:IAO_0000115>',
    )
    release.write_text(text, encoding="utf-8")
    _synthetic_module(module)
    with pytest.raises(ValueError, match="outside the OBO QC block"):
        update_release(release, module, "2026-09-18", allow_pending=True)
    assert QC_BEGIN in release.read_text(encoding="utf-8")
    assert QC_END in release.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not ROBOT_AVAILABLE or os.environ.get("FLOPO_RUN_ELK") != "1",
    reason="set FLOPO_RUN_ELK=1 (needs ROBOT/Java; classifies the full release twice, ~5 min)",
)
def test_elk_release_copy_is_coherent_and_new_inferences_are_the_reviewed_ones(tmp_path):
    """Classify flopo.owl before and after embedding the staged module on a scratch copy."""

    # The baseline is the release without this module's generated block, so the comparison stays
    # meaningful after the module has been released into ontology/flopo.owl.
    baseline = tmp_path / "baseline.owl"
    baseline.write_text(
        _without_generated_block((ROOT / "ontology" / "flopo.owl").read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    scratch = tmp_path / "flopo.owl"
    shutil.copyfile(baseline, scratch)
    update_release(scratch, MODULE_PATH, "2026-09-18", allow_pending=True)
    outputs = {}
    for name, source in (("baseline", baseline), ("module", scratch)):
        outputs[name] = tmp_path / f"{name}-inferred.owl"
        # ROBOT reason with ELK fails on any unsatisfiable class, so success means coherence.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.classify_flopo_release",
                "--source",
                str(source),
                "--output",
                str(outputs[name]),
            ],
            cwd=ROOT,
            check=True,
        )
    result = _inferred_diff(outputs["baseline"], outputs["module"])
    nothing = "http://www.w3.org/2002/07/owl#Nothing"
    assert set(result["unsat_new"]) <= {nothing}
    changes = {
        change["cls"].rsplit("/", 1)[1]: {
            added.rsplit("/", 1)[1]
            for added, _label in change["added"]
            if "/FLOPO_" in added
        }
        for change in result["changes"]
        if not change["cls"].endswith(("FLOPO_0987000", "FLOPO_0987001", "FLOPO_0987002",
                                       "FLOPO_0987003", "FLOPO_0987004"))
    }
    assert changes == EXPECTED_NEW_ANCESTORS
    assert all(not change["lost"] for change in result["changes"])
