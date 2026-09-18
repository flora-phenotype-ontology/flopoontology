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
  * **missing_obsolete_label** -> every deprecated FLOPO entity's rdfs:label starts with
    "obsolete " (idempotent; OBO practice keeps no synonym of the pre-obsolete label).
  * **missing_definition** -> definitions for non-registry EQ-pattern classes are generated from
    their equivalentClass axiom (towards / part_of / count variants); the remaining hand-made
    classes take curated genus-differentia definitions with dcterms:source from
    ``config/flopo_curated_definitions.tsv``.

Every existing FLOPO IRI is preserved (identifier-stability directive): we only add annotations and
remove dangling axioms from already-obsolete classes — no class is renamed, renumbered, or deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import csv
from dataclasses import dataclass

from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import XSD

from flopo2.owl.io import parse_ontology

OBO = "http://purl.obolibrary.org/obo/"
DCTERMS = "http://purl.org/dc/terms/"
IAO_DEF = URIRef(OBO + "IAO_0000115")        # textual definition
IAO_ROOT = URIRef(OBO + "IAO_0000700")       # has ontology root term
CC0 = URIRef("http://creativecommons.org/publicdomain/zero/1.0/")
ONTOLOGY_IRI = URIRef(OBO + "flopo.owl")
ROOT_CLASS = URIRef(OBO + "FLOPO_0000000")

DCTERMS_SOURCE = URIRef(DCTERMS + "source")
FLOPO_PREFIX = OBO + "FLOPO_"
HAS_PART = URIRef(OBO + "BFO_0000051")
PART_OF = URIRef(OBO + "BFO_0000050")
HAS_QUALITY = URIRef(OBO + "RO_0000053")
TOWARDS = URIRef("http://purl.obolibrary.org/obo/pato#towards")
HAS_VALUE = URIRef(OBO + "FLOPO_0907302")
OBSOLETE_PREFIX = "obsolete "
FACET_TEXT = {
    XSD.minExclusive: "greater than",
    XSD.minInclusive: "at least",
    XSD.maxExclusive: "less than",
    XSD.maxInclusive: "at most",
}

TITLE = "Flora Phenotype Ontology"
DESCRIPTION = "Traits and phenotypes of flowering plants occurring in digitized Floras."


CURATED_DEFINITIONS = Path("config/flopo_curated_definitions.tsv")


@dataclass(frozen=True)
class CuratedDefinition:
    label: str
    definition: str
    sources: tuple[URIRef | Literal, ...]


def is_obsolete_label(label: str) -> bool:
    return label.casefold().startswith(OBSOLETE_PREFIX)


def obsolete_label(label: str) -> str:
    """Return ``label`` with the OBO "obsolete " prefix, never doubling it."""
    return label if is_obsolete_label(label) else OBSOLETE_PREFIX + label


def strip_obsolete_prefix(label: str) -> str:
    return label[len(OBSOLETE_PREFIX):] if is_obsolete_label(label) else label


def deprecated_flopo_entities(g: Graph) -> set[URIRef]:
    return {
        s
        for s, o in g.subject_objects(OWL.deprecated)
        if isinstance(s, URIRef) and str(s).startswith(FLOPO_PREFIX)
        and str(o).strip().casefold() == "true"
    }


def prefix_obsolete_labels(g: Graph, deprecated: set[URIRef]) -> int:
    """Prefix every label of a deprecated FLOPO entity with "obsolete " (keeps lang/datatype)."""
    changed = 0
    for s in deprecated:
        if not str(s).startswith(FLOPO_PREFIX):
            continue
        for old in list(g.objects(s, RDFS.label)):
            new_text = obsolete_label(str(old))
            if new_text == str(old):
                continue
            g.remove((s, RDFS.label, old))
            g.add((s, RDFS.label, Literal(new_text, lang=old.language, datatype=old.datatype)))
            changed += 1
    return changed


def _source_term(value: str) -> URIRef | Literal:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        return URIRef(value)
    prefix, sep, local = value.partition(":")
    if sep and prefix.isalpha() and prefix.isupper() and local.isdigit():
        return URIRef(f"{OBO}{prefix}_{local}")
    return Literal(value)


