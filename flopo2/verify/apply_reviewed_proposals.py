"""Apply manually reviewed assertion proposals to a flora JSONL artifact.

The proposal format is intentionally small: each JSONL row identifies one source segment and
contains an ``assertion`` plus its retained ``source_statement``.  This module never invents an
ontology identifier or changes an unreviewed span; it only materializes proposals that already
carry their reviewed PO, PATO, provenance, and FAC identifiers.

Application is append-only by default.  A reviewed proposal may additionally supersede an
over-strong predecessor assertion — for example an atomic ``white`` extracted from a
``white or pinkish white`` statement that the reviewed disjunction replaces — by listing it under
``apply.remove_assertions``.  That allow-list is explicit and fail-closed: each selector carries the
importer's complete semantic/evidence identity (``po_id``, ``pato_id``, ``negated``,
``source_start``, ``source_end``, ``value_operator``, ``value_terms``) and must match exactly one
assertion already present in the input segment.  Removals are never inferred from source-range
containment or overlap, so an independent conjunct such as ``smooth`` in ``Bark smooth, brown or
grey`` is retained unless a curator selected it by full identity.  Superseded assertions never take
their ``source_statements`` provenance with them.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SegmentKey = tuple[str, str, int, str]
STATEMENT_IDENTITY_FIELDS = (
    "verbatim_text",
    "start",
    "end",
    "language",
    "document_start",
    "document_end",
)
REMOVAL_SELECTOR_FIELDS = (
    "po_id",
    "pato_id",
    "negated",
    "source_start",
    "source_end",
    "value_operator",
    "value_terms",
)


def _segment_key(row: dict[str, Any]) -> SegmentKey:
    return (
        str(row.get("source", "")),
        str(row.get("source_id", "")),
        int(row.get("source_segment_index", 0)),
        str(row.get("taxon", "")),
    )


def _assertion_key(assertion: dict[str, Any]) -> tuple[Any, ...]:
    return (
        assertion.get("po_id", ""),
        assertion.get("pato_id", ""),
        bool(assertion.get("negated", False)),
        int(assertion.get("source_start", -1)),
        int(assertion.get("source_end", -1)),
        assertion.get("value_operator", "atomic"),
        tuple(assertion.get("value_terms", []) or []),
    )


def _read_proposals(path: Path) -> dict[SegmentKey, list[dict[str, Any]]]:
    proposals: dict[SegmentKey, list[dict[str, Any]]] = defaultdict(list)
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            proposal = json.loads(line)
            if not isinstance(proposal, dict):
                raise ValueError(f"{path}:{line_number}: proposal is not an object")
            assertion = proposal.get("assertion")
            if not isinstance(assertion, dict):
                raise ValueError(f"{path}:{line_number}: proposal requires an assertion")
            key = _segment_key(proposal)
            if not all((key[0], key[1], key[3])):
                raise ValueError(f"{path}:{line_number}: incomplete segment identity")
            proposals[key].append(proposal)
    return proposals


def _statement_for_proposal(
    proposal: dict[str, Any],
    statements_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve retained evidence from either supported proposal representation."""

    assertion = proposal["assertion"]
    statement_id = str(assertion.get("source_statement_id", "") or "")
    if not statement_id:
        raise ValueError(f"proposal assertion has no source statement id: {_segment_key(proposal)}")
    candidates: list[dict[str, Any]] = []
    top_level = proposal.get("source_statement")
    if isinstance(top_level, dict):
        candidates.append(top_level)
    apply = proposal.get("apply")
    if isinstance(apply, dict):
        added = apply.get("added_source_statements", []) or []
        if not isinstance(added, list):
            raise ValueError(f"proposal has malformed added source statements: {_segment_key(proposal)}")
        candidates.extend(
            statement
            for statement in added
            if isinstance(statement, dict) and statement.get("statement_id") == statement_id
        )
    existing = statements_by_id.get(statement_id)
    if existing is not None:
        candidates.append(existing)
    if not candidates:
        raise ValueError(
            f"proposal source statement {statement_id} is neither retained nor already present"
        )
    for statement in candidates:
        if statement.get("statement_id") != statement_id:
            raise ValueError(f"proposal statement link mismatch for {_segment_key(proposal)}")
    canonical = candidates[0]
    if any(
        candidate.get(field) != canonical.get(field)
        for candidate in candidates[1:]
        for field in STATEMENT_IDENTITY_FIELDS
    ):
        raise ValueError(f"source statement identity collision for {statement_id}")
    return canonical


