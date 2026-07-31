"""Compare OAK lexmatch output with FLOPO's scope-preserving lexical baseline."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from flopo2.terminology.catalog import canonical_curie


FIELDS = (
    "surface_form",
    "target_id",
    "expected_relation",
    "oak_predicate",
    "oak_object_match_field",
    "status",
)


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _read_sssom(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if line.strip() and not line.startswith("#")]
    if not lines:
        return []
    return list(csv.DictReader(lines, delimiter="\t"))


def compare_oak_lexmatch(
    mapping_report: Path,
    query_map: Path,
    oak_sssom: list[Path],
) -> tuple[list[dict[str, str]], dict[str, object]]:
    query_surfaces = {row["query_id"]: row["surface_form"] for row in _read_tsv(query_map)}
    expected = {}
    for row in _read_tsv(mapping_report):
        surface = row["surface_form"]
        for target_id in (row.get("exact_target_ids") or "").split("|"):
            if target_id:
                expected[(surface, canonical_curie(target_id))] = "skos:exactMatch"
        scoped_ids = (row.get("scoped_target_ids") or "").split("|")
        scoped_relations = (row.get("scoped_relations") or "").split("|")
        if len(scoped_ids) != len(scoped_relations):
            raise ValueError(f"{mapping_report}: unaligned scoped targets for {surface!r}")
        for target_id, relation in zip(scoped_ids, scoped_relations, strict=True):
            if target_id:
                expected[(surface, canonical_curie(target_id))] = relation

    observed = {}
    for path in oak_sssom:
        for row in _read_sssom(path):
            subject_id = row.get("subject_id", "")
            if subject_id not in query_surfaces:
                continue
            key = (query_surfaces[subject_id], canonical_curie(row.get("object_id", "")))
            value = (
                row.get("predicate_id", ""),
                row.get("object_match_field", ""),
            )
            if key in observed and observed[key] != value:
                raise ValueError(f"conflicting OAK mappings for {key}")
            observed[key] = value

    rows = []
    statuses = Counter()
    for surface, target_id in sorted(set(expected) | set(observed)):
        expected_relation = expected.get((surface, target_id), "")
        oak_predicate, object_field = observed.get((surface, target_id), ("", ""))
        if not expected_relation:
            status = "oak_pair_not_in_scope_preserving_baseline"
        elif not oak_predicate:
            status = "oak_pair_missing"
        elif oak_predicate == expected_relation:
            status = "relation_agrees"
        else:
            status = "relation_differs"
        statuses[status] += 1
        rows.append(
            {
                "surface_form": surface,
                "target_id": target_id,
                "expected_relation": expected_relation,
                "oak_predicate": oak_predicate,
                "oak_object_match_field": object_field,
                "status": status,
            }
        )
    shared_pairs = set(expected) & set(observed)
    expected_surface_set = {surface for surface, _target in expected}
    observed_surface_set = {surface for surface, _target in observed}

    def ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 6) if denominator else 0.0

    summary: dict[str, object] = {
        "expected_pairs": len(expected),
        "oak_pairs": len(observed),
        "shared_pairs": len(shared_pairs),
        "pair_recall": ratio(len(shared_pairs), len(expected)),
        "pair_precision": ratio(len(shared_pairs), len(observed)),
        "expected_surfaces": len(expected_surface_set),
        "oak_surfaces": len(observed_surface_set),
        "shared_surfaces": len(expected_surface_set & observed_surface_set),
        "surface_recall": ratio(
            len(expected_surface_set & observed_surface_set), len(expected_surface_set)
        ),
        "surface_precision": ratio(
            len(expected_surface_set & observed_surface_set), len(observed_surface_set)
        ),
        "statuses": dict(sorted(statuses.items())),
        "policy": (
            "OAK is an independent normalized lexical-recall baseline. Formal OBO synonym scope "
            "from the scope-preserving baseline controls mapping direction and eligibility."
        ),
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-report", type=Path, required=True)
    parser.add_argument("--query-map", type=Path, required=True)
    parser.add_argument("--oak-sssom", type=Path, action="append", required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()
    rows, summary = compare_oak_lexmatch(
        args.mapping_report,
        args.query_map,
        args.oak_sssom,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
