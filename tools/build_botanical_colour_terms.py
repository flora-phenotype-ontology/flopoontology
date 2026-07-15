#!/usr/bin/env python3
"""Build generic PATO colours and FLOPO-local source-qualified colour senses."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef


FIELDS = ("proposal_key", "ontology_id", "status")
DEFERRED_STATUS = "deferred_optional_closed_union"
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
NEW_TERM_TIMESTAMP = "T00:00:00Z"
OBO = Namespace("http://purl.obolibrary.org/obo/")
IAO_DEFINITION = OBO.IAO_0000115
EDITOR_NOTE = OBO.IAO_0000116
MODULE = OBO["flopo-colour-sensu-extension.owl"]


def _rows(path: Path, key: str) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"duplicate {key} in {path}")
    return rows, indexed


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _definition_xrefs(
    source_field: str, evidence: dict[str, dict[str, str]]
) -> list[str]:
    xrefs: list[str] = []
    for token in source_field.split("|"):
        token = token.strip()
        if token.startswith("DOI:"):
            xref = token
        elif token in evidence:
            record = evidence[token]
            identifier = record["doi_or_identifier"]
            xref = identifier if identifier.startswith("DOI:") else record["url"]
        else:
            raise ValueError(f"unresolved definition source {token}")
        if xref and xref not in xrefs:
            xrefs.append(xref)
    if not xrefs:
        raise ValueError("a colour definition needs at least one source xref")
    return xrefs


def _source_iri(xref: str) -> URIRef:
    if xref.startswith("DOI:"):
        return URIRef("https://doi.org/" + xref.removeprefix("DOI:"))
    return URIRef(xref)


def _synonyms(row: dict[str, str]) -> list[str]:
    label = row["preferred_label"].casefold()
    synonyms = [
        surface.strip()
        for surface in row["surface_family"].split("|")
        if surface.strip() and surface.strip().casefold() != label
    ]
    if row["proposal_key"] in {
        "COLOR:salmon",
        "COLOR:chestnut",
        "COLOR:olive",
        "COLOR:rose",
    }:
        american = row["preferred_label"].replace("colour", "color")
        if american.casefold() != label:
            synonyms.append(american)
    return list(dict.fromkeys(synonyms))


def _validate_assignments(
    proposals: list[dict[str, str]], assignments: list[dict[str, str]]
) -> None:
    active = [row for row in assignments if row["status"] != DEFERRED_STATUS]
    ids = [row["ontology_id"] for row in active]
    if any(not ontology_id for ontology_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("active ontology IDs must be present and unique")

    new_pato = sorted(
        int(row["ontology_id"].split(":", 1)[1])
        for row in assignments
        if row["status"] == "new_pato_generic"
    )
    expected_pato = [
        104314,
        104317,
        104321,
        104324,
        104326,
        104329,
        104333,
        104336,
        104343,
    ]
    if new_pato != expected_pato:
        raise ValueError("generic PATO colours must retain their reviewed draft identifiers")

    new_flopo = sorted(
        int(row["ontology_id"].split(":", 1)[1])
        for row in assignments
        if row["status"] == "new_flopo_local_sensu"
    )
    if new_flopo != list(range(980586, 980611)):
        raise ValueError("FLOPO colour senses must occupy 0980586-0980610")

    deferred = [row for row in assignments if row["status"] == DEFERRED_STATUS]
    if deferred != [
        {
            "proposal_key": "COLOR:scarlet_reviewed_union",
            "ontology_id": "",
            "status": DEFERRED_STATUS,
        }
    ]:
        raise ValueError("only the optional scarlet closed view may be deferred")

    for proposal, assignment in zip(proposals, assignments, strict=True):
        if proposal["proposal_key"] != assignment["proposal_key"]:
            raise ValueError("proposal and identifier registry order differ")
        if proposal["class_role"] == "lexical_umbrella":
            if proposal["intended_ontology"] != "PATO" or not assignment[
                "ontology_id"
            ].startswith("PATO:"):
                raise ValueError("every generic colour must be owned by PATO")
        elif proposal["class_role"] == "sensu_colour":
            if proposal["intended_ontology"] != "FLOPO" or not assignment[
                "ontology_id"
            ].startswith("FLOPO:"):
                raise ValueError("every source-qualified colour must be owned by FLOPO")
            if proposal["current_id"]:
                raise ValueError("FLOPO-local sensu colours must not reuse a PATO ID")
        elif proposal["class_role"] != "closed_union_view":
            raise ValueError(f"unknown colour class role: {proposal['class_role']}")


def build_modules(
    proposals_path: Path,
    ids_path: Path,
    evidence_path: Path,
    release_date: str,
) -> tuple[str, str, list[dict[str, str]]]:
    proposals, proposals_by_key = _rows(proposals_path, "proposal_key")
    assignments, assignments_by_key = _rows(ids_path, "proposal_key")
    _evidence_rows, evidence = _rows(evidence_path, "evidence_id")
    if tuple(assignments[0].keys()) != FIELDS:
        raise ValueError(f"unexpected ID registry fields: {tuple(assignments[0].keys())}")
    if set(proposals_by_key) != set(assignments_by_key):
        raise ValueError("proposal and colour ID registry keys differ")
    _validate_assignments(proposals, assignments)

    labels = {
        key: proposal["preferred_label"] for key, proposal in proposals_by_key.items()
    }
    pato_blocks: list[str] = []
    rendered_rows: list[dict[str, str]] = []

    graph = Graph()
    graph.bind("dcterms", DCTERMS)
    graph.bind("obo", OBO)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, OWL.imports, OBO["pato.owl"]))
    graph.add((MODULE, OWL.versionInfo, Literal(release_date)))

    for proposal in proposals:
        key = proposal["proposal_key"]
        assignment = assignments_by_key[key]
        if assignment["status"] == DEFERRED_STATUS:
            continue

        ontology_id = assignment["ontology_id"]
        xrefs = _definition_xrefs(proposal["definition_sources"], evidence)
        if proposal["class_role"] == "lexical_umbrella":
            lines = [
                "[Term]",
                f"id: {ontology_id}",
                f"name: {proposal['preferred_label']}",
                (
                    f'def: "{_escape(proposal["definition_or_recognition_rule"])}" '
                    f"[{', '.join(xrefs)}]"
                ),
            ]
            comment = proposal["annotation_policy"]
            if key == "COLOR:cream":
                comment += (
                    " Source-qualified cream standards are represented by FLOPO-local "
                    "subclasses, not by additional PATO classes."
                )
            elif key == "COLOR:rose":
                comment += (
                    " This evidence-backed open umbrella replaces the former unsupported "
                    "red-plus-yellow definition of PATO:0001425."
                )
            elif proposal["caveat"]:
                comment += " " + proposal["caveat"]
            lines.extend([f"comment: {comment}", "subset: value_slim"])
            for synonym in _synonyms(proposal):
                lines.append(f'synonym: "{_escape(synonym)}" EXACT []')
            lines.extend(
                [
                    "is_a: PATO:0000014 ! color",
                    "property_value: http://purl.org/dc/terms/contributor "
                    + str(CONTRIBUTOR),
                ]
            )
            if assignment["status"] == "new_pato_generic":
                lines.append(f"creation_date: {release_date}{NEW_TERM_TIMESTAMP}")
            elif key == "COLOR:cream":
                lines.append("creation_date: 2026-07-11T18:39:19Z")
            pato_blocks.append("\n".join(lines))
            parent_id = "PATO:0000014"
        else:
            parent_key = proposal["asserted_parent"]
            parent_assignment = assignments_by_key[parent_key]
            parent_id = parent_assignment["ontology_id"]
            if not parent_id.startswith("PATO:"):
                raise ValueError(f"FLOPO sensu parent is not a PATO colour: {parent_key}")
            cls = OBO[ontology_id.replace(":", "_")]
            parent = OBO[parent_id.replace(":", "_")]
            graph.add((cls, RDF.type, OWL.Class))
            graph.add((cls, RDFS.label, Literal(proposal["preferred_label"], lang="en")))
            graph.add(
                (
                    cls,
                    IAO_DEFINITION,
                    Literal(proposal["definition_or_recognition_rule"], lang="en"),
                )
            )
            note = (
                proposal["annotation_policy"]
                + " FLOPO-local source-qualified colour quality; its generic colour is "
                + f"{parent_id} ({labels[parent_key]})."
            )
            if proposal["caveat"]:
                note += " " + proposal["caveat"]
            graph.add((cls, EDITOR_NOTE, Literal(note, lang="en")))
            graph.add((cls, RDFS.subClassOf, parent))
            graph.add((cls, DCTERMS.contributor, CONTRIBUTOR))
            graph.add((cls, DCTERMS.created, Literal(release_date, datatype=XSD.date)))
            for xref in xrefs:
                graph.add((cls, DCTERMS.source, _source_iri(xref)))

        rendered_rows.append(
            {
                **proposal,
                "ontology_id": ontology_id,
                "parent_id": parent_id,
                "status": assignment["status"],
            }
        )

    if len(pato_blocks) != 11:
        raise ValueError("expected two existing and nine new generic PATO colours")
    flopo_classes = set(graph.subjects(RDF.type, OWL.Class))
    if len(flopo_classes) != 25:
        raise ValueError("expected 25 FLOPO-local source-qualified colour classes")

    pato_obo = "\n\n".join(pato_blocks) + "\n"
    flopo_ttl = graph.serialize(format="turtle")
    return pato_obo, flopo_ttl, rendered_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proposals",
        type=Path,
        default=Path("curation/botanical_colour_sensu_proposals.tsv"),
    )
    parser.add_argument(
        "--ids", type=Path, default=Path("config/botanical_colour_id_registry.tsv")
    )
    parser.add_argument(
        "--evidence", type=Path, default=Path("curation/botanical_evidence.tsv")
    )
    parser.add_argument(
        "--pato-out", type=Path, default=Path("curation/pato_botanical_colour_terms.obo")
    )
    parser.add_argument(
        "--flopo-out",
        type=Path,
        default=Path("ontology/flopo-colour-sensu-extension.ttl"),
    )
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    pato_obo, flopo_ttl, rows = build_modules(
        args.proposals, args.ids, args.evidence, args.date
    )
    args.pato_out.parent.mkdir(parents=True, exist_ok=True)
    args.flopo_out.parent.mkdir(parents=True, exist_ok=True)
    args.pato_out.write_text(pato_obo, encoding="utf-8")
    args.flopo_out.write_text(flopo_ttl, encoding="utf-8")
    pato_count = sum(row["ontology_id"].startswith("PATO:") for row in rows)
    flopo_count = sum(row["ontology_id"].startswith("FLOPO:") for row in rows)
    print(f"wrote {pato_count} generic PATO colours to {args.pato_out}")
    print(f"wrote {flopo_count} FLOPO-local colour senses to {args.flopo_out}")


if __name__ == "__main__":
    main()
