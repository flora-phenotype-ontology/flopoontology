"""Recover additional source-bound qualitative ranges for independent LLM review.

The first qualitative campaign admitted only decisions whose historical analysis already carried
a bearer.  This second wave revisits the remaining high-confidence, two-endpoint continua and
resolves their bearer against the current frozen corpus and PO lexicon.  Historical decisions are
candidate-generation evidence only: every occurrence is rebound to verbatim text, exact current
unresolved spans, live ontology identifiers, and an allowed bearer/attribute combination before
it is sent to two independent model families.

Candidates from the first campaign are excluded by immutable expression identity.  This module
does not mutate the corpus and does not admit an assertion.
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
from flopo2.verify.recover_exact_pato_compounds import BearerResolver
from flopo2.verify.recover_qualitative_relations import (
    TARGET_DECISION,
    TARGET_INTERPRETATION,
    TARGET_RULE,
    _clear_targets,
    _load_combinations,
    _load_flopo_ids,
    _load_ids,
    _locate_relation,
    _overlaps,
    _pipe,
    _segment_key,
)


EXTRACTOR = "contextual_qualitative_relation_candidate_v1"
CANDIDATE_REASON = "contextual_qualitative_value_relation_candidate"
SegmentKey = tuple[str, str, int]


def _prior_expression_ids(path: Path) -> set[str]:
    identifiers: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid prior candidate JSON") from exc
            identifier = str(row.get("expression_uid", "") or "")
            if not identifier or identifier in identifiers:
                raise ValueError(f"{path}:{line_number}: missing or duplicate expression_uid")
            identifiers.add(identifier)
    return identifiers


def _eligible_decisions(
    path: Path,
    prior_ledger_path: Path,
) -> tuple[dict[SegmentKey, list[dict[str, str]]], Counter[str]]:
    prior = _prior_expression_ids(prior_ledger_path)
    grouped: defaultdict[SegmentKey, list[dict[str, str]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            counts["decision_rows"] += 1
            if row.get("decision") != TARGET_DECISION:
                counts["not_qualitative_range"] += 1
                continue
            if row.get("operator_interpretation") != TARGET_INTERPRETATION:
                counts["non_continuum_interpretation"] += 1
                continue
            if row.get("range_rule") != TARGET_RULE:
                counts["non_high_confidence_rule"] += 1
                continue
            if row.get("modifiers") or row.get("negation_guard"):
                counts["modified_or_negated"] += 1
                continue
            if not row.get("attribute_pato_id") or not row.get("family"):
                counts["missing_attribute_or_family"] += 1
                continue
            if len(_pipe(row.get("operand_term_ids"))) != 2:
                counts["not_exactly_two_grounded_endpoints"] += 1
                continue
            uid = str(row.get("expression_uid", "") or "")
            if not uid or uid in seen:
                raise ValueError(f"duplicate or missing expression identity: {uid!r}")
            seen.add(uid)
            counts["structurally_eligible_before_prior_exclusion"] += 1
            if uid in prior:
                counts["prior_candidate_skipped"] += 1
                continue
            grouped[_segment_key(row)].append(row)
            counts["structurally_eligible"] += 1
    return dict(grouped), counts


def _nearest_bearer_offsets(
    record: dict[str, Any],
    surface: str,
    expression_start: int,
    expression_end: int,
) -> tuple[str, int | None, int | None]:
    """Locate a resolver-returned surface in the same clause, without inventing evidence."""

    if not surface:
        return "", None, None
    text = str(record.get("text", "") or "")
    clause, clause_start = baseline._clause_at(text, expression_start)
    matches = list(re.finditer(re.escape(surface), clause, re.IGNORECASE))
    if not matches:
        return "", None, None

    def distance(match: re.Match[str]) -> tuple[int, int]:
        start = clause_start + match.start()
        end = clause_start + match.end()
        gap = max(expression_start - end, start - expression_end, 0)
        return gap, start

    selected = min(matches, key=distance)
    start = clause_start + selected.start()
    end = clause_start + selected.end()
    return text[start:end], start, end


def _candidate_for(
    record: dict[str, Any],
    row: dict[str, str],
    *,
    bearers: BearerResolver,
    po_ids: set[str],
    pato_ids: set[str],
    attribute_ids: set[str],
    flopo_ids: set[str],
    combinations: dict[tuple[str, str], str],
) -> tuple[QualitativeRelationCandidate | None, str, tuple[str, ...]]:
    rebound = dict(row)
    risk_flags: list[str] = []
    if not rebound.get("bearer_po_id"):
        start = int(rebound.get("expression_start", -1))
        end = int(rebound.get("expression_end", -1))
        endpoint_ids = _pipe(rebound.get("operand_term_ids"))
        if start < 0 or end <= start or len(endpoint_ids) != 2:
            return None, "invalid_expression_or_endpoint_accounting", ()
        resolution = bearers.resolve(record, start, end, endpoint_ids[0])
        if not resolution.po_id:
            return None, "bearer_not_resolved_to_reviewable_po_context", ()
        rebound["bearer_po_id"] = resolution.po_id
        rebound["bearer_method"] = resolution.method
        rebound["bearer_surface"] = resolution.surface_form
        risk_flags.append("live_bearer_recovery")

    candidate_data, reason = _locate_relation(record, rebound)
    if reason or candidate_data is None:
        return None, reason or "candidate_construction_failed", tuple(risk_flags)
    raw_signature = candidate_data["signature"]
    if raw_signature["from_value"] == raw_signature["to_value"]:
        return None, "identical_endpoints", tuple(risk_flags)
    try:
        signature = QualitativeRelationSignature.model_validate(raw_signature)
    except ValueError:
        return None, "invalid_candidate_signature", tuple(risk_flags)

    if signature.bearer_id.startswith("PO_") and signature.bearer_id not in po_ids:
        return None, "unknown_bearer_id", tuple(risk_flags)
    if signature.bearer_id.startswith("FLOPO_") and signature.bearer_id not in flopo_ids:
        return None, "unknown_bearer_id", tuple(risk_flags)
    if signature.attribute_id not in pato_ids:
        return None, "unknown_attribute_id", tuple(risk_flags)
    if signature.attribute_id not in attribute_ids:
        return None, "top_level_not_pato_attribute", tuple(risk_flags)
    if any(
        value.startswith("PATO_") and value not in pato_ids
        or value.startswith("FLOPO_") and value not in flopo_ids
        for value in (signature.from_value, signature.to_value)
    ):
        return None, "unknown_endpoint_id", tuple(risk_flags)
    if combinations.get((signature.bearer_id, signature.attribute_id), "novel") != "allowed":
        return None, "bearer_attribute_combination_not_allowed", tuple(risk_flags)

    clear_targets, reason = _clear_targets(record, candidate_data)
    if reason:
        return None, reason, tuple(risk_flags)
    candidate_data["clear_unresolved_spans"] = clear_targets
    if any(
        _overlaps(
            assertion,
            candidate_data["expression_start"],
            candidate_data["expression_end"],
        )
        for assertion in record.get("assertions", []) or []
    ):
        return None, "overlapping_existing_assertion", tuple(risk_flags)

    if candidate_data.get("bearer_start") is None:
        surface, start, end = _nearest_bearer_offsets(
            record,
            str(rebound.get("bearer_surface", "") or ""),
            candidate_data["expression_start"],
            candidate_data["expression_end"],
        )
        candidate_data["bearer_text"] = surface
        candidate_data["bearer_start"] = start
        candidate_data["bearer_end"] = end
    method = str(candidate_data.get("bearer_method", "") or "")
    if method == "organ_heading":
        risk_flags.append("organ_heading_bearer")
    if candidate_data.get("bearer_start") is None:
        risk_flags.append("bearer_without_local_offsets")
    return (
        QualitativeRelationCandidate.model_validate(candidate_data),
        "",
        tuple(dict.fromkeys(risk_flags)),
    )


def _immutable_text(path: Path, payload: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed derived artifact: {path}")
    atomic_write_text(path, payload)


def prepare_contextual_review_input(
    *,
    stage_path: Path,
    decisions_path: Path,
    prior_candidate_ledger_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    exclusions_path: Path,
    report_path: Path,
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Prepare a conserved second-wave candidate inventory without changing ``stage_path``."""

    inputs = {
        stage_path.resolve(),
        decisions_path.resolve(),
        prior_candidate_ledger_path.resolve(),
        po_lexicon.resolve(),
        pato_lexicon.resolve(),
        flopo_registry.resolve(),
        combinations_path.resolve(),
    }
    outputs = {
        review_input_path.resolve(),
        candidate_ledger_path.resolve(),
        exclusions_path.resolve(),
        report_path.resolve(),
    }
    if len(outputs) != 4 or inputs & outputs:
        raise ValueError("all contextual qualitative inputs and outputs must be distinct")

    grouped, counts = _eligible_decisions(decisions_path, prior_candidate_ledger_path)
    po_ids, _ = _load_ids(po_lexicon)
    pato_ids, attribute_ids = _load_ids(pato_lexicon)
    flopo_ids = _load_flopo_ids(flopo_registry)
    combinations = _load_combinations(combinations_path)
    bearers = BearerResolver(po_lexicon)
    wanted = set(grouped)
    found: set[SegmentKey] = set()
    review_records: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _segment_key(record)
            rows = grouped.get(key)
            if not rows:
                continue
            if key in found:
                raise ValueError(f"duplicate Stage segment identity at line {line_number}: {key}")
            found.add(key)
            prepared: list[tuple[dict[str, str], QualitativeRelationCandidate, tuple[str, ...]]] = []
            for row in rows:
                candidate, reason, risk_flags = _candidate_for(
                    record,
                    row,
                    bearers=bearers,
                    po_ids=po_ids,
                    pato_ids=pato_ids,
                    attribute_ids=attribute_ids,
                    flopo_ids=flopo_ids,
                    combinations=combinations,
                )
                if candidate is None:
                    exclusions.append(
                        {
                            "expression_uid": row.get("expression_uid", ""),
                            "source": key[0],
                            "source_id": key[1],
                            "source_segment_index": key[2],
                            "expression_start": row.get("expression_start", ""),
                            "expression_end": row.get("expression_end", ""),
                            "expression_text": row.get("expression_text", ""),
                            "reason": reason,
                            "risk_flags": list(risk_flags),
                        }
                    )
                    counts[f"excluded:{reason}"] += 1
                    continue
                prepared.append((row, candidate, risk_flags))

            clear_owners: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
            identities: defaultdict[tuple[Any, ...], list[int]] = defaultdict(list)
            for index, (_row, candidate, _risks) in enumerate(prepared):
                for clear_range in candidate.clear_unresolved_spans:
                    clear_owners[clear_range].append(index)
                identities[
                    (
                        candidate.expression_start,
                        candidate.expression_end,
                        candidate.signature,
                    )
                ].append(index)
            conflicted = {
                index
                for owners in clear_owners.values()
                if len(owners) > 1
                for index in owners
            } | {
                index
                for owners in identities.values()
                if len(owners) > 1
                for index in owners
            }
            synthetic_spans: list[dict[str, Any]] = []
            for index, (row, candidate, risk_flags) in enumerate(prepared):
                if index in conflicted:
                    exclusions.append(
                        {
                            "expression_uid": row.get("expression_uid", ""),
                            "source": key[0],
                            "source_id": key[1],
                            "source_segment_index": key[2],
                            "expression_start": row.get("expression_start", ""),
                            "expression_end": row.get("expression_end", ""),
                            "expression_text": row.get("expression_text", ""),
                            "reason": "competing_candidate_or_clear_target",
                            "risk_flags": list(risk_flags),
                        }
                    )
                    counts["excluded:competing_candidate_or_clear_target"] += 1
                    continue
                candidate_id = stable_id(
                    "ctxqual",
                    (
                        *key,
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
                        "reason": CANDIDATE_REASON,
                        "candidate_pato_id": candidate.signature.attribute_id,
                        "pending_bearer": candidate.signature.bearer_id,
                        "extractor": EXTRACTOR,
                        "candidate_id": candidate_id,
                        "qualitative_relation_candidate": candidate.model_dump(mode="json"),
                    }
                )
                ledger.append(
                    {
                        "candidate_id": candidate_id,
                        "expression_uid": row.get("expression_uid", ""),
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "family": row.get("family", ""),
                        "range_rule": row.get("range_rule", ""),
                        "risk_flags": list(risk_flags),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                counts["candidates"] += 1
                counts[f"candidate_family:{row.get('family', '')}"] += 1
                counts[f"candidate_bearer_method:{candidate.bearer_method}"] += 1
                for risk in risk_flags:
                    counts[f"candidate_risk:{risk}"] += 1
                counts["clear_targets"] += len(candidate.clear_unresolved_spans)
            if synthetic_spans:
                synthetic_spans.sort(
                    key=lambda span: (span["start"], span["end"], span["candidate_id"])
                )
                text = str(record.get("text", "") or "")
                review_records.append(
                    {
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "language": record.get("language", ""),
                        "char_start": record.get("char_start", 0),
                        "char_end": record.get("char_end", len(text)),
                        "text": text,
                        "unresolved_spans": synthetic_spans,
                    }
                )

    for missing in sorted(wanted - found):
        for row in grouped[missing]:
            exclusions.append(
                {
                    "expression_uid": row.get("expression_uid", ""),
                    "source": missing[0],
                    "source_id": missing[1],
                    "source_segment_index": missing[2],
                    "expression_start": row.get("expression_start", ""),
                    "expression_end": row.get("expression_end", ""),
                    "expression_text": row.get("expression_text", ""),
                    "reason": "segment_absent_from_stage",
                    "risk_flags": [],
                }
            )
            counts["excluded:segment_absent_from_stage"] += 1

    if len(ledger) + len(exclusions) != counts["structurally_eligible"]:
        raise ValueError("contextual qualitative candidate conservation failed")
    review_payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in review_records
    )
    ledger_payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ledger
    )
    exclusion_payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in exclusions
    )
    _immutable_text(review_input_path, review_payload)
    _immutable_text(candidate_ledger_path, ledger_payload)
    _immutable_text(exclusions_path, exclusion_payload)
    report = {
        "schema_version": "flopo-qualitative-candidate-report-v1",
        "candidate_kind": CANDIDATE_REASON,
        "input": str(stage_path),
        "decisions": str(decisions_path),
        "prior_candidate_ledger": str(prior_candidate_ledger_path),
        "review_records": len(review_records),
        "candidates": len(ledger),
        "exclusions": len(exclusions),
        "conserved": len(ledger) + len(exclusions) == counts["structurally_eligible"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage13": sha256_file(stage_path).model_dump(mode="json"),
            "decisions": sha256_file(decisions_path).model_dump(mode="json"),
            "prior_candidate_ledger": sha256_file(prior_candidate_ledger_path).model_dump(
                mode="json"
            ),
            "po_lexicon": sha256_file(po_lexicon).model_dump(mode="json"),
            "pato_lexicon": sha256_file(pato_lexicon).model_dump(mode="json"),
            "flopo_registry": sha256_file(flopo_registry).model_dump(mode="json"),
            "combinations": sha256_file(combinations_path).model_dump(mode="json"),
            "review_input": sha256_file(review_input_path).model_dump(mode="json"),
            "candidate_ledger": sha256_file(candidate_ledger_path).model_dump(mode="json"),
            "exclusions": sha256_file(exclusions_path).model_dump(mode="json"),
        },
    }
    _immutable_text(report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--prior-ledger", type=Path, required=True)
    parser.add_argument("--review-input", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = prepare_contextual_review_input(
        stage_path=args.stage,
        decisions_path=args.decisions,
        prior_candidate_ledger_path=args.prior_ledger,
        review_input_path=args.review_input,
        candidate_ledger_path=args.ledger,
        exclusions_path=args.exclusions,
        report_path=args.report,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
        flopo_registry=args.flopo_registry,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
