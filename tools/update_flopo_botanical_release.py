#!/usr/bin/env python3
"""Embed the approved botanical module and replace revised classes in flopo.owl."""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

from rdflib import OWL, RDF, Graph, URIRef

from tools.update_flopo_release import _extension_fragment, _update_release_metadata

OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-botanical-extension.owl")
GO_MODULE = (
    "https://raw.githubusercontent.com/flora-phenotype-ontology/"
    "flopoontology/master/ontology/imports/go_import.owl"
)
LEGACY_GO_MODULE = OBO + "flopo/imports/go_import.owl"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO BOTANICAL EXTENSION -->"
END_MARKER = "  <!-- END GENERATED FLOPO BOTANICAL EXTENSION -->"
LEGACY_PROCESS_QUALITY = OBO + "PATO_0001236"


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated botanical-extension markers")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?",
        re.DOTALL,
    )
    return pattern.sub("\n", text, count=1)


def _remove_named_owl_class(text: str, class_iri: str) -> tuple[str, bool]:
    """Remove every RDF/XML description of one named OWL class.

    The historical release uses nested ``owl:Class`` elements, while generated
    extension blocks use flat ``rdf:Description`` elements with an explicit class
    type. A class can occur in both forms after successive release updaters. Removing
    only the first occurrence leaves duplicate definitions and stale parent axioms.
    """

    def remove_one(document: str, tag: str) -> tuple[str, bool]:
        opening = f'<{tag} rdf:about="{class_iri}">'
        start = document.find(opening)
        if start < 0:
            return document, False
        line_start = document.rfind("\n", 0, start) + 1
        token = re.compile(rf"<{re.escape(tag)}\b|</{re.escape(tag)}>")
        depth = 0
        for match in token.finditer(document, start):
            if match.group(0).startswith(f"<{tag}"):
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end = match.end()
                    if end < len(document) and document[end] == "\n":
                        end += 1
                    return document[:line_start] + document[end:], True
        raise ValueError(f"unterminated {tag} element for {class_iri}")

    removed_any = False
    for tag in ("owl:Class", "rdf:Description"):
        while True:
            text, removed = remove_one(text, tag)
            if not removed:
                break
            removed_any = True
    return text, removed_any


def _remove_legacy_process_quality_constraint(text: str) -> tuple[str, bool]:
    """Remove the old owl:Thing-based GCI that also made valid processes impossible."""

    target = f'rdf:resource="{LEGACY_PROCESS_QUALITY}"'
    target_positions = [match.start() for match in re.finditer(re.escape(target), text)]
    token = re.compile(r"<owl:Restriction\b[^>]*>|</owl:Restriction>")
    candidates: list[tuple[int, int]] = []
    for target_position in target_positions:
        stack: list[int] = []
        for match in token.finditer(text, 0, target_position):
            if match.group(0).startswith("<owl:Restriction"):
                stack.append(match.start())
            elif stack:
                stack.pop()
        for start in stack:
            depth = 0
            end = None
            for match in token.finditer(text, start):
                if match.group(0).startswith("<owl:Restriction"):
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        end = match.end()
                        break
            if end is None:
                raise ValueError("unterminated legacy process-quality restriction")
            block = text[start:end]
            if all(
                marker in block
                for marker in (
                    OBO + "BFO_0000051",
                    OBO + "PATO_0001236",
                    "http://www.w3.org/2002/07/owl#Thing",
                    "http://www.w3.org/2002/07/owl#Nothing",
                    "<rdfs:subClassOf>",
                )
            ):
                line_start = text.rfind("\n", 0, start) + 1
                line_end = end + (1 if end < len(text) and text[end] == "\n" else 0)
                candidates.append((line_start, line_end))
    candidates = sorted(set(candidates))
    if not candidates:
        return text, False
    if len(candidates) != 1:
        raise ValueError("expected exactly one legacy owl:Thing process-quality GCI")
    start, end = candidates[0]
    return text[:start] + text[end:], True


def _ensure_go_import(text: str) -> str:
    import_line = f'    <owl:imports rdf:resource="{GO_MODULE}"/>'
    text = text.replace(
        f'    <owl:imports rdf:resource="{LEGACY_GO_MODULE}"/>', import_line
    )
    if import_line in text:
        return text
    ontology_start = re.search(r"  <owl:Ontology\b[^>]*>\n", text)
    if ontology_start is None:
        raise ValueError("could not locate main owl:Ontology element")
    position = ontology_start.end()
    return text[:position] + import_line + "\n" + text[position:]


def _module_fragment(extension_path: Path) -> tuple[str, int, set[str]]:
    graph = Graph()
    graph.parse(extension_path.as_posix())
    ontology_subjects = set(graph.subjects(RDF.type, OWL.Ontology))
    if ontology_subjects != {MODULE}:
        raise ValueError("botanical module must have exactly its expected ontology header")
    modified = {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    fragment, class_count = _extension_fragment(
        extension_path, node_id_prefix="FLOPOBotanical_"
    )
    # _extension_fragment currently knows the value-module ontology IRI. Remove this
    # module's header explicitly if it occurs in its generic RDF description output.
    header_pattern = re.compile(
        rf"  <rdf:Description rdf:about={re.escape(chr(34) + str(MODULE) + chr(34))}>"
        rf".*?  </rdf:Description>\n?",
        re.DOTALL,
    )
    fragment = header_pattern.sub("", fragment)
    if str(MODULE) in fragment:
        raise ValueError("botanical module ontology header leaked into release fragment")
    return fragment.strip(), class_count, modified


def update_release(release_path: Path, extension_path: Path, release_date: str) -> int:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    text, _removed_legacy_constraint = _remove_legacy_process_quality_constraint(text)
    fragment, class_count, modified = _module_fragment(extension_path)
    for class_iri in sorted(modified):
        text, _removed = _remove_named_owl_class(text, class_iri)
    text = _ensure_go_import(text)
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n"
    text = text.replace(closing, block + closing, 1)
    release_path.write_text(text, encoding="utf-8")

    check = Graph()
    check.parse(release_path.as_posix())
    if (MODULE, RDF.type, OWL.Ontology) in check:
        raise ValueError("botanical extension ontology header leaked into flopo.owl")
    for class_iri in modified:
        if (URIRef(class_iri), RDF.type, OWL.Class) not in check:
            raise ValueError(f"missing embedded class {class_iri}")
    return class_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--extension",
        type=Path,
        default=Path("ontology/flopo-botanical-extension.ttl"),
    )
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args()
    count = update_release(args.release, args.extension, args.date)
    print(f"embedded_or_replaced {count} FLOPO botanical classes")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