def load_curated_definitions(path: Path) -> dict[str, CuratedDefinition]:
    """flopo_id -> curated genus-differentia definition with its dcterms:source values."""
    out: dict[str, CuratedDefinition] = {}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            flopo_id = row["flopo_id"].strip()
            if flopo_id in out:
                raise ValueError(f"duplicate curated definition for {flopo_id}")
            sources = tuple(_source_term(v) for v in row["sources"].split("|") if v.strip())
            if not row["definition"].strip() or not sources:
                raise ValueError(f"curated definition for {flopo_id} needs text and a source")
            out[flopo_id] = CuratedDefinition(row["label"], row["definition"].strip(), sources)
    return out


def _intersection(g: Graph, node) -> list:
    lst = g.value(node, OWL.intersectionOf)
    return list(Collection(g, lst)) if lst is not None else [node]


def _restriction(g: Graph, node, prop: URIRef):
    """Return the someValuesFrom filler of ``node`` if it is ``prop some X``."""
    if isinstance(node, BNode) and g.value(node, OWL.onProperty) == prop:
        return g.value(node, OWL.someValuesFrom)
    return None


def _value_phrase(g: Graph, node) -> str | None:
    """Phrase for a ``hasValue`` restriction: a literal value or an integer range."""
    if not isinstance(node, BNode) or g.value(node, OWL.onProperty) != HAS_VALUE:
        return None
    literal = g.value(node, OWL.hasValue)
    if literal is not None:
        return f"with value {literal}"
    datatype = g.value(node, OWL.someValuesFrom)
    facets = g.value(datatype, OWL.withRestrictions) if datatype is not None else None
    if facets is None:
        return None
    parts = []
    for facet_node in Collection(g, facets):
        for facet, value in g.predicate_objects(facet_node):
            if facet in FACET_TEXT:
                parts.append(f"{FACET_TEXT[facet]} {value}")
    return f"with value {' and '.join(parts)}" if parts else None


def axiom_definition(g: Graph, cls: URIRef, labels: dict[str, str]) -> str | None:
    """Genus-differentia text for ``has_part some (E and has_quality some Q...)`` classes.

    Covers the variants the registry signature reports as ``OTHER``: a ``part_of`` bearer,
    a relational quality (``Q and towards some E2``) and a counted quality
    (``Q and hasValue <n | range>``). Returns ``None`` when any term lacks a label.
    """

    def label(term) -> str | None:
        if not isinstance(term, URIRef):
            return None
        return labels.get(str(term).replace(OBO, "")) or (
            str(v) if (v := g.value(term, RDFS.label)) is not None else None
        )

    for eq in g.objects(cls, OWL.equivalentClass):
        filler = _restriction(g, eq, HAS_PART)
        if filler is None:
            continue
        bearer, bearer_is_part, quality_expr = None, False, None
        for conjunct in _intersection(g, filler):
            if isinstance(conjunct, URIRef):
                bearer = conjunct
            elif (whole := _restriction(g, conjunct, PART_OF)) is not None:
                bearer, bearer_is_part = whole, True
            elif (q := _restriction(g, conjunct, HAS_QUALITY)) is not None:
                quality_expr = q
        if bearer is None or quality_expr is None:
            continue
        quality, extras = None, []
        for conjunct in _intersection(g, quality_expr):
            if isinstance(conjunct, URIRef):
                quality = conjunct
            elif (other := _restriction(g, conjunct, TOWARDS)) is not None:
                other_label = label(other)
                if other_label is None:
                    return None
                extras.append(("towards", f"a(n) {other_label}"))
            elif (value := _value_phrase(g, conjunct)) is not None:
                extras.append(("value", value))
            else:
                return None
        e_label, q_label = label(bearer), label(quality)
        if not e_label or not q_label:
            return None
        subject = f"a part of a(n) {e_label}" if bearer_is_part else f"a(n) {e_label}"
        kinds = {kind for kind, _ in extras}
        if "value" in kinds:
            value_text = " ".join(text for kind, text in extras if kind == "value")
            return f"A phenotype in which {subject} exhibits a(n) {q_label} quality {value_text}."
        towards = " ".join(text for kind, text in extras if kind == "towards")
        quality_text = f"{q_label} {towards}" if towards else q_label
        return f"A phenotype in which {subject} exhibits the quality of being {quality_text}."
    return None


