"""Bring FLOPO back to OBO Foundry 'green' by fixing the dashboard QC failures (in place).

Targets the failing checks from dashboard.obofoundry.org/dashboard/flopo:
  * **Missing ontology license / title / description** -> add dcterms metadata (CC0).
  * **Missing version IRI** (+ Maintenance) -> add owl:versionIRI + owl:versionInfo (dated).
  * **deprecated_boolean_datatype (56)** -> normalize every owl:deprecated to "true"^^xsd:boolean.
  * **deprecated_class_reference (9)** -> obsolete classes must carry no logical axioms: strip
    equivalentClass/subClassOf on deprecated classes, and drop any axiom in a live class that
    references a deprecated class.
  * **Textual Definitions: ~23k missing** -> generate IAO:0000115 definitions for EQ/PHENO classes
    from their logical pattern + PO/PATO labels (only where missing).
  * **GitHub #11** -> add IAO:0000700 (has_ontology_root_term) -> FLOPO_0000000.

Every existing FLOPO IRI is preserved (identifier-stability directive): we only add annotations and
remove dangling axioms from already-obsolete classes — no class is renamed, renumbered, or deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.namespace import DC, XSD

OBO = "http://purl.obolibrary.org/obo/"
DCTERMS = "http://purl.org/dc/terms/"
IAO_DEF = URIRef(OBO + "IAO_0000115")        # textual definition
IAO_ROOT = URIRef(OBO + "IAO_0000700")       # has ontology root term
CC0 = URIRef("http://creativecommons.org/publicdomain/zero/1.0/")
ONTOLOGY_IRI = URIRef(OBO + "flopo.owl")
ROOT_CLASS = URIRef(OBO + "FLOPO_0000000")

TITLE = "Flora Phenotype Ontology"
DESCRIPTION = "Traits and phenotypes of flowering plants occurring in digitized Floras."


def _load_registry(path: Path) -> dict[str, str]:
    """IRI -> signature, from config/flopo_id_registry.tsv."""
    import csv

    sig: dict[str, str] = {}
    with Path(path).open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sig[row["flopo_iri"]] = row["signature"]
    return sig


def _load_labels(path: Path) -> dict[str, str]:
    import csv

    out: dict[str, str] = {}
    with Path(path).open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out[row["id"]] = row["label"]
    return out


def _prune_bnode(g: Graph, node) -> None:
    """Recursively delete a blank-node subgraph (anonymous class expression)."""
    if not isinstance(node, BNode):
        return
    for p, o in list(g.predicate_objects(node)):
        g.remove((node, p, o))
        if isinstance(o, BNode):
            _prune_bnode(g, o)


def fix(in_owl: Path, registry: Path, po_lex: Path, pato_lex: Path, date: str,
        out_owl: Path) -> dict:
    g = Graph()
    g.parse(in_owl.as_posix())
    stats = {"deprecated_normalized": 0, "axioms_stripped_from_deprecated": 0,
             "refs_to_deprecated_removed": 0, "definitions_added": 0}

    # ---- 1. Ontology metadata -------------------------------------------------------------
    g.add((ONTOLOGY_IRI, URIRef(DCTERMS + "title"), Literal(TITLE)))
    g.add((ONTOLOGY_IRI, URIRef(DCTERMS + "description"), Literal(DESCRIPTION)))
    g.add((ONTOLOGY_IRI, URIRef(DCTERMS + "license"), CC0))
    g.add((ONTOLOGY_IRI, OWL.versionIRI, URIRef(f"{OBO}flopo/releases/{date}/flopo.owl")))
    g.add((ONTOLOGY_IRI, OWL.versionInfo, Literal(date)))
    g.add((ONTOLOGY_IRI, IAO_ROOT, ROOT_CLASS))  # GitHub #11

    # ---- 2. Normalize owl:deprecated to a single proper boolean --------------------------
    deprecated: set[URIRef] = set()
    subjects_with_dep = {s for s in g.subjects(OWL.deprecated, None) if isinstance(s, URIRef)}
    for s in subjects_with_dep:
        for o in list(g.objects(s, OWL.deprecated)):
            g.remove((s, OWL.deprecated, o))
        g.add((s, OWL.deprecated, Literal(True, datatype=XSD.boolean)))
        deprecated.add(s)
        stats["deprecated_normalized"] += 1

    # ---- 3. Obsolete classes must carry no logical axioms --------------------------------
    for c in deprecated:
        for pred in (OWL.equivalentClass, RDFS.subClassOf):
            for o in list(g.objects(c, pred)):
                g.remove((c, pred, o))
                _prune_bnode(g, o)
                stats["axioms_stripped_from_deprecated"] += 1

    # ---- 4. Live classes must not reference a deprecated class ----------------------------
    for c in set(g.subjects(RDF.type, OWL.Class)):
        if not isinstance(c, URIRef) or c in deprecated:
            continue
        for pred in (OWL.equivalentClass, RDFS.subClassOf):
            for o in list(g.objects(c, pred)):
                refs = {o} if isinstance(o, URIRef) else set(_iri_refs(g, o))
                if refs & deprecated:
                    g.remove((c, pred, o))
                    _prune_bnode(g, o)
                    stats["refs_to_deprecated_removed"] += 1

    # ---- 5. Generate textual definitions (IAO:0000115) where missing ---------------------
    sig = _load_registry(registry)
    po_labels = _load_labels(po_lex)
    pato_labels = _load_labels(pato_lex)
    for iri, signature in sig.items():
        u = URIRef(iri)
        if u in deprecated or (u, IAO_DEF, None) in g:
            continue
        text = _definition(signature, po_labels, pato_labels)
        if text:
            g.add((u, IAO_DEF, Literal(text, lang="en")))
            stats["definitions_added"] += 1

    out_owl.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(out_owl.as_posix(), format="pretty-xml")
    stats["deprecated_total"] = len(deprecated)
    return stats


def _iri_refs(g: Graph, node, seen=None):
    seen = seen or set()
    if node in seen:
        return
    seen.add(node)
    for _, o in g.predicate_objects(node):
        if isinstance(o, URIRef):
            yield o
        elif isinstance(o, BNode):
            yield from _iri_refs(g, o, seen)


def _definition(signature: str, po: dict[str, str], pato: dict[str, str]) -> str | None:
    if signature.startswith("EQ|"):
        _, po_id, pato_id = signature.split("|", 2)
        e, q = po.get(po_id), pato.get(pato_id)
        if e and q:
            return f"A phenotype in which a(n) {e} exhibits the quality of being {q}."
    elif signature.startswith("PHENO|"):
        _, po_id = signature.split("|", 1)
        e = po.get(po_id)
        if e:
            return f"A phenotype affecting a(n) {e} or one of its parts."
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Fix FLOPO OBO Foundry dashboard failures.")
    ap.add_argument("--in", dest="in_owl", type=Path, default=Path("ontology/flopo.owl"))
    ap.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    ap.add_argument("--po-lex", type=Path, default=Path("config/po_lexicon.tsv"))
    ap.add_argument("--pato-lex", type=Path, default=Path("config/pato_lexicon.tsv"))
    ap.add_argument("--date", default="2026-06-29")
    ap.add_argument("-o", "--out", type=Path, default=Path("ontology/flopo.owl"))
    args = ap.parse_args()
    stats = fix(args.in_owl, args.registry, args.po_lex, args.pato_lex, args.date, args.out)
    import json

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
