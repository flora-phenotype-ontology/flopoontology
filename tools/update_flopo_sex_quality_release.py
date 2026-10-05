#!/usr/bin/env python3
"""Remove the phenotypic-sex class axiom from flopo.owl and embed the sex-quality module.

See ``tools/build_flopo_sex_quality_extension.py`` for the rationale.  Idempotent and
marker-delimited like the other extension release tools: the general class axiom is removed if it
is still there, the obsolete declarations of the reinstated classes are replaced, and the module
fragment is (re-)inserted.
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
MODULE = URIRef(OBO + "flopo-sex-quality-extension.owl")
PHENOTYPIC_SEX = OBO + "PATO_0001894"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO SEX QUALITY EXTENSION -->"
END_MARKER = "  <!-- END GENERATED FLOPO SEX QUALITY EXTENSION -->"


def _without_generated_block(text: str) -> str:
    begin_count, end_count = text.count(BEGIN_MARKER), text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated sex-quality markers")
    if not begin_count:
        return text
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def remove_phenotypic_sex_constraint(text: str) -> tuple[str, bool]:
    """Remove the top-level ``has_part some (owl:Thing and has_quality some phenotypic sex)
    SubClassOf owl:Nothing`` restriction element."""

    token = re.compile(r"<owl:Restriction\b[^>]*>|</owl:Restriction>")
    candidates: set[tuple[int, int]] = set()
    for target in re.finditer(re.escape(f'rdf:resource="{PHENOTYPIC_SEX}"'), text):
        stack: list[int] = []
        for match in token.finditer(text, 0, target.start()):
            if match.group(0).startswith("<owl:Restriction"):
                stack.append(match.start())
            elif stack:
                stack.pop()
        if not stack:
            continue
        start = stack[0]  # outermost enclosing restriction
        depth = 0
        end = None
        for match in token.finditer(text, start):
            depth += 1 if match.group(0).startswith("<owl:Restriction") else -1
            if depth == 0:
                end = match.end()
                break
        if end is None:
            raise ValueError("unterminated phenotypic-sex restriction")
        block = text[start:end]
        if (
            OBO + "BFO_0000051" in block
            and "http://www.w3.org/2002/07/owl#Thing" in block
            and '<rdfs:subClassOf rdf:resource="http://www.w3.org/2002/07/owl#Nothing"/>' in block
        ):
            line_start = text.rfind("\n", 0, start) + 1
            line_end = end + (1 if end < len(text) and text[end] == "\n" else 0)
            candidates.add((line_start, line_end))
    if not candidates:
        return text, False
    if len(candidates) != 1:
        raise ValueError("expected exactly one phenotypic-sex general class axiom")
    start, end = candidates.pop()
    return text[:start] + text[end:], True


def module_fragment(module_path: Path) -> tuple[str, set[str]]:
    graph = Graph().parse(module_path.as_posix())
    if set(graph.subjects(RDF.type, OWL.Ontology)) != {MODULE}:
        raise ValueError("sex-quality module must have exactly its expected ontology header")
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
        raise ValueError("sex-quality ontology header leaked into release fragment")
    return fragment.strip(), classes


def update_release(release_path: Path, module_path: Path, release_date: str) -> dict[str, int]:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    text, removed_axiom = remove_phenotypic_sex_constraint(text)
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
        if (cls, RDF.type, OWL.Class) not in check or (cls, OWL.deprecated, None) in check:
            raise ValueError(f"sex-quality class not embedded as a live class: {class_iri}")
    return {"classes": len(classes), "replaced_declarations": replaced, "removed_gci": int(removed_axiom)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--module", type=Path, default=Path("ontology/flopo-sex-quality-extension.ttl"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    print(update_release(args.release, args.module, args.date))


if __name__ == "__main__":
    main()
