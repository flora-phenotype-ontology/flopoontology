"""Merge independently validated flora JSONL artifacts without losing segment identity."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _segment_key(obj: dict) -> tuple[object, ...]:
    text = obj.get("text", "")
    return (
        obj.get("source", ""),
        obj.get("source_id", ""),
        obj.get("source_segment_index", 0),
        obj.get("taxon", ""),
        obj.get("organ", ""),
        obj.get("char_start", 0),
        obj.get("char_end", len(text)),
        text,
    )


def merge_jsonl(inputs: list[Path], output: Path) -> dict:
    """Stream ``inputs`` into ``output`` and reject duplicate segment identities.

    A duplicate would make JSONL/SQLite segment counts disagree and can conceal accidental reuse
    of an artifact.  Assertions within a segment are not deduplicated: their independently gated
    evidence remains the source of truth.
    """

    if not inputs:
        raise ValueError("at least one input is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[object, ...]] = set()
    segments = assertions = unresolved_spans = 0
    statuses: Counter[str] = Counter()
    with output.open("w", encoding="utf-8") as out:
        for path in inputs:
            with Path(path).open(encoding="utf-8") as inp:
                for line_number, line in enumerate(inp, 1):
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        raise ValueError(f"{path}:{line_number}: JSONL row is not an object")
                    key = _segment_key(obj)
                    if key in seen:
                        raise ValueError(f"{path}:{line_number}: duplicate segment identity")
                    seen.add(key)
                    rows = obj.get("assertions", []) or []
                    if not isinstance(rows, list):
                        raise ValueError(f"{path}:{line_number}: assertions is not a list")
                    assertions += len(rows)
                    unresolved = obj.get("unresolved_spans", []) or []
                    if not isinstance(unresolved, list):
                        raise ValueError(f"{path}:{line_number}: unresolved_spans is not a list")
                    unresolved_spans += len(unresolved)
                    statuses.update(
                        status
                        for row in rows
                        if (status := (row.get("gate") or {}).get("status", ""))
                    )
                    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    segments += 1
    return {
        "inputs": [str(path) for path in inputs],
        "output": str(output),
        "segments": segments,
        "assertions": assertions,
        "unresolved_spans": unresolved_spans,
        "gate_statuses": dict(sorted(statuses.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge flora trait JSONL artifacts safely.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(merge_jsonl(args.inputs, args.output), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
