"""Prepare isolated botanical shape compounds for exact two-family machine review.

The deterministic baseline intentionally withholds every quality cue touching a hyphen or
slash.  Most of those spans are not safe to decompose blindly: they include standardized colour
names, mixtures, cross-aspect shape phrases, nested logical expressions, and unresolved bearers.
This module extracts one deliberately narrow review wave from that residual evidence:

* the complete token consists of exactly two distinct, gross-outline PATO values joined by one
  printed dash;
* both endpoint spans are still unresolved and no other unresolved evidence or assertion overlaps
  the token;
* no adjacent logical, range, temporal, modal, negated, seasonal, or subregion context survives;
* both endpoints resolve to one identical local PO bearer, or to the same typed organ heading; and
* the bearer--shape combination is already allowed by the frozen combination catalog.

Every candidate remains only a source-bound ``structured_qualitative_relation`` proposal.  This
pass does not mutate the input, does not mint a FLOPO/PATO class, and does not itself admit an
assertion.  It emits a one-row-per-input-span conservation ledger so that all excluded evidence is
accounted for as well as the candidate wave.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from flopo2.extract import baseline
from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import QualitativeRelationCandidate, QualitativeRelationSignature
from flopo2.verify.recover_exact_pato_compounds import (
    BearerResolution,
    BearerResolver,
    _compound_bounds,
    _nearby_context_reason,
    _unsafe_bearer_scope,
)


TARGET_REASON = "hyphenated_or_slash_compound"
REVIEW_REASON = "shape_compound_continuum_candidate"
EXTRACTOR = "shape_compound_continuum_candidate_v1"
SHAPE_ATTRIBUTE = "PATO_0000052"

# These are comparable gross-outline values.  Acuminate, attenuate, obtuse, and related terms
# share PATO's broad shape family but describe a different aspect (usually apex/base shape) and
# must not be turned into a gross-outline continuum merely because a dash joins the words.
GROSS_OUTLINE_VALUES = frozenset(
    {
        "PATO_0000946",  # oblong
        "PATO_0000947",  # elliptic
        "PATO_0001199",  # linear
        "PATO_0001877",  # lanceolate
        "PATO_0001891",  # ovate
    }
)

_DASH_ONLY = re.compile(r"\s*[-\u2013\u2014]\s*")
_ADJACENT_OPERATOR_LEFT = re.compile(
    r"\b(?:or|ou|and|et|to|through|vers|jusqu['’]?à|jusqu['’]?a|à|au)\s*$",
    re.IGNORECASE,
)
_ADJACENT_OPERATOR_RIGHT = re.compile(
    r"^\s*(?:or|ou|and|et|to|through|vers|jusqu['’]?à|jusqu['’]?a|à|au)\b",
    re.IGNORECASE,
)

SegmentKey = tuple[str, str, int, str]
SpanKey = tuple[str, str, int, str, int, int, str, str]


def _segment_key(record: dict[str, Any]) -> SegmentKey:
    return (
        str(record.get("source", "") or ""),
        str(record.get("source_id", "") or ""),
        int(record.get("source_segment_index", 0) or 0),
        str(record.get("taxon", "") or ""),
    )


def _span_key(record: dict[str, Any], span: dict[str, Any]) -> SpanKey:
    source, source_id, segment, taxon = _segment_key(record)
    return (
        source,
        source_id,
        segment,
        taxon,
        int(span.get("start", -1)),
        int(span.get("end", -1)),
        str(span.get("surface_form", "") or ""),
        str(span.get("candidate_pato_id", "") or ""),
    )


def _load_ids(path: Path) -> tuple[set[str], set[str]]:
    identifiers: set[str] = set()
    attributes: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            identifier = str(row.get("id", "") or "")
            if identifier:
                identifiers.add(identifier)
                if "attribute_slim" in str(row.get("slim", "") or "").split("|"):
                    attributes.add(identifier)
    return identifiers, attributes


def _load_combinations(path: Path) -> dict[tuple[str, str], str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (str(row.get("po_id", "") or ""), str(row.get("pato_id", "") or "")): str(
                row.get("status", "") or ""
            )
            for row in csv.DictReader(handle, delimiter="\t")
        }


def _overlaps(assertion: dict[str, Any], start: int, end: int) -> bool:
    try:
        other_start = int(assertion.get("source_start", -1))
        other_end = int(assertion.get("source_end", -1))
    except (TypeError, ValueError):
        return False
    return other_start < end and start < other_end


def _bearer_evidence(
    text: str, bearer: BearerResolution, quality_start: int
) -> tuple[str, int | None, int | None]:
    """Rebind a selected local bearer surface without inventing heading offsets."""

    if bearer.method not in {"explicit_local", "contextual_local"} or not bearer.surface_form:
        return "", None, None
    matches = list(re.finditer(re.escape(bearer.surface_form), text, re.IGNORECASE))
    if not matches:
        return "", None, None
    selected = min(matches, key=lambda match: abs(match.start() - quality_start))
    return text[selected.start() : selected.end()], selected.start(), selected.end()


def _validate_target_span(record: dict[str, Any], span: dict[str, Any]) -> None:
    text = str(record.get("text", "") or "")
    try:
        start, end = int(span["start"]), int(span["end"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("target compound span has invalid offsets") from error
    surface = str(span.get("surface_form", "") or "")
    if start < 0 or end <= start or end > len(text) or text[start:end] != surface:
        raise ValueError("target compound span is not verbatim in its source record")


def _candidate_for_group(
    record: dict[str, Any],
    target_spans: list[dict[str, Any]],
    expression_start: int,
    expression_end: int,
    *,
    resolver: BearerResolver,
    pato_ids: set[str],
    pato_attributes: set[str],
    combinations: dict[tuple[str, str], str],
) -> tuple[QualitativeRelationCandidate | None, str]:
    text = str(record.get("text", "") or "")
    all_unresolved = [
        span
        for span in (record.get("unresolved_spans", []) or [])
        if expression_start <= int(span.get("start", -1))
        and int(span.get("end", -1)) <= expression_end
    ]
    if len(target_spans) != 2 or len(all_unresolved) != 2:
        return None, "not_exactly_two_unresolved_endpoints"
    ordered = sorted(target_spans, key=lambda span: int(span["start"]))
    left, right = ordered
    left_start, left_end = int(left["start"]), int(left["end"])
    right_start, right_end = int(right["start"]), int(right["end"])
    endpoint_ids = (
        str(left.get("candidate_pato_id", "") or ""),
        str(right.get("candidate_pato_id", "") or ""),
    )
    if (
        endpoint_ids[0] == endpoint_ids[1]
        or any(identifier not in GROSS_OUTLINE_VALUES for identifier in endpoint_ids)
    ):
        return None, "not_two_distinct_gross_outline_values"
    if any(identifier not in pato_ids for identifier in (*endpoint_ids, SHAPE_ATTRIBUTE)):
        return None, "unknown_pato_identifier"
    if SHAPE_ATTRIBUTE not in pato_attributes:
        return None, "shape_attribute_not_pato_attribute"
    if left_start != expression_start or right_end != expression_end:
        return None, "endpoint_spans_do_not_cover_complete_token"
    connector = text[left_end:right_start]
    if not _DASH_ONLY.fullmatch(connector):
        return None, "connector_is_not_one_printed_dash"
    dash = re.search(r"[-\u2013\u2014]", connector)
    if dash is None:  # Defensive: the full-match above already requires one.
        return None, "connector_dash_not_locatable"
    connector_start = left_end + dash.start()
    connector_end = left_end + dash.end()
    if any(
        _overlaps(assertion, expression_start, expression_end)
        for assertion in (record.get("assertions", []) or [])
    ):
        return None, "overlapping_existing_assertion"
    if baseline._unmodelled_bearer_category(text, expression_start):
        return None, "unmodelled_bearer_category"
    contextual = _nearby_context_reason(text, expression_start, expression_end)
    if contextual:
        return None, contextual
    modalities, _modality_start, modality_text = baseline._modality_context(
        text, expression_start
    )
    if modalities or modality_text:
        return None, "modal_or_frequency_context"
    seasons, _season_operator, _season_start, _season_end = baseline._season_context(
        text, expression_start, expression_end
    )
    if seasons:
        return None, "season_context"
    clause, clause_start = baseline._clause_at(text, expression_start)
    local_start = expression_start - clause_start
    local_end = expression_end - clause_start
    before = clause[max(0, local_start - 80) : local_start]
    after = clause[local_end : min(len(clause), local_end + 80)]
    if _ADJACENT_OPERATOR_LEFT.search(before) or _ADJACENT_OPERATOR_RIGHT.match(after):
        return None, "adjacent_logical_or_range_operator"

    bearer_rows = tuple(
        resolver.resolve(record, expression_start, expression_end, endpoint_id)
        for endpoint_id in endpoint_ids
    )
    if any(
        not bearer.po_id
        or bearer.method not in {"explicit_local", "contextual_local", "organ_heading"}
        for bearer in bearer_rows
    ):
        return None, "bearer_not_resolved_to_reviewable_po_context"
    if len({bearer.po_id for bearer in bearer_rows}) != 1:
        return None, "endpoint_bearers_disagree"
    bearer = bearer_rows[0]
    unsafe = _unsafe_bearer_scope(text, expression_start, expression_end, bearer)
    if unsafe is not None:
        return None, f"unsafe_bearer_scope:{unsafe[0]}"
    if combinations.get((bearer.po_id, SHAPE_ATTRIBUTE), "novel") != "allowed":
        return None, "bearer_shape_combination_not_allowed"

    bearer_text, bearer_start, bearer_end = _bearer_evidence(
        text, bearer, expression_start
    )
    signature = QualitativeRelationSignature(
        bearer_id=bearer.po_id,
        attribute_id=SHAPE_ATTRIBUTE,
        interpretation="continuum",
        from_value=endpoint_ids[0],
        to_value=endpoint_ids[1],
    )
    candidate = QualitativeRelationCandidate(
        signature=signature,
        bearer_method=bearer.method,
        bearer_text=bearer_text,
        bearer_start=bearer_start,
        bearer_end=bearer_end,
        expression_start=expression_start,
        expression_end=expression_end,
        expression_text=text[expression_start:expression_end],
        from_text=text[left_start:left_end],
        from_start=left_start,
        from_end=left_end,
        connector_text=text[connector_start:connector_end],
        connector_start=connector_start,
        connector_end=connector_end,
        to_text=text[right_start:right_end],
        to_start=right_start,
        to_end=right_end,
        clear_unresolved_spans=((left_start, left_end), (right_start, right_end)),
    )
    return candidate, ""


def _write_immutable_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed derived artifact: {path}")
    atomic_write_text(path, payload)


def _write_immutable_report(path: Path, report: dict[str, Any]) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed report: {path}")
    atomic_write_text(path, payload)


def prepare_shape_compound_review(
    *,
    stage_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    span_ledger_path: Path,
    report_path: Path,
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Extract immutable candidates and conserve every target residual span."""

    paths = (
        stage_path,
        review_input_path,
        candidate_ledger_path,
        span_ledger_path,
        report_path,
        po_lexicon_path,
        pato_lexicon_path,
        combinations_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("shape compound inputs and outputs must resolve to distinct paths")
    resolver = BearerResolver(po_lexicon_path)
    pato_ids, pato_attributes = _load_ids(pato_lexicon_path)
    combinations = _load_combinations(combinations_path)
    counts: Counter[str] = Counter()
    candidate_records: list[dict[str, Any]] = []
    candidate_ledger: list[dict[str, Any]] = []
    span_ledger: list[dict[str, Any]] = []
    seen_span_keys: set[SpanKey] = set()

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{stage_path}:{line_number}: invalid JSON") from error
            if not isinstance(record, dict):
                raise ValueError(f"{stage_path}:{line_number}: record must be an object")
            text = str(record.get("text", "") or "")
            targets = [
                span
                for span in (record.get("unresolved_spans", []) or [])
                if isinstance(span, dict) and span.get("reason") == TARGET_REASON
            ]
            groups: defaultdict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
            for span in targets:
                _validate_target_span(record, span)
                key = _span_key(record, span)
                if key in seen_span_keys:
                    raise ValueError(f"duplicate physical target span: {key}")
                seen_span_keys.add(key)
                groups[
                    _compound_bounds(text, int(span["start"]), int(span["end"]))
                ].append(span)
                counts["target_spans"] += 1

            synthetic_spans: list[dict[str, Any]] = []
            dispositions: dict[SpanKey, dict[str, Any]] = {}
            used_clear_ranges: set[tuple[int, int]] = set()
            for (expression_start, expression_end), members in sorted(groups.items()):
                candidate, exclusion_reason = _candidate_for_group(
                    record,
                    members,
                    expression_start,
                    expression_end,
                    resolver=resolver,
                    pato_ids=pato_ids,
                    pato_attributes=pato_attributes,
                    combinations=combinations,
                )
                if candidate is None:
                    reason = exclusion_reason or "candidate_construction_failed"
                    for span in members:
                        dispositions[_span_key(record, span)] = {
                            "status": "excluded",
                            "reason": reason,
                            "candidate_id": "",
                        }
                        counts[f"excluded:{reason}"] += 1
                    continue
                clear_ranges = set(candidate.clear_unresolved_spans)
                if overlap := used_clear_ranges.intersection(clear_ranges):
                    raise ValueError(f"overlapping candidate clear ranges: {sorted(overlap)}")
                used_clear_ranges.update(clear_ranges)
                candidate_id = stable_id(
                    "shapecomp",
                    (
                        *_segment_key(record),
                        candidate.expression_start,
                        candidate.expression_end,
                        candidate.signature.model_dump(mode="json"),
                    ),
                )
                synthetic_spans.append(
                    {
                        "start": candidate.expression_start,
                        "end": candidate.expression_end,
                        "surface_form": candidate.expression_text,
                        "reason": REVIEW_REASON,
                        "candidate_pato_id": SHAPE_ATTRIBUTE,
                        "pending_bearer": candidate.signature.bearer_id,
                        "extractor": EXTRACTOR,
                        "candidate_id": candidate_id,
                        "qualitative_relation_candidate": candidate.model_dump(mode="json"),
                    }
                )
                candidate_ledger.append(
                    {
                        "candidate_id": candidate_id,
                        "source": record.get("source", ""),
                        "source_id": record.get("source_id", ""),
                        "source_segment_index": int(
                            record.get("source_segment_index", 0) or 0
                        ),
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                for span in members:
                    dispositions[_span_key(record, span)] = {
                        "status": "candidate",
                        "reason": REVIEW_REASON,
                        "candidate_id": candidate_id,
                    }
                    counts["candidate_spans"] += 1
                counts["candidates"] += 1
                counts[f"candidate_bearer_method:{candidate.bearer_method}"] += 1
                counts[
                    "candidate_pair:"
                    f"{candidate.signature.from_value}>{candidate.signature.to_value}"
                ] += 1

            for span in targets:
                key = _span_key(record, span)
                disposition = dispositions.get(key)
                if disposition is None:
                    # A target sharing token bounds with another group member still requires its
                    # own terminal row even when the group was not eligible.
                    disposition = {
                        "status": "excluded",
                        "reason": "target_not_accounted_by_compound_group",
                        "candidate_id": "",
                    }
                    counts["excluded:target_not_accounted_by_compound_group"] += 1
                span_ledger.append(
                    {
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "taxon": key[3],
                        "start": key[4],
                        "end": key[5],
                        "surface_form": key[6],
                        "candidate_pato_id": key[7],
                        **disposition,
                    }
                )
            if synthetic_spans:
                synthetic_spans.sort(
                    key=lambda span: (span["start"], span["end"], span["candidate_id"])
                )
                candidate_records.append(
                    {
                        "source": record.get("source", ""),
                        "source_id": record.get("source_id", ""),
                        "source_segment_index": int(
                            record.get("source_segment_index", 0) or 0
                        ),
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "language": record.get("language", ""),
                        "char_start": int(record.get("char_start", 0) or 0),
                        "char_end": int(record.get("char_end", len(text)) or len(text)),
                        "text": text,
                        "assertions": record.get("assertions", []) or [],
                        "term_mentions": record.get("term_mentions", []) or [],
                        "unresolved_spans": synthetic_spans,
                    }
                )

    if len(span_ledger) != counts["target_spans"]:
        raise ValueError("shape compound span ledger does not conserve the target scope")
    if counts["candidate_spans"] != 2 * counts["candidates"]:
        raise ValueError("every shape compound candidate must clear exactly two target spans")
    status_counts = Counter(row["status"] for row in span_ledger)
    if status_counts["candidate"] + status_counts["excluded"] != counts["target_spans"]:
        raise ValueError("shape compound dispositions are not exhaustive")

    candidate_records.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["taxon"],
        )
    )
    candidate_ledger.sort(key=lambda row: row["candidate_id"])
    span_ledger.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["taxon"],
            row["start"],
            row["end"],
            row["candidate_pato_id"],
        )
    )
    _write_immutable_rows(review_input_path, candidate_records)
    _write_immutable_rows(candidate_ledger_path, candidate_ledger)
    _write_immutable_rows(span_ledger_path, span_ledger)
    report = {
        "schema_version": "flopo-qualitative-candidate-report-v1",
        "input_scope": TARGET_REASON,
        "candidate_kind": REVIEW_REASON,
        "candidates": counts["candidates"],
        "exclusions": status_counts["excluded"],
        "target_spans": counts["target_spans"],
        "candidate_spans": status_counts["candidate"],
        "conserved": len(span_ledger) == counts["target_spans"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            # The generic qualitative materializer uses this historical key but validates the
            # hash against the caller-supplied baseline, which is Stage 15 for this campaign.
            "stage13": sha256_file(stage_path).model_dump(mode="json"),
            "review_input": sha256_file(review_input_path).model_dump(mode="json"),
            "candidate_ledger": sha256_file(candidate_ledger_path).model_dump(mode="json"),
            "span_ledger": sha256_file(span_ledger_path).model_dump(mode="json"),
            "po_lexicon": sha256_file(po_lexicon_path).model_dump(mode="json"),
            "pato_lexicon": sha256_file(pato_lexicon_path).model_dump(mode="json"),
            "combinations": sha256_file(combinations_path).model_dump(mode="json"),
        },
    }
    _write_immutable_report(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--review-input", type=Path, required=True)
    parser.add_argument("--candidate-ledger", type=Path, required=True)
    parser.add_argument("--span-ledger", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument(
        "--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = prepare_shape_compound_review(
        stage_path=args.stage,
        review_input_path=args.review_input,
        candidate_ledger_path=args.candidate_ledger,
        span_ledger_path=args.span_ledger,
        report_path=args.report,
        po_lexicon_path=args.po_lexicon,
        pato_lexicon_path=args.pato_lexicon,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
