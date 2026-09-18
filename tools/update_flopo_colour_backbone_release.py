#!/usr/bin/env python3
"""Embed the ISCC-NBS colour backbone module (curator decision 2026-09-18) into flopo.owl.

Idempotent, marker-delimited, same style as ``tools/update_flopo_anatomy_support_release.py``
and ``tools/update_flopo_colour_sensu_release.py``.  Unlike those two extensions, this module
does not only add brand-new classes: it also redefines existing FLOPO classes whose colour
filler is re-pointed to a backbone class, and obsoletes the superseded FLOPO colour-value and
sensu classes.  Every FLOPO class the module declares therefore has its previous declaration
(if any) removed before the module fragment is re-inserted; the 27 reused PATO backbone classes
are never declared as ``owl:Class`` by the module (see ``tools/build_flopo_colour_backbone.py``)
and are left untouched other than the extra axioms the fragment adds about them.

Run ``tools/build_flopo_colour_backbone.py build`` first to (re)generate the module from the
committed configuration tables.  After embedding, run the identifier-registry resync and
classification (see the repository CLAUDE.md pipeline notes).
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import date
from pathlib import Path

from rdflib import OWL, RDF, Graph, URIRef

from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _extension_fragment, _update_release_metadata


OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-colour-backbone.owl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO COLOUR BACKBONE EXTENSION -->"
END_MARKER = "  <!-- END GENERATED FLOPO COLOUR BACKBONE EXTENSION -->"
REGISTRY = Path("config/flopo_colour_backbone_id_registry.tsv")
CHANGES = Path("curation/flopo_colour_backbone_eq_changes.tsv")


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated colour-backbone markers")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def _expected_flopo_classes(root: Path) -> set[str]:
    """The FLOPO classes the module is expected to (re)declare: new backbone classes, plus every
    class the build's change list recorded as redefined or obsoleted."""

    # Annotation properties are typed owl:AnnotationProperty, not owl:Class, so only new backbone
    # *classes* (never the merged-into-canonical duplicate rows, and never a reused PATO class,
    # which the registry marks "existing_pato_reused") belong in the expected owl:Class set here.
    expected: set[str] = set()
    registry_path = root / REGISTRY
    with registry_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if (
                row["kind"] == "backbone_class"
                and row["status"] == "new_flopo_local"
                and row["ontology_id"].startswith("FLOPO:")
            ):
                expected.add(OBO + row["ontology_id"].replace(":", "_", 1))
    changes_path = root / CHANGES
    with changes_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["flopo_id"]:
                expected.add(OBO + row["flopo_id"].replace(":", "_", 1))
    return expected


def module_fragment(module_path: Path, root: Path) -> tuple[str, set[str]]:
    graph = Graph().parse(module_path.as_posix())
    if set(graph.subjects(RDF.type, OWL.Ontology)) != {MODULE}:
        raise ValueError("colour backbone module must have exactly its expected ontology header")
    # Skolemized anonymous class-expression nodes (``tools.build_flopo_colour_backbone``'s
    # ``_new_expr_node``, IRIs under "<module>#expr_...") stand in for what would otherwise be
    # rdflib BNodes; they are module-internal plumbing, never declared classes, and must not be
    # confused with the genuine named FLOPO classes this check validates.
    module_ns = str(MODULE) + "#"
    classes = {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and not str(cls).startswith(module_ns)
    }
    foreign = sorted(cls for cls in classes if not cls.startswith(OBO + "FLOPO_"))
    if foreign:
        raise ValueError(
            f"colour backbone module declares non-FLOPO classes (reused PATO classes must "
            f"never be re-typed as owl:Class): {foreign}"
        )
    expected = _expected_flopo_classes(root)
    if classes != expected:
        missing = sorted(expected - classes)
        extra = sorted(classes - expected)
        raise ValueError(
            f"colour backbone module class set does not match the registry/change list "
            f"(missing={missing}, extra={extra})"
        )
    fragment, _count = _extension_fragment(module_path)
    header_pattern = re.compile(
        rf"  <rdf:Description rdf:about={re.escape(chr(34) + str(MODULE) + chr(34))}>"
        rf".*?  </rdf:Description>\n?",
        re.DOTALL,
    )
    fragment = header_pattern.sub("", fragment)
    # Skolemized expression nodes are legitimately named "<MODULE>#expr_..." /
    # "<MODULE>#axiom_..." and appear throughout the fragment, so only the ontology header's own
    # self-describing ``rdf:Description`` (matched and removed above) must be absent -- not every
    # occurrence of the module IRI as a substring.
    if f'rdf:about={chr(34)}{MODULE}{chr(34)}' in fragment:
        raise ValueError("colour backbone ontology header leaked into release fragment")
    return fragment.strip(), classes


def update_release(
    release_path: Path,
    module_path: Path,
    release_date: str,
    *,
    root: Path | None = None,
    verify: bool = True,
) -> int:
    root = root or Path(__file__).resolve().parents[1]
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    fragment, classes = module_fragment(module_path, root)
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
            raise ValueError("colour backbone ontology header leaked into flopo.owl")
        for class_iri in classes:
            if (URIRef(class_iri), RDF.type, OWL.Class) not in check:
                raise ValueError(f"missing embedded colour backbone class {class_iri}")
    return len(classes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--module", type=Path, default=Path("ontology/flopo-colour-backbone.ttl")
    )
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    count = update_release(args.release, args.module, args.date)
    print(f"embedded_or_replaced {count} FLOPO colour backbone classes")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
