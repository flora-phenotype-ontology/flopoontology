"""Write reproducible, source- and bearer-stratified samples of recovered assertions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path


FIELDS = (
    "sample_index",
    "seed",
    "extractor",
    "source",
    "source_id",
    "source_segment_index",
    "organ",
    "po_id",
    "pato_id",
    "value_operator",
    "quality_values",
    "source_start",
    "source_end",
    "source_text",
    "context",
    "review_decision",
    "review_notes",
)


def _int_or_default(value: object, default: int) -> int:
    return default if value is None or value == "" else int(value)


def _stable_seed(seed: int, *values: str) -> int:
    payload = "\x1f".join((str(seed), *values)).encode()
    return int(hashlib.sha256(payload).hexdigest()[:16], 16)


def _stable_key(row: tuple[dict, dict]) -> tuple:
    record, assertion = row
    return (
        str(record.get("source_id", "")),
        _int_or_default(record.get("source_segment_index"), 0),
        _int_or_default(assertion.get("source_start"), -1),
        _int_or_default(assertion.get("source_end"), -1),
        str(assertion.get("po_id", "")),
        str(assertion.get("pato_id", "")),
        json.dumps(assertion.get("quality_values", []), sort_keys=True),
    )


def _stratified_rows(rows: list[tuple[dict, dict]], quota: int, seed: int) -> list:
    """Round-robin PO strata so rare bearer mappings are represented in an audit."""

    by_po: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for row in sorted(rows, key=_stable_key):
        by_po[str(row[1].get("po_id", ""))].append(row)
    po_ids = sorted(by_po)
    random.Random(_stable_seed(seed, "po-order")).shuffle(po_ids)
    for po_id, values in by_po.items():
        random.Random(_stable_seed(seed, "po", po_id)).shuffle(values)
    selected = []
    while po_ids and len(selected) < quota:
        remaining = []
        for po_id in po_ids:
            if by_po[po_id] and len(selected) < quota:
                selected.append(by_po[po_id].pop())
            if by_po[po_id]:
                remaining.append(po_id)
        po_ids = remaining
    return selected


def sample_recoveries(
    input_paths: list[Path], extractor: str, *, size: int = 50, seed: int = 20260718
) -> list[tuple[dict, dict]]:
    groups: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for path in input_paths:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                for assertion in record.get("assertions", []) or []:
                    if assertion.get("extractor") == extractor:
                        groups[str(record.get("source", ""))].append((record, assertion))
    available = sum(map(len, groups.values()))
    if not available:
        return []
    target = min(size, available)
    sources = sorted(groups)
    quotas = {source: min(len(groups[source]), target // len(sources)) for source in sources}
    remaining = target - sum(quotas.values())
    while remaining:
        advanced = False
        for source in sources:
            if quotas[source] < len(groups[source]) and remaining:
                quotas[source] += 1
                remaining -= 1
                advanced = True
        if not advanced:
            break
    selected = []
    for source in sources:
        selected.extend(
            _stratified_rows(
                groups[source], quotas[source], _stable_seed(seed, "source", source)
            )
        )
    return sorted(selected, key=lambda row: (str(row[0].get("source", "")), _stable_key(row)))


def write_sample(
    input_paths: list[Path],
    output: Path,
    extractor: str,
    *,
    size: int = 50,
    seed: int = 20260718,
) -> int:
    rows = sample_recoveries(input_paths, extractor, size=size, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for index, (record, assertion) in enumerate(rows, start=1):
            text = str(record.get("text", ""))
            start = _int_or_default(assertion.get("source_start"), -1)
            end = _int_or_default(assertion.get("source_end"), -1)
            context = text[max(0, start - 120) : min(len(text), end + 120)]
            writer.writerow(
                {
                    "sample_index": index,
                    "seed": seed,
                    "extractor": extractor,
                    "source": record.get("source", ""),
                    "source_id": record.get("source_id", ""),
                    "source_segment_index": record.get("source_segment_index", 0),
                    "organ": record.get("organ", ""),
                    "po_id": assertion.get("po_id", ""),
                    "pato_id": assertion.get("pato_id", ""),
                    "value_operator": assertion.get("value_operator", "atomic"),
                    "quality_values": json.dumps(
                        assertion.get("quality_values", []), ensure_ascii=False, sort_keys=True
                    ),
                    "source_start": start,
                    "source_end": end,
                    "source_text": assertion.get("source_text", ""),
                    "context": context,
                    "review_decision": "",
                    "review_notes": "",
                }
            )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--extractor", required=True)
    parser.add_argument("--size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    count = write_sample(
        args.inputs,
        args.output,
        args.extractor,
        size=args.size,
        seed=args.seed,
    )
    print(f"sampled {count} assertions -> {args.output}")


if __name__ == "__main__":
    main()
