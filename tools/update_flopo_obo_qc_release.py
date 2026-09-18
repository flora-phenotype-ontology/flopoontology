#!/usr/bin/env python3
"""Apply the OBO QC label/definition fixes to the release RDF/XML without reserializing it.

``flopo2.owl.obo_fix`` holds the rules (obsolete-label prefix, axiom-derived and curated
definitions).  Running its rdflib round-trip on the current release would drop the
``BEGIN/END GENERATED`` blocks that the other ``tools/update_flopo_*_release.py`` commands
replace in place, so this command applies the same rules as a text patch:

* labels of deprecated FLOPO entities in the hand-maintained body get the "obsolete " prefix
  in place (generated blocks must already comply; their builders own those labels);
* missing IAO:0000115 definitions (with dcterms:source for curated rows) are written to one
  marked block that a re-run replaces, so the command is idempotent.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from rdflib import RDFS, Graph, URIRef

from flopo2.owl.obo_fix import (
    CURATED_DEFINITIONS,
    IAO_DEF,
    _load_labels,
    _load_registry,
    deprecated_flopo_entities,
    is_obsolete_label,
    load_curated_definitions,
    missing_definitions,
    obsolete_label,
)
from tools.update_flopo_release import _update_release_metadata


BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO OBO QC DEFINITIONS -->"
END_MARKER = "  <!-- END GENERATED FLOPO OBO QC DEFINITIONS -->"
ANY_BEGIN = re.compile(r"^  <!-- BEGIN GENERATED (.+) -->$")
ANY_END = re.compile(r"^  <!-- END GENERATED (.+) -->$")
TOP_OPEN = re.compile(r'^  <([\w:]+) rdf:about="([^"]+)"\s*>$')
LABEL_LINE = re.compile(r"^(    <rdfs:label\b[^>]*>)(.*)(</rdfs:label>)$")


def _without_generated_block(text: str) -> str:
    begin_count, end_count = text.count(BEGIN_MARKER), text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated OBO QC markers in release OWL")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def prefix_obsolete_labels_text(text: str, deprecated: set[URIRef]) -> tuple[str, int]:
    """Prefix top-level body labels of deprecated entities; refuse edits inside blocks."""
    wanted = {str(iri) for iri in deprecated}
    out: list[str] = []
    block: str | None = None
    about: str | None = None
    closing: str | None = None
    changed = 0
    offending: list[str] = []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n")
        if (m := ANY_BEGIN.match(bare)) is not None:
            block = m.group(1)
        elif ANY_END.match(bare):
            block = None
        elif about is None and (m := TOP_OPEN.match(bare)) is not None:
            about, closing = m.group(2), f"  </{m.group(1)}>"
        elif about is not None and bare == closing:
            about = closing = None
        elif about in wanted and (m := LABEL_LINE.match(bare)) is not None:
            if not is_obsolete_label(m.group(2)):
                if block is not None:
                    offending.append(f"{about} ({block})")
                else:
                    line = f"{m.group(1)}{obsolete_label(m.group(2))}{m.group(3)}\n"
                    changed += 1
        out.append(line)
    if offending:
        raise ValueError(
            "deprecated labels inside generated blocks must be fixed in their module: "
            + ", ".join(sorted(offending)[:10])
        )
    return "".join(out), changed


def _definition_block(definitions: dict) -> str:
    lines = [BEGIN_MARKER]
    for iri, (text, sources) in sorted(definitions.items(), key=lambda item: str(item[0])):
        lines.append(f"  <rdf:Description rdf:about={quoteattr(str(iri))}>")
        lines.append(f'    <obo:IAO_0000115 xml:lang="en">{escape(text)}</obo:IAO_0000115>')
        for source in sources:
            if isinstance(source, URIRef):
                lines.append(f"    <dcterms:source rdf:resource={quoteattr(str(source))}/>")
            else:
                lines.append(f"    <dcterms:source>{escape(str(source))}</dcterms:source>")
        lines.append("  </rdf:Description>")
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def check_release(graph: Graph) -> dict[str, int]:
    """Count remaining obsolete-label, missing-definition and duplicate-definition problems."""
    deprecated = deprecated_flopo_entities(graph)
    bad_labels = sum(
        1
        for iri in deprecated
        for label in graph.objects(iri, RDFS.label)
        if not is_obsolete_label(str(label))
    )
    seen: dict[str, URIRef] = {}
    duplicates = 0
    for iri, text in graph.subject_objects(IAO_DEF):
        if iri in deprecated or not str(iri).startswith("http://purl.obolibrary.org/obo/FLOPO_"):
            continue
        key = " ".join(str(text).split()).casefold()
        if key in seen and seen[key] != iri:
            duplicates += 1
        seen[key] = iri
    return {"missing_obsolete_label": bad_labels, "duplicate_live_definitions": duplicates}


def update_release(
    release_path: Path,
    out_path: Path,
    *,
    registry: Path = Path("config/flopo_id_registry.tsv"),
    po_lex: Path = Path("config/po_lexicon.tsv"),
    pato_lex: Path = Path("config/pato_lexicon.tsv"),
    curated: Path = CURATED_DEFINITIONS,
    release_date: str | None = None,
) -> dict[str, int]:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    graph = Graph().parse(data=text, format="xml")
    deprecated = deprecated_flopo_entities(graph)
    text, labels_prefixed = prefix_obsolete_labels_text(text, deprecated)
    definitions = missing_definitions(
        graph,
        _load_registry(registry),
        _load_labels(po_lex),
        _load_labels(pato_lex),
        load_curated_definitions(curated),
    )
    if release_date:
        text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    if definitions:
        text = text.replace(closing, _definition_block(definitions) + closing, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    check = check_release(Graph().parse(out_path.as_posix(), format="xml"))
    if check["missing_obsolete_label"] or check["duplicate_live_definitions"]:
        raise ValueError(f"OBO QC fixes incomplete: {check}")
    return {
        "obsolete_labels_prefixed": labels_prefixed,
        "definitions_added": len(definitions),
        "curated_definitions": sum(1 for _, sources in definitions.values() if sources),
        **check,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--out", type=Path, default=None, help="default: overwrite --release")
    parser.add_argument("--curated", type=Path, default=CURATED_DEFINITIONS)
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument(
        "--date",
        default=None,
        help="also bump versionIRI/versionInfo/modified (e.g. %s)" % date.today().isoformat(),
    )
    args = parser.parse_args()
    stats = update_release(
        args.release,
        args.out or args.release,
        registry=args.registry,
        curated=args.curated,
        release_date=args.date,
    )
    for key, value in stats.items():
        print(f"{key} {value}")


if __name__ == "__main__":
    main()

