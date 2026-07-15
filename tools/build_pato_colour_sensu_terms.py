#!/usr/bin/env python3
"""Build the curator-approved PATO botanical colour sensu OBO term module."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path


FIELDS = ("proposal_key", "pato_id", "status")
DEFERRED_STATUS = "deferred_optional_closed_union"
CONTRIBUTOR = "https://orcid.org/0000-0001-8149-5890"
NEW_TERM_TIMESTAMP = "T00:00:00Z"


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
        raise ValueError("a PATO definition needs at least one source xref")
    return xrefs


def _synonyms(row: dict[str, str]) -> list[str]:
    if row["class_role"] != "lexical_umbrella":
        return []
    label = row["preferred_label"].casefold()
    synonyms = [
        surface.strip()
        for surface in row["surface_family"].split("|")
        if surface.strip() and surface.strip().casefold() != label
    ]
    # Preserve both spellings when the preferred generic label uses British English.
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


def build_terms(
    proposals_path: Path,
    ids_path: Path,
    evidence_path: Path,
    release_date: str,
) -> tuple[str, list[dict[str, str]]]:
    proposals, proposals_by_key = _rows(proposals_path, "proposal_key")
    ids, ids_by_key = _rows(ids_path, "proposal_key")
    _evidence_rows, evidence = _rows(evidence_path, "evidence_id")
    if tuple(ids[0].keys()) != FIELDS:
        raise ValueError(f"unexpected ID registry fields: {tuple(ids[0].keys())}")
    if set(proposals_by_key) != set(ids_by_key):
        raise ValueError("proposal and PATO ID registry keys differ")

    active_ids = [row["pato_id"] for row in ids if row["status"] != DEFERRED_STATUS]
    if any(not pato_id for pato_id in active_ids) or len(active_ids) != len(set(active_ids)):
        raise ValueError("active PATO IDs must be present and unique")
    new_ids = sorted(
        int(row["pato_id"].split(":", 1)[1])
        for row in ids
        if row["status"] == "new_approved"
    )
    if new_ids != list(range(104312, 104346)):
        raise ValueError("new colour IDs must occupy Robert's contiguous 0104312-0104345 block")

    labels = {
        key: proposal["preferred_label"] for key, proposal in proposals_by_key.items()
    }
    labels["PATO:0000014"] = "color"
    blocks: list[str] = []
    rendered_rows: list[dict[str, str]] = []
    for proposal in proposals:
        key = proposal["proposal_key"]
        assignment = ids_by_key[key]
        if assignment["status"] == DEFERRED_STATUS:
            if proposal["class_role"] != "closed_union_view" or assignment["pato_id"]:
                raise ValueError("only the optional closed-union view may be deferred")
            continue

        pato_id = assignment["pato_id"]
        parent_key = proposal["asserted_parent"]
        parent_id = (
            parent_key
            if parent_key.startswith("PATO:")
            else ids_by_key[parent_key]["pato_id"]
        )
        if not parent_id:
            raise ValueError(f"unresolved parent for {key}")
        parent_label = labels[parent_key]
        xrefs = _definition_xrefs(proposal["definition_sources"], evidence)
        lines = [
            "[Term]",
            f"id: {pato_id}",
            f"name: {proposal['preferred_label']}",
            (
                f'def: "{_escape(proposal["definition_or_recognition_rule"])}" '
                f"[{', '.join(xrefs)}]"
            ),
        ]
        comment_parts = [proposal["annotation_policy"]]
        if key == "COLOR:cream":
            comment_parts.append(
                "PATO:0104031 retains the narrower RHS fifth-edition sense."
            )
        elif key == "COLOR:olive":
            comment_parts.append(
                "Saccardo and Ridgway distinguish multiple olive and olive-green "
                "standards, so this umbrella is not classified under a core hue."
            )
        elif key == "COLOR:rose":
            comment_parts.append(
                "This evidence-backed open umbrella replaces the former unsupported "
                "red-plus-yellow definition of PATO:0001425."
            )
        elif key == "COLOR:cream_rhs_5":
            comment_parts.append(
                "The physical RHS chips are normative; unqualified cream or creamy "
                "annotations should use PATO:0104312."
            )
        elif proposal["caveat"]:
            comment_parts.append(proposal["caveat"])
        if key == "COLOR:cream_rhs_5":
            comment_parts.append(
                "Requested for FLOPO; corresponding temporary classes: "
                "FLOPO_0980084 (creamy) and FLOPO_0980114 (cream)."
            )
        lines.append(f"comment: {' '.join(comment_parts)}")
        lines.append("subset: value_slim")
        for synonym in _synonyms(proposal):
            lines.append(f'synonym: "{_escape(synonym)}" EXACT []')
        lines.append(f"is_a: {parent_id} ! {parent_label}")
        lines.append(
            "property_value: http://purl.org/dc/terms/contributor " + CONTRIBUTOR
        )
        if assignment["status"] == "new_approved":
            lines.append(f"creation_date: {release_date}{NEW_TERM_TIMESTAMP}")
        elif key == "COLOR:cream_rhs_5":
            lines.append("creation_date: 2026-07-11T18:39:19Z")
        blocks.append("\n".join(lines))
        rendered_rows.append(
            {
                **proposal,
                "pato_id": pato_id,
                "parent_id": parent_id,
                "status": assignment["status"],
            }
        )

    return "\n\n".join(blocks) + "\n", rendered_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proposals",
        type=Path,
        default=Path("curation/botanical_colour_sensu_proposals.tsv"),
    )
    parser.add_argument(
        "--ids",
        type=Path,
        default=Path("config/pato_colour_sensu_id_registry.tsv"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("curation/botanical_evidence.tsv"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("curation/pato_botanical_colour_sensu_terms.obo"),
    )
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    rendered, rows = build_terms(args.proposals, args.ids, args.evidence, args.date)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {len(rows)} approved PATO colour terms to {args.out}")


if __name__ == "__main__":
    main()
