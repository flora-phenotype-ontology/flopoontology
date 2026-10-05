#!/usr/bin/env python3
"""Carry ``config/valid_combinations.tsv`` over to the ISCC-NBS colour backbone.

The validity table keys entity-quality pairs by their exact quality identifier.  The colour
backbone (``tools/build_flopo_colour_backbone.py``) re-points FLOPO colour phenotypes from a PATO
or superseded FLOPO colour to its canonical backbone class, so every allowed ``(entity, colour)``
row whose colour has a different canonical reading in ``config/colour_backbone_crosswalk.tsv``
gets a companion ``(entity, canonical colour)`` row.  Existing rows are never changed or removed,
and blocked pairs are never translated.  Running the tool again adds nothing.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMBINATIONS = Path("config/valid_combinations.tsv")
CROSSWALK = Path("config/colour_backbone_crosswalk.tsv")
SOURCE = "colour_backbone_2026-10-05"
FIELDS = ("po_id", "pato_id", "status", "source", "example_label")


def _crosswalk(path: Path) -> dict[str, tuple[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    canonical: dict[str, tuple[str, str]] = {}
    for row in csv.DictReader(lines, delimiter="\t"):
        if row["canonical_id"] and row["canonical_id"] != row["source_id"]:
            canonical[row["source_id"]] = (row["canonical_id"], row["source_label"])
    return canonical


def translate(rows: list[dict[str, str]], canonical: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    present = {(row["po_id"], row["pato_id"]) for row in rows}
    blocked = {(row["po_id"], row["pato_id"]) for row in rows if row["status"] == "blocked"}
    added: list[dict[str, str]] = []
    for row in rows:
        if row["status"] != "allowed" or row["pato_id"] not in canonical:
            continue
        target, colour_label = canonical[row["pato_id"]]
        key = (row["po_id"], target)
        if key in present or key in blocked:
            continue
        present.add(key)
        added.append(
            {
                "po_id": row["po_id"],
                "pato_id": target,
                "status": "allowed",
                "source": SOURCE,
                "example_label": f"{row['example_label']} (backbone reading of {colour_label}, {row['pato_id']})",
            }
        )
    return added


def update(root: Path = ROOT) -> int:
    path = root / COMBINATIONS
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    added = translate(rows, _crosswalk(root / CROSSWALK))
    if added:
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writerows(sorted(added, key=lambda r: (r["po_id"], r["pato_id"])))
    return len(added)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(f"added {update()} colour backbone combinations to {COMBINATIONS}")


if __name__ == "__main__":
    main()
