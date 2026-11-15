"""Apply the second round of the second-model review (curation/opus-review-2026-11-15/).

- combinations.tsv: part-quality pairs that kept statements in review. "allowed" and "blocked"
  verdicts of high or medium confidence become rows of config/valid_combinations.tsv; a pair the
  table has already is left as it is.

    python -m tools.apply_review_round2 [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

REVIEW = Path("curation/opus-review-2026-11-15")
COMBINATIONS = Path("config/valid_combinations.tsv")
SOURCE = "second_model_review_2026-11-15"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with COMBINATIONS.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = reader.fieldnames
        have = {(row["po_id"], row["pato_id"]) for row in reader}
    new, stats, statements = [], Counter(), Counter()
    with (REVIEW / "combinations.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            key = (row["po_id"].replace(":", "_"), row["pato_id"].replace(":", "_"))
            verdict = row["decision"]
            if verdict not in ("allowed", "blocked") or row["confidence"] == "low" or key in have or not row.get("statements"):
                stats[f"left: {verdict}" + (" (low confidence)" if row["confidence"] == "low" else "")] += 1
                continue
            have.add(key)
            stats[verdict] += 1
            statements[verdict] += int(row["statements"])
            new.append({"po_id": key[0], "pato_id": key[1], "status": verdict, "source": SOURCE,
                        "example_label": f"{row['part']} {row['quality']}: {row['reason'][:160]}".replace("\t", " ")})
    for key in sorted(stats):
        print(f"{stats[key]:6d}  {key}")
    print(dict(statements), "statements in review with these pairs")
    if not args.dry_run and new:
        with COMBINATIONS.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n").writerows(new)


if __name__ == "__main__":
    main()
