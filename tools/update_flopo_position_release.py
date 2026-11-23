#!/usr/bin/env python3
"""Embed 'has position' and the named positioned parts in flopo.owl (marker-delimited, idempotent).

Pattern 18 (``docs/odp/18-position-of-the-bearer.md``, ``flopo2/owl/position.py``):

    'has position' SubPropertyOf 'has characteristic'
    'basal leaf' EquivalentTo leaf and 'has position' some basal

``config/flopo_positioned_parts.tsv`` lists the positioned parts that have a name: those that
many taxa use (``--min-taxa``, counted in the flora annotations), with identifiers of the block
FLOPO_0996000-FLOPO_0996999. A row with a Plant Ontology identifier names no new class: the
Plant Ontology has the part ('cauline leaf'), and the release states that it is the same as the
expression. Identifiers are never reused: ``--counts`` adds rows for new frequent pairs and keeps
the rows that are there. The column ``synonyms`` gives the words botanists use where the label, built
from the ontology labels, is not theirs (``exact:lateral vein|related:side vein``).

    python -m tools.update_flopo_position_release [--counts pairs.json --min-taxa 100]

Run before the final passes of the release procedure.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import DCTERMS, XSD

from flopo2.owl import position
from tools.update_flopo_release import _graph_fragment, _update_release_metadata

OBO = "http://purl.obolibrary.org/obo/"
DEFINITION, EDITOR_NOTE, EXAMPLE = (URIRef(OBO + n) for n in ("IAO_0000115", "IAO_0000116", "IAO_0000112"))
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO POSITIONED PARTS -->"
END_MARKER = "  <!-- END GENERATED FLOPO POSITIONED PARTS -->"
FIRST_ID, LAST_ID = 996000, 996999
WHERE = {
    "FLOPO_0991002": "is located at the base of the plant or of the axis that bears it",
    "FLOPO_0991117": "is borne on the stem",
    "FLOPO_0991376": "is located nearer the apex of the axis or structure that bears it than the others of its kind",
    "FLOPO_0991377": "is located nearer the base of the axis or structure that bears it than the others of its kind",
    "FLOPO_0991378": "is located nearer the centre or the axis than the others of its kind",
    "FLOPO_0991379": "is located farther from the centre or the axis than the others of its kind",
    "FLOPO_0991380": "is located at the side of the structure that bears it, neither at its end nor in its middle",
    "FLOPO_0991381": "is located in the middle of a series of its kind",
    "PATO_0002476": "is located at the end of the axis or series that bears it",
}
SKIP_PARTS = {"PO_0009002"}  # plant cell: "basal cells" of a moss leaf are a tissue region, not a member


def _labels() -> tuple[dict[str, str], dict[str, str]]:
    from flopo2.saudi.vocab import Vocabulary

    vocab = Vocabulary()
    po_by_label = {term.name.lower(): cid.replace(":", "_") for cid, term in vocab.po.items()}
    return {"vocab": vocab}, po_by_label  # type: ignore[return-value]


def update_table(counts: Path, min_taxa: int, table: Path = position.POSITIONED_PARTS) -> int:
    """Add the frequent pairs of ``counts`` (``{"pairs": [[part, position, records, taxa], ...]}``)."""

    holder, po_by_label = _labels()
    vocab = holder["vocab"]
    rows = []
    if table.exists():
        with table.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    have = {(r["part"], r["position"]) for r in rows}
    used = {int(r["flopo_id"].split("_")[1]) for r in rows if r["flopo_id"].startswith("FLOPO_")}
    labels = {r["label"].lower() for r in rows}
    next_id = max(used | {FIRST_ID - 1}) + 1
    added = 0
    for part, value, records, taxa in json.loads(counts.read_text(encoding="utf-8"))["pairs"]:
        if taxa < min_taxa or (part, value) in have or part in SKIP_PARTS or value not in position.position_values():
            continue
        label = f"{position.position_values()[value]} {vocab.label(part)}"
        existing = po_by_label.get(label.lower(), "")
        if not existing and label.lower() in labels:
            continue
        if existing:
            identifier = existing
        else:
            if next_id > LAST_ID:
                raise ValueError("the identifier block of the positioned parts is full")
            identifier, next_id = f"FLOPO_{next_id:07d}", next_id + 1
        rows.append({"flopo_id": identifier, "part": part, "position": value, "label": label,
                     "part_label": vocab.label(part), "taxa": str(taxa), "records": str(records), "synonyms": ""})
        labels.add(label.lower())
        added += 1
    with table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["flopo_id", "part", "position", "label", "part_label", "taxa", "records", "synonyms"],
                                delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return added


def module(release_date: str, table: Path = position.POSITIONED_PARTS) -> tuple[Graph, int, int]:
    graph = Graph()
    rel = position.HAS_POSITION
    graph.add((rel, RDF.type, OWL.ObjectProperty))
    graph.add((rel, RDFS.subPropertyOf, position.HAS_CHARACTERISTIC))
    graph.add((rel, RDFS.label, Literal(position.HAS_POSITION_LABEL, datatype=XSD.string)))
    graph.add((rel, DEFINITION, Literal(
        "A relation between a plant part and a position quality that inheres in it and says where the part is "
        "located among the parts of its kind or on the structure that bears it (basal, cauline, upper, lower, "
        "inner, outer, lateral, median, terminal).", lang="en")))
    graph.add((rel, EXAMPLE, Literal(
        "'basal leaf' EquivalentTo (leaf and 'has position' some basal); \"basal leaves spatulate\" is "
        "'has part' some (leaf and 'has position' some basal and 'has characteristic' some spatulate).", lang="en")))
    graph.add((rel, EDITOR_NOTE, Literal(
        "Temporary FLOPO relation, added 2026-11-23. A sub-relation of 'has characteristic' (RO:0000053): the "
        "position is a quality of the part like any other, but it selects which parts a statement is about and is "
        "kept apart from the quality that the statement asserts (docs/odp/18-position-of-the-bearer.md). "
        "Provisional: pending final curator vetting.", lang="en")))
    graph.add((rel, DCTERMS.date, Literal("2026-11-23", datatype=XSD.date)))
    graph.add((rel, RDFS.domain, URIRef(OBO + "PO_0025131")))
    graph.add((rel, RDFS.range, URIRef(OBO + "PATO_0000140")))
    named = bridged = 0
    with table.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            cls, part, value = (URIRef(OBO + row[k]) for k in ("flopo_id", "part", "position"))
            restriction, expression, head = BNode(), BNode(), BNode()
            graph.add((restriction, RDF.type, OWL.Restriction))
            graph.add((restriction, OWL.onProperty, rel))
            graph.add((restriction, OWL.someValuesFrom, value))
            graph.add((expression, RDF.type, OWL.Class))
            graph.add((expression, OWL.intersectionOf, head))
            Collection(graph, head, [part, restriction])
            graph.add((cls, OWL.equivalentClass, expression))
            if not row["flopo_id"].startswith("FLOPO_"):
                bridged += 1  # the Plant Ontology has the class: only the equivalence is stated
                continue
            named += 1
            graph.add((cls, RDF.type, OWL.Class))
            graph.add((cls, RDFS.label, Literal(row["label"], datatype=XSD.string)))
            graph.add((cls, RDFS.subClassOf, part))
            article = "An" if row["part_label"][0].lower() in "aeiou" else "A"
            graph.add((cls, DEFINITION, Literal(f"{article} {row['part_label']} that {WHERE[row['position']]}.", lang="en")))
            graph.add((cls, EDITOR_NOTE, Literal(
                f"FLOPO-local anatomy class, added 2026-11-23: a positioned part named because the flora annotations "
                f"use it in {int(row['taxa']):,} taxa (pattern 18, docs/odp/18-position-of-the-bearer.md). Defined by "
                f"'has position' (FLOPO:0995004). Provisional: pending final curator vetting.", lang="en")))
            graph.add((cls, DCTERMS.date, Literal("2026-11-23", datatype=XSD.date)))
            # The label is built from the ontology labels ("lateral vascular bundle"); the words
            # botanists use ("lateral vein") are synonyms: "exact:lateral vein|related:side vein".
            for entry in filter(None, (row.get("synonyms") or "").split("|")):
                scope, _, name = entry.partition(":")
                prop = {"exact": "hasExactSynonym", "related": "hasRelatedSynonym", "broad": "hasBroadSynonym",
                        "narrow": "hasNarrowSynonym"}[scope]
                graph.add((cls, URIRef("http://www.geneontology.org/formats/oboInOwl#" + prop),
                           Literal(name, datatype=XSD.string)))
    return graph, named, bridged


def update_release(release: Path, release_date: str) -> dict[str, int]:
    text = release.read_text(encoding="utf-8")
    if text.count(BEGIN_MARKER) != text.count(END_MARKER) or text.count(BEGIN_MARKER) > 1:
        raise ValueError("malformed positioned-part markers")
    text = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL).sub("\n", text, count=1)
    graph, named, bridged = module(release_date)
    fragment, _count = _graph_fragment(graph, node_id_prefix="FLOPOPosition_")
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    text = text.replace(closing, f"{BEGIN_MARKER}\n{fragment.strip()}\n{END_MARKER}\n{closing}", 1)
    release.write_text(text, encoding="utf-8")
    return {"named": named, "bridged_to_po": bridged}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--counts", type=Path, help="pairs counted in the annotations; adds frequent pairs to the table")
    parser.add_argument("--min-taxa", type=int, default=100)
    parser.add_argument("--table-only", action="store_true")
    args = parser.parse_args()
    if args.counts:
        print(f"{update_table(args.counts, args.min_taxa)} rows added to {position.POSITIONED_PARTS}")
    if not args.table_only:
        print(update_release(args.release, args.date))


if __name__ == "__main__":
    main()