def _validate_offsets(
    text: str,
    proposal: dict[str, Any],
    statement: dict[str, Any],
) -> None:
    assertion = proposal["assertion"]
    start = int(assertion["source_start"])
    end = int(assertion["source_end"])
    source_text = str(assertion.get("source_text", ""))
    if start < 0 or end <= start or end > len(text) or text[start:end] != source_text:
        raise ValueError(
            f"proposal evidence mismatch for {_segment_key(proposal)} at {start}:{end}"
        )
    if statement.get("statement_id") != assertion.get("source_statement_id"):
        raise ValueError(f"proposal statement link mismatch for {_segment_key(proposal)}")
    statement_start = int(statement["start"])
    statement_end = int(statement["end"])
    if (
        statement_start < 0
        or statement_end <= statement_start
        or statement_end > len(text)
        or text[statement_start:statement_end] != statement.get("verbatim_text", "")
    ):
        raise ValueError(f"proposal statement offsets mismatch for {_segment_key(proposal)}")


def _declared_clear_ranges(
    text: str,
    proposal: dict[str, Any],
) -> list[tuple[int, int]] | None:
    """Return an exact unresolved-span allow-list when a proposal supplies one.

    Older reviewed proposals predate ``apply.clear_unresolved_spans`` and retain the
    source-range fallback. Logical-expression proposals use the allow-list so an unrelated
    unresolved span inside the wider class-description evidence cannot be cleared accidentally.
    """

    apply = proposal.get("apply")
    if not isinstance(apply, dict) or "clear_unresolved_spans" not in apply:
        return None
    declared = apply["clear_unresolved_spans"]
    if not isinstance(declared, list) or not declared:
        raise ValueError(f"proposal has an empty or malformed clear list: {_segment_key(proposal)}")
    ranges: list[tuple[int, int]] = []
    for item in declared:
        if not isinstance(item, dict) or "start" not in item or "end" not in item:
            raise ValueError(f"proposal has a malformed clear range: {_segment_key(proposal)}")
        start = int(item["start"])
        end = int(item["end"])
        if start < 0 or end <= start or end > len(text):
            raise ValueError(f"proposal clear range is outside source text: {_segment_key(proposal)}")
        ranges.append((start, end))
    if len(ranges) != len(set(ranges)):
        raise ValueError(f"proposal has duplicate clear ranges: {_segment_key(proposal)}")
    return ranges


def _selector_key(selector: Any, proposal: dict[str, Any]) -> tuple[Any, ...]:
    """Return the assertion identity a removal selector denotes, or fail closed."""

    key = _segment_key(proposal)
    if not isinstance(selector, dict):
        raise ValueError(f"proposal has a malformed removal selector: {key}")
    missing = [field for field in REMOVAL_SELECTOR_FIELDS if field not in selector]
    if missing:
        raise ValueError(
            f"proposal removal selector is incomplete ({', '.join(missing)}): {key}"
        )
    unknown = sorted(set(selector) - set(REMOVAL_SELECTOR_FIELDS))
    if unknown:
        raise ValueError(
            f"proposal removal selector has unknown fields ({', '.join(unknown)}): {key}"
        )
    po_id = selector["po_id"]
    pato_id = selector["pato_id"]
    negated = selector["negated"]
    start = selector["source_start"]
    end = selector["source_end"]
    operator = selector["value_operator"]
    terms = selector["value_terms"]
    if not all(isinstance(value, str) and value for value in (po_id, pato_id, operator)):
        raise ValueError(f"proposal removal selector has malformed identifiers: {key}")
    if not isinstance(negated, bool):
        raise ValueError(f"proposal removal selector has a malformed negation flag: {key}")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end)):
        raise ValueError(f"proposal removal selector has malformed offsets: {key}")
    if start < 0 or end <= start:
        raise ValueError(f"proposal removal selector has an invalid source range: {key}")
    if not isinstance(terms, list) or any(
        not isinstance(term, str) or not term for term in terms
    ):
        raise ValueError(f"proposal removal selector has malformed value terms: {key}")
    return (po_id, pato_id, negated, start, end, operator, tuple(terms))


