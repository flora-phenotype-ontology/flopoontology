#!/usr/bin/env python3
"""Build the FLOPO growth-form and life-span logical-definition module.

Input is ``curation/flopo_growth_form_logical_definitions_20260918.tsv`` (one row per proposed
class, axiom, disjointness or definition revision; see ``ACTIONS``). The module gives the
released whole-plant growth-form and life-span classes the FLOPO EQ pattern

    <phenotype> EquivalentTo BFO:0000051 some (PO:0000003 and RO:0000053 some <quality>)

where the quality is a live PATO class, an approved FLOPO-local PATO candidate
(FLOPO:0985010 annual life span, FLOPO:0985011 perennial life span) or a new FLOPO-local
support quality proposed here. Supporting qualities sit directly beneath their closest live PATO
class and carry a genus-differentia definition with glossary evidence. Necessary-only conditions
are ``SubClassOf`` axioms.

The module is additive: it never repeats a released label, and it only adds a textual
definition for rows with action ``revise_definition``. The paired release tool strips the
superseded OBO QC definition for exactly those classes.

Every row is review-only until ``curator_decision`` is ``accept`` or ``accept_with_revision``.
By default only accepted rows are built; ``--include-pending`` builds the whole staged proposal
for review and testing. The release tool refuses a module that differs from an accepted-only
build.

Identifiers come from ``config/flopo_growth_form_id_registry.tsv``, which reserves the block
FLOPO_0987000-FLOPO_0987999 above the botanical-concept (0985xxx) and anatomy-support
(0986xxx) blocks.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection


OBO = Namespace("http://purl.obolibrary.org/obo/")
OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
MODULE = URIRef(OBO + "flopo-growth-form-extension.owl")
PATO_ONTOLOGY = URIRef(OBO + "pato.owl")
PO_ONTOLOGY = URIRef(OBO + "po.owl")
HAS_PART = URIRef(OBO + "BFO_0000051")
HAS_CHARACTERISTIC = URIRef(OBO + "RO_0000053")
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
ID_BLOCK = (987000, 987999)
ACCEPTED = {"accept", "accept_with_revision"}
DECISIONS = ACCEPTED | {"", "defer", "reject"}
ACTIONS = {
    "new_local_quality",
    "new_phenotype",
    "logical_axiom",
    "disjoint_qualities",
    "revise_definition",
    "no_logical_definition",
}
# PATO:0002352 herbaceous is the die-back sense, PATO:0095004 arboreal is adaptation for living
# in trees; neither may stand for a woodiness or tree-habit value in this module.
FORBIDDEN_QUALITIES = {"PATO:0002352", "PATO:0095004"}
SPEC = Path("curation/flopo_growth_form_logical_definitions_20260918.tsv")
REGISTRY = Path("config/flopo_growth_form_id_registry.tsv")
EVIDENCE = Path("curation/botanical_evidence.tsv")
FLOPO_REGISTRY = Path("config/flopo_id_registry.tsv")
PO = Path("ont/plant_ontology.obo")
PATO = Path("ont/quality.obo")
OUTPUT = Path("ontology/flopo-growth-form-extension.ttl")
SYNONYM_PROPERTY = {
    "exact": OIO.hasExactSynonym,
    "related": OIO.hasRelatedSynonym,
    "narrow": OIO.hasNarrowSynonym,
    "broad": OIO.hasBroadSynonym,
}
UPSTREAM_DRAFT = "PATO new-term request batch with the approved annual/perennial life spans"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def live_obo_ids(*paths: Path) -> set[str]:
    """Return non-obsolete ``PREFIX:nnnnnnn`` term identifiers of the pinned OBO files."""

    live: set[str] = set()
    for path in paths:
        current: str | None = None
        obsolete = False
        in_term = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("["):
                if in_term and current and not obsolete:
                    live.add(current)
                in_term = line == "[Term]"
                current, obsolete = None, False
            elif in_term and line.startswith("id: ") and current is None:
                current = line[4:].strip()
            elif in_term and line.startswith("is_obsolete: true"):
                obsolete = True
        if in_term and current and not obsolete:
            live.add(current)
    return live


def active_flopo_ids(path: Path = FLOPO_REGISTRY) -> dict[str, str]:
    """Return ``FLOPO:nnnnnnn -> label`` for non-deprecated released FLOPO classes."""

    return {
        "FLOPO:" + row["flopo_iri"].rsplit("_", 1)[1]: row["label"]
        for row in _rows(path)
        if row.get("deprecated", "0") == "0"
    }


def selected_rows(spec: list[dict[str, str]], include_pending: bool) -> list[dict[str, str]]:
    for row in spec:
        if row["action"] not in ACTIONS:
            raise ValueError(f"{row['row_id']}: unknown action {row['action']!r}")
        if row["curator_decision"] not in DECISIONS:
            raise ValueError(f"{row['row_id']}: unknown curator decision")
    return [
        row
        for row in spec
        if row["action"] != "no_logical_definition"
        and (
            row["curator_decision"] in ACCEPTED
            or (include_pending and row["curator_decision"] in {"", "defer"})
        )
    ]


def build_module(
    spec_path: Path = SPEC,
    registry_path: Path = REGISTRY,
    evidence_path: Path = EVIDENCE,
    flopo_registry_path: Path = FLOPO_REGISTRY,
    po_path: Path = PO,
    pato_path: Path = PATO,
    release_date: str = "2026-09-18",
    *,
    include_pending: bool = False,
) -> Graph:
    spec = _rows(spec_path)
    allocations = {row["proposal_key"]: row for row in _rows(registry_path)}
    evidence = {row["evidence_id"]: row for row in _rows(evidence_path)}
    released = active_flopo_ids(flopo_registry_path)
    live = live_obo_ids(po_path, pato_path)

    ids = [row["flopo_id"] for row in allocations.values()]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate FLOPO identifier in growth-form registry")
    for key, entry in allocations.items():
        number = int(entry["flopo_id"].removeprefix("FLOPO_"))
        if not ID_BLOCK[0] <= number <= ID_BLOCK[1]:
            raise ValueError(f"{entry['flopo_id']} is outside the reserved block")
        curie = "FLOPO:" + entry["flopo_id"][6:]
        if curie in released and released[curie] != entry["label"]:
            # After a release the global registry lists these classes too; a shared
            # identifier must denote the same class.
            raise ValueError(f"{entry['flopo_id']} is released with a different label")
    by_key = {
        row["target"]: row
        for row in spec
        if row["action"] in {"new_local_quality", "new_phenotype"}
    }
    if set(by_key) != set(allocations):
        raise ValueError("growth-form registry and specification disagree on new classes")
    for key, row in by_key.items():
        if allocations[key]["label"] != row["label"]:
            raise ValueError(f"label mismatch for {key}")

    rows = selected_rows(spec, include_pending)
    built_new = {row["target"] for row in rows if row["target"] in allocations}

    def resolve(token: str) -> URIRef:
        token = token.strip()
        if token in allocations:
            if token not in built_new:
                raise ValueError(f"{token} is referenced but its proposal row is not accepted")
            return URIRef(OBO + allocations[token]["flopo_id"])
        if token in FORBIDDEN_QUALITIES:
            raise ValueError(f"{token} is a homonym that must not be used here")
        if token.startswith(("PO:", "PATO:")):
            if token not in live:
                raise ValueError(f"{token} is not a live term in the pinned PO/PATO")
            return URIRef(OBO + token.replace(":", "_", 1))
        if token.startswith("FLOPO:"):
            if token not in released:
                raise ValueError(f"{token} is not an active released FLOPO class")
            return URIRef(OBO + token.replace(":", "_", 1))
        raise ValueError(f"unresolvable reference {token!r}")

    graph = Graph()
    for prefix, namespace in (
        ("dcterms", DCTERMS),
        ("obo", OBO),
        ("oboInOwl", OIO),
        ("owl", OWL),
        ("rdf", RDF),
        ("rdfs", RDFS),
    ):
        graph.bind(prefix, namespace)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, OWL.imports, PATO_ONTOLOGY))
    graph.add((MODULE, OWL.imports, PO_ONTOLOGY))
    graph.add(
        (
            MODULE,
            RDFS.label,
            Literal("FLOPO growth-form and life-span logical definitions", lang="en"),
        )
    )
    graph.add((MODULE, DCTERMS.modified, Literal(release_date, datatype=XSD.date)))
    graph.add(
        (MODULE, DCTERMS.license, URIRef("https://creativecommons.org/publicdomain/zero/1.0/"))
    )

    def sources(row: dict[str, str]) -> list[URIRef]:
        urls = []
        for token in _split(row["definition_sources"]):
            if token not in evidence or not evidence[token]["url"]:
                raise ValueError(f"{row['row_id']}: unknown evidence {token}")
            urls.append(URIRef(evidence[token]["url"]))
        if not urls:
            raise ValueError(f"{row['row_id']}: a definition needs at least one source")
        return urls

    def status(row: dict[str, str]) -> str:
        decision = row["curator_decision"]
        if decision in ACCEPTED:
            return f"curator decision {decision}"
        return "PENDING curator review (review-only; not releasable)"

    def note(cls: URIRef, row: dict[str, str], text: str) -> None:
        graph.add(
            (
                cls,
                IAO_EDITOR_NOTE,
                Literal(
                    f"Growth-form logical definition row {row['row_id']} "
                    f"(curation/flopo_growth_form_logical_definitions_20260918.tsv, "
                    f"{status(row)}). {text}",
                    lang="en",
                ),
            )
        )

    counter = 0
    axiom_rows: dict[URIRef, list[dict[str, str]]] = {}

    def restriction(prop: URIRef, filler) -> BNode:
        nonlocal counter
        counter += 1
        node = BNode(f"gf{counter:03d}")
        graph.add((node, RDF.type, OWL.Restriction))
        graph.add((node, OWL.onProperty, prop))
        graph.add((node, OWL.someValuesFrom, filler))
        return node

    def eq_expression(entity: URIRef, quality: URIRef | None) -> BNode:
        if quality is None:
            return restriction(HAS_PART, entity)
        nonlocal counter
        counter += 1
        filler = BNode(f"gf{counter:03d}")
        head = BNode(f"gf{counter:03d}_list")
        Collection(graph, head, [entity, restriction(HAS_CHARACTERISTIC, quality)])
        graph.add((filler, RDF.type, OWL.Class))
        graph.add((filler, OWL.intersectionOf, head))
        return restriction(HAS_PART, filler)

    for row in rows:
        action = row["action"]
        if action in {"new_local_quality", "new_phenotype"}:
            entry = allocations[row["target"]]
            cls = URIRef(OBO + entry["flopo_id"])
            parent = resolve(row["parent"])
            if action == "new_local_quality":
                if not row["parent"].startswith("PATO:"):
                    raise ValueError(f"{row['row_id']}: a local quality needs a PATO parent")
            elif not row["parent"].startswith("FLOPO:"):
                raise ValueError(f"{row['row_id']}: a phenotype needs a FLOPO parent")
            graph.add((cls, RDF.type, OWL.Class))
            graph.add((cls, RDFS.label, Literal(row["label"], lang="en")))
            graph.add((cls, RDFS.subClassOf, parent))
            graph.add((cls, IAO_DEFINITION, Literal(row["definition"], lang="en")))
            graph.add((cls, DCTERMS.contributor, CONTRIBUTOR))
            graph.add((cls, DCTERMS.created, Literal(release_date, datatype=XSD.date)))
            for url in sources(row):
                graph.add((cls, DCTERMS.source, url))
            for synonym in _split(row["synonyms"]):
                scope, text = synonym.split(":", 1)
                graph.add((cls, SYNONYM_PROPERTY[scope], Literal(text, lang="en")))
            if action == "new_local_quality":
                note(
                    cls,
                    row,
                    "Provisional FLOPO-local support quality parented directly beneath its "
                    f"closest live PATO class; propose to PATO ({UPSTREAM_DRAFT}) and replace "
                    "via IAO:0100001 once a PATO identifier is assigned.",
                )
            else:
                note(cls, row, "FLOPO-local whole-plant growth-form phenotype.")
        elif action == "logical_axiom":
            cls = resolve(row["target"])
            entity = resolve(row["entity"])
            quality = resolve(row["quality"]) if row["quality"] else None
            expression = eq_expression(entity, quality)
            if row["axiom"] == "EquivalentTo":
                if quality is None:
                    raise ValueError(f"{row['row_id']}: an equivalence needs a quality")
                graph.add((cls, OWL.equivalentClass, expression))
            elif row["axiom"] == "SubClassOf":
                graph.add((cls, RDFS.subClassOf, expression))
            else:
                raise ValueError(f"{row['row_id']}: unknown axiom type {row['axiom']!r}")
            if row["target"] not in allocations:
                axiom_rows.setdefault(cls, []).append(row)
        elif action == "disjoint_qualities":
            members = [resolve(token) for token in _split(row["target"])]
            if len(members) < 2:
                raise ValueError(f"{row['row_id']}: disjointness needs two classes")
            node = BNode("gf_disjoint_life_spans")
            head = BNode("gf_disjoint_life_spans_list")
            Collection(graph, head, members)
            graph.add((node, RDF.type, OWL.AllDisjointClasses))
            graph.add((node, OWL.members, head))
        elif action == "revise_definition":
            cls = resolve(row["target"])
            if row["target"] in allocations:
                raise ValueError(f"{row['row_id']}: revise only released classes")
            graph.add((cls, IAO_DEFINITION, Literal(row["definition"], lang="en")))
            for url in sources(row):
                graph.add((cls, DCTERMS.source, url))
            note(cls, row, "Textual definition revised in place; the referent is unchanged.")

    for cls, class_rows in axiom_rows.items():
        pending = any(row["curator_decision"] not in ACCEPTED for row in class_rows)
        graph.add(
            (
                cls,
                IAO_EDITOR_NOTE,
                Literal(
                    "Logical axioms added by growth-form rows "
                    f"{', '.join(row['row_id'] for row in class_rows)} "
                    "(curation/flopo_growth_form_logical_definitions_20260918.tsv, "
                    + (
                        "PENDING curator review (review-only; not releasable)"
                        if pending
                        else "curator-accepted"
                    )
                    + "). Rationale and necessary/sufficient status are recorded per row.",
                    lang="en",
                ),
            )
        )

    declared = {
        subject
        for subject in graph.subjects(RDF.type, OWL.Class)
        if isinstance(subject, URIRef)
    }
    foreign = sorted(str(cls) for cls in declared if not str(cls).startswith(OBO + "FLOPO_"))
    if foreign:
        raise ValueError(f"module declares non-FLOPO classes: {foreign}")
    return graph


def serialize(graph: Graph) -> str:
    return str(graph.serialize(format="turtle")).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--id-registry", type=Path, default=REGISTRY)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--flopo-registry", type=Path, default=FLOPO_REGISTRY)
    parser.add_argument("--po", type=Path, default=PO)
    parser.add_argument("--pato", type=Path, default=PATO)
    parser.add_argument("-o", "--out", type=Path, default=OUTPUT)
    parser.add_argument("--date", default="2026-09-18")
    parser.add_argument(
        "--include-pending",
        action="store_true",
        help="also build rows without a curator decision (staged review module, not releasable)",
    )
    args = parser.parse_args()
    graph = build_module(
        args.spec,
        args.id_registry,
        args.evidence,
        args.flopo_registry,
        args.po,
        args.pato,
        args.date,
        include_pending=args.include_pending,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(serialize(graph), encoding="utf-8")
    new = {
        s
        for s in graph.subjects(RDFS.label, None)
        if isinstance(s, URIRef) and s != MODULE
    }
    print(f"new_classes {len(new)}")
    print(f"equivalences {len(set(graph.triples((None, OWL.equivalentClass, None))))}")
    print(f"output {args.out}")


if __name__ == "__main__":
    main()
