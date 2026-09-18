#!/usr/bin/env python3
"""Build the curator-approved FLOPO anatomy support module of 2026-09-18.

Input is ``curation/flopo_anatomy_support_classes_20260918.tsv``. Rows with action
``new_flopo_local`` become provisional FLOPO-local bearer classes directly beneath their closest
live PO parent (or beneath another class of this module), with a genus-differentia definition,
only universally true ``part_of``/``has_part`` restrictions, and exact English and French
synonyms. Rows with action ``map_existing_po`` record bearers PO already has; they create no
class. No PO identifier is minted.

Identifiers come from ``config/flopo_anatomy_support_id_registry.tsv``, which reserves the block
FLOPO_0986000-FLOPO_0986999. The block sits above the sequential allocations and the botanical
concept block (FLOPO_0985000-0985999), so concurrent allocators cannot collide with it.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef


OBO = Namespace("http://purl.obolibrary.org/obo/")
OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
MODULE = URIRef(OBO + "flopo-anatomy-support-extension.owl")
PO_ONTOLOGY = URIRef(OBO + "po.owl")
HAS_PART = URIRef(OBO + "BFO_0000051")
PART_OF = URIRef(OBO + "BFO_0000050")
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
ID_BLOCK = (986000, 986999)
PROVENANCE = "Provisional FLOPO bearer; PO submission pending"
DEFAULT_SPEC = Path("curation/flopo_anatomy_support_classes_20260918.tsv")
DEFAULT_REGISTRY = Path("config/flopo_anatomy_support_id_registry.tsv")
DEFAULT_EVIDENCE = Path("curation/botanical_evidence.tsv")
DEFAULT_PO = Path("ont/plant_ontology.obo")
DEFAULT_OUTPUT = Path("ontology/flopo-anatomy-support-extension.ttl")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def live_po_ids(path: Path = DEFAULT_PO) -> set[str]:
    """Return non-obsolete PO identifiers (``PO_nnnnnnn``) of the pinned OBO file."""

    live: set[str] = set()
    current: str | None = None
    obsolete = False
    in_term = False

    def finish() -> None:
        if in_term and current and not obsolete:
            live.add(current.replace(":", "_"))

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            finish()
            in_term = line == "[Term]"
            current, obsolete = None, False
        elif in_term and line.startswith("id: "):
            current = line[4:].strip()
        elif in_term and line.startswith("is_obsolete: true"):
            obsolete = True
    finish()
    return {identifier for identifier in live if identifier.startswith("PO_")}


def load_allocations(path: Path = DEFAULT_REGISTRY) -> dict[str, str]:
    allocations: dict[str, str] = {}
    for row in _rows(path):
        key, flopo_id = row["proposal_key"], row["flopo_id"]
        match = re.fullmatch(r"FLOPO_(\d{7})", flopo_id)
        if not match or not ID_BLOCK[0] <= int(match.group(1)) <= ID_BLOCK[1]:
            raise ValueError(f"{key}: {flopo_id} is outside the reserved block")
        if key in allocations or flopo_id in allocations.values():
            raise ValueError(f"duplicate allocation for {key} / {flopo_id}")
        allocations[key] = flopo_id
    return allocations


def _restriction(graph: Graph, prop: URIRef, filler: URIRef) -> BNode:
    node = BNode()
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, prop))
    graph.add((node, OWL.someValuesFrom, filler))
    return node


def build_module(
    spec_path: Path = DEFAULT_SPEC,
    registry_path: Path = DEFAULT_REGISTRY,
    evidence_path: Path = DEFAULT_EVIDENCE,
    po_path: Path = DEFAULT_PO,
    created: str = "2026-09-18",
) -> Graph:
    spec = _rows(spec_path)
    allocations = load_allocations(registry_path)
    evidence = {row["evidence_id"]: row for row in _rows(evidence_path)}
    live = live_po_ids(po_path)
    new_rows = [row for row in spec if row["action"] == "new_flopo_local"]
    if {row["proposal_key"] for row in new_rows} != set(allocations):
        raise ValueError("registry and new_flopo_local rows disagree")

    def resolve(token: str) -> URIRef:
        if token in allocations:
            return URIRef(OBO + allocations[token])
        if token.startswith("PO_"):
            if token not in live:
                raise ValueError(f"{token} is not a live PO class in {po_path}")
            return URIRef(OBO + token)
        raise ValueError(f"unresolvable parent or filler {token!r}")

    for row in spec:
        if row["action"] == "map_existing_po" and row["target_id"] not in live:
            raise ValueError(f"mapping target {row['target_id']} is not a live PO class")

    graph = Graph()
    graph.bind("obo", OBO)
    graph.bind("oboInOwl", OIO)
    graph.bind("dcterms", DCTERMS)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, OWL.imports, PO_ONTOLOGY))
    graph.add((MODULE, RDFS.label, Literal("FLOPO anatomy support extension", lang="en")))
    graph.add((MODULE, DCTERMS.created, Literal(created, datatype=XSD.date)))
    graph.add(
        (MODULE, DCTERMS.license, URIRef("https://creativecommons.org/publicdomain/zero/1.0/"))
    )
    for prop in (IAO_DEFINITION, IAO_EDITOR_NOTE):
        graph.add((prop, RDF.type, OWL.AnnotationProperty))
    for prop in (HAS_PART, PART_OF):
        graph.add((prop, RDF.type, OWL.ObjectProperty))

    for row in new_rows:
        cls = URIRef(OBO + allocations[row["proposal_key"]])
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((cls, RDFS.label, Literal(row["label"], lang="en")))
        graph.add((cls, IAO_DEFINITION, Literal(row["definition"], lang="en")))
        note = (
            f"{PROVENANCE}. Curator-approved FLOPO-local anatomy support class "
            f"{row['proposal_key']} (Robert Hoehndorf, 2026-09-18; "
            "curation/flopo_anatomy_support_classes_20260918.tsv). PO check: "
            f"{row['po_check']} Replace with the PO identifier via IAO:0100001 once assigned. "
            "No PO identifier is minted locally."
        )
        graph.add((cls, IAO_EDITOR_NOTE, Literal(note, lang="en")))
        graph.add((cls, DCTERMS.contributor, CONTRIBUTOR))
        graph.add((cls, DCTERMS.created, Literal(created, datatype=XSD.date)))
        for evidence_id in _split(row["evidence"]):
            if evidence_id not in evidence:
                raise ValueError(f"unknown evidence {evidence_id}")
            graph.add((cls, DCTERMS.source, URIRef(evidence[evidence_id]["url"])))
        for text in _split(row["exact_synonyms_en"]):
            graph.add((cls, OIO.hasExactSynonym, Literal(text, lang="en")))
        for text in _split(row["exact_synonyms_fr"]):
            graph.add((cls, OIO.hasExactSynonym, Literal(text, lang="fr")))
        for text in _split(row["related_synonyms_en"]):
            graph.add((cls, OIO.hasRelatedSynonym, Literal(text, lang="en")))
        for parent in _split(row["is_a"]):
            graph.add((cls, RDFS.subClassOf, resolve(parent)))
        for filler in _split(row["part_of"]):
            graph.add((cls, RDFS.subClassOf, _restriction(graph, PART_OF, resolve(filler))))
        for filler in _split(row["has_part"]):
            graph.add((cls, RDFS.subClassOf, _restriction(graph, HAS_PART, resolve(filler))))
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--po", type=Path, default=DEFAULT_PO)
    parser.add_argument("--date", default="2026-09-18")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    graph = build_module(args.spec, args.registry, args.evidence, args.po, args.date)
    args.output.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    count = len(set(graph.subjects(RDF.type, OWL.Class)))
    print(f"wrote {count} FLOPO anatomy support classes to {args.output}")


if __name__ == "__main__":
    main()
