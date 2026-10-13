#!/usr/bin/env python3
"""Embed the FLOPO flora value-term module in flopo.owl (marker-delimited and idempotent).

See ``tools/build_flopo_flora_value_extension.py``.  Earlier declarations of the module's classes
are removed and the module fragment is (re-)inserted before the closing ``rdf:RDF`` tag; after
this run the final passes of the README release procedure.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef

from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _extension_fragment, _update_release_metadata

OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-flora-value-extension.owl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO FLORA VALUE TERMS -->"
END_MARKER = "  <!-- END GENERATED FLOPO FLORA VALUE TERMS -->"


def _without_generated_block(text: str) -> str:
    begin_count, end_count = text.count(BEGIN_MARKER), text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated flora value markers")
    if not begin_count:
        return text
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def module_fragment(module_path: Path) -> tuple[str, set[str]]:
    graph = Graph().parse(module_path.as_posix())
    if set(graph.subjects(RDF.type, OWL.Ontology)) != {MODULE}:
        raise ValueError("flora value module must have exactly its expected ontology header")
    classes = {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    fragment, _count = _extension_fragment(module_path)
    header = re.compile(
        rf"  <rdf:Description rdf:about={re.escape(chr(34) + str(MODULE) + chr(34))}>.*?  </rdf:Description>\n?",
        re.DOTALL,
    )
    fragment = header.sub("", fragment)
    if f'rdf:about="{MODULE}"' in fragment:
        raise ValueError("flora value ontology header leaked into release fragment")
    return fragment.strip(), classes


def update_release(release_path: Path, module_path: Path, release_date: str) -> dict[str, int]:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    fragment, classes = module_fragment(module_path)
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
        cls = URIRef(class_iri)
        parents = [p for p in check.objects(cls, RDFS.subClassOf) if str(p).startswith(OBO + "PATO_")]
        if (cls, RDF.type, OWL.Class) not in check or not parents:
            raise ValueError(f"flora value class not embedded beneath PATO: {class_iri}")
    return {"classes": len(classes), "replaced_declarations": replaced}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--module", type=Path, default=Path("ontology/flopo-flora-value-extension.ttl"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    print(update_release(args.release, args.module, args.date))


if __name__ == "__main__":
    main()
