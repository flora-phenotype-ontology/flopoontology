"""Build a curator-facing review sheet for novel PO–PATO combinations.

The semantic gate deliberately refuses to promote combinations absent from the reviewed
whitelist.  This module aggregates their retained evidence without changing that whitelist or
minting FLOPO identifiers.  Every output row therefore starts in ``pending`` state.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


FIELDS = (
    "review_rank",
    "po_id",
    "po_label",
    "pato_id",
    "pato_label",
    "proposed_label",
    "review_scope",
    "pato_is_attribute",
    "evidence_count",
    "composition_accepted_count",
    "composition_review_count",
    "source_collection_count",
    "accepted_source_collection_count",
    "source_collections",
    "evidence_by_source",
    "taxon_count",
    "source_document_count",
    "numeric_count",
    "qualified_count",
    "example_1_source",
    "example_1",
    "example_2_source",
    "example_2",
    "example_3_source",
    "example_3",
    "review_status",
    "reviewer",
    "review_date",
    "review_notes",
)


def _catalog(path: Path) -> tuple[dict[str, str], set[str]]:
    labels: dict[str, str] = {}
    attributes: set[str] = set()
    if not path.exists():
        return labels, attributes
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            identifier = row.get("id", "")
            if not identifier:
                continue
            labels[identifier] = row.get("label", "")
            if "attribute_slim" in (row.get("slim") or "").split("|"):
                attributes.add(identifier)
    return labels, attributes


def _qualified(assertion: dict[str, Any]) -> bool:
    return bool(
        (assertion.get("frequency_qualifier", "unspecified") or "unspecified")
        != "unspecified"
        or (assertion.get("epistemic_modality", "asserted") or "asserted") != "asserted"
        or (assertion.get("value_qualifier", "exact") or "exact") != "exact"
        or (assertion.get("degree_qualifier", "unmodified") or "unmodified")
        != "unmodified"
    )


def _clean_example(value: object) -> str:
    return " ".join(str(value or "").split())


def _composition_accepted(assertion: dict[str, Any]) -> bool:
    """Treat legacy assertions without an audit as usable, but expose audited rejections."""

    composition = assertion.get("composition")
    return not isinstance(composition, dict) or composition.get("status") == "accept"


def _representative_examples(examples: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Prefer examples from different flora before taking additional examples from one flora."""

    chosen: list[tuple[str, str]] = []
    used_sources: set[str] = set()
    for source, example in examples:
        if source not in used_sources:
            chosen.append((source, example))
            used_sources.add(source)
        if len(chosen) == 3:
            return chosen
    for item in examples:
        if item not in chosen:
            chosen.append(item)
        if len(chosen) == 3:
            break
    return chosen


