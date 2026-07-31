#!/usr/bin/env python3
"""Embed curator-approved reusable PO--PATO classes in the FLOPO release."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, Graph, URIRef

from flopo2.owl.reviewed_extension import MODULE
from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _graph_fragment, _update_release_metadata

OBO = "http://purl.obolibrary.org/obo/"
FLOPOANN = "https://w3id.org/flopo/annotation/"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO REVIEWED COMBINATIONS -->"
END_MARKER = "  <!-- END GENERATED FLOPO REVIEWED COMBINATIONS -->"


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated reviewed-combinations markers")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def _ensure_flopoann_namespace(text: str) -> str:
    if "xmlns:flopoann=" in text:
        return text
    if text.count("<rdf:RDF") != 1:
        raise ValueError("main FLOPO RDF/XML must contain one rdf:RDF root")
    return text.replace(
        "<rdf:RDF", f'<rdf:RDF\n  xmlns:flopoann="{FLOPOANN}"', 1
    )


def _module_fragment(module_path: Path) -> tuple[str, set[str]]:
    graph = Graph().parse(module_path.as_posix())
    ontology_subjects = set(graph.subjects(RDF.type, OWL.Ontology))
    if ontology_subjects != {MODULE}:
        raise ValueError("reviewed module must have exactly its expected ontology header")
    promoted = {
        str(cls)
        for cls in graph.subjects(DCTERMS.source, None)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    if not promoted:
        raise ValueError("reviewed module contains no FLOPO classes")
    for class_iri in promoted:
        cls = URIRef(class_iri)
        if (cls, RDF.type, OWL.Class) not in graph:
            raise ValueError(f"promoted resource is not an OWL class: {class_iri}")
        if (cls, DCTERMS.contributor, None) not in graph:
            raise ValueError(f"promoted class lacks curator provenance: {class_iri}")
        if (cls, DCTERMS.source, None) not in graph:
            raise ValueError(f"promoted class lacks approval source: {class_iri}")

    promoted_nodes = {URIRef(class_iri) for class_iri in promoted}
    declared_classes = set(graph.subjects(RDF.type, OWL.Class))
    declaration_only = declared_classes - promoted_nodes
    release_graph = Graph()
    for subject, predicate, obj in graph:
        if subject == MODULE:
            continue
        if subject in declaration_only and (
            (predicate == RDF.type and obj == OWL.Class) or predicate == RDFS.label
        ):
            continue
        release_graph.add((subject, predicate, obj))
    fragment, embedded_class_count = _graph_fragment(
        release_graph, node_id_prefix="FLOPOReviewed_"
    )
    if embedded_class_count != len(promoted):
        raise ValueError("release fragment contains declaration-only FLOPO classes")
    return fragment.strip(), promoted


def update_release(release_path: Path, module_path: Path, release_date: str) -> int:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    fragment, classes = _module_fragment(module_path)
    for class_iri in sorted(classes):
        text, _removed = _remove_named_owl_class(text, class_iri)
    text = _ensure_flopoann_namespace(text)
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n"
    text = text.replace(closing, block + closing, 1)
    release_path.write_text(text, encoding="utf-8")

    check = Graph().parse(release_path.as_posix())
    if (MODULE, RDF.type, OWL.Ontology) in check:
        raise ValueError("reviewed module ontology header leaked into flopo.owl")
    for class_iri in classes:
        cls = URIRef(class_iri)
        if (cls, RDF.type, OWL.Class) not in check:
            raise ValueError(f"missing embedded reviewed class {class_iri}")
        if (cls, DCTERMS.contributor, None) not in check:
            raise ValueError(f"embedded reviewed class lost provenance {class_iri}")
    return len(classes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--module",
        type=Path,
        default=Path("ontology/flopo-reviewed-combinations.ttl"),
    )
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args()
    count = update_release(args.release, args.module, args.date)
    print(f"embedded_or_replaced {count} curator-approved FLOPO classes")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