def missing_definitions(
    g: Graph,
    signatures: dict[str, str],
    po_labels: dict[str, str],
    pato_labels: dict[str, str],
    curated: dict[str, CuratedDefinition],
) -> dict[URIRef, tuple[str, tuple[URIRef | Literal, ...]]]:
    """Definitions for live FLOPO entities that lack IAO:0000115.

    Order: registry EQ/PHENO signature, then the entity's own equivalentClass axiom, then the
    curated table. Curated rows are checked against the entity's current label so a drifted
    label cannot silently receive another term's definition.
    """
    deprecated = deprecated_flopo_entities(g)
    labels = {**po_labels, **pato_labels}
    entity_types = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty)
    entities = {
        s
        for t in entity_types
        for s in g.subjects(RDF.type, t)
        if isinstance(s, URIRef) and str(s).startswith(FLOPO_PREFIX)
    }
    out: dict[URIRef, tuple[str, tuple[URIRef | Literal, ...]]] = {}
    for u in sorted(entities - deprecated):
        if (u, IAO_DEF, None) in g:
            continue
        text = _definition(signatures.get(str(u), ""), po_labels, pato_labels)
        text = text or axiom_definition(g, u, labels)
        if text:
            out[u] = (text, ())
            continue
        row = curated.get(str(u).replace(OBO, ""))
        if row is None:
            continue
        current = {str(v) for v in g.objects(u, RDFS.label)}
        if row.label not in current:
            raise ValueError(f"curated definition label {row.label!r} does not match {u}")
        out[u] = (row.definition, row.sources)
    return out


def _load_registry(path: Path) -> dict[str, str]:
    """IRI -> signature, from config/flopo_id_registry.tsv."""
    sig: dict[str, str] = {}
    with Path(path).open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sig[row["flopo_iri"]] = row["signature"]
    return sig


def _load_labels(path: Path) -> dict[str, str]:
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
        out_owl: Path, curated: Path | None = CURATED_DEFINITIONS) -> dict:
    g = parse_ontology(in_owl)
    stats = {"deprecated_normalized": 0, "axioms_stripped_from_deprecated": 0,
             "refs_to_deprecated_removed": 0, "definitions_added": 0,
             "obsolete_labels_prefixed": 0}

    # ---- 1. Ontology metadata -------------------------------------------------------------
    # ``set`` (not ``add``) keeps a re-run from accumulating a second versionIRI/versionInfo.
    g.set((ONTOLOGY_IRI, URIRef(DCTERMS + "title"), Literal(TITLE)))
    g.set((ONTOLOGY_IRI, URIRef(DCTERMS + "description"), Literal(DESCRIPTION)))
    g.set((ONTOLOGY_IRI, URIRef(DCTERMS + "license"), CC0))
    g.set((ONTOLOGY_IRI, OWL.versionIRI, URIRef(f"{OBO}flopo/releases/{date}/flopo.owl")))
    g.set((ONTOLOGY_IRI, OWL.versionInfo, Literal(date)))
    g.set((ONTOLOGY_IRI, IAO_ROOT, ROOT_CLASS))  # GitHub #11

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

    # ---- 5. Obsolete labels ---------------------------------------------------------------
    stats["obsolete_labels_prefixed"] = prefix_obsolete_labels(g, deprecated)

    # ---- 6. Textual definitions (IAO:0000115) where missing -------------------------------
    po_labels = _load_labels(po_lex)
    pato_labels = _load_labels(pato_lex)
    curated_rows = load_curated_definitions(curated) if curated else {}
    for u, (text, sources) in missing_definitions(
        g, _load_registry(registry), po_labels, pato_labels, curated_rows
    ).items():
        g.add((u, IAO_DEF, Literal(text, lang="en")))
        for source in sources:
            g.add((u, DCTERMS_SOURCE, source))
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
    ap.add_argument("--curated", type=Path, default=CURATED_DEFINITIONS)
    ap.add_argument("--date", default="2026-06-29")
    ap.add_argument("-o", "--out", type=Path, default=Path("ontology/flopo.owl"))
    args = ap.parse_args()
    stats = fix(args.in_owl, args.registry, args.po_lex, args.pato_lex, args.date, args.out,
                args.curated)
    import json

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
