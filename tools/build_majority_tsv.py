#!/usr/bin/env python3
"""Build a majority-vote TSV while preserving categorical values."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from flopo2.extract.ground import load_lexicons


VALUE_SPLIT_RE = re.compile(r"\s*(?:,|\bor\b|\band\b|/)\s*", re.I)
COLORISH_RE = re.compile(r"^([a-z]+ish)-([a-z]+)$", re.I)
LEADING_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.I)
VALUE_PATO_OVERRIDES = {
    # In botanical morphology, categorical "long" usually describes an elongated form/state.
    # Numeric spans such as "5 cm long" remain represented as length + measurement.
    "long": "PATO_0001154",
}


def value_terms(value_text: str) -> list[str]:
    """Split categorical value text conservatively for PATO grounding."""
    value = (value_text or "").strip().lower()
    if not value:
        return []
    out: list[str] = []
    for part in VALUE_SPLIT_RE.split(value):
        part = part.strip(" .;:")
        if not part:
            continue
        out.append(part)
        if "-" in part:
            out.extend(p for p in part.split("-") if p)
        if " " in part:
            out.extend(p for p in part.split() if p)
        m = COLORISH_RE.match(part)
        if m:
            out.append(m.group(2))
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def evidence_key(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip().lower())
    return LEADING_ARTICLE_RE.sub("", text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", action="append", nargs=2, metavar=("NAME", "JSONL"), required=True)
    parser.add_argument("--flopo-values", type=Path, default=Path("ontology/flopo-value-extensions.tsv"))
    args = parser.parse_args()

    _po_lex, pato_lex = load_lexicons()
    flopo_value_by_label: dict[str, tuple[str, str]] = {}
    if args.flopo_values.exists():
        with args.flopo_values.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                flopo_value_by_label[row["label"].lower()] = (row["flopo_id"], row["label"])
    support: Counter[tuple] = Counter()
    examples: dict[tuple, dict] = {}
    values_by_key: dict[tuple, list[dict]] = {}

    for model_name, filename in args.model:
        seen = set()
        for line in Path(filename).open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            taxon = row.get("taxon", "")
            for assertion in row.get("assertions") or []:
                key = (
                    taxon,
                    assertion.get("po_id", ""),
                    assertion.get("pato_id", ""),
                    bool(assertion.get("negated", False)),
                    evidence_key(assertion.get("source_text", "")),
                )
                seen.add(key)
                comp = assertion.get("composition") or {}
                gate = assertion.get("gate") or {}
                value_record = {
                    "value_text": assertion.get("value_text", "") or "",
                    "value_low": assertion.get("value_low"),
                    "value_high": assertion.get("value_high"),
                    "unit": assertion.get("unit", "") or "",
                }
                values_by_key.setdefault(key, []).append(value_record)
                examples.setdefault(
                    key,
                    {
                        "taxon": taxon,
                        "po_label": comp.get("entity_label") or assertion.get("po_label") or "",
                        "pato_label": comp.get("quality_label") or assertion.get("pato_label") or "",
                        "source_id": row.get("source_id", ""),
                        "source_text": assertion.get("source_text", ""),
                        "flopo_iri": gate.get("flopo_iri", ""),
                        "flopo_status": gate.get("flopo_status", ""),
                        "example_model": model_name,
                    },
                )
        support.update(seen)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                "support",
                "taxon",
                "po_id",
                "po_label",
                "pato_id",
                "pato_label",
                "negated",
                "value_text",
                "value_pato_ids",
                "value_pato_labels",
                "value_flopo_ids",
                "value_flopo_labels",
                "value_low",
                "value_high",
                "unit",
                "flopo_status",
                "flopo_iri",
                "source_id",
                "source_text",
            ]
        )
        for key, votes in sorted(support.items(), key=lambda item: tuple(str(x) for x in item[0])):
            if votes < 2:
                continue
            example = examples[key]
            value_texts: list[str] = []
            numeric_values: list[tuple[str, str, str]] = []
            for value in values_by_key.get(key, []):
                if value["value_text"] and value["value_text"] not in value_texts:
                    value_texts.append(value["value_text"])
                if value["value_low"] is not None or value["value_high"] is not None:
                    numeric = (
                        "" if value["value_low"] is None else str(value["value_low"]),
                        "" if value["value_high"] is None else str(value["value_high"]),
                        value["unit"],
                    )
                    if numeric not in numeric_values:
                        numeric_values.append(numeric)
            grounded_values = []
            flopo_values = []
            for value_text in value_texts:
                direct_flopo = flopo_value_by_label.get(value_text.lower())
                if direct_flopo and direct_flopo not in flopo_values:
                    flopo_values.append(direct_flopo)
                for term in value_terms(value_text):
                    pato_id = VALUE_PATO_OVERRIDES.get(term) or pato_lex.ground(term)
                    if pato_id:
                        pair = (pato_id, pato_lex.id_to_label[pato_id])
                        if pair not in grounded_values:
                            grounded_values.append(pair)
                    flopo_pair = flopo_value_by_label.get(term.lower())
                    if flopo_pair and flopo_pair not in flopo_values:
                        flopo_values.append(flopo_pair)
            value_low = "|".join(x[0] for x in numeric_values)
            value_high = "|".join(x[1] for x in numeric_values)
            unit = "|".join(x[2] for x in numeric_values)
            writer.writerow(
                [
                    votes,
                    key[0],
                    key[1],
                    example["po_label"],
                    key[2],
                    example["pato_label"],
                    key[3],
                    "|".join(value_texts),
                    "|".join(x[0] for x in grounded_values),
                    "|".join(x[1] for x in grounded_values),
                    "|".join(x[0] for x in flopo_values),
                    "|".join(x[1] for x in flopo_values),
                    value_low,
                    value_high,
                    unit,
                    example["flopo_status"],
                    example["flopo_iri"],
                    example["source_id"],
                    example["source_text"],
                ]
            )


if __name__ == "__main__":
    main()
