#!/usr/bin/env python3
"""Replace FLOPO classes with malformed legacy IRIs by properly identified classes.

Four seed-weight classes were added in 2019 under ``http://purl.obolibrary.org/obo/flopo.owl#FLOPO_02102xx``,
an IRI form outside FLOPO's identifier scheme (``http://purl.obolibrary.org/obo/FLOPO_n``) that no
PURL resolves, no registry tracks and no release pass places in the hierarchy.  Curator decision
2026-10-13: obsolete them and replace them with proper identifiers.

``config/flopo_legacy_iri_replacements.tsv`` maps each legacy IRI to its new identifier (block
FLOPO_0992000-FLOPO_0992999) with the same meaning: an entity-quality definition (``entity``,
``quality``) or, for "seed normal weight" which had none, its asserted parent.  The legacy IRI
keeps an obsolete stub (label "obsolete ...", ``owl:deprecated``, ``IAO:0100001`` replaced_by,
creator and date).  Marker-delimited and idempotent; run before the final passes.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

from tools.build_flopo_sex_quality_extension import _eq
from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _graph_fragment, _update_release_metadata

OBO = Namespace("http://purl.obolibrary.org/obo/")
TABLE = Path("config/flopo_legacy_iri_replacements.tsv")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO LEGACY IRI REPLACEMENTS -->"
END_MARKER = "  <!-- END GENERATED FLOPO LEGACY IRI REPLACEMENTS -->"
DECISION_DATE = "2026-10-13"
DC = Namespace("http://purl.org/dc/elements/1.1/")


def _local(curie: str) -> URIRef:
    return OBO[curie.replace(":", "_", 1)]


def _without_block(text: str) -> str:
    import re

    if text.count(BEGIN_MARKER) != text.count(END_MARKER) or text.count(BEGIN_MARKER) > 1:
        raise ValueError("malformed legacy-IRI markers")
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def build_graph(rows: list[dict[str, str]], current: Graph) -> Graph:
    graph = Graph()
    for row in rows:
        old, new = URIRef(row["legacy_iri"]), _local(row["flopo_id"])
        graph.add((new, RDF.type, OWL.Class))
        graph.add((new, RDFS.label, Literal(row["label"], lang="en")))
        graph.add((new, OBO.IAO_0000115, Literal(row["definition"], lang="en")))
        graph.add((new, OBO.IAO_0000116, Literal(
            f"Replaces {row['legacy_iri']} (malformed legacy IRI; curator decision {DECISION_DATE}).", lang="en")))
        graph.add((new, DCTERMS.date, Literal(DECISION_DATE, datatype=XSD.date)))
        if row["entity"]:
            _eq(graph, new, _local(row["entity"]), _local(row["quality"]))
        if row["parent"]:
            graph.add((new, RDFS.subClassOf, _local(row["parent"])))

        label = current.value(old, RDFS.label) or row["label"]
        graph.add((old, RDF.type, OWL.Class))
        graph.add((old, RDFS.label, Literal(f"obsolete {label}", lang="en")))
        graph.add((old, OWL.deprecated, Literal(True)))
        graph.add((old, OBO.IAO_0100001, new))
        graph.add((old, OBO.IAO_0000116, Literal(
            f"Obsolete: malformed IRI outside the FLOPO identifier scheme; replaced by {row['flopo_id']} "
            f"(curator decision {DECISION_DATE}).", lang="en")))
        # Original dc: creator/date, kept as their dcterms: equivalents.
        for source, target in ((DC.creator, DCTERMS.creator), (DC.date, DCTERMS.date)):
            for value in current.objects(old, source):
                graph.add((old, target, value))
    return graph


def update_release(release: Path, release_date: str, root: Path = Path(".")) -> int:
    with (root / TABLE).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    current = Graph().parse(release.as_posix())
    text = _without_block(release.read_text(encoding="utf-8"))
    for row in rows:
        for iri in (row["legacy_iri"], str(_local(row["flopo_id"]))):
            text, _removed = _remove_named_owl_class(text, iri)
    fragment, _count = _graph_fragment(build_graph(rows, current), node_id_prefix="FLOPOLegacy_")
    text = _update_release_metadata(text, release_date)
    text = text.replace("</rdf:RDF>", f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n</rdf:RDF>", 1)
    release.write_text(text, encoding="utf-8")

    check = Graph().parse(release.as_posix())
    for row in rows:
        old, new = URIRef(row["legacy_iri"]), _local(row["flopo_id"])
        if (old, OWL.deprecated, Literal(True)) not in check or (old, OWL.equivalentClass, None) in check:
            raise ValueError(f"{old} is not a clean obsolete stub")
        if (new, RDF.type, OWL.Class) not in check:
            raise ValueError(f"{new} is missing")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    print(f"replaced {update_release(args.release, args.date)} legacy-IRI classes")


if __name__ == "__main__":
    main()