def build_review_sheet(
    input_path: Path,
    output_path: Path,
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
) -> dict[str, Any]:
    """Aggregate gated novel combinations into a non-authoritative TSV review queue."""

    po_labels, _ = _catalog(po_lexicon)
    pato_labels, pato_attributes = _catalog(pato_lexicon)
    aggregates: dict[tuple[str, str], dict[str, Any]] = {}

    with Path(input_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            source = str(record.get("source", "") or "")
            taxon = str(record.get("taxon", "") or "")
            document = "|".join(
                (source, str(record.get("source_id", "") or ""))
            )
            for assertion in record.get("assertions", []) or []:
                gate = assertion.get("gate") or {}
                reasons = set(gate.get("reasons", []) or [])
                if gate.get("po_pato_status") != "novel" and "po_pato_novel" not in reasons:
                    continue
                pair = (str(assertion.get("po_id", "")), str(assertion.get("pato_id", "")))
                aggregate = aggregates.setdefault(
                    pair,
                    {
                        "evidence_count": 0,
                        "composition_accepted_count": 0,
                        "composition_review_count": 0,
                        "sources": Counter(),
                        "accepted_sources": Counter(),
                        "taxa": set(),
                        "documents": set(),
                        "numeric_count": 0,
                        "qualified_count": 0,
                        "examples": [],
                    },
                )
                aggregate["evidence_count"] += 1
                if source:
                    aggregate["sources"][source] += 1
                if _composition_accepted(assertion):
                    aggregate["composition_accepted_count"] += 1
                    if source:
                        aggregate["accepted_sources"][source] += 1
                else:
                    aggregate["composition_review_count"] += 1
                if taxon:
                    aggregate["taxa"].add(taxon)
                if document.strip("|"):
                    aggregate["documents"].add(document)
                if assertion.get("value_low") is not None or assertion.get("value_high") is not None:
                    aggregate["numeric_count"] += 1
                if _qualified(assertion):
                    aggregate["qualified_count"] += 1
                example = _clean_example(assertion.get("source_text"))
                example_key = (source, example)
                if example and example_key not in aggregate["examples"]:
                    aggregate["examples"].append(example_key)

    rows: list[dict[str, object]] = []
    for (po_id, pato_id), aggregate in aggregates.items():
        po_label = po_labels.get(po_id, "")
        pato_label = pato_labels.get(pato_id, "")
        examples = _representative_examples(aggregate["examples"])
        examples += [("", "")] * (3 - len(examples))
        sources = aggregate["sources"]
        source_names = sorted(sources)
        is_attribute = pato_id in pato_attributes
        rows.append(
            {
                "review_rank": 0,
                "po_id": po_id,
                "po_label": po_label,
                "pato_id": pato_id,
                "pato_label": pato_label,
                "proposed_label": " ".join(part for part in (po_label, pato_label) if part),
                "review_scope": "reusable_trait" if is_attribute else "reusable_phenotype",
                "pato_is_attribute": str(is_attribute).lower(),
                "evidence_count": aggregate["evidence_count"],
                "composition_accepted_count": aggregate["composition_accepted_count"],
                "composition_review_count": aggregate["composition_review_count"],
                "source_collection_count": len(sources),
                "accepted_source_collection_count": len(aggregate["accepted_sources"]),
                "source_collections": "|".join(source_names),
                "evidence_by_source": "|".join(
                    f"{source}:{sources[source]}" for source in source_names
                ),
                "taxon_count": len(aggregate["taxa"]),
                "source_document_count": len(aggregate["documents"]),
                "numeric_count": aggregate["numeric_count"],
                "qualified_count": aggregate["qualified_count"],
                "example_1_source": examples[0][0],
                "example_1": examples[0][1],
                "example_2_source": examples[1][0],
                "example_2": examples[1][1],
                "example_3_source": examples[2][0],
                "example_3": examples[2][1],
                "review_status": "pending",
                "reviewer": "",
                "review_date": "",
                "review_notes": "",
            }
        )
    rows.sort(
        key=lambda row: (
            -int(row["accepted_source_collection_count"]),
            -int(row["composition_accepted_count"]),
            -int(row["source_collection_count"]),
            -int(row["evidence_count"]),
            -int(row["taxon_count"]),
            -int(row["source_document_count"]),
            str(row["po_id"]),
            str(row["pato_id"]),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["review_rank"] = rank

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    totals: Counter[str] = Counter()
    totals["combinations"] = len(rows)
    totals["evidence"] = sum(int(row["evidence_count"]) for row in rows)
    totals["attribute_combinations"] = sum(row["pato_is_attribute"] == "true" for row in rows)
    totals["numeric_evidence"] = sum(int(row["numeric_count"]) for row in rows)
    totals["qualified_evidence"] = sum(int(row["qualified_count"]) for row in rows)
    totals["composition_accepted_evidence"] = sum(
        int(row["composition_accepted_count"]) for row in rows
    )
    totals["composition_review_evidence"] = sum(
        int(row["composition_review_count"]) for row in rows
    )
    return {**dict(totals), "out": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate novel PO–PATO pairs for curator review.")
    parser.add_argument("input", type=Path, help="gated review or all-status JSONL")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    args = parser.parse_args()
    print(
        json.dumps(
            build_review_sheet(args.input, args.output, args.po_lexicon, args.pato_lexicon),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
