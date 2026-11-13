#!/usr/bin/env python3
"""List the pairs of qualities that floras state as alternatives ("X or Y") although they share
no attribute, and that are not yet reviewed in config/flora_union_pairs.tsv.

    python -m tools.list_union_pair_candidates                  # every flora with dispositions
    python -m tools.list_union_pair_candidates eflora-fop -o curation/candidates/union_pairs.tsv

Such rows are left unresolved with the reason ``alternatives_across_attributes_unreviewed:A|B``
(docs/odp/07-alternatives.md). A reviewer copies a pair into the table with ``accept`` or
``reject``; the next annotation of the flora then uses, or skips, the secondary union pattern.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

REASON = "alternatives_across_attributes_unreviewed:"


def labels() -> dict[str, str]:
    out: dict[str, str] = {}
    with Path("config/pato_lexicon.tsv").open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) > 1 and row[0].startswith("PATO"):
                out.setdefault(row[0].replace(":", "_"), row[1])
    with Path("config/flopo_id_registry.tsv").open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) > 2 and "FLOPO_" in row[0]:
                out["FLOPO_" + row[0].rsplit("_", 1)[-1]] = row[2]
    return out


def collect(sources: list[str]) -> list[dict]:
    csv.field_size_limit(sys.maxsize)
    counts: Counter = Counter()
    floras: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, Counter] = defaultdict(Counter)
    for source in sources:
        path = Path("local-corpora") / source / "derived" / f"{source}-dispositions.tsv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row.get("reason", "").startswith(REASON):
                    pair = row["reason"][len(REASON):]
                    counts[pair] += 1
                    floras[pair].add(source)
                    examples[pair][row.get("source_en", "")[:80]] += 1
    names = labels()
    rows = []
    for pair, count in counts.most_common():
        first, second = pair.split("|")
        rows.append({"value_a": first, "value_b": second, "label_a": names.get(first, ""), "label_b": names.get(second, ""),
                     "decision": "", "example": examples[pair].most_common(1)[0][0], "note": "",
                     "reviewed": "", "rows": count, "floras": len(floras[pair])})
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="*")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)
    sources = args.sources or sorted(p.name for p in Path("local-corpora").iterdir() if (p / "derived").is_dir())
    rows = collect(sources)
    fields = ["value_a", "value_b", "label_a", "label_b", "decision", "example", "note", "reviewed", "rows", "floras"]
    handle = args.output.open("w", encoding="utf-8", newline="") if args.output else sys.stdout
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    if args.output:
        handle.close()
        print(f"{len(rows)} unreviewed pairs, {sum(r['rows'] for r in rows)} rows -> {args.output}")


if __name__ == "__main__":
    main()