def _declared_removals(proposal: dict[str, Any]) -> list[tuple[Any, ...]] | None:
    """Return the exact assertion-removal allow-list when a proposal supplies one.

    Absence of ``apply.remove_assertions`` keeps the append-only behaviour.  Presence requires a
    non-empty list of complete selectors; anything else fails before output is written.
    """

    apply = proposal.get("apply")
    if not isinstance(apply, dict) or "remove_assertions" not in apply:
        return None
    declared = apply["remove_assertions"]
    if not isinstance(declared, list) or not declared:
        raise ValueError(
            f"proposal has an empty or malformed removal list: {_segment_key(proposal)}"
        )
    keys = [_selector_key(selector, proposal) for selector in declared]
    if len(keys) != len(set(keys)):
        raise ValueError(
            f"proposal has duplicate removal selectors: {_segment_key(proposal)}"
        )
    return keys


def apply_reviewed_proposals(
    input_path: Path,
    proposals_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Stream ``input_path`` and materialize every reviewed proposal exactly once."""

    if output_path.resolve() in {input_path.resolve(), proposals_path.resolve()}:
        raise ValueError("output must be distinct from both input and proposal files")
    proposals = _read_proposals(proposals_path)
    matched: Counter[SegmentKey] = Counter()
    counts: Counter[str] = Counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    try:
        with input_path.open(encoding="utf-8") as source, temp_handle as output:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{input_path}:{line_number}: JSONL row is not an object")
                key = _segment_key(row)
                row_proposals = proposals.get(key, [])
                if row_proposals:
                    matched[key] += 1
                    if matched[key] > 1:
                        raise ValueError(f"duplicate input segment matched proposals: {key}")
                    text = str(row.get("text", ""))
                    assertions = row.setdefault("assertions", [])
                    statements = row.setdefault("source_statements", [])
                    unresolved = row.setdefault("unresolved_spans", [])
                    if not all(
                        isinstance(value, list) for value in (assertions, statements, unresolved)
                    ):
                        raise ValueError(f"{input_path}:{line_number}: malformed segment lists")
                    original_assertions = list(assertions)
                    if not all(
                        isinstance(assertion, dict) for assertion in original_assertions
                    ):
                        raise ValueError(f"{input_path}:{line_number}: malformed assertion entry")
                    assertion_keys = {_assertion_key(assertion) for assertion in assertions}
                    proposed_keys: set[tuple[Any, ...]] = set()
                    removal_selectors: dict[tuple[Any, ...], None] = {}
                    statements_by_id = {
                        statement.get("statement_id"): statement
                        for statement in statements
                        if isinstance(statement, dict) and statement.get("statement_id")
                    }
                    fallback_ranges: list[tuple[int, int]] = []
                    exact_clear_ranges: set[tuple[int, int]] = set()
                    for proposal in row_proposals:
                        assertion = proposal["assertion"]
                        statement = _statement_for_proposal(proposal, statements_by_id)
                        _validate_offsets(text, proposal, statement)
                        assertion_key = _assertion_key(assertion)
                        proposed_keys.add(assertion_key)
                        for removal_key in _declared_removals(proposal) or ():
                            if removal_key == assertion_key:
                                raise ValueError(
                                    f"proposal removes the assertion it adds for {key}: "
                                    f"{removal_key}"
                                )
                            if removal_key in removal_selectors:
                                raise ValueError(
                                    f"proposals duplicate removal selectors for {key}: "
                                    f"{removal_key}"
                                )
                            removal_selectors[removal_key] = None
                        if assertion_key in assertion_keys:
                            counts["duplicate_assertions"] += 1
                        else:
                            assertions.append(assertion)
                            assertion_keys.add(assertion_key)
                            counts["assertions_added"] += 1
                        statement_id = statement["statement_id"]
                        existing_statement = statements_by_id.get(statement_id)
                        if existing_statement is not None and any(
                            existing_statement.get(field) != statement.get(field)
                            for field in STATEMENT_IDENTITY_FIELDS
                        ):
                            raise ValueError(
                                f"source statement identity collision for {statement_id} in {key}"
                            )
                        if existing_statement is None:
                            statements.append(statement)
                            statements_by_id[statement_id] = statement
                            counts["source_statements_added"] += 1
                        declared_ranges = _declared_clear_ranges(text, proposal)
                        if declared_ranges is None:
                            fallback_ranges.append(
                                (int(assertion["source_start"]), int(assertion["source_end"]))
                            )
                        else:
                            overlap = exact_clear_ranges.intersection(declared_ranges)
                            if overlap:
                                raise ValueError(
                                    f"proposals duplicate exact clear ranges for {key}: "
                                    f"{sorted(overlap)}"
                                )
                            exact_clear_ranges.update(declared_ranges)
                    retained_spans = []
                    matched_exact_ranges: Counter[tuple[int, int]] = Counter()
                    for span in unresolved:
                        span_start = int(span.get("start", -1))
                        span_end = int(span.get("end", -1))
                        span_range = (span_start, span_end)
                        if span_range in exact_clear_ranges:
                            matched_exact_ranges[span_range] += 1
                            counts["unresolved_spans_removed"] += 1
                        elif any(
                            start <= span_start and span_end <= end
                            for start, end in fallback_ranges
                        ):
                            counts["unresolved_spans_removed"] += 1
                        else:
                            retained_spans.append(span)
                    unmatched_exact = sorted(
                        span_range
                        for span_range in exact_clear_ranges
                        if matched_exact_ranges[span_range] != 1
                    )
                    if unmatched_exact:
                        raise ValueError(
                            f"proposal clear ranges did not match exactly once for {key}: "
                            f"{unmatched_exact[:3]}"
                        )
                    row["unresolved_spans"] = retained_spans
                    if removal_selectors:
                        indices_by_key: dict[tuple[Any, ...], list[int]] = defaultdict(list)
                        for index, assertion in enumerate(original_assertions):
                            indices_by_key[_assertion_key(assertion)].append(index)
                        removed_indices: set[int] = set()
                        for removal_key in removal_selectors:
                            if removal_key in proposed_keys:
                                raise ValueError(
                                    f"proposal removes an assertion added for {key}: {removal_key}"
                                )
                            indices = indices_by_key.get(removal_key, [])
                            if len(indices) != 1:
                                raise ValueError(
                                    f"removal selector matched {len(indices)} assertions "
                                    f"for {key}: {removal_key}"
                                )
                            removed_indices.add(indices[0])
                        row["assertions"] = [
                            assertion
                            for index, assertion in enumerate(assertions)
                            if index not in removed_indices
                        ]
                        counts["assertions_removed"] += len(removed_indices)
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                counts["records"] += 1

        missing = [key for key in proposals if matched[key] != 1]
        if missing:
            raise ValueError(
                f"{len(missing)} proposal segment(s) were not matched exactly once: {missing[:3]}"
            )
        os.replace(temp_path, output_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return {
        "input": str(input_path),
        "proposals": str(proposals_path),
        "output": str(output_path),
        "proposal_rows": sum(len(rows) for rows in proposals.values()),
        **dict(sorted(counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("proposals", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            apply_reviewed_proposals(args.input, args.proposals, args.output),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
