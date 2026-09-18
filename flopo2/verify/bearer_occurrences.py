"""Build a lossless occurrence ledger for retained missing-bearer spans.

Group-level bearer routing is useful for estimating the curation workload, but it is not a safe
unit for promotion: the same word can be a bearer in one sentence and merely locative context in
another. This module records one immutable row per unresolved occurrence while preserving both
the original routing decision and the stricter context-recovery audit decision. It is inventory
only: review decisions are always left unset.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from flopo2.annotation.provenance import stable_statement_id
from flopo2.extract.baseline import _clause_at
from flopo2.extract.context_recovery import recover_record
from flopo2.verify.missing_bearers import (
    _classify as classify_bearer_candidate,
)
from flopo2.verify.missing_bearers import (
    _po_exact_forms,
    _po_forms,
    load_po_terms,
)

MISSING_REASON = "missing_or_unsupported_bearer"
AUDITED_REASONS = {"developmental_stage_context", MISSING_REASON}
ROUTE_FAMILIES = {
    # ``existing_po_context_review`` is the root branch's conservative name for vocabulary
    # reuse. It does not imply that assertion attachment has been accepted.
    "existing_po_context_review": "accepted_existing_po",
    "attachment_or_region_review": "attachment_review",
    "flopo_extension_candidate": "concept_review",
}


def _integer(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_occurrence_id(record: dict, span: dict) -> str:
    """Return an identifier over the immutable, source-scoped span coordinate."""

    payload = {
        "source": str(record.get("source", "") or ""),
        "source_id": str(record.get("source_id", "") or ""),
        "source_segment_index": _integer(record.get("source_segment_index")),
        "start": _integer(span.get("start"), -1),
        "end": _integer(span.get("end"), -1),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return f"bearer-occurrence-{digest}"


def _document_key(record: dict) -> tuple[str, str]:
    return str(record.get("source", "") or ""), str(record.get("source_id", "") or "")


def _neighbor(record: dict | None, current: dict) -> dict | None:
    if record is None or _document_key(record) != _document_key(current):
        return None
    return {
        "source_segment_index": _integer(record.get("source_segment_index")),
        "organ": str(record.get("organ", "") or ""),
        "text": str(record.get("text", "") or ""),
    }


def _records_with_neighbors(path: Path) -> Iterator[tuple[dict, dict | None, dict | None]]:
    """Stream records with adjacent document context without retaining the corpus in memory."""

    def records() -> Iterator[dict]:
        with Path(path).open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error

    iterator = iter(records())
    previous: dict | None = None
    current = next(iterator, None)
    following = next(iterator, None)
    while current is not None:
        yield current, _neighbor(previous, current), _neighbor(following, current)
        previous, current = current, following
        following = next(iterator, None)


def _scoped_audits(record: dict, audit: list[dict]) -> dict[int, dict]:
    """Align recovery audit rows to source spans and fail closed on schema drift."""

    scoped = [
        span
        for span in record.get("unresolved_spans", []) or []
        if span.get("reason") in AUDITED_REASONS
    ]
    if len(scoped) != len(audit):
        raise ValueError(
            "context-recovery audit no longer aligns with audited unresolved spans: "
            f"{_document_key(record)} segment {record.get('source_segment_index', 0)} has "
            f"{len(scoped)} scoped spans and {len(audit)} audit rows"
        )
    aligned: dict[int, dict] = {}
    for span, row in zip(scoped, audit, strict=True):
        expected = (
            str(span.get("reason", "") or ""),
            str(span.get("surface_form", "") or ""),
            str(span.get("candidate_pato_id", "") or ""),
        )
        observed = (
            str(row.get("reason", "") or ""),
            str(row.get("surface_form", "") or ""),
            str(row.get("candidate_pato_id", "") or ""),
        )
        if expected != observed:
            raise ValueError(f"context-recovery audit order drifted: {expected!r} != {observed!r}")
        aligned[id(span)] = row
    return aligned


def _route_family(disposition: str) -> str:
    try:
        return ROUTE_FAMILIES[disposition]
    except KeyError as error:
        raise ValueError(f"unknown missing-bearer disposition: {disposition!r}") from error


def _reconciliation(route_po_id: str, audit_po_id: str) -> tuple[str, str]:
    if route_po_id and audit_po_id and route_po_id == audit_po_id:
        return "agree_existing_same_po", route_po_id
    if route_po_id and audit_po_id:
        return "existing_po_conflict", ""
    if audit_po_id:
        return "recovery_only_existing_po", ""
    if route_po_id:
        return "routing_only_existing_po", ""
    return "agree_review", ""


def _review_family(route_family: str, group_key: str, reconciliation_status: str) -> str:
    if reconciliation_status == "agree_existing_same_po":
        return "accepted_existing_po"
    if reconciliation_status in {
        "existing_po_conflict",
        "recovery_only_existing_po",
        "routing_only_existing_po",
    }:
        return "po_identity_review"
    if route_family == "attachment_review" and group_key == "unresolved_attachment":
        return "unresolved_contextual_bearer"
    return route_family


def _risk_tier(review_family: str, audit: dict) -> str:
    if review_family == "accepted_existing_po":
        if audit.get("attachment_status") == "container_attachment":
            return "high_container_or_part"
        if str(audit.get("method", "")).startswith("accepted_existing_po_candidate:"):
            return "high_syntax_fallback"
        return "medium_atomic_safety_hold"
    if review_family == "po_identity_review":
        return "critical_po_identity_conflict"
    if review_family == "unresolved_contextual_bearer":
        return "high_coreference"
    if review_family == "attachment_review":
        return "high_attachment_or_region"
    return "semantic_concept_review"


def _read_labels(path: Path) -> dict[str, str]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get("id", "") or ""): str(row.get("label", "") or "")
            for row in csv.DictReader(handle, delimiter="\t")
        }


def _occurrence_row(
    record: dict,
    span: dict,
    audit: dict,
    *,
    previous: dict | None,
    following: dict | None,
    candidate_po_forms: dict[tuple[str, ...], set[str]],
    po_terms: dict,
    pato_labels: dict[str, str],
) -> dict:
    text = str(record.get("text", "") or "")
    start = _integer(span.get("start"), -1)
    end = _integer(span.get("end"), -1)
    surface = str(span.get("surface_form", "") or "")
    if not (0 <= start <= end <= len(text)) or text[start:end] != surface:
        raise ValueError(
            f"non-verbatim unresolved span in {_document_key(record)} segment "
            f"{record.get('source_segment_index', 0)}: {(start, end, surface)!r}"
        )
    clause, clause_start = _clause_at(text, start)
    group_key, bearer_label, route_disposition, route_po_id, route_note = (
        classify_bearer_candidate(
            str(record.get("organ", "") or ""),
            clause,
            start - clause_start,
            candidate_po_forms,
        )
    )
    route_family = _route_family(route_disposition)
    audit_po_id = str(audit.get("bearer_po_id", "") or "")
    reconciliation_status, authoritative_po_id = _reconciliation(route_po_id, audit_po_id)
    review_family = _review_family(route_family, group_key, reconciliation_status)
    candidate_po_ids = list(dict.fromkeys(value for value in (route_po_id, audit_po_id) if value))
    candidate_terms = [po_terms[value] for value in candidate_po_ids if value in po_terms]
    terminal_state = (
        "already_recovered"
        if str(audit.get("disposition", "")).startswith("recovered")
        else "pending_review"
    )
    return {
        "occurrence_id": stable_occurrence_id(record, span),
        "source_statement_id": stable_statement_id(record, start, end, surface),
        "source": str(record.get("source", "") or ""),
        "source_id": str(record.get("source_id", "") or ""),
        "source_segment_index": _integer(record.get("source_segment_index")),
        "segment_document_start": _integer(record.get("char_start")),
        "segment_document_end": _integer(record.get("char_end")),
        "taxon": str(record.get("taxon", "") or ""),
        "organ": str(record.get("organ", "") or ""),
        "language": str(record.get("language", "") or ""),
        "text": text,
        "segment_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "previous_segment": previous,
        "next_segment": following,
        "quality": {
            "start": start,
            "end": end,
            "surface_form": surface,
            "candidate_pato_id": str(span.get("candidate_pato_id", "") or ""),
            "candidate_pato_label": pato_labels.get(
                str(span.get("candidate_pato_id", "") or ""), ""
            ),
            "extractor": str(span.get("extractor", "") or ""),
            "reason": str(span.get("reason", "") or ""),
        },
        "clause": {
            "start": clause_start,
            "end": clause_start + len(clause),
            "text": clause,
        },
        "routing": {
            "group_key": group_key,
            "bearer_label": bearer_label,
            "disposition": route_disposition,
            "family": route_family,
            "candidate_po_id": route_po_id,
            "note": route_note,
        },
        "context_audit": {
            "candidate_po_id": audit_po_id,
            "bearer_surface": str(audit.get("bearer_surface", "") or ""),
            "vocabulary_status": str(audit.get("vocabulary_status", "") or ""),
            "attachment_status": str(audit.get("attachment_status", "") or ""),
            "disposition": str(audit.get("disposition", "") or ""),
            "method": str(audit.get("method", "") or ""),
        },
        "review": {
            "family": review_family,
            "risk_tier": _risk_tier(review_family, audit),
            "reconciliation_status": reconciliation_status,
            "authoritative_po_id": authoritative_po_id,
            "candidate_po_ids": candidate_po_ids,
            "candidate_po_terms": [
                {
                    "po_id": term.po_id,
                    "label": term.label,
                    "definition": term.definition,
                    "parents": list(term.parents),
                    "part_of": list(term.part_of),
                }
                for term in candidate_terms
            ],
            "terminal_state": terminal_state,
            "decision": None,
        },
    }


def build_occurrence_ledger(
    input_path: Path,
    output_path: Path,
    summary_path: Path,
    *,
    po_obo: Path = Path("ont/plant_ontology.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    reviewed_bearers: Path = Path("config/reviewed_local_bearers.tsv"),
    expected: dict[str, int] | None = None,
) -> dict[str, object]:
    """Write one JSON object per missing-bearer occurrence plus conservation statistics."""

    paths = [Path(input_path).resolve(), Path(output_path).resolve(), Path(summary_path).resolve()]
    if len(paths) != len(set(paths)):
        raise ValueError("ledger input, output, and summary paths must all be distinct")
    po_forms = _po_exact_forms(po_obo, reviewed_bearers)
    candidate_po_forms = _po_forms(po_lexicon, reviewed_bearers)
    po_terms = load_po_terms(po_obo)
    pato_labels = _read_labels(pato_lexicon)
    counts: Counter[str] = Counter()
    route_families: Counter[str] = Counter()
    review_families: Counter[str] = Counter()
    risk_tiers: Counter[str] = Counter()
    route_groups: Counter[str] = Counter()
    review_groups: Counter[str] = Counter()
    reconciliation_statuses: Counter[str] = Counter()
    occurrence_ids: set[str] = set()
    coordinate_keys: set[tuple[str, str, int, int, int]] = set()

    output_path = Path(output_path)
    summary_path = Path(summary_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        for record, previous, following in _records_with_neighbors(input_path):
            counts["records"] += 1
            _recovered, audit_rows = recover_record(record, po_forms, candidate_po_forms)
            audits = _scoped_audits(record, audit_rows)
            for span in record.get("unresolved_spans", []) or []:
                if span.get("reason") != MISSING_REASON:
                    continue
                counts["original_missing_spans"] += 1
                audit = audits[id(span)]
                row = _occurrence_row(
                    record,
                    span,
                    audit,
                    previous=previous,
                    following=following,
                    candidate_po_forms=candidate_po_forms,
                    po_terms=po_terms,
                    pato_labels=pato_labels,
                )
                occurrence_id = row["occurrence_id"]
                if occurrence_id in occurrence_ids:
                    raise ValueError(f"duplicate bearer occurrence ID: {occurrence_id}")
                occurrence_ids.add(occurrence_id)
                coordinate_key = (
                    row["source"],
                    row["source_id"],
                    row["source_segment_index"],
                    row["quality"]["start"],
                    row["quality"]["end"],
                )
                if coordinate_key in coordinate_keys:
                    raise ValueError(f"duplicate bearer occurrence coordinate: {coordinate_key!r}")
                coordinate_keys.add(coordinate_key)
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                if row["review"]["terminal_state"] == "already_recovered":
                    counts["recovered_missing_spans"] += 1
                    continue
                counts["retained_missing_spans"] += 1
                route_family = row["routing"]["family"]
                review_family = row["review"]["family"]
                route_families[route_family] += 1
                review_families[review_family] += 1
                risk_tiers[row["review"]["risk_tier"]] += 1
                route_groups[
                    f"{row['routing']['group_key']}|{row['routing']['candidate_po_id']}"
                ] += 1
                candidate_key = "|".join(row["review"]["candidate_po_ids"])
                review_groups[f"{row['routing']['group_key']}|{candidate_key}"] += 1
                reconciliation_statuses[row["review"]["reconciliation_status"]] += 1

    if counts["original_missing_spans"] != (
        counts["recovered_missing_spans"] + counts["retained_missing_spans"]
    ):
        raise ValueError("missing-bearer conservation failed")
    observed = {
        "original_missing_spans": counts["original_missing_spans"],
        "recovered_missing_spans": counts["recovered_missing_spans"],
        "retained_missing_spans": counts["retained_missing_spans"],
        **{f"route_{key}": value for key, value in route_families.items()},
        **{f"review_{key}": value for key, value in review_families.items()},
    }
    if expected:
        mismatches = {
            key: {"expected": value, "observed": observed.get(key, 0)}
            for key, value in expected.items()
            if observed.get(key, 0) != value
        }
        if mismatches:
            raise ValueError(f"canonical occurrence expectations failed: {mismatches}")

    summary: dict[str, object] = {
        "schema_version": 1,
        "input": str(Path(input_path).resolve()),
        "input_sha256": _sha256(input_path),
        "output": str(output_path.resolve()),
        "counts": dict(sorted(counts.items())),
        "route_families": dict(sorted(route_families.items())),
        "review_families": dict(sorted(review_families.items())),
        "risk_tiers": dict(sorted(risk_tiers.items())),
        "reconciliation_statuses": dict(sorted(reconciliation_statuses.items())),
        "route_group_count": len(route_groups),
        "review_group_count": len(review_groups),
        "route_groups": dict(route_groups.most_common()),
        "review_groups": dict(review_groups.most_common()),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--reviewed-bearers", type=Path, default=Path("config/reviewed_local_bearers.tsv")
    )
    parser.add_argument("--expect-original", type=int)
    parser.add_argument("--expect-recovered", type=int)
    parser.add_argument("--expect-retained", type=int)
    args = parser.parse_args()
    expected = {
        key: value
        for key, value in {
            "original_missing_spans": args.expect_original,
            "recovered_missing_spans": args.expect_recovered,
            "retained_missing_spans": args.expect_retained,
        }.items()
        if value is not None
    }
    summary = build_occurrence_ledger(
        args.input,
        args.output,
        args.summary,
        po_obo=args.po_obo,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
        reviewed_bearers=args.reviewed_bearers,
        expected=expected,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
