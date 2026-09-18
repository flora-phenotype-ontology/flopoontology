#!/usr/bin/env python3
"""Generate FLOPO value-class candidates for value strings missing in PATO."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from tools.build_majority_tsv import VALUE_PATO_OVERRIDES, value_terms


STOP = {
    "a", "an", "and", "at", "in", "of", "on", "or", "the", "to", "with",
    "almost", "bright", "dark", "deep", "deeply", "faint", "fairly", "light",
    "much", "pale", "pure", "slightly", "sometimes", "very",
    "cm", "mm", "metres", "several",
}

ALIASES = {
    "gray": "grey",
    "greyish": "grey",
    "grayish": "grey",
    "greenish": "green",
    "reddish": "red",
    "yellowish": "yellow",
    "pinkish": "pink",
    "purplish": "purple",
    "bluish": "blue",
    "brownish": "brown",
    "blackish": "black",
    "creamy": "cream",
    "rosylilac": "rosy-lilac",
    "greygreen": "grey-green",
    "bluegreen": "blue-green",
    "apricotcoloured": "apricot",
}

COLOR_WORDS = {
    "black", "blue", "brown", "cream", "crimson", "fawn", "golden", "green",
    "grey", "gray", "lilac", "magenta", "orange", "pink", "purple", "red",
    "rose", "rosy", "scarlet", "silvery", "violet", "white", "yellow",
}

MANUAL_PARENT_LABELS = {
    "cream": ["white", "yellow"],
    "creamy": ["white", "yellow"],
    "crimson": ["red"],
    "scarlet": ["red"],
    "fawn": ["brown", "yellow"],
    "golden": ["yellow"],
    "silvery": ["grey"],
    "rosy": ["pink", "red"],
    "rose": ["pink", "red"],
    "papery": ["texture"],
    "leathery": ["texture"],
    "velvety": ["texture"],
    "succulent": ["fleshy"],
    "terete": ["shape"],
    "palmate": ["shape"],
    "pendent": ["orientation"],
    "pendulous": ["orientation"],
    "feathery": ["texture"],
    "bristly": ["texture"],
    "cottony": ["texture"],
    "glaucous": ["color"],
}


def parse_pato(path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    terms: dict[str, dict] = {}
    cur: dict[str, object] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line == "[Term]":
            if cur and cur.get("id") and not cur.get("obsolete"):
                terms[cur["id"]] = cur  # type: ignore[index]
            cur = {"synonyms": [], "is_a": []}
            continue
        if line.startswith("["):
            if cur and cur.get("id") and not cur.get("obsolete"):
                terms[cur["id"]] = cur  # type: ignore[index]
            cur = None
            continue
        if cur is None or not line:
            continue
        if line.startswith("id: "):
            cur["id"] = line[4:].replace(":", "_")
        elif line.startswith("name: "):
            cur["name"] = line[6:]
        elif line.startswith("is_obsolete: true"):
            cur["obsolete"] = True
        elif line.startswith("synonym: "):
            m = re.match(r'synonym: "([^"]+)"', line)
            if m:
                cur["synonyms"].append(m.group(1))  # type: ignore[union-attr]
        elif line.startswith("is_a: "):
            cur["is_a"].append(line.split()[1].replace(":", "_"))  # type: ignore[union-attr]
    if cur and cur.get("id") and not cur.get("obsolete"):
        terms[cur["id"]] = cur  # type: ignore[index]

    label_to_id: dict[str, str] = {}
    for tid, term in terms.items():
        label_to_id.setdefault(str(term.get("name", "")).lower(), tid)
        for syn in term.get("synonyms", []):
            label_to_id.setdefault(str(syn).lower(), tid)
    return terms, label_to_id


def direct_ground(label: str, label_to_id: dict[str, str]) -> str:
    key = label.strip().lower()
    if key in VALUE_PATO_OVERRIDES:
        return VALUE_PATO_OVERRIDES[key]
    return label_to_id.get(key, "")


def normalized_parts(value: str) -> list[str]:
    out: list[str] = []
    for term in value_terms(value):
        term = ALIASES.get(term, term)
        if term in STOP or term.isdigit() or len(term) <= 1:
            continue
        out.append(term)
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def propose_parents(value: str, label_to_id: dict[str, str], terms: dict[str, dict]) -> list[str]:
    parents: list[str] = []
    parts = normalized_parts(value)
    for part in parts:
        pid = direct_ground(part, label_to_id)
        if pid:
            parents.append(pid)
        for parent_label in MANUAL_PARENT_LABELS.get(part, []):
            pid = direct_ground(parent_label, label_to_id)
            if pid:
                parents.append(pid)
    # For hyphenated/multiword color blends, map color components to PATO colors.
    for token in re.split(r"[-\s]+", value.lower()):
        token = ALIASES.get(token.strip(), token.strip())
        if token in COLOR_WORDS:
            pid = direct_ground(token, label_to_id)
            if pid:
                parents.append(pid)
            for parent_label in MANUAL_PARENT_LABELS.get(token, []):
                pid = direct_ground(parent_label, label_to_id)
                if pid:
                    parents.append(pid)
    seen = set()
    return [p for p in parents if p and not (p in seen or seen.add(p))]


def candidate_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return f"FLOPO_VALUE_{slug}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--majority", type=Path, default=Path("scratchpad/collenette-saudi-majority-2of3.tsv"))
    ap.add_argument("--pato", type=Path, default=Path("ont/pato.obo"))
    ap.add_argument("--out", type=Path, default=Path("scratchpad/flopo-value-candidates.tsv"))
    args = ap.parse_args()

    terms, label_to_id = parse_pato(args.pato)
    raw_counts: Counter[str] = Counter()
    examples: defaultdict[str, list[str]] = defaultdict(list)
    contexts: defaultdict[str, Counter[str]] = defaultdict(Counter)

    with args.majority.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            for raw in [x.strip() for x in row.get("value_text", "").split("|") if x.strip()]:
                # Skip raw values already exactly grounded or measurement-ish.
                if direct_ground(raw.lower(), label_to_id):
                    continue
                raw_counts[raw] += 1
                contexts[raw][f"{row['po_label']} {row['pato_label']}"] += 1
                if len(examples[raw]) < 4:
                    examples[raw].append(f"{row['taxon']}: {row['source_text']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow([
            "candidate_id", "value_label", "frequency", "status",
            "suggested_parent_pato_ids", "suggested_parent_pato_labels",
            "quality_contexts", "examples", "notes",
        ])
        for value, count in raw_counts.most_common():
            parents = propose_parents(value, label_to_id, terms)
            parent_labels = [str(terms[p]["name"]) for p in parents]
            if parents:
                status = "candidate"
            elif any(part in STOP for part in normalized_parts(value)) or re.search(r"\d", value):
                status = "parser_or_measurement_review"
            else:
                status = "needs_manual_parent"
            writer.writerow([
                candidate_id(value),
                value,
                count,
                status,
                "|".join(parents),
                "|".join(parent_labels),
                "|".join(f"{k} ({v})" for k, v in contexts[value].most_common(5)),
                " || ".join(examples[value]),
                "",
            ])
    print(f"wrote {len(raw_counts)} candidates to {args.out}")


if __name__ == "__main__":
    main()
