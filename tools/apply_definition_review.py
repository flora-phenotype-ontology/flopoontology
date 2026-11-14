"""Apply the second-model review of the FLOPO flora value definitions.

Reads the answers of the ``definitions`` queue (tools/llm_candidate_review.py) and changes
``config/flopo_flora_value_terms.tsv``: a rewritten definition replaces the old one, and a
parent that the review corrects (a value placed under 'shape' although PATO has 'serrated')
replaces the old parent when it is a live PATO class or a value of the module. Synonym and
rule changes that the review asks for in words are listed in ``HAND`` after reading each one.

    python -m tools.apply_definition_review [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from flopo2.saudi.vocab import parse_obo

REVIEW = Path("curation/opus-review-2026-11-14")
SPEC = Path("config/flopo_flora_value_terms.tsv")
NOTE = "2026-11-14: {what} after the second-model review of the definitions (Claude Opus; checked, AI review, Claude Fable 5.2)."
# (class, field, name to remove): the name is the label of another class or means something else
DROP = [
    ("FLOPO:0991019", "related_synonyms", "sour"),          # a taste in floras, not an odour
    ("FLOPO:0991023", "exact_synonyms", "stalked leaf"),    # a part with a quality
    ("FLOPO:0991047", "related_synonyms", "papery"),        # exact synonym of PATO papyraceous
    ("FLOPO:0991048", "related_synonyms", "hairy"),         # label of PATO:0000454
    ("FLOPO:0991055", "related_synonyms", "mucronate"),     # label of FLOPO:0991054
    ("FLOPO:0991059", "related_synonyms", "papillary"),     # label of PATO:0002108, another sense
    ("FLOPO:0991060", "related_synonyms", "verrucose"),     # means warty (PATO:0001361)
    ("FLOPO:0991070", "related_synonyms", "discolored"),    # label of PATO:0000331, another sense
    ("FLOPO:0991075", "related_synonyms", "adhesive"),      # PATO:0002331
    ("FLOPO:0991077", "related_synonyms", "obconical"),     # label of PATO:0002347
]
# Two senses under one word: the class keeps the defined sense, and the rule reads the word as
# this class only on these bearers.
CONSTRAIN = {
    "FLOPO:0991194": r"capitul|head|inflorescence",   # radiate: the Asteraceae head
    "FLOPO:0991195": r"capitul|head|inflorescence",   # disciform: the Asteraceae head
    "FLOPO:0991171": r"seed|achene|cypsela|fruit",    # comose: a tuft of hairs
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    pato = parse_obo(Path("ont/quality.obo"))
    with SPEC.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        fields = reader.fieldnames
        rows = list(reader)
    by_id = {row["flopo_id"]: row for row in rows}
    answers: dict[str, dict] = {}
    for path in sorted((REVIEW / "batches" / "definitions").glob("*.answer.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data if isinstance(data, list) else data.get("items", []):
            answers[item["flopo_id"]] = item
    changed = {"definition": 0, "parent": 0, "synonym": 0, "rule": 0}
    for flopo_id, answer in answers.items():
        row = by_id.get(flopo_id)
        if row is None or row.get("status") == "obsolete" or answer.get("decision") == "keep":
            continue
        if str(answer.get("confidence")) == "low":
            continue
        what = []
        parent = str(answer.get("parent") or "").strip().replace("_", ":")
        parent = (re.search(r"(?:PATO|FLOPO):\d{7}", parent) or [""])[0] if parent else ""
        if parent and parent != row["parent"] and parent != flopo_id and (parent in pato or parent in by_id):
            what.append(f"parent {row['parent']} -> {parent}")
            row["parent"] = parent
            changed["parent"] += 1
        definition = re.sub(r"\s+", " ", str(answer.get("definition") or "")).strip()
        if definition and definition != row["definition"] and re.match(r"An? ", definition) and "inhering in" in definition:
            what.append("definition reworded")
            row["definition"] = definition
            changed["definition"] += 1
        if what:
            note = NOTE.format(what="; ".join(what))
            row["review_note"] = (row.get("review_note", "") + " " + note).strip()
            if args.dry_run:
                print(flopo_id, row["label"], "|", "; ".join(what))
    for flopo_id, field, name in DROP:
        row = by_id[flopo_id]
        names = [n for n in row[field].split("|") if n]
        if name in names:
            names.remove(name)
            row[field] = "|".join(names)
            row["rule_words"] = "|".join(w for w in (row.get("rule_words") or "").split("|") if w and w != name)
            changed["synonym"] += 1
    for flopo_id, constraint in CONSTRAIN.items():
        if by_id[flopo_id].get("rule_bearer_constraint") != constraint:
            by_id[flopo_id]["rule_bearer_constraint"] = constraint
            changed["rule"] += 1
    print(changed)
    if not args.dry_run:
        with SPEC.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
