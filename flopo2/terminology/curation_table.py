"""Build a complete curator table from deterministic mappings and evidence proposals."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from flopo2.terminology.normalize import fold


PROPOSAL_FIELDS = (
    "proposal_id",
    "surface_forms",
    "corpus_frequency",
    "intended_ontology",
    "recommendation",
    "preferred_label",
    "definition",
    "definition_sources",
    "direct_parent_ids",
    "part_of_ids",
    "other_axioms",
    "evidence_status",
    "current_ontology_status",
    "counterexample_or_caveat",
    "curator_decision",
    "curator_notes",
)

CURATION_FIELDS = (
    "surface_form",
    "corpus_frequency",
    "semantic_roles",
    "exact_target_ids",
    "exact_target_labels",
    "scoped_target_ids",
    "scoped_target_labels",
    "scoped_relations",
    "existing_target_ids",
    "existing_relations",
    "existing_review_statuses",
    "mapping_recommendation",
    "mapping_findings",
    "mapping_next_action",
    "proposal_id",
    "surface_forms",
    "proposal_corpus_frequency",
    *PROPOSAL_FIELDS[3:],
)

_ONTOLOGIES = {"PO", "PATO", "FLOPO", "NONE"}
_RECOMMENDATIONS = {
    "accept_proposal",
    "blocked_by_dependency",
    "contextual_composition",
    "definition_required",
    "map_existing",
    "modeling_pattern",
    "new_compositional_phenotype",
    "new_local_entity_and_phenotype_branch",
    "reject_current_proposal",
    "reject_as_noise",
    "revise_and_sense_split",
    "revise_and_split",
    "revise_existing",
    "revise_proposal",
    "sense_split",
}
_DEFINITION_OPTIONAL = {
    "blocked_by_dependency",
    "map_existing",
    "reject_current_proposal",
    "reject_as_noise",
    "sense_split",
}


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _evidence_ids(path: Path) -> set[str]:
    rows = _read_tsv(path)
    ids = {row.get("evidence_id", "") for row in rows}
    if "" in ids:
        raise ValueError(f"{path}: empty evidence_id")
    if len(ids) != len(rows):
        raise ValueError(f"{path}: duplicate evidence_id")
    return ids


def _proposal_index(
    path: Path, evidence_manifest: Path
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    evidence_ids = _evidence_ids(evidence_manifest)
    rows = _read_tsv(path)
    aliases: dict[str, dict[str, str]] = {}
    proposal_ids: set[str] = set()

    for line_number, row in enumerate(rows, start=2):
        extra_values = row.get(None)
        if extra_values:
            raise ValueError(
                f"{path}:{line_number}: unexpected extra columns {extra_values!r}"
            )
        missing = [field for field in PROPOSAL_FIELDS if field not in row]
        if missing:
            raise ValueError(f"{path}:{line_number}: missing columns {', '.join(missing)}")
        proposal_id = row["proposal_id"].strip()
        if not proposal_id or proposal_id in proposal_ids:
            raise ValueError(f"{path}:{line_number}: empty or duplicate proposal_id {proposal_id!r}")
        proposal_ids.add(proposal_id)
        if row["intended_ontology"] not in _ONTOLOGIES:
            raise ValueError(f"{path}:{line_number}: invalid intended_ontology")
        if row["recommendation"] not in _RECOMMENDATIONS:
            raise ValueError(f"{path}:{line_number}: invalid recommendation")
        if row["recommendation"] not in _DEFINITION_OPTIONAL and not row["definition"].strip():
            raise ValueError(f"{path}:{line_number}: definition required for proposal")
        if row["recommendation"] == "accept_proposal" and not row[
            "definition_sources"
        ].strip():
            raise ValueError(
                f"{path}:{line_number}: accept_proposal requires definition evidence"
            )
        if row["curator_decision"].strip() or row["curator_notes"].strip():
            raise ValueError(
                f"{path}:{line_number}: machine proposal must leave curator fields blank"
            )
        unknown_evidence = {
            value
            for value in row["definition_sources"].split("|")
            if value and value not in evidence_ids
        }
        if unknown_evidence:
            raise ValueError(
                f"{path}:{line_number}: unknown evidence IDs {sorted(unknown_evidence)}"
            )
        for value in row["surface_forms"].split("|"):
            alias = fold(value)
            if not alias:
                continue
            if alias in aliases:
                if aliases[alias]["proposal_id"] == proposal_id:
                    continue
                raise ValueError(
                    f"{path}:{line_number}: surface alias {alias!r} belongs to both "
                    f"{aliases[alias]['proposal_id']} and {proposal_id}"
                )
            aliases[alias] = row
    return aliases, rows


def build_curation_table(
    mapping_report: Path,
    proposals_path: Path,
    evidence_manifest: Path,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Join evidence-backed proposals onto every row of a deterministic mapping report."""
    mapping_rows = _read_tsv(mapping_report)
    aliases, proposals = _proposal_index(proposals_path, evidence_manifest)
    output: list[dict[str, str]] = []
    seen_surfaces: set[str] = set()
    linked_proposals: set[str] = set()
    proposal_recommendations = Counter()

    for source in mapping_rows:
        surface = fold(source.get("surface_form", ""))
        if not surface or surface in seen_surfaces:
            raise ValueError(f"{mapping_report}: empty or duplicate surface {surface!r}")
        seen_surfaces.add(surface)
        proposal = aliases.get(surface)
        row = {
            "surface_form": surface,
            "corpus_frequency": source.get("corpus_frequency", ""),
            "semantic_roles": source.get("semantic_roles", ""),
            "exact_target_ids": source.get("exact_target_ids", ""),
            "exact_target_labels": source.get("exact_target_labels", ""),
            "scoped_target_ids": source.get("scoped_target_ids", ""),
            "scoped_target_labels": source.get("scoped_target_labels", ""),
            "scoped_relations": source.get("scoped_relations", ""),
            "existing_target_ids": source.get("existing_target_ids", ""),
            "existing_relations": source.get("existing_relations", ""),
            "existing_review_statuses": source.get("existing_review_statuses", ""),
            "mapping_recommendation": source.get("recommendation", ""),
            "mapping_findings": source.get("validation_findings", ""),
            "mapping_next_action": source.get("next_action", ""),
        }
        if proposal:
            row.update(
                {
                    field: proposal.get(field, "")
                    for field in PROPOSAL_FIELDS
                    if field != "corpus_frequency"
                }
            )
            row["proposal_corpus_frequency"] = proposal.get("corpus_frequency", "")
            linked_proposals.add(proposal["proposal_id"])
            proposal_recommendations[proposal["recommendation"]] += 1
        else:
            row.update(
                {field: "" for field in PROPOSAL_FIELDS if field != "corpus_frequency"}
            )
            row["proposal_corpus_frequency"] = ""
            row["recommendation"] = (
                "mapping_candidate_review"
                if source.get("recommendation") != "no_lexical_candidate"
                else "evidence_review_pending"
            )
            proposal_recommendations[row["recommendation"]] += 1
        output.append(row)

    output.sort(key=lambda row: (-int(row["corpus_frequency"] or 0), row["surface_form"]))
    all_proposal_ids = {row["proposal_id"] for row in proposals}
    summary: dict[str, object] = {
        "total_surfaces": len(output),
        "total_missing_mentions": sum(int(row["corpus_frequency"] or 0) for row in output),
        "evidence_enriched_surfaces": sum(bool(row["proposal_id"]) for row in output),
        "evidence_enriched_mentions": sum(
            int(row["corpus_frequency"] or 0) for row in output if row["proposal_id"]
        ),
        "pending_surfaces": sum(not row["proposal_id"] for row in output),
        "pending_mentions": sum(
            int(row["corpus_frequency"] or 0) for row in output if not row["proposal_id"]
        ),
        "recommendations": dict(sorted(proposal_recommendations.items())),
        "linked_proposals": len(linked_proposals),
        "unlinked_proposal_ids": sorted(all_proposal_ids - linked_proposals),
        "policy": {
            "curator_decision_default": "blank",
            "automatic_acceptance": False,
            "unlinked_proposals": (
                "retained because a glossary or ontology need can be valid even when its preferred "
                "surface is absent from the frozen Saudi missing-surface set"
            ),
        },
    }
    return output, summary


def write_curation_table(path: Path, rows: list[dict[str, str]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CURATION_FIELDS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-report", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()

    rows, summary = build_curation_table(
        args.mapping_report, args.proposals, args.evidence_manifest
    )
    write_curation_table(args.out, rows)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
