"""Give existing records the position of the bearer that the flora names (pattern 04).

"Basal leaves spatulate" is a statement about the basal leaves, "the lateral umbels usually
sterile" one about the lateral umbels. Records made before the position words were in
``config/flora_context_words.tsv`` (2026-11-13/14) say it of the part in general: "leaf
spatulate", "umbel sterile". This pass reads the word that stands directly before the bearer in
the source text and

* adds its class to ``bearer_context_qualities`` when the table has the word for that bearer
  (the class identifier follows), or
* sets the record to ``review`` (reason ``bearer_position_not_modelled``) when the word has no
  class ("axillary"), is not listed for that bearer, or two positions are joined ("the terminal
  and uppermost umbels"): the statement is then about some of the parts only, and the record
  must not claim it of all.

    python -m flopo2.verify.apply_bearer_position FILES            # count only
    python -m flopo2.verify.apply_bearer_position --write-suffix .position FILES
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path

WORDS = Path("config/flora_context_words.tsv")
REASON = "bearer_position_not_modelled"
NO_CLASS = {"axillary"}  # position words of a bearer without a value class


def load(path: Path = WORDS) -> dict[str, tuple[str, list[str]]]:
    """``{word: (class, bearer words it may be said of)}`` for the kind ``bearer_quality``."""

    found = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["kind"] == "bearer_quality" and " " not in row["word"] and row["target"].startswith(("PATO_", "FLOPO_")):
                if row["target_label"] in {row["word"], "basal", "cauline", "upper", "lower", "inner", "outer", "median",
                                           "lateral (sensu botany)", "terminal"}:
                    found[row["word"].lower()] = (row["target"], [w for w in row["bearer_constraint"].split("|") if w])
    return found


def _pattern(words: dict) -> re.Pattern:
    word = "|".join(sorted(map(re.escape, [*words, *NO_CLASS]), key=len, reverse=True))
    return re.compile(rf"(?:^|[^\w-])((?:{word})(?:\s*(?:,|and|or|to)\s*(?:{word}))*)\s+$", re.IGNORECASE)


def class_linked(assertion: dict) -> bool:
    """Whether the record is linked to an annotation class. A value relation ("glabrous to
    pubescent") and operands that a class cannot hold are written in the record only; such a
    record must not carry a class identifier (the builder of the formal assertions refuses it)."""

    from flopo2.annotation.operands import operands_fac_representable

    return not (assertion.get("qualitative_value_relation") or not operands_fac_representable(assertion)
                or assertion.get("specimen_condition") or assertion.get("count_position"))


def apply(assertion: dict, text: str, words: dict, pattern: re.Pattern) -> str:
    """'' (nothing to do), 'added' or 'review'."""

    from flopo2.owl.annotation_class import ensure_annotation_class_iri

    start, end = assertion.get("bearer_start"), assertion.get("bearer_end")
    if start is None or end is None or not text:
        return ""
    match = pattern.search(text[max(0, start - 60):start])
    if not match:
        return ""
    named = re.findall(r"[A-Za-z]+", match.group(1).lower())
    named = [w for w in named if w in words or w in NO_CLASS]
    bearer = (assertion.get("raw_entity_text") or text[start:end]).lower()
    targets = []
    for word in named:
        target, allowed = words.get(word, ("", []))
        if not target or (allowed and not any(a in bearer for a in allowed)):
            targets = None
            break
        if target not in targets:
            targets.append(target)
    present = [str(c).replace(":", "_") for c in assertion.get("bearer_context_qualities") or []]
    if targets and len(targets) == 1:
        target = targets[0]
        own = {str(assertion.get("pato_id") or "").replace(":", "_"),
               *(str(v).replace(":", "_") for v in assertion.get("value_terms") or [])}
        if target in present or target in own:
            return ""
        before = assertion.pop("phenotype_class_iri", None)
        assertion["bearer_context_qualities"] = [*(assertion.get("bearer_context_qualities") or []), target]
        try:
            ensure_annotation_class_iri(assertion)
        except ValueError:
            assertion["bearer_context_qualities"] = assertion["bearer_context_qualities"][:-1]
            if before:
                assertion["phenotype_class_iri"] = before
            return ""
        if not class_linked(assertion):
            assertion.pop("phenotype_class_iri", None)
        return "added"
    if any(w in present for w in (words.get(n, ("",))[0] for n in named)):
        return ""  # one of the positions is recorded already
    gate = assertion.setdefault("gate", {})
    reasons = gate.setdefault("reasons", [])
    if REASON in reasons:
        return ""
    reasons.append(REASON)
    gate["status"] = "review" if gate.get("status") in (None, "", "accepted", "review") else gate["status"]
    return "review"


def run(paths: list[Path], suffix: str | None) -> dict:
    words = load()
    pattern = _pattern(words)
    counts: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    for path in paths:
        out = open(str(path) + suffix, "w", encoding="utf-8") if suffix else None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                text = record.get("text", "")
                for assertion in record.get("assertions", []):
                    counts["assertions"] += 1
                    result = apply(assertion, text, words, pattern)
                    if result:
                        counts[result] += 1
                        start = assertion["bearer_start"]
                        kinds[(result, pattern.search(text[max(0, start - 60):start]).group(1).lower(),
                               (assertion.get("composition") or {}).get("entity_label", ""))] += 1
                if out:
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
        if out:
            out.close()
    return {"counts": dict(counts), "kinds": [[*key, n] for key, n in kinds.most_common()]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--write-suffix", help="write each file with this suffix added; omit to count only")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = run(args.files, args.write_suffix)
    if args.report:
        args.report.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["counts"], indent=1))
    for row in result["kinds"][:40]:
        print(*row, sep="\t")


if __name__ == "__main__":
    main()
