#!/usr/bin/env python3
"""Build the approved FLOPO botanical-pubescence obsolete/replacement module."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection


OBO = Namespace("http://purl.obolibrary.org/obo/")
MODULE = URIRef(OBO + "flopo-pubescent-migration.owl")
PATO = URIRef(OBO + "pato.owl")
PO = URIRef(OBO + "po.owl")
HAS_PART = URIRef(OBO + "BFO_0000051")
HAS_CHARACTERISTIC = URIRef(OBO + "RO_0000053")
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
TERM_REPLACED_BY = URIRef(OBO + "IAO_0100001")
ANATOMICAL_ENTITY_PHENOTYPE = URIRef(OBO + "FLOPO_0980418")
BOTANICAL_PUBESCENCE = URIRef(OBO + "PATO_0001320")
HUMAN_PUBERTY = URIRef(OBO + "PATO_0000455")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")


def _rows(path: Path, key: str) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"duplicate {key} in {path}")
    return rows, indexed


def _restriction(graph: Graph, prop: URIRef, filler: URIRef | BNode, name: str) -> BNode:
    node = BNode(name)
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, prop))
    graph.add((node, OWL.someValuesFrom, filler))
    return node


def _entity_quality(graph: Graph, entity: URIRef, quality: URIRef, name: str) -> BNode:
    characteristic = _restriction(
        graph, HAS_CHARACTERISTIC, quality, f"{name}_characteristic"
    )
    intersection = BNode(f"{name}_intersection")
    members = BNode(f"{name}_members")
    Collection(graph, members, [entity, characteristic])
    graph.add((intersection, RDF.type, OWL.Class))
    graph.add((intersection, OWL.intersectionOf, members))
    return _restriction(graph, HAS_PART, intersection, f"{name}_outer")


def _source_urls(
    source_field: str, evidence: dict[str, dict[str, str]]
) -> list[URIRef]:
    urls: list[URIRef] = []
    for token in source_field.split("|"):
        if token in evidence and evidence[token]["url"]:
            url = URIRef(evidence[token]["url"])
            if url not in urls:
                urls.append(url)
    return urls


def build_module(
    release_path: Path,
    migration_path: Path,
    evidence_path: Path,
    approvals_path: Path,
    release_date: str,
) -> tuple[Graph, set[URIRef], set[URIRef]]:
    rows, _by_old = _rows(migration_path, "old_flopo_id")
    _evidence_rows, evidence = _rows(evidence_path, "evidence_id")
    with approvals_path.open(encoding="utf-8", newline="") as handle:
        approvals = list(csv.DictReader(handle, delimiter="\t"))
    if not any(
        row["proposal_set"] == "curation/pubescent_migration.tsv"
        and row["decision"] == "accept"
        and row["curator_orcid"] == "0000-0001-8149-5890"
        for row in approvals
    ):
        raise ValueError("pubescent migration lacks the required curator approval")
    if len(rows) != 154:
        raise ValueError(f"expected 154 approved migration rows, found {len(rows)}")
    if any(
        row["replacement_id_status"] != "new_approved_reserved"
        or row["curator_decision"] != "accept"
        for row in rows
    ):
        raise ValueError("all migration rows must be approved and their IDs reserved")

    old_ids = {URIRef(OBO + row["old_flopo_id"]) for row in rows}
    new_ids = {URIRef(OBO + row["replacement_flopo_id"]) for row in rows}
    expected_numbers = set(range(980432, 980586))
    actual_numbers = {
        int(row["replacement_flopo_id"].removeprefix("FLOPO_")) for row in rows
    }
    if actual_numbers != expected_numbers or old_ids & new_ids:
        raise ValueError("replacement IDs must occupy the reserved 0980432-0980585 range")

    source = Graph().parse(release_path.as_posix())
    for old in old_ids:
        incoming = list(source.subject_predicates(old))
        if incoming:
            raise ValueError(f"cannot obsolete {old}; it has incoming logical/annotation uses")
    present_replacements = {new for new in new_ids if (new, None, None) in source}
    if present_replacements and present_replacements != new_ids:
        raise ValueError("only part of the approved pubescence migration is present")

    graph = Graph()
    graph.bind("dcterms", DCTERMS)
    graph.bind("obo", OBO)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, OWL.imports, PATO))
    graph.add((MODULE, OWL.imports, PO))
    graph.add(
        (MODULE, RDFS.label, Literal("FLOPO botanical pubescence migration", lang="en"))
    )
    graph.add((MODULE, DCTERMS.modified, Literal(release_date, datatype=XSD.date)))
    graph.add(
        (
            MODULE,
            DCTERMS.license,
            URIRef("https://creativecommons.org/publicdomain/zero/1.0/"),
        )
    )

    for row in rows:
        old = URIRef(OBO + row["old_flopo_id"])
        new = URIRef(OBO + row["replacement_flopo_id"])
        signature = row["replacement_signature"].split("|")
        if len(signature) != 3 or signature[0] != "EQ" or signature[2] != "PATO_0001320":
            raise ValueError(f"unexpected replacement signature for {new}")
        entity = URIRef(OBO + signature[1])
        old_definitions = list(source.objects(old, IAO_DEFINITION))
        if len(old_definitions) != 1:
            raise ValueError(f"expected one definition on {old}")
        evidence_urls = _source_urls(row["evidence"], evidence)
        if len(evidence_urls) < 2:
            raise ValueError(f"missing botanical evidence for {old}")

        # The old identifier remains available only as an obsolete annotation shell.
        graph.add((old, RDF.type, OWL.Class))
        graph.add((old, RDFS.label, Literal(row["obsolete_label"])))
        graph.add((old, IAO_DEFINITION, old_definitions[0]))
        graph.add((old, OWL.deprecated, Literal(True, datatype=XSD.boolean)))
        graph.add((old, TERM_REPLACED_BY, new))
        graph.add((old, DCTERMS.contributor, CONTRIBUTOR))
        graph.add((old, DCTERMS.modified, Literal(release_date, datatype=XSD.date)))
        graph.add(
            (
                old,
                IAO_EDITOR_NOTE,
                Literal(
                    "Obsoleted because its botanical label was incorrectly defined using "
                    "PATO:0000455, the human-puberty maturity quality. Use the linked "
                    "replacement defined with PATO:0001320 botanical pubescence.",
                    lang="en",
                ),
            )
        )
        for url in evidence_urls:
            graph.add((old, DCTERMS.source, url))

        # The replacement preserves the botanical label and uses the correct pilosity quality.
        bearer_label = row["replacement_label"][: -len(" pubescent")]
        graph.add((new, RDF.type, OWL.Class))
        graph.add((new, RDFS.label, Literal(row["replacement_label"])))
        graph.add(
            (
                new,
                IAO_DEFINITION,
                Literal(
                    f"A phenotype in which the {bearer_label} is covered with short hairs "
                    "or soft down.",
                    lang="en",
                ),
            )
        )
        graph.add((new, RDFS.subClassOf, ANATOMICAL_ENTITY_PHENOTYPE))
        graph.add(
            (
                new,
                OWL.equivalentClass,
                _entity_quality(graph, entity, BOTANICAL_PUBESCENCE, row["replacement_flopo_id"]),
            )
        )
        graph.add((new, DCTERMS.contributor, CONTRIBUTOR))
        graph.add((new, DCTERMS.created, Literal(release_date, datatype=XSD.date)))
        graph.add(
            (
                new,
                IAO_EDITOR_NOTE,
                Literal(
                    f"Replaces {row['old_flopo_id']}; the corrected EQ uses botanical "
                    "pilosity PATO:0001320 rather than human puberty PATO:0000455.",
                    lang="en",
                ),
            )
        )
        for url in evidence_urls:
            graph.add((new, DCTERMS.source, url))

    if (None, None, HUMAN_PUBERTY) in graph:
        raise ValueError("human-puberty PATO class leaked into the migration module")
    return graph, old_ids, new_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--migration", type=Path, default=Path("curation/pubescent_migration.tsv")
    )
    parser.add_argument(
        "--evidence", type=Path, default=Path("curation/botanical_evidence.tsv")
    )
    parser.add_argument(
        "--approvals", type=Path, default=Path("curation/curator_approvals.tsv")
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("ontology/flopo-pubescent-migration.ttl"),
    )
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    graph, old_ids, new_ids = build_module(
        args.release, args.migration, args.evidence, args.approvals, args.date
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    print(f"wrote {len(old_ids)} obsolete and {len(new_ids)} replacement classes")
    print(f"output {args.out}")


if __name__ == "__main__":
    main()
