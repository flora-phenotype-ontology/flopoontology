#!/usr/bin/env python3
"""Embed the approved pubescence migration into the released FLOPO OWL file."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from rdflib import OWL, RDF, Graph, URIRef

from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _extension_fragment, _update_release_metadata


OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-pubescent-migration.owl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO PUBESCENT MIGRATION -->"
END_MARKER = "  <!-- END GENERATED FLOPO PUBESCENT MIGRATION -->"


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated pubescence-migration markers")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def _module_fragment(module_path: Path) -> tuple[str, set[str], set[str]]:
    graph = Graph().parse(module_path.as_posix())
    ontology_subjects = set(graph.subjects(RDF.type, OWL.Ontology))
    if ontology_subjects != {MODULE}:
        raise ValueError("migration module must have exactly its expected ontology header")
    classes = {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    obsolete = {
        str(cls)
        for cls in classes
        if (URIRef(cls), OWL.deprecated, None) in graph
    }
    replacements = classes - obsolete
    if len(obsolete) != 154 or len(replacements) != 154:
        raise ValueError("migration module must contain 154 obsolete/replacement pairs")

    fragment, _class_count = _extension_fragment(module_path)
    header_pattern = re.compile(
        rf"  <rdf:Description rdf:about={re.escape(chr(34) + str(MODULE) + chr(34))}>"
        rf".*?  </rdf:Description>\n?",
        re.DOTALL,
    )
    fragment = header_pattern.sub("", fragment)
    if str(MODULE) in fragment:
        raise ValueError("migration ontology header leaked into release fragment")
    return fragment.strip(), obsolete, replacements


def update_release(release_path: Path, module_path: Path, release_date: str) -> int:
    original = release_path.read_text(encoding="utf-8")
    had_generated_block = BEGIN_MARKER in original
    text = _without_generated_block(original)
    fragment, obsolete, replacements = _module_fragment(module_path)
    for class_iri in sorted(obsolete | replacements):
        text, removed = _remove_named_owl_class(text, class_iri)
        if class_iri in obsolete and not removed and not had_generated_block:
            raise ValueError(f"missing old class to obsolete: {class_iri}")
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n"
    text = text.replace(closing, block + closing, 1)
    release_path.write_text(text, encoding="utf-8")

    check = Graph().parse(release_path.as_posix())
    if (MODULE, RDF.type, OWL.Ontology) in check:
        raise ValueError("migration ontology header leaked into flopo.owl")
    for class_iri in obsolete:
        cls = URIRef(class_iri)
        if (cls, OWL.deprecated, None) not in check:
            raise ValueError(f"old class was not deprecated: {class_iri}")
        if (cls, OWL.equivalentClass, None) in check or (cls, None, None) not in check:
            raise ValueError(f"old class retained logic or disappeared: {class_iri}")
    for class_iri in replacements:
        cls = URIRef(class_iri)
        if (cls, OWL.equivalentClass, None) not in check:
            raise ValueError(f"replacement lacks EQ definition: {class_iri}")
    if (None, None, URIRef(OBO + "PATO_0000455")) in check:
        raise ValueError("released FLOPO still uses human-puberty PATO:0000455")
    return len(obsolete)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--module",
        type=Path,
        default=Path("ontology/flopo-pubescent-migration.ttl"),
    )
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    count = update_release(args.release, args.module, args.date)
    print(f"obsoleted_and_replaced {count} FLOPO botanical pubescence classes")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
