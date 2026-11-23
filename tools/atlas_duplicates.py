#!/usr/bin/env python3
"""Descriptions that the atlas holds twice, and how far their two extractions agree.

Aggregators republish floras: World Flora Online carries the descriptions of Flora of China, of
the Kew and Meise floras and others; the POWO floras overlap with each other. Each copy was read
by the model on its own, so one description gave two sets of statements and the taxon showed
every trait twice.

A description is a **copy** when at least ``--share`` of its sentences (40 characters or more,
compared without case, spaces and punctuation) are sentences of one description of another
source. Of two copies the atlas keeps one (``primary``): an aggregator loses against a flora, and
otherwise the source with more descriptions wins.

    python -m tools.atlas_duplicates            # writes the list and the agreement report

Outputs (under ``local-corpora/saudi-flora/``):

* ``duplicates.tsv``: one line per copy that the atlas build leaves out
  (``flopo2.saudi.build`` reads it), with the description that is kept;
* ``duplicate-agreement.tsv``: per pair of sources, the statements both extractions give and
  those only one gives; ``duplicate-disagreements.tsv``: the statements only one gives, by class,
  for debugging the extraction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("local-corpora/saudi-flora")
AGGREGATORS = ["powo-ftea", "powo-kew", "eflora-other", "wfo"]  # later = loses against all before
_SPLIT = re.compile(r"(?<=[.;])\s+")
_NORM = re.compile(r"[^a-z0-9]+")


def sentences(text: str) -> set[int]:
    found = set()
    for part in _SPLIT.split(text or ""):
        plain = _NORM.sub("", part.lower())
        if len(plain) >= 40:
            found.add(int.from_bytes(hashlib.blake2b(plain.encode(), digest_size=8).digest(), "big"))
    return found


def text_key(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def corpora() -> dict[str, Path]:
    """The annotated corpus of every atlas source. A source whose full run is unfinished (WFO) is
    read as far as it has come: the atlas shows an older snapshot of it, but the copies have to
    be known before the full source arrives."""

    from flopo2.saudi import build

    return {name: cfg["corpus"] for name, cfg in build.SOURCES.items() if cfg["corpus"].exists()}


def _slim(record: dict) -> list[tuple]:
    """What the comparison needs of a record (whole records of 60,000 descriptions do not fit in memory)."""

    kept = []
    for a in record.get("assertions") or []:
        if a.get("phenotype_class_iri"):
            comp = a.get("composition") or {}
            kept.append((a["phenotype_class_iri"], (a.get("gate") or {}).get("status") == "accepted",
                         comp.get("entity_label", ""), comp.get("quality_label", ""), a.get("po_id", ""), a.get("pato_id", "")))
    return kept


def _statements(record: list[tuple], accepted: bool) -> dict[str, tuple]:
    return {row[0]: row for row in record if not accepted or row[1]}


def find(share: float = 0.9, minimum: int = 3) -> tuple[list[dict], dict, list[dict]]:
    from flopo2.verify.apply_bryophyte_terms import misfiled

    files = corpora()
    index: dict[int, list[tuple[str, int]]] = defaultdict(list)  # sentence -> (source, record no.)
    meta: dict[tuple[str, int], tuple] = {}
    size = Counter()
    for source, path in files.items():
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle):
                record = json.loads(line)
                if record.get("language") == "ar" or misfiled(source, record):
                    continue
                size[source] += 1
                found = sentences(record.get("text", ""))
                if len(found) < minimum:
                    continue
                meta[(source, number)] = (len(found), record.get("source_id", ""), text_key(record.get("text", "")),
                                          record.get("taxon", ""))
                for sentence in found:
                    index[sentence].append((source, number))
    rank = {s: (AGGREGATORS.index(s) + 1 if s in AGGREGATORS else 0, -size[s], s) for s in files}
    shared: dict[tuple[str, int], Counter] = defaultdict(Counter)
    for holders in index.values():
        if len({s for s, _ in holders}) < 2 or len(holders) > 50:  # a stock sentence says nothing
            continue
        for one in holders:
            for other in holders:
                if one[0] != other[0]:
                    shared[one][other] += 1
    copies: dict[tuple[str, int], tuple[str, int]] = {}
    for record, others in shared.items():
        best = None
        for other, count in others.items():
            if count >= share * meta[record][0] and rank[other[0]] < rank[record[0]]:
                if best is None or (rank[other[0]], -count) < (rank[best[0]], -others[best]):
                    best = other
        if best is not None:
            copies[record] = best
    # a copy of a copy points to the description that is kept
    for record in list(copies):
        seen = {record}
        while copies[record] in copies and copies[copies[record]] not in seen:
            seen.add(copies[record])
            copies[record] = copies[copies[record]]
    wanted = set(copies) | set(copies.values())
    records: dict[tuple[str, int], list] = {}
    for source, path in files.items():
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle):
                if (source, number) in wanted:
                    records[(source, number)] = _slim(json.loads(line))
    rows, agreement, disagreements = [], defaultdict(Counter), Counter()
    for copy, primary in sorted(copies.items()):
        a, b = records[copy], records[primary]
        rows.append({
            "source": copy[0], "source_id": meta[copy][1], "text_key": meta[copy][2], "taxon": meta[copy][3],
            "primary_source": primary[0], "primary_source_id": meta[primary][1], "primary_text_key": meta[primary][2],
            "primary_taxon": meta[primary][3], "sentences": meta[copy][0], "shared": shared[copy][primary],
        })
        pair = agreement[(copy[0], primary[0])]
        pair["descriptions"] += 1
        for name, accepted in (("all", False), ("accepted", True)):
            A, B = _statements(a, accepted), _statements(b, accepted)
            pair[f"{name}_both"] += len(A.keys() & B.keys())
            pair[f"{name}_copy_only"] += len(A.keys() - B.keys())
            pair[f"{name}_primary_only"] += len(B.keys() - A.keys())
            if accepted:
                for side, only in (("copy", A.keys() - B.keys()), ("primary", B.keys() - A.keys())):
                    for cls in only:
                        s = (A if side == "copy" else B)[cls]
                        disagreements[s[2:6]] += 1
    worst = [
        {"entity": k[0], "quality": k[1], "po_id": k[2], "pato_id": k[3], "only_in_one_extraction": n}
        for k, n in disagreements.most_common(2000)
    ]
    return rows, agreement, worst


def write(rows: list[dict], agreement: dict, worst: list[dict], out: Path = OUT) -> None:
    def table(name: str, data: list[dict]) -> None:
        with (out / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(data[0]) if data else ["empty"], delimiter="\t",
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)

    table("duplicates.tsv", rows)
    lines = []
    for (copy, primary), c in sorted(agreement.items(), key=lambda item: -item[1]["descriptions"]):
        both, one = c["accepted_both"], c["accepted_copy_only"] + c["accepted_primary_only"]
        lines.append({
            "copy": copy, "kept": primary, "descriptions": c["descriptions"], "accepted_in_both": both,
            "only_in_copy": c["accepted_copy_only"], "only_in_kept": c["accepted_primary_only"],
            "agreement_percent": round(100 * both / (both + one), 1) if both + one else "",
        })
    table("duplicate-agreement.tsv", lines)
    table("duplicate-disagreements.tsv", worst)


def load(path: Path = OUT / "duplicates.tsv") -> dict[tuple[str, str, str], tuple[str, str]]:
    """``{(source, source_id, text_key): (primary source, primary source_id)}``; empty without the file."""

    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return {
            (r["source"], r["source_id"], r["text_key"]): (r["primary_source"], r["primary_source_id"])
            for r in csv.DictReader(handle, delimiter="\t")
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--share", type=float, default=0.9)
    args = parser.parse_args()
    rows, agreement, worst = find(args.share)
    write(rows, agreement, worst)
    both = sum(c["accepted_both"] for c in agreement.values())
    one = sum(c["accepted_copy_only"] + c["accepted_primary_only"] for c in agreement.values())
    print(json.dumps({"copies": len(rows), "by_source": dict(Counter(r["source"] for r in rows)),
                      "accepted_in_both": both, "only_in_one": one,
                      "agreement_percent": round(100 * both / max(1, both + one), 1)}))


if __name__ == "__main__":
    main()
