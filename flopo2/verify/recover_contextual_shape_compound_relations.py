"""Prepare a second, non-overlapping review wave for contextual shape compounds.

The isolated first wave deliberately rejects a complete compound whenever any surrounding
operator, modifier, season, developmental cue, or bearer-scope warning is present.  Some of those
warnings belong to a neighbouring character rather than to the compound itself.  This module
reconsiders only spans that the first wave conserved as excluded, keeps the same exact two-endpoint
and bearer bindings, and delegates the contextual scope decision to two independent model
families.  It never requeues a first-wave candidate and never mutates the baseline corpus.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from flopo2.extract import baseline
from flopo2.review.io import sha256_file, stable_id
from flopo2.review.models import QualitativeRelationCandidate, QualitativeRelationSignature
from flopo2.verify.recover_exact_pato_compounds import (
    BearerResolver,
    _compound_bounds,
    _nearby_context_reason,
    _unsafe_bearer_scope,
)
from flopo2.verify.recover_shape_compound_relations import (
    GROSS_OUTLINE_VALUES,
    SHAPE_ATTRIBUTE,
    TARGET_REASON,
    SpanKey,
    _bearer_evidence,
    _load_combinations,
    _load_ids,
    _overlaps,
    _segment_key,
    _span_key,
    _validate_target_span,
    _write_immutable_report,
    _write_immutable_rows,
)


REVIEW_REASON = "contextual_shape_compound_continuum_candidate"
EXTRACTOR = "contextual_shape_compound_continuum_candidate_v1"
_DASH_ONLY = re.compile(r"\s*[-\u2013\u2014]\s*")
_ADJACENT_OPERATOR_LEFT = re.compile(
    r"\b(?:or|ou|and|et|to|through|vers|jusqu['’]?à|jusqu['’]?a|à|au)\s*$",
    re.IGNORECASE,
)
_ADJACENT_OPERATOR_RIGHT = re.compile(
    r"^\s*(?:or|ou|and|et|to|through|vers|jusqu['’]?à|jusqu['’]?a|à|au)\b",
    re.IGNORECASE,
)


def _load_prior_ledger(path: Path) -> dict[SpanKey, dict[str, Any]]:
    rows: dict[SpanKey, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            key: SpanKey = (
                str(row.get("source", "") or ""),
                str(row.get("source_id", "") or ""),
                int(row.get("source_segment_index", 0) or 0),
                str(row.get("taxon", "") or ""),
                int(row.get("start", -1)),
                int(row.get("end", -1)),
                str(row.get("surface_form", "") or ""),
                str(row.get("candidate_pato_id", "") or ""),
            )
            if key in rows:
                raise ValueError(f"{path}:{line_number}: duplicate prior span ledger row")
            if row.get("status") not in {"candidate", "excluded"}:
                raise ValueError(f"{path}:{line_number}: invalid prior disposition")
            rows[key] = row
    return rows


def _risk_flags(
    record: dict[str, Any],
    start: int,
    end: int,
    bearer,
) -> tuple[str, ...]:
    text = str(record.get("text", "") or "")
    flags: list[str] = []
    if reason := _nearby_context_reason(text, start, end):
        flags.append(reason)
    modalities, _modality_start, modality_text = baseline._modality_context(text, start)
    if modalities or modality_text:
        flags.append("modal_or_frequency_context")
    seasons, _operator, _season_start, _season_end = baseline._season_context(
        text, start, end
    )
    if seasons:
        flags.append("season_context")
    if baseline._unmodelled_bearer_category(text, start):
        flags.append("unmodelled_bearer_category")
    if unsafe := _unsafe_bearer_scope(text, start, end, bearer):
        flags.append(f"unsafe_bearer_scope:{unsafe[0]}")
    clause, clause_start = baseline._clause_at(text, start)
    local_start, local_end = start - clause_start, end - clause_start
    before = clause[max(0, local_start - 80) : local_start]
    after = clause[local_end : min(len(clause), local_end + 80)]
    if _ADJACENT_OPERATOR_LEFT.search(before) or _ADJACENT_OPERATOR_RIGHT.match(after):
        flags.append("adjacent_logical_or_range_operator")
    return tuple(dict.fromkeys(flags))


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
) -> tuple[QualitativeRelationCandidate | None, str, tuple[str, ...]]:
    text = str(record.get("text", "") or "")
    all_unresolved = [
        span
        for span in (record.get("unresolved_spans", []) or [])
        if expression_start <= int(span.get("start", -1))
        and int(span.get("end", -1)) <= expression_end
    ]
    if len(target_spans) != 2 or len(all_unresolved) != 2:
        return None, "not_exactly_two_unresolved_endpoints", ()
    left, right = sorted(target_spans, key=lambda span: int(span["start"]))
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
        return None, "not_two_distinct_gross_outline_values", ()
    if any(identifier not in pato_ids for identifier in (*endpoint_ids, SHAPE_ATTRIBUTE)):
        return None, "unknown_pato_identifier", ()
    if SHAPE_ATTRIBUTE not in pato_attributes:
        return None, "shape_attribute_not_pato_attribute", ()
    if left_start != expression_start or right_end != expression_end:
        return None, "endpoint_spans_do_not_cover_complete_token", ()
    connector = text[left_end:right_start]
    if not _DASH_ONLY.fullmatch(connector):
        return None, "connector_is_not_one_printed_dash", ()
    dash = re.search(r"[-\u2013\u2014]", connector)
    if dash is None:
        return None, "connector_dash_not_locatable", ()
    if any(
        _overlaps(assertion, expression_start, expression_end)
        for assertion in (record.get("assertions", []) or [])
    ):
        return None, "overlapping_existing_assertion", ()

    bearer_rows = tuple(
        resolver.resolve(record, expression_start, expression_end, endpoint_id)
        for endpoint_id in endpoint_ids
    )
    if any(
        not bearer.po_id
        or bearer.method not in {"explicit_local", "contextual_local", "organ_heading"}
        for bearer in bearer_rows
    ):
        return None, "bearer_not_resolved_to_reviewable_po_context", ()
    if len({bearer.po_id for bearer in bearer_rows}) != 1:
        return None, "endpoint_bearers_disagree", ()
    bearer = bearer_rows[0]
    if combinations.get((bearer.po_id, SHAPE_ATTRIBUTE), "novel") != "allowed":
        return None, "bearer_shape_combination_not_allowed", ()

    bearer_text, bearer_start, bearer_end = _bearer_evidence(
        text, bearer, expression_start
    )
    connector_start = left_end + dash.start()
    connector_end = left_end + dash.end()
    candidate = QualitativeRelationCandidate(
        signature=QualitativeRelationSignature(
            bearer_id=bearer.po_id,
            attribute_id=SHAPE_ATTRIBUTE,
            interpretation="continuum",
            from_value=endpoint_ids[0],
            to_value=endpoint_ids[1],
        ),
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
    return candidate, "", _risk_flags(
        record, expression_start, expression_end, bearer
    )


def prepare_contextual_shape_compound_review(
    *,
    stage_path: Path,
    prior_span_ledger_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    span_ledger_path: Path,
    report_path: Path,
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Reconsider first-wave exclusions while preserving exact span conservation."""

    paths = (
        stage_path,
        prior_span_ledger_path,
        review_input_path,
        candidate_ledger_path,
        span_ledger_path,
        report_path,
        po_lexicon_path,
        pato_lexicon_path,
        combinations_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("contextual shape inputs and outputs must resolve to distinct paths")
    prior = _load_prior_ledger(prior_span_ledger_path)
    resolver = BearerResolver(po_lexicon_path)
    pato_ids, pato_attributes = _load_ids(pato_lexicon_path)
    combinations = _load_combinations(combinations_path)
    counts: Counter[str] = Counter()
    candidate_records: list[dict[str, Any]] = []
    candidate_ledger: list[dict[str, Any]] = []
    span_ledger: list[dict[str, Any]] = []
    seen_stage_keys: set[SpanKey] = set()

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            text = str(record.get("text", "") or "")
            all_targets = [
                span
                for span in (record.get("unresolved_spans", []) or [])
                if isinstance(span, dict) and span.get("reason") == TARGET_REASON
            ]
            targets: list[dict[str, Any]] = []
            for span in all_targets:
                _validate_target_span(record, span)
                key = _span_key(record, span)
                if key in seen_stage_keys:
                    raise ValueError(f"duplicate physical target span: {key}")
                seen_stage_keys.add(key)
                previous = prior.get(key)
                if previous is None:
                    raise ValueError(
                        f"{stage_path}:{line_number}: target absent from prior span ledger"
                    )
                if previous["status"] == "excluded":
                    targets.append(span)
                    counts["target_spans"] += 1
                else:
                    counts["prior_candidate_spans_skipped"] += 1

            groups: defaultdict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
            for span in targets:
                groups[_compound_bounds(text, int(span["start"]), int(span["end"]))].append(
                    span
                )
            synthetic: list[dict[str, Any]] = []
            dispositions: dict[SpanKey, dict[str, Any]] = {}
            for (start, end), members in sorted(groups.items()):
                candidate, exclusion, risks = _candidate_for_group(
                    record,
                    members,
                    start,
                    end,
                    resolver=resolver,
                    pato_ids=pato_ids,
                    pato_attributes=pato_attributes,
                    combinations=combinations,
                )
                prior_reasons = tuple(
                    sorted({str(prior[_span_key(record, span)]["reason"]) for span in members})
                )
                if candidate is None:
                    reason = exclusion or "candidate_construction_failed"
                    for span in members:
                        dispositions[_span_key(record, span)] = {
                            "status": "excluded",
                            "reason": reason,
                            "candidate_id": "",
                            "prior_reasons": list(prior_reasons),
                        }
                        counts[f"excluded:{reason}"] += 1
                    continue
                candidate_id = stable_id(
                    "ctxshape",
                    (
                        *_segment_key(record),
                        candidate.expression_start,
                        candidate.expression_end,
                        candidate.signature.model_dump(mode="json"),
                    ),
                )
                synthetic.append(
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
                        "prior_reasons": list(prior_reasons),
                        "risk_flags": list(risks),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                for span in members:
                    dispositions[_span_key(record, span)] = {
                        "status": "candidate",
                        "reason": REVIEW_REASON,
                        "candidate_id": candidate_id,
                        "prior_reasons": list(prior_reasons),
                    }
                    counts["candidate_spans"] += 1
                counts["candidates"] += 1
                counts[f"candidate_bearer_method:{candidate.bearer_method}"] += 1
                for risk in risks or ("no_runner_risk_flag",):
                    counts[f"candidate_risk:{risk}"] += 1

            for span in targets:
                key = _span_key(record, span)
                disposition = dispositions.get(key)
                if disposition is None:
                    disposition = {
                        "status": "excluded",
                        "reason": "target_not_accounted_by_compound_group",
                        "candidate_id": "",
                        "prior_reasons": [str(prior[key]["reason"])],
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
            if synthetic:
                synthetic.sort(key=lambda span: (span["start"], span["end"]))
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
                        "unresolved_spans": synthetic,
                    }
                )

    if set(prior) != seen_stage_keys:
        extras = sorted(set(prior) - seen_stage_keys)
        raise ValueError(f"prior span ledger has targets absent from Stage: {extras[:3]}")
    if len(span_ledger) != counts["target_spans"]:
        raise ValueError("contextual span ledger does not conserve first-wave exclusions")
    if counts["candidate_spans"] != 2 * counts["candidates"]:
        raise ValueError("every contextual shape candidate must bind two residual spans")
    statuses = Counter(row["status"] for row in span_ledger)
    if statuses["candidate"] + statuses["excluded"] != counts["target_spans"]:
        raise ValueError("contextual shape dispositions are not exhaustive")

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
        "input_scope": f"{TARGET_REASON}:first_wave_excluded_only",
        "candidate_kind": REVIEW_REASON,
        "candidates": counts["candidates"],
        "exclusions": statuses["excluded"],
        "target_spans": counts["target_spans"],
        "candidate_spans": statuses["candidate"],
        "conserved": len(span_ledger) == counts["target_spans"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage13": sha256_file(stage_path).model_dump(mode="json"),
            "review_input": sha256_file(review_input_path).model_dump(mode="json"),
            "candidate_ledger": sha256_file(candidate_ledger_path).model_dump(mode="json"),
            "span_ledger": sha256_file(span_ledger_path).model_dump(mode="json"),
            "prior_span_ledger": sha256_file(prior_span_ledger_path).model_dump(
                mode="json"
            ),
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
    parser.add_argument("--prior-span-ledger", type=Path, required=True)
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
    report = prepare_contextual_shape_compound_review(
        stage_path=args.stage,
        prior_span_ledger_path=args.prior_span_ledger,
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
