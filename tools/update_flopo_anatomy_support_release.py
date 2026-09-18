#!/usr/bin/env python3
"""Embed the curator-approved anatomy support module (2026-09-18) into flopo.owl.

Idempotent: the module is embedded as one replaceable generated block, and any earlier copy of
one of its classes is removed first. Run the identifier-registry resync and classification
afterwards (see ``curation/flopo_anatomy_support_classes_20260918.tsv``).
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from rdflib import OWL, RDF, Graph, URIRef

from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _extension_fragment, _update_release_metadata


OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-anatomy-support-extension.owl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO ANATOMY SUPPORT EXTENSION -->"
END_MARKER = "  <!-- END GENERATED FLOPO ANATOMY SUPPORT EXTENSION -->"


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated anatomy-support markers")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def module_fragment(module_path: Path) -> tuple[str, set[str]]:
    graph = Graph().parse(module_path.as_posix())
    if set(graph.subjects(RDF.type, OWL.Ontology)) != {MODULE}:
        raise ValueError("anatomy support module must have exactly its expected ontology header")
    classes = {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef)
    }
    foreign = sorted(cls for cls in classes if not cls.startswith(OBO + "FLOPO_"))
    if foreign:
        raise ValueError(f"anatomy support module declares non-FLOPO classes: {foreign}")
    fragment, _count = _extension_fragment(module_path)
    header_pattern = re.compile(
        rf"  <rdf:Description rdf:about={re.escape(chr(34) + str(MODULE) + chr(34))}>"
        rf".*?  </rdf:Description>\n?",
        re.DOTALL,
    )
    fragment = header_pattern.sub("", fragment)
    if str(MODULE) in fragment:
        raise ValueError("anatomy support ontology header leaked into release fragment")
    return fragment.strip(), classes


def update_release(
    release_path: Path, module_path: Path, release_date: str, *, verify: bool = True
) -> int:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    fragment, classes = module_fragment(module_path)
    for class_iri in sorted(classes):
        text, _removed = _remove_named_owl_class(text, class_iri)
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n"
    text = text.replace(closing, block + closing, 1)
    release_path.write_text(text, encoding="utf-8")

    if verify:
        check = Graph().parse(release_path.as_posix())
        if (MODULE, RDF.type, OWL.Ontology) in check:
            raise ValueError("anatomy support ontology header leaked into flopo.owl")
        for class_iri in classes:
            if (URIRef(class_iri), RDF.type, OWL.Class) not in check:
                raise ValueError(f"missing embedded class {class_iri}")
    return len(classes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--module", type=Path, default=Path("ontology/flopo-anatomy-support-extension.ttl")
    )
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    count = update_release(args.release, args.module, args.date)
    print(f"embedded_or_replaced {count} FLOPO anatomy support classes")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
