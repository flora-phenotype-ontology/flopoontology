"""Convert reviewed assertion proposals into a per-segment delta against a later stage.

Machine-review materializers emit proposals bound to the stage their campaign was inventoried
from.  This module rebinds those proposals to a later corpus stage without copying it: every
proposal must match exactly one segment, its evidence offsets must still hold, and every
unresolved span it clears must still be present exactly once.  The result is a delta with one
line per touched segment::

    {"key": {source, source_id, source_segment_index, taxon, organ, char_start, char_end},
     "add_source_statements": [...], "add_assertions": [...],
     "remove_unresolved": [{start, end, reason, surface_form}]}

:func:`apply_delta` materializes a delta onto a distinct copy for validation.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

from flopo2.verify.apply_reviewed_proposals import (
    STATEMENT_IDENTITY_FIELDS,
    _assertion_key,
    _segment_key,
)


DELTA_KEY_FIELDS = (
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "char_start",
    "char_end",
)


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _delta_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(field) for field in DELTA_KEY_FIELDS)


def _segment_delta(record: dict[str, Any], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    key = _segment_key(record)
    text = str(record.get("text", "") or "")
    statements = {
        row.get("statement_id"): row for row in record.get("source_statements", []) or []
    }
    assertion_keys = {_assertion_key(row) for row in record.get("assertions", []) or []}
    unresolved = Counter(
        (int(span.get("start", -1)), int(span.get("end", -1)))
        for span in record.get("unresolved_spans", []) or []
    )
    spans_by_range = {
        (int(span.get("start", -1)), int(span.get("end", -1))): span
        for span in record.get("unresolved_spans", []) or []
    }
    add_statements: list[dict[str, Any]] = []
    add_assertions: list[dict[str, Any]] = []
    remove: list[dict[str, Any]] = []
    cleared: set[tuple[int, int]] = set()
    next_index = len(record.get("assertions", []) or [])
    for proposal in sorted(proposals, key=lambda row: row["assertion"]["source_start"]):
        assertion = copy.deepcopy(proposal["assertion"])
        start, end = int(assertion["source_start"]), int(assertion["source_end"])
        if text[start:end] != assertion.get("source_text"):
            raise ValueError(f"{key}: assertion evidence drifted at {start}:{end}")
        if _assertion_key(assertion) in assertion_keys:
            raise ValueError(f"{key}: assertion already present in target stage")
        assertion_keys.add(_assertion_key(assertion))
        statement = proposal["source_statement"]
        statement_id = statement["statement_id"]
        if assertion.get("source_statement_id") != statement_id:
            raise ValueError(f"{key}: proposal statement link mismatch")
        s_start, s_end = int(statement["start"]), int(statement["end"])
        if text[s_start:s_end] != statement.get("verbatim_text"):
            raise ValueError(f"{key}: source statement drifted")
        existing = statements.get(statement_id)
        if existing is None:
            add_statements.append(statement)
            statements[statement_id] = statement
        elif any(existing.get(f) != statement.get(f) for f in STATEMENT_IDENTITY_FIELDS):
            raise ValueError(f"{key}: source statement identity collision {statement_id}")
        if isinstance(assertion.get("gate"), dict):
            assertion["gate"]["assertion_index"] = next_index
        next_index += 1
        add_assertions.append(assertion)
        for item in proposal.get("apply", {}).get("clear_unresolved_spans", []):
            span_range = (int(item["start"]), int(item["end"]))
            if span_range in cleared or unresolved[span_range] != 1:
                raise ValueError(f"{key}: clear range {span_range} is not unique in target stage")
            cleared.add(span_range)
            span = spans_by_range[span_range]
            remove.append(
                {
                    "start": span_range[0],
                    "end": span_range[1],
                    "reason": span.get("reason"),
                    "surface_form": span.get("surface_form"),
                }
            )
    return {
        "key": dict(zip(DELTA_KEY_FIELDS, _delta_key(record))),
        "add_source_statements": add_statements,
        "add_assertions": add_assertions,
        "remove_unresolved": remove,
    }


def build_delta(proposals_path: Path, stage_path: Path, delta_path: Path) -> dict[str, int]:
    """Rebind ``proposals_path`` to ``stage_path`` and write a per-segment delta."""

    proposals: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for proposal in _rows(proposals_path):
        proposals[_segment_key(proposal)].append(proposal)
    matched: Counter[tuple] = Counter()
    deltas: list[dict[str, Any]] = []
    for record in _rows(stage_path):
        rows = proposals.get(_segment_key(record))
        if not rows:
            continue
        matched[_segment_key(record)] += 1
        if matched[_segment_key(record)] > 1:
            raise ValueError(f"duplicate target segment identity: {_segment_key(record)}")
        deltas.append(_segment_delta(record, rows))
    missing = [key for key in proposals if matched[key] != 1]
    if missing:
        raise ValueError(f"{len(missing)} proposal segment(s) missing from target: {missing[:3]}")
    delta_path.parent.mkdir(parents=True, exist_ok=True)
    delta_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in deltas), encoding="utf-8"
    )
    return {
        "segments": len(deltas),
        "assertions": sum(len(row["add_assertions"]) for row in deltas),
        "source_statements": sum(len(row["add_source_statements"]) for row in deltas),
        "unresolved_removed": sum(len(row["remove_unresolved"]) for row in deltas),
    }


def apply_delta_record(record: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(record)
    statements = out.setdefault("source_statements", [])
    statement_ids = {row.get("statement_id") for row in statements}
    for statement in delta.get("add_source_statements", []):
        if statement["statement_id"] not in statement_ids:
            statements.append(statement)
            statement_ids.add(statement["statement_id"])
    for assertion in delta.get("add_assertions", []):
        if assertion.get("source_statement_id") not in statement_ids:
            raise ValueError(f"assertion references unknown statement for {_delta_key(record)}")
        out.setdefault("assertions", []).append(assertion)
    remove = Counter(
        (row["start"], row["end"], row["reason"], row["surface_form"])
        for row in delta.get("remove_unresolved", [])
    )
    kept = []
    for span in out.get("unresolved_spans", []) or []:
        span_key = (span.get("start"), span.get("end"), span.get("reason"), span.get("surface_form"))
        if remove[span_key]:
            remove[span_key] -= 1
            continue
        kept.append(span)
    if sum(remove.values()):
        raise ValueError(f"delta removes unresolved spans absent from {_delta_key(record)}")
    out["unresolved_spans"] = kept
    for index, assertion in enumerate(out.get("assertions", [])):
        if isinstance(assertion.get("gate"), dict):
            assertion["gate"]["assertion_index"] = index
    return out


def apply_delta(input_path: Path, delta_path: Path, output_path: Path) -> dict[str, int]:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("apply output must differ from input")
    deltas: dict[tuple, dict[str, Any]] = {}
    for delta in _rows(delta_path):
        key = tuple(delta["key"].get(field) for field in DELTA_KEY_FIELDS)
        if key in deltas:
            raise ValueError(f"duplicate delta key {key}")
        deltas[key] = delta
    applied = 0
    with output_path.open("w", encoding="utf-8") as out:
        for record in _rows(input_path):
            delta = deltas.pop(_delta_key(record), None)
            if delta is not None:
                record = apply_delta_record(record, delta)
                applied += 1
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    if deltas:
        raise ValueError(f"{len(deltas)} delta keys matched no segment")
    return {"segments_patched": applied}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--proposals", type=Path, required=True)
    build.add_argument("--stage", type=Path, required=True)
    build.add_argument("--delta", type=Path, required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("input", type=Path)
    apply.add_argument("--delta", type=Path, required=True)
    apply.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        result = build_delta(args.proposals, args.stage, args.delta)
    else:
        result = apply_delta(args.input, args.delta, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
