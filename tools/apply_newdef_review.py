"""Apply the review of the classes added on 2026-11-14 (queue ``newdefs`` of the second round).

For a FLOPO flora value (config/flopo_flora_value_terms.tsv) and for a FLOPO anatomy class
(curation/flopo_anatomy_support_classes_20260918.tsv):

- a reworded definition replaces the old one;
- a corrected parent replaces the old one when it is a live class;
- a synonym or rule word that the review says does not fit (quoted in a sentence that says so)
  becomes a related synonym and stops being a rule word.

    python -m tools.apply_newdef_review [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from flopo2.saudi.vocab import parse_obo

REVIEW = Path("curation/opus-review-2026-11-15")
VALUES = Path("config/flopo_flora_value_terms.tsv")
ANATOMY = Path("curation/flopo_anatomy_support_classes_20260918.tsv")
REGISTRY = Path("config/flopo_anatomy_support_id_registry.tsv")
NOTE = "2026-11-15: {what} after the review of the new classes (Claude Opus; checked, AI review, Claude Fable 5.2)."
_UNFIT = re.compile(
    r"does not fit|do not fit|not an exact|too broad|too wide|misspelling|remove|move |clash|should be a (?:related|narrow)|"
    r"should not|at most related|make .{0,40}related|narrower",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"'([^']{2,60})'")


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames), list(reader)


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def unfit_names(reason: str, names: set[str]) -> list[str]:
    out = []
    for sentence in re.split(r"(?<=[.;])\s+", reason):
        if _UNFIT.search(sentence):
            out += [q for q in _QUOTED.findall(sentence) if q in names and re.search(
                r"keep\s+'" + re.escape(q) + "'", sentence, re.IGNORECASE) is None]
    return list(dict.fromkeys(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    pato = parse_obo(Path("ont/quality.obo"))
    po = parse_obo(Path("ont/plant_ontology.obo"))
    value_fields, values = _rows(VALUES)
    anatomy_fields, anatomy = _rows(ANATOMY)
    ids = {row["flopo_id"]: row["proposal_key"] for row in _rows(REGISTRY)[1]}
    by_value = {row["flopo_id"]: row for row in values}
    by_part = {row["proposal_key"]: row for row in anatomy}
    answers: dict[str, dict] = {}
    for path in sorted((REVIEW / "batches" / "newdefs").glob("*.answer.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            answers[str(item.get("flopo_id", "")).replace("_", ":")] = item
    stats = {"definition": 0, "parent": 0, "synonym": 0}
    for flopo_id, answer in answers.items():
        if answer.get("decision") == "keep" or str(answer.get("confidence")) == "low":
            continue
        what: list[str] = []
        definition = re.sub(r"\s+", " ", str(answer.get("definition") or "")).strip()
        parent = (re.search(r"(?:PATO|FLOPO|PO)[_:]\d{7}", str(answer.get("parent") or "")) or [""])[0].replace("_", ":")
        reason = str(answer.get("reason") or "")
        if flopo_id in by_value:
            row = by_value[flopo_id]
            if parent and parent != row["parent"] and parent != flopo_id and (parent in pato or parent in by_value):
                what.append(f"parent {row['parent']} -> {parent}")
                row["parent"] = parent
                stats["parent"] += 1
            if definition and definition != row["definition"] and re.match(r"An? ", definition) and "inhering in" in definition:
                row["definition"] = definition
                what.append("definition reworded")
                stats["definition"] += 1
            names = {n for f in ("exact_synonyms", "rule_words") for n in row[f].split("|") if n}
            for name in unfit_names(reason, names):
                for field in ("exact_synonyms", "rule_words"):
                    row[field] = "|".join(n for n in row[field].split("|") if n and n != name)
                row["related_synonyms"] = "|".join(dict.fromkeys([*filter(None, row["related_synonyms"].split("|")), name]))
                what.append(f"'{name}' is a related synonym")
                stats["synonym"] += 1
            if what:
                row["review_note"] = (row.get("review_note", "") + " " + NOTE.format(what="; ".join(what))).strip()
        elif ids.get(flopo_id.replace(":", "_")) in by_part:
            row = by_part[ids[flopo_id.replace(":", "_")]]
            new_parent = parent.replace(":", "_")
            live = new_parent.startswith("PO_") and new_parent.replace("_", ":") in po or new_parent in ids
            if new_parent and new_parent != row["is_a"] and new_parent != flopo_id.replace(":", "_") and live:
                what.append(f"is_a {row['is_a']} -> {new_parent}")
                row["is_a"] = ids.get(new_parent, new_parent) if new_parent in ids else new_parent
                stats["parent"] += 1
            if definition and definition != row["definition"] and re.match(r"An? ", definition):
                row["definition"] = definition
                what.append("definition reworded")
                stats["definition"] += 1
            names = set(filter(None, row["exact_synonyms_en"].split("|")))
            for name in unfit_names(reason, names):
                row["exact_synonyms_en"] = "|".join(n for n in row["exact_synonyms_en"].split("|") if n and n != name)
                row["related_synonyms_en"] = "|".join(dict.fromkeys([*filter(None, row["related_synonyms_en"].split("|")), name]))
                what.append(f"'{name}' is a related synonym")
                stats["synonym"] += 1
            if what:
                row["note"] = (row.get("note", "") + " " + NOTE.format(what="; ".join(what))).strip()
        if what and args.dry_run:
            print(flopo_id, answer.get("label", ""), "|", "; ".join(what))
    print(stats)
    if not args.dry_run:
        _write(VALUES, value_fields, values)
        _write(ANATOMY, anatomy_fields, anatomy)


if __name__ == "__main__":
    main()
