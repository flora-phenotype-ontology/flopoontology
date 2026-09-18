"""Validate ontology and provisional references in botanical curation proposals."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from flopo2.terminology.catalog import (
    OntologyCatalog,
    canonical_curie,
    load_catalog_from_ontology_files,
)
from flopo2.terminology.curation_table import PROPOSAL_FIELDS


_REFERENCE_FIELDS = ("direct_parent_ids", "part_of_ids", "other_axioms")
_ONTOLOGY_REFERENCE = re.compile(r"\b(?:PO|PATO|FLOPO):\d+\b")
_PROPOSAL_REFERENCE = re.compile(
    r"\b(?:PO|PATO|FLOPO)-(?:CAND|PATTERN):[a-z0-9_]+\b"
)


def _read_proposals(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != PROPOSAL_FIELDS:
            raise ValueError(f"{path}: proposal columns differ from the required schema")
        rows = list(reader)
    for line_number, row in enumerate(rows, start=2):
        if row.get(None):
            raise ValueError(f"{path}:{line_number}: unexpected extra columns")
    return rows


def validate_proposal_references(
    path: Path, catalog: OntologyCatalog
) -> dict[str, object]:
    """Fail when a structured identifier is unknown or an asserted parent is obsolete."""
    rows = _read_proposals(path)
    proposal_ids = {row["proposal_id"] for row in rows}
    if len(proposal_ids) != len(rows):
        raise ValueError(f"{path}: duplicate proposal_id")

    recommendation_counts: Counter[str] = Counter()
    ontology_counts: Counter[str] = Counter()
    ontology_reference_mentions = 0
    proposal_reference_mentions = 0
    deprecated_narrative_references: set[str] = set()
    errors: list[str] = []

    for line_number, row in enumerate(rows, start=2):
        recommendation_counts[row["recommendation"]] += 1
        ontology_counts[row["intended_ontology"]] += 1
        if row["recommendation"] == "accept_proposal" and not row[
            "direct_parent_ids"
        ].strip():
            errors.append(
                f"{path}:{line_number}: accept_proposal requires a direct parent"
            )

        for field in _REFERENCE_FIELDS:
            value = row[field]
            for reference in _ONTOLOGY_REFERENCE.findall(value):
                ontology_reference_mentions += 1
                canonical = canonical_curie(reference)
                term = catalog.terms.get(canonical)
                if term is None:
                    errors.append(
                        f"{path}:{line_number}: unknown {field} reference {reference}"
                    )
                elif term.deprecated and field != "other_axioms":
                    errors.append(
                        f"{path}:{line_number}: obsolete {field} reference {reference}"
                    )
                elif term.deprecated:
                    deprecated_narrative_references.add(reference)
            for reference in _PROPOSAL_REFERENCE.findall(value):
                proposal_reference_mentions += 1
                if reference not in proposal_ids:
                    errors.append(
                        f"{path}:{line_number}: unknown provisional reference {reference}"
                    )

    if errors:
        raise ValueError("\n".join(errors))

    accepted = [row for row in rows if row["recommendation"] == "accept_proposal"]
    return {
        "proposal_file": Path(path).as_posix(),
        "total_proposals": len(rows),
        "proposals_with_textual_definition": sum(bool(row["definition"].strip()) for row in rows),
        "proposals_with_definition_evidence": sum(
            bool(row["definition_sources"].strip()) for row in rows
        ),
        "accepted_class_proposals": len(accepted),
        "accepted_class_proposals_with_definition": sum(
            bool(row["definition"].strip()) for row in accepted
        ),
        "accepted_class_proposals_with_definition_evidence": sum(
            bool(row["definition_sources"].strip()) for row in accepted
        ),
        "intended_ontologies": dict(sorted(ontology_counts.items())),
        "recommendations": dict(sorted(recommendation_counts.items())),
        "ontology_reference_mentions": ontology_reference_mentions,
        "provisional_reference_mentions": proposal_reference_mentions,
        "deprecated_narrative_references": sorted(deprecated_narrative_references),
        "unknown_references": 0,
        "obsolete_asserted_parents_or_parts": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "proposals",
        type=Path,
        nargs="?",
        default=Path("curation/botanical_concept_proposals.tsv"),
    )
    parser.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--flopo-owl", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--flopo-registry", type=Path)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()

    catalog = load_catalog_from_ontology_files(
        args.po_obo, args.pato_obo, args.flopo_owl, args.flopo_registry
    )
    summary = validate_proposal_references(args.proposals, catalog)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
