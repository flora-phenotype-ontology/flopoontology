"""Build the pre-classified, phenotype-only FLOPO light release.

``ontology/flopo.owl`` remains the full development artifact: it contains logical
definitions, imported support vocabularies, local PO/PATO support classes, and obsolete
identifier shells.  This module projects its active phenotype taxonomy from an ELK-
classified copy.  The resulting browser artifact contains only named FLOPO phenotype
classes and materialized FLOPO-to-FLOPO ``is_a`` edges, so ``flora phenotype`` is its
single named root.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD


OBO = Namespace("http://purl.obolibrary.org/obo/")
FLOPO_PREFIX = str(OBO) + "FLOPO_"
FULL_ONTOLOGY = URIRef(OBO + "flopo.owl")
LIGHT_ONTOLOGY = URIRef(OBO + "flopo-light.owl")
ROOT_CLASS = URIRef(OBO + "FLOPO_0000000")
ANATOMICAL_ENTITY_PHENOTYPE = URIRef(OBO + "FLOPO_0980418")
HAS_PART = URIRef(OBO + "BFO_0000051")
IAO_ROOT_TERM = URIRef(OBO + "IAO_0000700")

LOGICAL_CLASS_PREDICATES = {
    RDF.type,
    RDFS.subClassOf,
    OWL.complementOf,
    OWL.disjointUnionOf,
    OWL.disjointWith,
    OWL.equivalentClass,
    OWL.hasKey,
    OWL.intersectionOf,
    OWL.oneOf,
    OWL.unionOf,
}
RDFXML_PREFIXES = (
    (str(RDF), "rdf"),
    (str(RDFS), "rdfs"),
    (str(OWL), "owl"),
    (str(DCTERMS), "dcterms"),
    (str(OBO), "obo"),
    ("http://www.geneontology.org/formats/oboInOwl#", "oboInOwl"),
    ("https://w3id.org/flopo/annotation/", "flopoann"),
)


def _is_flopo_iri(node) -> bool:
    return isinstance(node, URIRef) and str(node).startswith(FLOPO_PREFIX)


def _is_deprecated(graph: Graph, cls: URIRef) -> bool:
    return any(str(value).strip().lower() in {"1", "true"} for value in graph.objects(cls, OWL.deprecated))


def _expression_uses_property(graph: Graph, cls: URIRef, prop: URIRef) -> bool:
    frontier = [
        expression
        for expression in graph.objects(cls, OWL.equivalentClass)
        if isinstance(expression, BNode)
    ]
    visited: set[BNode] = set()
    while frontier:
        node = frontier.pop()
        if node in visited:
            continue
        visited.add(node)
        if (node, OWL.onProperty, prop) in graph:
            return True
        frontier.extend(
            obj
            for obj in graph.objects(node)
            if isinstance(obj, BNode) and obj not in visited
        )
    return False


def _ontology_version(graph: Graph) -> str:
    ontology = next(graph.subjects(RDF.type, OWL.Ontology), None)
    if ontology is None:
        raise ValueError("ontology has no owl:Ontology header")
    versions = [str(value) for value in graph.objects(ontology, OWL.versionInfo)]
    if len(versions) != 1:
        raise ValueError("ontology must have exactly one owl:versionInfo value")
    return versions[0]


def _registry_maps(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    iri_to_signature: dict[str, str] = {}
    signature_to_iri: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            iri = row["flopo_iri"]
            signature = row["signature"]
            iri_to_signature[iri] = signature
            if signature != "OTHER" and row["deprecated"] != "1":
                signature_to_iri.setdefault(signature, iri)
    return iri_to_signature, signature_to_iri


def _descendants(root: URIRef, edges: dict[URIRef, set[URIRef]]) -> set[URIRef]:
    children: dict[URIRef, set[URIRef]] = defaultdict(set)
    for child, parents in edges.items():
        for parent in parents:
            children[parent].add(child)
    reached = {root}
    frontier = [root]
    while frontier:
        for child in children.get(frontier.pop(), set()):
            if child not in reached:
                reached.add(child)
                frontier.append(child)
    return reached


def _transitive_reduction(
    classes: set[URIRef], edges: dict[URIRef, set[URIRef]]
) -> dict[URIRef, set[URIRef]]:
    visiting: set[URIRef] = set()

    @lru_cache(maxsize=None)
    def ancestors(node: URIRef) -> frozenset[URIRef]:
        if node in visiting:
            raise ValueError(f"cycle in classified FLOPO hierarchy at {node}")
        visiting.add(node)
        found: set[URIRef] = set()
        for parent in edges.get(node, set()):
            found.add(parent)
            found.update(ancestors(parent))
        visiting.remove(node)
        return frozenset(found)

    reduced: dict[URIRef, set[URIRef]] = {}
    for child in classes:
        parents = edges.get(child, set())
        reduced[child] = {
            parent
            for parent in parents
            if not any(
                parent in ancestors(other_parent)
                for other_parent in parents
                if other_parent != parent
            )
        }
    return reduced


def _serialize_deterministic_rdfxml(graph: Graph, path: Path) -> None:
    """Serialize the named-node light graph with stable byte ordering."""

    def qname(predicate: URIRef) -> str:
        value = str(predicate)
        for namespace, prefix in RDFXML_PREFIXES:
            if value.startswith(namespace):
                return f"{prefix}:{value.removeprefix(namespace)}"
        raise ValueError(f"light ontology uses an undeclared predicate namespace: {value}")

    def object_key(obj) -> tuple[str, str, str, str]:
        if isinstance(obj, URIRef):
            return ("0", str(obj), "", "")
        if isinstance(obj, Literal):
            return ("1", str(obj), obj.language or "", str(obj.datatype or ""))
        raise ValueError(f"light ontology cannot serialize anonymous object {obj!r}")

    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<rdf:RDF"]
    for namespace, prefix in RDFXML_PREFIXES:
        lines.append(f"  xmlns:{prefix}={quoteattr(namespace)}")
    lines[-1] += ">"
    for subject in sorted(set(graph.subjects()), key=str):
        if not isinstance(subject, URIRef):
            raise ValueError(f"light ontology cannot serialize anonymous subject {subject!r}")
        lines.append(f"  <rdf:Description rdf:about={quoteattr(str(subject))}>")
        statements = sorted(
            graph.predicate_objects(subject),
            key=lambda pair: (str(pair[0]), *object_key(pair[1])),
        )
        for predicate, obj in statements:
            predicate_name = qname(predicate)
            if isinstance(obj, URIRef):
                lines.append(
                    f"    <{predicate_name} rdf:resource={quoteattr(str(obj))}/>"
                )
                continue
            attributes = ""
            if obj.language:
                attributes = f" xml:lang={quoteattr(obj.language)}"
            elif obj.datatype:
                attributes = f" rdf:datatype={quoteattr(str(obj.datatype))}"
            lines.append(
                f"    <{predicate_name}{attributes}>{escape(str(obj))}</{predicate_name}>"
            )
        lines.append("  </rdf:Description>")
    lines.append("</rdf:RDF>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_light_ontology(
    source_path: Path,
    classified_path: Path,
    registry_path: Path,
    output_path: Path,
    release_date: str | None = None,
) -> dict[str, int | str]:
    source = Graph().parse(source_path.as_posix())
    classified = Graph().parse(classified_path.as_posix())
    source_version = _ontology_version(source)
    classified_version = _ontology_version(classified)
    if source_version != classified_version:
        raise ValueError(
            "classified ontology is stale: "
            f"source version {source_version!r}, classified version {classified_version!r}"
        )

    version = release_date or source_version
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
        raise ValueError("light releases require an ISO release date (YYYY-MM-DD)")

    source_classes = {
        cls
        for cls in source.subjects(RDF.type, OWL.Class)
        if _is_flopo_iri(cls)
    }
    active = {cls for cls in source_classes if not _is_deprecated(source, cls)}
    if ROOT_CLASS not in active:
        raise ValueError("active FLOPO root is missing from the development ontology")

    named_edges: dict[URIRef, set[URIRef]] = defaultdict(set)
    for graph in (source, classified):
        for child, parent in graph.subject_objects(RDFS.subClassOf):
            if child in active and parent in active and child != parent:
                named_edges[child].add(parent)

    phenotype_classes = _descendants(ROOT_CLASS, named_edges)
    phenotype_classes.update(
        cls for cls in active if _expression_uses_property(source, cls, HAS_PART)
    )

    iri_to_signature, signature_to_iri = _registry_maps(registry_path)
    registry_parent_edges = 0
    for cls in list(phenotype_classes):
        parts = iri_to_signature.get(str(cls), "").split("|")
        if not parts or parts[0] not in {"EQ", "EQV"} or len(parts) < 2:
            continue
        parent_iri = signature_to_iri.get(f"PHENO|{parts[1]}")
        parent = URIRef(parent_iri) if parent_iri else None
        if parent in active:
            phenotype_classes.add(parent)
            if parent not in named_edges[cls]:
                named_edges[cls].add(parent)
                registry_parent_edges += 1

    named_edges = {
        child: {parent for parent in parents if parent in phenotype_classes}
        for child, parents in named_edges.items()
        if child in phenotype_classes
    }
    named_edges.setdefault(ROOT_CLASS, set()).clear()
    fallback_parent_edges = 0
    for cls in phenotype_classes - {ROOT_CLASS}:
        if not named_edges.get(cls):
            parent = (
                ANATOMICAL_ENTITY_PHENOTYPE
                if ANATOMICAL_ENTITY_PHENOTYPE in phenotype_classes
                and cls != ANATOMICAL_ENTITY_PHENOTYPE
                else ROOT_CLASS
            )
            named_edges.setdefault(cls, set()).add(parent)
            fallback_parent_edges += 1

    unreachable = phenotype_classes - _descendants(ROOT_CLASS, named_edges)
    if unreachable:
        raise ValueError(
            "phenotype classes do not reach flora phenotype: "
            + ", ".join(sorted(map(str, unreachable))[:20])
        )
    reduced_edges = _transitive_reduction(phenotype_classes, named_edges)

    light = Graph()
    light.bind("dcterms", DCTERMS)
    light.bind("obo", OBO)
    light.bind("owl", OWL)
    light.bind("rdf", RDF)
    light.bind("rdfs", RDFS)
    light.add((LIGHT_ONTOLOGY, RDF.type, OWL.Ontology))
    light.add(
        (
            LIGHT_ONTOLOGY,
            OWL.versionIRI,
            URIRef(OBO + f"flopo/releases/{version}/flopo-light.owl"),
        )
    )
    light.add((LIGHT_ONTOLOGY, OWL.versionInfo, Literal(version)))
    light.add((LIGHT_ONTOLOGY, DCTERMS.modified, Literal(version, datatype=XSD.date)))
    light.add(
        (
            LIGHT_ONTOLOGY,
            DCTERMS.title,
            Literal("Flora Phenotype Ontology (FLOPO) light taxonomy", lang="en"),
        )
    )
    light.add(
        (
            LIGHT_ONTOLOGY,
            DCTERMS.description,
            Literal(
                "A pre-classified, phenotype-only view of FLOPO for ontology browsers. "
                "Logical definitions, imported support vocabularies, local support "
                "classes, and obsolete terms remain in the full development ontology.",
                lang="en",
            ),
        )
    )
    light.add(
        (
            LIGHT_ONTOLOGY,
            DCTERMS.license,
            URIRef("https://creativecommons.org/publicdomain/zero/1.0/"),
        )
    )
    light.add((LIGHT_ONTOLOGY, DCTERMS.source, FULL_ONTOLOGY))
    light.add((LIGHT_ONTOLOGY, IAO_ROOT_TERM, ROOT_CLASS))

    used_annotation_properties: set[URIRef] = set()
    for cls in sorted(phenotype_classes, key=str):
        light.add((cls, RDF.type, OWL.Class))
        for predicate, obj in source.predicate_objects(cls):
            if predicate in LOGICAL_CLASS_PREDICATES or isinstance(obj, BNode):
                continue
            light.add((cls, predicate, obj))
            if isinstance(predicate, URIRef) and predicate not in {RDFS.label, RDFS.comment}:
                used_annotation_properties.add(predicate)
        for parent in sorted(reduced_edges.get(cls, set()), key=str):
            light.add((cls, RDFS.subClassOf, parent))

    declared_annotation_properties = set(source.subjects(RDF.type, OWL.AnnotationProperty))
    for prop in used_annotation_properties & declared_annotation_properties:
        light.add((prop, RDF.type, OWL.AnnotationProperty))
        for predicate, obj in source.predicate_objects(prop):
            if predicate != RDF.type and not isinstance(obj, BNode):
                light.add((prop, predicate, obj))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _serialize_deterministic_rdfxml(light, output_path)

    check = Graph().parse(output_path.as_posix())
    released_classes = set(check.subjects(RDF.type, OWL.Class))
    roots = {
        cls
        for cls in released_classes
        if not any(parent in released_classes for parent in check.objects(cls, RDFS.subClassOf))
    }
    if roots != {ROOT_CLASS}:
        raise ValueError(f"light ontology has unexpected named roots: {sorted(map(str, roots))}")
    if any(not _is_flopo_iri(cls) for cls in released_classes):
        raise ValueError("light ontology contains a non-FLOPO class declaration")
    if (LIGHT_ONTOLOGY, OWL.imports, None) in check:
        raise ValueError("light ontology must not import support ontologies")
    if (None, OWL.equivalentClass, None) in check:
        raise ValueError("light ontology must contain taxonomy only, not logical definitions")

    direct_root_children = set(check.subjects(RDFS.subClassOf, ROOT_CLASS))
    return {
        "classes": len(released_classes),
        "subclass_axioms": sum(1 for _ in check.triples((None, RDFS.subClassOf, None))),
        "direct_root_children": len(direct_root_children),
        "registry_parent_edges_added": registry_parent_edges,
        "fallback_parent_edges_added": fallback_parent_edges,
        "omitted_active_support_classes": len(active - phenotype_classes),
        "version": version,
        "out": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--classified", type=Path, default=Path("ontology/flopo-inferred.owl")
    )
    parser.add_argument(
        "--registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument("--out", type=Path, default=Path("ontology/flopo-light.owl"))
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    stats = build_light_ontology(
        args.source,
        args.classified,
        args.registry,
        args.out,
        args.date,
    )
    for key, value in stats.items():
        print(f"{key} {value}")


if __name__ == "__main__":
    main()
