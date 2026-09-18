"""Record curator-approved PO–PATO review rows and promote them to the whitelist."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


BEARER_ID = re.compile(r"^(?:PO|FLOPO)_\d+$")
PATO_ID = re.compile(r"^PATO_\d+$")
COMBINATION_FIELDS = ("po_id", "pato_id", "status", "source", "example_label")


def _read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"TSV has no header: {path}")
        return list(reader.fieldnames), list(reader)


def _write_tsv(path: Path, fields: list[str] | tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def approve_review(
    review_path: Path,
    combinations_path: Path,
    approved_review_path: Path,
    reviewer: str,
    review_date: str,
    source: str,
    note: str = "",
) -> dict[str, Any]:
    """Approve every row in a reviewed sheet and idempotently extend the combination registry."""

    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", review_date):
        raise ValueError("review_date must be YYYY-MM-DD")
    if not source.strip():
        raise ValueError("curation source is required")

    review_fields, reviews = _read_tsv(review_path)
    required = {"po_id", "pato_id", "proposed_label", "review_status", "reviewer", "review_date", "review_notes"}
    missing = required - set(review_fields)
    if missing:
        raise ValueError(f"review sheet is missing columns: {', '.join(sorted(missing))}")

    pairs: set[tuple[str, str]] = set()
    approved_rows: list[dict[str, str]] = []
    for row in reviews:
        po_id, pato_id = row.get("po_id", ""), row.get("pato_id", "")
        if not BEARER_ID.fullmatch(po_id) or not PATO_ID.fullmatch(pato_id):
            raise ValueError(f"invalid reviewed pair: {po_id!r}, {pato_id!r}")
        pair = (po_id, pato_id)
        if pair in pairs:
            raise ValueError(f"duplicate reviewed pair: {po_id}, {pato_id}")
        pairs.add(pair)
        out = dict(row)
        out["review_status"] = "approved"
        out["reviewer"] = reviewer
        out["review_date"] = review_date
        existing_note = (out.get("review_notes") or "").strip()
        out["review_notes"] = "; ".join(value for value in (existing_note, note.strip()) if value)
        approved_rows.append(out)

    combo_fields, combo_rows = _read_tsv(combinations_path)
    if tuple(combo_fields) != COMBINATION_FIELDS:
        raise ValueError("unexpected valid-combinations header")
    combinations = {(row["po_id"], row["pato_id"]): dict(row) for row in combo_rows}
    added = 0
    already_allowed = 0
    for row in approved_rows:
        pair = (row["po_id"], row["pato_id"])
        existing = combinations.get(pair)
        if existing and existing.get("status") != "allowed":
            raise ValueError(
                f"approved pair conflicts with {existing.get('status')}: {pair[0]}, {pair[1]}"
            )
        if existing:
            already_allowed += 1
            continue
        combinations[pair] = {
            "po_id": pair[0],
            "pato_id": pair[1],
            "status": "allowed",
            "source": source,
            "example_label": row.get("proposed_label", ""),
        }
        added += 1

    _write_tsv(approved_review_path, review_fields, approved_rows)
    sorted_combinations = [combinations[pair] for pair in sorted(combinations)]
    _write_tsv(combinations_path, COMBINATION_FIELDS, sorted_combinations)
    return {
        "approved": len(approved_rows),
        "added": added,
        "already_allowed": already_allowed,
        "approved_review": str(approved_review_path),
        "combinations": str(combinations_path),
        "combination_count": len(sorted_combinations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path)
    parser.add_argument("--combinations", type=Path, default=Path("config/valid_combinations.tsv"))
    parser.add_argument("--approved-review", type=Path, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--review-date", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    print(
        json.dumps(
            approve_review(
                args.review,
                args.combinations,
                args.approved_review,
                args.reviewer,
                args.review_date,
                args.source,
                args.note,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
