"""Tie-break row normalization and correction-aware delta application.

Two small utilities for third-reviewer (``two_of_three``) admissions:

``normalize``
    The leaf-base, leaf-apex and shape tie-break files record the third reviewer's decision as
    flat fields (``disposition``, ``proposed_signature``, ``evidence_ids``,
    ``validation_passed``) without a ``campaign_id``.  :mod:`flopo2.review.tiebreak` reads rows
    of the form ``{"campaign_id", "item_id", "decision": {...}, "rationale"}``.  This rewrites
    the flat rows into that form for one campaign without changing any decision.

``apply``
    Applies one or more deltas to a distinct copy of a stage.  Besides the usual
    ``add_source_statements`` / ``add_assertions`` / ``remove_unresolved`` of
    :mod:`flopo2.verify.proposal_delta`, a correction delta may carry ``remove_assertions``::

        {"source_statement_id", "po_id", "pato_id", "source_start", "source_end"}

    Each entry must match exactly one existing assertion in the segment; removals run before
    additions, so a correction can replace a wrongly attached assertion with a corrected one.
    When no correct bearer exists, ``add_unresolved`` restores the evidence span to
    ``unresolved_spans`` instead (``{start, end, surface_form, reason, ...}``; the surface form
    must match the segment text and the span must not already be unresolved for that reason).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from flopo2.verify.proposal_delta import DELTA_KEY_FIELDS, apply_delta_record


REMOVE_FIELDS = ("source_statement_id", "po_id", "pato_id", "source_start", "source_end")
DECISION_FIELDS = ("disposition", "proposed_signature", "evidence_ids", "validation_passed")


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def normalize_tiebreak_row(row: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    """Return ``row`` in the :mod:`flopo2.review.tiebreak` input form for ``campaign_id``."""

    if isinstance(row.get("decision"), dict):
        if row.get("campaign_id") not in (None, campaign_id):
            raise ValueError(f"{row.get('item_id')}: tie-break row names another campaign")
        return {**row, "campaign_id": campaign_id}
    missing = [name for name in DECISION_FIELDS if name not in row]
    if missing or not row.get("item_id"):
        raise ValueError(f"{row.get('item_id')}: flat tie-break row lacks {missing or 'item_id'}")
    return {
        "campaign_id": campaign_id,
        "item_id": row["item_id"],
        "occurrence_id": row.get("occurrence_id"),
        "decision": {name: row[name] for name in DECISION_FIELDS},
        "rationale": row.get("rationale") or "tie-break decision",
        "agrees_with": row.get("agrees_with"),
        "revised_after_spot_check": bool(row.get("revised_after_spot_check", False)),
        "source_reviewer_label": row.get("reviewer_id"),
    }


def normalize_tiebreak_file(source: Path, target: Path, campaign_id: str) -> int:
    rows = [normalize_tiebreak_row(row, campaign_id) for row in _rows(source)]
    items = [row["item_id"] for row in rows]
    if len(items) != len(set(items)):
        raise ValueError(f"{source}: duplicate tie-break item ids")
    if target.resolve() == source.resolve():
        raise ValueError("normalized tie-break file must differ from its source")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return len(rows)


def _remove_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("source_statement_id"),
        row.get("po_id"),
        row.get("pato_id"),
        int(row.get("source_start", -1)),
        int(row.get("source_end", -1)),
    )


def remove_assertions(record: dict[str, Any], removals: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return a copy of ``record`` without the assertions named by ``removals``."""

    out = dict(record)
    assertions = list(record.get("assertions", []) or [])
    for removal in removals:
        if any(name not in removal for name in REMOVE_FIELDS):
            raise ValueError(f"remove_assertions entry lacks one of {REMOVE_FIELDS}: {removal}")
        target = _remove_key(removal)
        hits = [index for index, row in enumerate(assertions) if _remove_key(row) == target]
        if len(hits) != 1:
            raise ValueError(f"remove_assertions {target} matched {len(hits)} assertions")
        del assertions[hits[0]]
    out["assertions"] = assertions
    return out


def add_unresolved(record: dict[str, Any], spans: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return a copy of ``record`` with ``spans`` appended to ``unresolved_spans``."""

    out = dict(record)
    text = str(record.get("text", "") or "")
    current = list(record.get("unresolved_spans", []) or [])
    present = {(row.get("start"), row.get("end"), row.get("reason")) for row in current}
    for span in spans:
        start, end = int(span["start"]), int(span["end"])
        if not span.get("reason") or text[start:end] != span.get("surface_form"):
            raise ValueError(f"add_unresolved span {start}:{end} does not match the segment text")
        if (start, end, span["reason"]) in present:
            raise ValueError(f"add_unresolved span {start}:{end} is already unresolved")
        present.add((start, end, span["reason"]))
        current.append(dict(span))
    out["unresolved_spans"] = current
    return out


def apply_correction_record(record: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """Apply removals and restored spans, then the standard additions and clears."""

    removed = remove_assertions(record, delta.get("remove_assertions", []) or [])
    restored = add_unresolved(removed, delta.get("add_unresolved", []) or [])
    return apply_delta_record(restored, delta)


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(name) for name in DELTA_KEY_FIELDS)


def apply_deltas(input_path: Path, delta_paths: list[Path], output_path: Path) -> dict[str, int]:
    """Apply ``delta_paths`` in order to a distinct copy of ``input_path``."""

    if input_path.resolve() == output_path.resolve():
        raise ValueError("apply output must differ from input")
    pending: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    counts = {
        "deltas": 0,
        "assertions_added": 0,
        "assertions_removed": 0,
        "unresolved_added": 0,
        "unresolved_removed": 0,
    }
    for path in delta_paths:
        seen: set[tuple[Any, ...]] = set()
        for delta in _rows(path):
            key = tuple(delta["key"].get(name) for name in DELTA_KEY_FIELDS)
            if key in seen:
                raise ValueError(f"{path}: duplicate delta key {key}")
            seen.add(key)
            pending.setdefault(key, []).append(delta)
            counts["deltas"] += 1
            counts["assertions_added"] += len(delta.get("add_assertions", []) or [])
            counts["assertions_removed"] += len(delta.get("remove_assertions", []) or [])
            counts["unresolved_added"] += len(delta.get("add_unresolved", []) or [])
            counts["unresolved_removed"] += len(delta.get("remove_unresolved", []) or [])
    patched = 0
    with output_path.open("w", encoding="utf-8") as out:
        for record in _rows(input_path):
            deltas = pending.pop(_key(record), None)
            if deltas:
                for delta in deltas:
                    record = apply_correction_record(record, delta)
                patched += 1
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    if pending:
        raise ValueError(f"{len(pending)} delta keys matched no segment: {list(pending)[:3]}")
    return {**counts, "segments_patched": patched}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    normalize = sub.add_parser("normalize")
    normalize.add_argument("source", type=Path)
    normalize.add_argument("--campaign-id", required=True)
    normalize.add_argument("-o", "--output", type=Path, required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("input", type=Path)
    apply.add_argument("--delta", type=Path, action="append", required=True)
    apply.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "normalize":
        result: dict[str, Any] = {
            "rows": normalize_tiebreak_file(args.source, args.output, args.campaign_id)
        }
    else:
        result = apply_deltas(args.input, args.delta, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
