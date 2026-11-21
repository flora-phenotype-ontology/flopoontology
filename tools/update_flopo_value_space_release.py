#!/usr/bin/env python3
"""Embed the FLOPO value-space module in flopo.owl (marker-delimited and idempotent).

See ``tools/build_flopo_value_space_extension.py``. The module holds the temporary attribute
classes and relations by which value classes are defined, and the neighbours of each value. The
numeric axioms stay in ``ontology/flopo-value-ranges.ofn``. After this run the final passes of
the README release procedure.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef

from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _graph_fragment, _update_release_metadata

OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-value-space-extension.owl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO VALUE SPACES -->"
END_MARKER = "  <!-- END GENERATED FLOPO VALUE SPACES -->"


def _without_generated_block(text: str) -> str:
    begin_count, end_count = text.count(BEGIN_MARKER), text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated value-space markers")
    if not begin_count:
        return text
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def module_fragment(module_path: Path) -> tuple[str, set[str], set[str]]:
    graph = Graph().parse(module_path.as_posix())
    if set(graph.subjects(RDF.type, OWL.Ontology)) != {MODULE}:
        raise ValueError("value-space module must have exactly its expected ontology header")
    classes = {str(c) for c in graph.subjects(RDF.type, OWL.Class) if str(c).startswith(OBO + "FLOPO_")}
    properties = {str(p) for kind in (OWL.DatatypeProperty, OWL.AnnotationProperty)
                  for p in graph.subjects(RDF.type, kind) if str(p).startswith(OBO + "FLOPO_")}
    body = Graph()
    for triple in graph:
        if triple[0] != MODULE:
            body.add(triple)
    fragment, _count = _graph_fragment(body, node_id_prefix="FLOPOValueSpace_")
    return fragment.strip(), classes, properties


def update_release(release_path: Path, module_path: Path, release_date: str) -> dict[str, int]:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    fragment, classes, properties = module_fragment(module_path)
    replaced = 0
    for class_iri in sorted(classes):
        text, removed = _remove_named_owl_class(text, class_iri)
        replaced += removed
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    text = text.replace(closing, f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n{closing}", 1)
    release_path.write_text(text, encoding="utf-8")

    check = Graph().parse(release_path.as_posix())
    for class_iri in classes:
        if not any(str(p).startswith(OBO + "PATO_") for p in check.objects(URIRef(class_iri), RDFS.subClassOf)):
            raise ValueError(f"value-space class not embedded beneath PATO: {class_iri}")
    for prop in properties:
        if not list(check.objects(URIRef(prop), URIRef(OBO + "IAO_0000115"))):
            raise ValueError(f"value-space relation embedded without its definition: {prop}")
    return {"classes": len(classes), "relations": len(properties), "replaced_declarations": replaced}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--module", type=Path, default=Path("ontology/flopo-value-space-extension.ttl"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    print(update_release(args.release, args.module, args.date))


if __name__ == "__main__":
    main()
