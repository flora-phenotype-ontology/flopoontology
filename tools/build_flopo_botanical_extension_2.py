#!/usr/bin/env python3
"""Build the second approved FLOPO botanical module from curated concept proposals.

Input is ``curation/botanical_concept_proposals.tsv`` after the 2026-09-18 curator decision.
Accepted PATO-candidate and PO-candidate rows become provisional FLOPO-local classes directly
beneath their closest live PATO or PO parent, never PO or PATO identifiers. Accepted FLOPO-local
growth-form rows become FLOPO phenotypes, and six released FLOPO classes are revised in place.
Colour rows are deliberately excluded: the ISCC-NBS colour backbone implements them.

Identifiers come from ``config/flopo_botanical_concept_id_registry.tsv``. That registry owns the
block FLOPO_0985000-FLOPO_0985999, well above the sequential allocations (FLOPO_0981091 and
below at the time of writing), so concurrent allocators cannot collide with it.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection


OBO = Namespace("http://purl.obolibrary.org/obo/")
OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
MODULE = URIRef(OBO + "flopo-botanical-extension-2.owl")
PATO_ONTOLOGY = URIRef(OBO + "pato.owl")
PO_ONTOLOGY = URIRef(OBO + "po.owl")
HAS_PART = URIRef(OBO + "BFO_0000051")
PART_OF = URIRef(OBO + "BFO_0000050")
HAS_CHARACTERISTIC = URIRef(OBO + "RO_0000053")
TOWARDS = URIRef(OBO + "RO_0002503")
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
ID_BLOCK = (985000, 985999)
ACCEPTED = {"accept", "accept_with_revision"}

# Accepted new-class rows that are already materialized elsewhere and must not be re-minted.
ALREADY_IMPLEMENTED = {
    "PO-CAND:orchid_labellum": "FLOPO_0980978 (machine-reviewed support class, ratified)",
}

# Released FLOPO classes revised in place: proposal key -> FLOPO identifier.
IN_PLACE = {
    "FLOPO-CAND:liana": "FLOPO_0900035",
    "FLOPO-CAND:herb": "FLOPO_0022142",
    "FLOPO-CAND:shrubby_growth": "FLOPO_0900034",
    "FLOPO-CAND:arborescent_growth": "FLOPO_0900033",
    "FLOPO-PATTERN:aquatic_position": "FLOPO_0900044",
    "MAP-CAND:woody": "FLOPO_0900039",
}

# Definitions for in-place revisions whose proposal row carries none (mapping rows).
IN_PLACE_DEFINITIONS = {
    "MAP-CAND:woody": (
        "A shoot axis phenotype in which the shoot axis is ligneous (PATO:0002348), "
        "that is, woody in structure."
    ),
}

# Synonyms stated in the approved rows (scope, text); plurals only where a row asks for them.
SYNONYMS: dict[str, list[tuple[str, str]]] = {
    "PATO-CAND:campanulate": [("related", "bell-shaped")],
    "PATO-CAND:winged": [("exact", "alate")],
    "PATO-CAND:lanate": [("related", "woolly")],
    "PATO-CAND:sericeous": [("related", "silky")],
    "PATO-CAND:plicate": [("related", "pleated")],
    "PATO-CAND:clasping": [("narrow", "amplexicaul")],
    "PATO-CAND:annual_life_span": [("exact", "annual")],
    "PATO-CAND:perennial_life_span": [("exact", "perennial")],
    "PATO-CAND:floccose_cottony": [("narrow", "flocculose"), ("related", "cottony")],
    "PATO-CAND:entire_margin": [("related", "entire margin")],
    "PO-CAND:corolla_lip": [("related", "lip")],
    "PO-CAND:plant_structure_apex": [("exact", "apices")],
    "PO-CAND:pinna": [("exact", "pinnae")],
    "PO-CAND:pinnule": [("exact", "pinnules")],
    "PO-CAND:cyathium": [("exact", "cyathia")],
    "SURFACE-CAND:corona": [("related", "corona")],
    "FLOPO-CAND:climber": [("exact", "climber"), ("exact", "scandent")],
    "FLOPO-CAND:vine": [("related", "vine")],
    "FLOPO-CAND:caespitose_growth": [("exact", "caespitose")],
    "FLOPO-CAND:leafless": [("related", "leafless")],
    "FLOPO-PATTERN:creeping_trailing_sprawling": [
        ("related", "creeping"),
        ("related", "trailing"),
        ("related", "sprawling"),
    ],
    "FLOPO-CAND:herb": [("related", "herb"), ("related", "herbs")],
    "FLOPO-CAND:shrubby_growth": [("related", "shrubby")],
}
SYNONYM_PROPERTY = {
    "exact": OIO.hasExactSynonym,
    "related": OIO.hasRelatedSynonym,
    "narrow": OIO.hasNarrowSynonym,
    "broad": OIO.hasBroadSynonym,
}

UPSTREAM_DRAFT = {
    "PATO": "curation/upstream_drafts/pato-pr-1-botanical-qualities.md",
    "PO": "curation/upstream_drafts/po-pr-5-anatomy-classes.md",
}


def iri(curie: str) -> URIRef:
    return URIRef(OBO + curie.replace(":", "_", 1))


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _live_obo_ids(*paths: Path) -> set[str]:
    live: set[str] = set()
    for path in paths:
        current = None
        obsolete = False
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if line == "[Term]":
                    if current and not obsolete:
                        live.add(current)
                    current, obsolete = None, False
                elif line.startswith("[") and line.endswith("]"):
                    if current and not obsolete:
                        live.add(current)
                    current, obsolete = None, True
                elif line.startswith("id: ") and current is None:
                    current = line[4:].strip()
                elif line.startswith("is_obsolete: true"):
                    obsolete = True
        if current and not obsolete:
            live.add(current)
    return live


def _restriction(
    graph: Graph, prop: URIRef, filler: URIRef | BNode, name: str
) -> BNode:
    node = BNode(name)
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, prop))
    graph.add((node, OWL.someValuesFrom, filler))
    return node


def _intersection(graph: Graph, members: list[URIRef | BNode], name: str) -> BNode:
    node = BNode(name)
    head = BNode(f"{name}_list")
    Collection(graph, head, members)
    graph.add((node, RDF.type, OWL.Class))
    graph.add((node, OWL.intersectionOf, head))
    return node


def _entity_with_quality(
    graph: Graph, entity: URIRef, quality: URIRef | BNode, name: str
) -> BNode:
    characteristic = _restriction(graph, HAS_CHARACTERISTIC, quality, f"{name}_characteristic")
    filler = _intersection(graph, [entity, characteristic], f"{name}_filler")
    return _restriction(graph, HAS_PART, filler, f"{name}_outer")


def _class_snippet(text: str, class_iri: str) -> str:
    opening = f'<owl:Class rdf:about="{class_iri}">'
    start = text.find(opening)
    if start < 0:
        raise ValueError(f"release does not declare {class_iri} as an owl:Class element")
    if text.find(opening, start + 1) >= 0:
        raise ValueError(f"release declares {class_iri} more than once")
    token = re.compile(r"<owl:Class\b[^>]*?(/?)>|</owl:Class>")
    depth = 0
    for match in token.finditer(text, start):
        if match.group(0).startswith("</"):
            depth -= 1
        elif match.group(1) != "/":
            depth += 1
        if depth == 0:
            return text[start : match.end()]
    raise ValueError(f"unterminated owl:Class element for {class_iri}")


def _released_classes(release_path: Path, class_iris: list[str]) -> Graph:
    """Parse only the named class elements; the release is too large to parse per build."""

    text = release_path.read_text(encoding="utf-8")
    header_end = text.find(">", text.find("<rdf:RDF")) + 1
    header = text[:header_end]
    body = "\n".join(_class_snippet(text, class_iri) for class_iri in class_iris)
    graph = Graph()
    graph.parse(data=f"{header}\n{body}\n</rdf:RDF>\n", format="xml")
    return graph


def _source_urls(row: dict[str, str], evidence: dict[str, dict[str, str]]) -> set[URIRef]:
    urls: set[URIRef] = set()
    for token in row["definition_sources"].split("|"):
        token = token.strip()
        if token in evidence and evidence[token]["url"]:
            urls.add(URIRef(evidence[token]["url"]))
    return urls


def build_module(
    proposals_path: Path,
    id_registry_path: Path,
    evidence_path: Path,
    release_path: Path,
    po_path: Path,
    pato_path: Path,
    release_date: str,
) -> tuple[Graph, set[URIRef]]:
    proposals = {row["proposal_id"]: row for row in _rows(proposals_path)}
    registry = {row["proposal_key"]: row for row in _rows(id_registry_path)}
    evidence = {row["evidence_id"]: row for row in _rows(evidence_path)}
    live = _live_obo_ids(po_path, pato_path)

    ids = [row["flopo_id"] for row in registry.values()]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate FLOPO identifier in concept registry")
    for key, entry in registry.items():
        number = int(entry["flopo_id"].removeprefix("FLOPO_"))
        if not ID_BLOCK[0] <= number <= ID_BLOCK[1]:
            raise ValueError(f"{entry['flopo_id']} is outside the reserved block")
        row = proposals.get(key)
        if row is None or row["curator_decision"] not in ACCEPTED:
            raise ValueError(f"registry key {key} is not a curator-accepted proposal")
        if row["preferred_label"] != entry["label"]:
            raise ValueError(f"label mismatch for {key}")
        if entry["provisional_for"] != row["intended_ontology"]:
            raise ValueError(f"target ontology mismatch for {key}")
    for key in IN_PLACE:
        if proposals[key]["curator_decision"] not in ACCEPTED:
            raise ValueError(f"in-place revision {key} is not curator-accepted")

    # Every accepted new PO/PATO class proposal must be materialized exactly once.
    expected = {
        key
        for key, row in proposals.items()
        if row["curator_decision"] in ACCEPTED
        and row["intended_ontology"] in {"PO", "PATO"}
        and row["recommendation"] in {"accept_proposal", "revise_proposal"}
        and (key.startswith("PO-CAND:") or key.startswith("PATO-CAND:"))
    }
    missing = expected - set(registry) - set(ALREADY_IMPLEMENTED)
    if missing:
        raise ValueError(f"accepted PO/PATO class proposals lack identifiers: {sorted(missing)}")

    local = {key: URIRef(OBO + entry["flopo_id"]) for key, entry in registry.items()}

    def resolve(token: str) -> URIRef:
        token = token.strip()
        if token in local:
            return local[token]
        if token.startswith(("PO:", "PATO:")):
            if token not in live:
                raise ValueError(f"{token} is not a live term in the pinned PO/PATO")
            return iri(token)
        if token.startswith("FLOPO:"):
            return iri(token)
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
        (MODULE, RDFS.label, Literal("FLOPO botanical extension module 2", lang="en"))
    )
    graph.add((MODULE, DCTERMS.modified, Literal(release_date, datatype=XSD.date)))
    graph.add(
        (
            MODULE,
            DCTERMS.license,
            URIRef("https://creativecommons.org/publicdomain/zero/1.0/"),
        )
    )
    graph.add((TOWARDS, RDF.type, OWL.ObjectProperty))
    graph.add((TOWARDS, RDFS.label, Literal("towards", lang="en")))

    # Copy released classes that are revised in place, with every triple they carry.
    revised_iris = [str(OBO + curie) for curie in IN_PLACE.values()]
    released = _released_classes(release_path, revised_iris)
    for triple in released:
        graph.add(triple)
    modified_existing = {URIRef(value) for value in revised_iris}

    def annotate(key: str, cls: URIRef, *, new: bool, note: str) -> None:
        row = proposals[key]
        graph.add((cls, RDF.type, OWL.Class))
        if new:
            graph.set((cls, RDFS.label, Literal(row["preferred_label"], lang="en")))
        definition = row["definition"].strip() or IN_PLACE_DEFINITIONS.get(key, "")
        if not definition:
            raise ValueError(f"no textual definition for {key}")
        graph.set((cls, IAO_DEFINITION, Literal(definition, lang="en")))
        graph.add((cls, DCTERMS.contributor, CONTRIBUTOR))
        graph.set(
            (
                cls,
                DCTERMS.created if new else DCTERMS.modified,
                Literal(release_date, datatype=XSD.date),
            )
        )
        graph.add(
            (
                cls,
                IAO_EDITOR_NOTE,
                Literal(
                    f"Approved FLOPO botanical concept proposal {key} "
                    f"(curation/botanical_concept_proposals.tsv, curator decision "
                    f"{row['curator_decision']} on 2026-09-18). {note}",
                    lang="en",
                ),
            )
        )
        for url in _source_urls(row, evidence):
            graph.add((cls, DCTERMS.source, url))
        for scope, text in SYNONYMS.get(key, []):
            graph.add((cls, SYNONYM_PROPERTY[scope], Literal(text, lang="en")))

    # Provisional PATO qualities and PO entities, parented directly under live PATO/PO terms.
    for key, entry in registry.items():
        row = proposals[key]
        cls = local[key]
        target = entry["provisional_for"]
        if target in {"PATO", "PO"}:
            annotate(
                key,
                cls,
                new=True,
                note=(
                    f"Provisional FLOPO-local representation of a class proposed to {target} "
                    f"({UPSTREAM_DRAFT[target]}); replace it with the {target} identifier via "
                    "IAO:0100001 once assigned. No PO or PATO identifier is minted locally."
                ),
            )
            parents = [token for token in row["direct_parent_ids"].split("|") if token]
            if not parents:
                raise ValueError(f"{key} has no parent")
            for parent in parents:
                parent_iri = resolve(parent)
                if target == "PATO" and not str(parent_iri).startswith(OBO + "PATO_"):
                    raise ValueError(f"PATO candidate {key} must sit under a PATO parent")
                graph.add((cls, RDFS.subClassOf, parent_iri))
            for index, whole in enumerate(
                token for token in row["part_of_ids"].split("|") if token
            ):
                graph.add(
                    (
                        cls,
                        RDFS.subClassOf,
                        _restriction(
                            graph,
                            PART_OF,
                            resolve(whole),
                            f"{entry['flopo_id']}_part_of_{index}",
                        ),
                    )
                )

    # Cyathium: universal staminate flowers and involucre, no pistillate/whole-plant axiom.
    cyathium = local["PO-CAND:cyathium"]
    for curie in ("PO:0025600", "PO:0009100"):
        graph.add(
            (
                cyathium,
                RDFS.subClassOf,
                _restriction(graph, HAS_PART, resolve(curie), f"cyathium_has_{curie[3:]}"),
            )
        )

    # Growth-form phenotypes.
    phenotype_note = "FLOPO-local whole-plant phenotype."
    for key, entry in registry.items():
        if entry["provisional_for"] != "FLOPO":
            continue
        row = proposals[key]
        cls = local[key]
        annotate(key, cls, new=True, note=phenotype_note)
        parents = [token for token in row["direct_parent_ids"].split("|") if token]
        if len(parents) != 1 or not parents[0].startswith(("FLOPO:", "FLOPO-CAND:")):
            raise ValueError(f"{key} must have exactly one FLOPO phenotype parent")
        graph.add((cls, RDFS.subClassOf, resolve(parents[0])))

    # Leafless: whole plant lacking all leaves (PATO absence pattern), necessary condition only.
    absence = _intersection(
        graph,
        [
            iri("PATO:0002000"),
            _restriction(graph, TOWARDS, resolve("PO:0025034"), "leafless_towards_leaf"),
        ],
        "leafless_absence",
    )
    graph.add(
        (
            local["FLOPO-CAND:leafless"],
            RDFS.subClassOf,
            _entity_with_quality(graph, resolve("PO:0000003"), absence, "leafless"),
        )
    )
    # Twining: a coiled stem is necessary but not sufficient (support relation stays textual).
    graph.add(
        (
            local["FLOPO-CAND:twining"],
            RDFS.subClassOf,
            _entity_with_quality(
                graph, resolve("PO:0009047"), resolve("PATO:0000404"), "twining_coiled_stem"
            ),
        )
    )

    # In-place revisions of released classes.
    climber = local["FLOPO-CAND:climber"]
    in_place_note = (
        "Revised in place: the referent is unchanged, so the identifier is kept "
        "(definition, synonym-scope or parent repair)."
    )
    for key, curie in IN_PLACE.items():
        annotate(key, URIRef(OBO + curie), new=False, note=in_place_note)

    liana = URIRef(OBO + IN_PLACE["FLOPO-CAND:liana"])
    graph.remove((liana, RDFS.subClassOf, iri("FLOPO:0900032")))
    graph.add((liana, RDFS.subClassOf, climber))
    graph.remove((liana, OIO.hasExactSynonym, Literal("climber", lang="en")))
    graph.add(
        (
            liana,
            RDFS.subClassOf,
            _entity_with_quality(
                graph, resolve("PO:0025029"), resolve("PATO:0002348"), "liana_ligneous_axis"
            ),
        )
    )

    graph.add((URIRef(OBO + "FLOPO_0900039"), IAO_EDITOR_NOTE, Literal(
        "Mapping target for woody shoot axes (MAP-CAND:woody); the underlying quality is "
        "PATO:0002348 ligneous.",
        lang="en",
    )))

    subjects = {
        subject
        for subject in graph.subjects(RDF.type, OWL.Class)
        if isinstance(subject, URIRef)
    }
    minted = [s for s in subjects if not str(s).startswith(OBO + "FLOPO_")]
    if minted:
        raise ValueError(f"module declares non-FLOPO classes: {sorted(map(str, minted))}")
    return graph, modified_existing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proposals",
        type=Path,
        default=Path("curation/botanical_concept_proposals.tsv"),
    )
    parser.add_argument(
        "--id-registry",
        type=Path,
        default=Path("config/flopo_botanical_concept_id_registry.tsv"),
    )
    parser.add_argument(
        "--evidence", type=Path, default=Path("curation/botanical_evidence.tsv")
    )
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--po", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--pato", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("ontology/flopo-botanical-extension-2.ttl"),
    )
    parser.add_argument("--date", default="2026-09-18")
    args = parser.parse_args()
    graph, modified = build_module(
        args.proposals,
        args.id_registry,
        args.evidence,
        args.release,
        args.po,
        args.pato,
        args.date,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(str(graph.serialize(format="turtle")).rstrip() + "\n", encoding="utf-8")
    named = {s for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    print(f"classes {len(named)}")
    print(f"modified_existing {len(modified)}")
    print(f"output {args.out}")


if __name__ == "__main__":
    main()
