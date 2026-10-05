#!/usr/bin/env python3
"""Obsolete curator-listed FLOPO classes in flopo.owl (marker-delimited and idempotent).

``config/flopo_obsoletions.tsv`` lists each class to obsolete with the reason and an optional
replacement (``replaced_by``) or alternative (``consider``).  The release tool replaces the live
declaration with an obsolete stub that keeps the identifier, label (prefixed "obsolete "),
definition (prefixed "OBSOLETE. ") and annotations, drops the logical axioms, and records the
reason, decision date and replacement.  Stubs live in their own generated block so the tool can
be rerun; a class that is already obsolete is restubbed from the block's copy.
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import date
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef

from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _graph_fragment, _update_release_metadata

OBO = Namespace("http://purl.obolibrary.org/obo/")
OBO_IN_OWL = Namespace("http://www.geneontology.org/formats/oboInOwl#")
TABLE = Path("config/flopo_obsoletions.tsv")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO CURATOR OBSOLETIONS -->"
END_MARKER = "  <!-- END GENERATED FLOPO CURATOR OBSOLETIONS -->"
DEFINITION = OBO.IAO_0000115
EDITOR_NOTE = OBO.IAO_0000116
REPLACED_BY = OBO.IAO_0100001


def read_table(root: Path) -> list[dict[str, str]]:
    with (root / TABLE).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _block(text: str) -> tuple[str, str]:
    begin, end = text.count(BEGIN_MARKER), text.count(END_MARKER)
    if begin != end or begin > 1:
        raise ValueError("malformed generated obsoletion markers")
    if not begin:
        return text, ""
    start = text.index(BEGIN_MARKER)
    stop = text.index(END_MARKER) + len(END_MARKER)
    if stop < len(text) and text[stop] == "\n":
        stop += 1
    return text[:start] + text[stop:], text[start:stop]


def update_release(release_path: Path, release_date: str, root: Path = Path(".")) -> int:
    rows = read_table(root)
    text = release_path.read_text(encoding="utf-8")
    current = Graph().parse(release_path.as_posix())
    text, _old_block = _block(text)

    stubs = Graph()
    for row in rows:
        cls = OBO[row["flopo_id"].replace(":", "_")]
        label = current.value(cls, RDFS.label)
        if label is None:
            raise ValueError(f"class to obsolete is not in the release: {row['flopo_id']}")
        label_text = str(label)
        if not label_text.startswith("obsolete "):
            label_text = f"obsolete {label_text}"
        stubs.add((cls, RDF.type, OWL.Class))
        stubs.add((cls, RDFS.label, Literal(label_text, datatype=XSD.string)))
        for predicate, obj in current.predicate_objects(cls):
            if predicate in {RDF.type, RDFS.label, RDFS.subClassOf, OWL.equivalentClass, OWL.deprecated}:
                continue
            if isinstance(obj, BNode) or predicate in {EDITOR_NOTE, REPLACED_BY, OBO_IN_OWL.consider}:
                continue
            if predicate == DEFINITION and not str(obj).startswith("OBSOLETE."):
                obj = Literal(f"OBSOLETE. {obj}", lang=obj.language)
            stubs.add((cls, predicate, obj))
        stubs.add((cls, OWL.deprecated, Literal(True)))
        stubs.add((cls, EDITOR_NOTE, Literal(row["reason"], lang="en")))
        stubs.add((cls, DCTERMS.modified, Literal(row["decision_date"], datatype=XSD.date)))
        if row.get("replaced_by"):
            stubs.add((cls, REPLACED_BY, OBO[row["replaced_by"].replace(":", "_")]))
        for alternative in filter(None, (row.get("consider") or "").split("|")):
            stubs.add((cls, OBO_IN_OWL.consider, OBO[alternative.replace(":", "_")]))
        text, _removed = _remove_named_owl_class(text, str(cls))

    # Nothing live may still point at a class obsoleted here.
    obsoleted = {OBO[row["flopo_id"].replace(":", "_")] for row in rows}
    for cls in obsoleted:
        users = {s for s in current.subjects(RDFS.subClassOf, cls) if isinstance(s, URIRef)}
        if users - obsoleted:
            raise ValueError(f"{cls} still has asserted subclasses: {sorted(map(str, users))[:3]}")

    fragment, _count = _graph_fragment(stubs, node_id_prefix="FLOPOObsolete_")
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    text = text.replace(closing, f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n{closing}", 1)
    release_path.write_text(text, encoding="utf-8")

    check = Graph().parse(release_path.as_posix())
    for cls in obsoleted:
        if (cls, OWL.deprecated, Literal(True)) not in check or (cls, OWL.equivalentClass, None) in check:
            raise ValueError(f"{cls} is not a clean obsolete stub after the update")
    return len(obsoleted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    print(f"obsoleted {update_release(args.release, args.date)} classes")


if __name__ == "__main__":
    main()
