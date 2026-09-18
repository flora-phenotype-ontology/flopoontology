#!/usr/bin/env python3
"""Embed the growth-form and life-span logical-definition module in flopo.owl.

The module is additive. Released classes keep their owl:Class elements; the generated block adds
their logical axioms, editor notes and (for ``revise_definition`` rows) a replacement textual
definition. The superseded definition of such a class may only come from the generated OBO QC
definitions block, and it is removed from there so the class keeps exactly one IAO:0000115. A
later run of ``tools/update_flopo_obo_qc_release.py`` does not re-add it, because it writes only
missing definitions.

The tool refuses a module that is not identical to an accepted-only build of its specification,
so pending proposal rows cannot reach the release. ``--allow-pending`` exists only for scratch
copies used by tests and reasoner checks.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, BNode, Graph, URIRef
from rdflib.compare import isomorphic

from tools.build_flopo_growth_form_extension import (
    EVIDENCE,
    FLOPO_REGISTRY,
    IAO_DEFINITION,
    MODULE,
    PATO,
    PO,
    REGISTRY,
    SPEC,
    build_module,
)
from tools.update_flopo_release import _graph_fragment, _update_release_metadata


OBO = "http://purl.obolibrary.org/obo/"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO GROWTH FORM EXTENSION -->"
END_MARKER = "  <!-- END GENERATED FLOPO GROWTH FORM EXTENSION -->"
QC_BEGIN = "  <!-- BEGIN GENERATED FLOPO OBO QC DEFINITIONS -->"
QC_END = "  <!-- END GENERATED FLOPO OBO QC DEFINITIONS -->"
NODE_ID_PREFIX = "FLOPOGrowthForm_"


def _block_pattern(begin: str, end: str) -> re.Pattern[str]:
    return re.compile(rf"\n?{re.escape(begin)}.*?{re.escape(end)}\n?", re.DOTALL)


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated growth-form markers")
    if not begin_count:
        return text
    return _block_pattern(BEGIN_MARKER, END_MARKER).sub("\n", text, count=1)


def check_module_is_releasable(module: Graph, release_date: str) -> None:
    accepted = build_module(
        SPEC, REGISTRY, EVIDENCE, FLOPO_REGISTRY, PO, PATO, release_date, include_pending=False
    )
    if not isomorphic(module, accepted):
        raise ValueError(
            "growth-form module differs from an accepted-only build: it is stale or contains "
            "rows without a curator decision; rebuild with "
            "`python3 -m tools.build_flopo_growth_form_extension` after the curator review"
        )


def module_fragment(module: Graph) -> tuple[str, set[str], set[str]]:
    """Return the RDF/XML fragment, the new classes and the redefined released classes."""

    if set(module.subjects(RDF.type, OWL.Ontology)) != {MODULE}:
        raise ValueError("growth-form module must have exactly its expected ontology header")
    new_classes = {
        str(cls)
        for cls in module.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef)
    }
    foreign = sorted(cls for cls in new_classes if not cls.startswith(OBO + "FLOPO_"))
    if foreign:
        raise ValueError(f"growth-form module declares non-FLOPO classes: {foreign}")
    redefined = {
        str(subject)
        for subject in module.subjects(IAO_DEFINITION, None)
        if isinstance(subject, URIRef) and str(subject) not in new_classes
    }
    fragment_graph = Graph()
    for triple in module:
        if triple[0] != MODULE:
            fragment_graph.add(triple)
    fragment, _count = _graph_fragment(fragment_graph, node_id_prefix=NODE_ID_PREFIX)
    if str(MODULE) in fragment:
        raise ValueError("growth-form module ontology header leaked into release fragment")
    return fragment.strip(), new_classes, redefined


def _definition_elements(text: str, class_iri: str) -> list[tuple[int, int]]:
    """Return spans of top-level elements about ``class_iri`` that carry IAO:0000115."""

    spans = []
    opening = re.compile(
        rf'^  <(owl:Class|rdf:Description) rdf:about="{re.escape(class_iri)}">$', re.MULTILINE
    )
    for match in opening.finditer(text):
        close = text.find(f"\n  </{match.group(1)}>", match.end())
        if close < 0:
            raise ValueError(f"unterminated element for {class_iri}")
        body = text[match.end() : close]
        if "<obo:IAO_0000115" in body:
            spans.append((match.start(), close))
    return spans


def strip_superseded_definitions(text: str, class_iris: set[str]) -> tuple[str, int]:
    """Remove released definitions that a ``revise_definition`` row replaces.

    Only the generated OBO QC block may hold them; a definition anywhere else means the class is
    owned by another builder and the row must be handled there instead.
    """

    qc_start = text.find(QC_BEGIN)
    qc_end = text.find(QC_END)
    removed = 0
    for class_iri in sorted(class_iris):
        for start, _end in _definition_elements(text, class_iri):
            if not (0 <= qc_start < start < qc_end):
                raise ValueError(
                    f"{class_iri} already has a definition outside the OBO QC block; "
                    "revise it in its owning module"
                )
        pattern = re.compile(
            rf'(  <rdf:Description rdf:about="{re.escape(class_iri)}">\n)(.*?)(  </rdf:Description>\n)',
            re.DOTALL,
        )
        qc_start = text.find(QC_BEGIN)
        qc_end = text.find(QC_END)
        block = text[qc_start:qc_end]

        def drop(match: re.Match[str]) -> str:
            nonlocal removed
            lines = [
                line
                for line in match.group(2).splitlines(keepends=True)
                if "<obo:IAO_0000115" not in line
            ]
            removed += len(match.group(2).splitlines()) - len(lines)
            return match.group(1) + "".join(lines) + match.group(3) if lines else ""

        block = pattern.sub(drop, block)
        text = text[:qc_start] + block + text[qc_end:]
    return text, removed


def update_release(
    release_path: Path,
    module_path: Path,
    release_date: str,
    *,
    verify: bool = True,
    allow_pending: bool = False,
) -> dict[str, int]:
    module = Graph().parse(module_path.as_posix())
    if not allow_pending:
        module_date = str(next(module.objects(MODULE, DCTERMS.modified)))
        check_module_is_releasable(module, module_date)
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    fragment, new_classes, redefined = module_fragment(module)
    for class_iri in new_classes:
        if f'rdf:about="{class_iri}"' in text:
            raise ValueError(f"new growth-form class {class_iri} is already in the release")
    for class_iri in redefined:
        if f'rdf:about="{class_iri}"' not in text:
            raise ValueError(f"redefined class {class_iri} is not in the release")
    text, stripped = strip_superseded_definitions(text, redefined)
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
            raise ValueError("growth-form module ontology header leaked into flopo.owl")
        for class_iri in new_classes:
            if (URIRef(class_iri), RDF.type, OWL.Class) not in check:
                raise ValueError(f"missing embedded class {class_iri}")
        for class_iri in redefined | new_classes:
            if len(set(check.objects(URIRef(class_iri), IAO_DEFINITION))) != 1:
                raise ValueError(f"{class_iri} does not have exactly one definition")
        missing = [triple for triple in module if triple[0] != MODULE and not _has(check, triple)]
        if missing:
            raise ValueError(f"{len(missing)} module triples are missing from the release")
    return {
        "new_classes": len(new_classes),
        "redefined_classes": len(redefined),
        "stripped_qc_definitions": stripped,
    }


def _has(graph: Graph, triple) -> bool:
    """Check a ground module triple; blank-node structure is compared in the tests."""

    subject, _predicate, obj = triple
    if isinstance(subject, BNode) or isinstance(obj, BNode):
        return True
    return triple in graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--module", type=Path, default=Path("ontology/flopo-growth-form-extension.ttl")
    )
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="skip the curator-decision gate (scratch copies only, never the release)",
    )
    args = parser.parse_args()
    stats = update_release(
        args.release, args.module, args.date, allow_pending=args.allow_pending
    )
    for key, value in stats.items():
        print(f"{key} {value}")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
