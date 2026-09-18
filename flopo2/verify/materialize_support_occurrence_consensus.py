"""Materialize exact support-bearer occurrence consensus as Stage 14 proposals.

The accepted anatomy class and each occurrence are reviewed separately.  This bridge admits only
two-family agreement on the runner's exact expression, rebinds it to the frozen Stage 13 span,
and reruns deterministic assertion gates.  Pair approval is injected only in memory with explicit
``llm_consensus`` provenance; no human curator status is created and no configuration allow-list
is modified.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file
from flopo2.review.models import (
    CampaignManifest,
    ConsensusDecision,
    Occurrence,
    ProposedSignature,
)
from flopo2.review.report import campaign_report
from flopo2.review.validation import load_validation_context
from flopo2.verify.gates import (
    Combination,
    check_assertion,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)


EXTRACTOR = "llm_consensus_support_occurrence_v1"
SegmentKey = tuple[str, str, int, str]


def _segment_key(row: dict[str, Any] | Occurrence) -> SegmentKey:
    if isinstance(row, Occurrence):
        return row.source, row.source_id, row.source_segment_index, row.taxon
    return (
        str(row.get("source", "") or ""),
        str(row.get("source_id", "") or ""),
        int(row.get("source_segment_index", 0) or 0),
        str(row.get("taxon", "") or ""),
    )


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
        raise FileExistsError(f"refusing to replace changed materialization report: {path}")
    atomic_write_text(path, payload)


def _artifact_matches(record: dict[str, Any], path: Path, label: str) -> None:
    actual = sha256_file(path)
    if (actual.sha256, actual.bytes) != (record.get("sha256"), record.get("bytes")):
        raise ValueError(f"{label} hash does not match the occurrence candidate report")


def _verify_candidate_report(
    path: Path,
    *,
    manifest: CampaignManifest,
    stage13_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid support occurrence candidate report {path}: {error}") from error
    if report.get("schema_version") != "flopo-support-occurrence-candidate-report-v1":
        raise ValueError("unsupported support occurrence candidate report")
    if report.get("campaign_id") != manifest.campaign_id:
        raise ValueError("support occurrence candidate report belongs to another campaign")
    conservation = report.get("conservation", {})
    if not all(
        conservation.get(key)
        for key in (
            "one_cluster_per_occurrence",
            "accepted_occurrences_accounted",
            "stage13_exact_span_rebinding",
            "support_allocations_match_consensus",
        )
    ):
        raise ValueError("support occurrence candidate extraction is not conserved")
    actual_stage = sha256_file(stage13_path)
    if (actual_stage.sha256, actual_stage.bytes) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("Stage 13 does not match the occurrence campaign baseline")
    if (report["stage13"]["sha256"], report["stage13"]["bytes"]) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("candidate report Stage 13 binding drift")
    for expected, actual_path, key in (
        (manifest.occurrences, occurrence_path, "occurrences"),
        (manifest.clusters, cluster_path, "clusters"),
        (manifest.evidence_registry, evidence_path, "evidence_registry"),
    ):
        if (report[key]["sha256"], report[key]["bytes"]) != (
            expected.sha256,
            expected.bytes,
        ):
            raise ValueError(f"candidate report {key} binding drift")
        _artifact_matches(report[key], actual_path, key)
    if int(report.get("review_candidates", -1)) != manifest.starting_occurrences:
        raise ValueError("candidate report occurrence count drift")
    if manifest.starting_occurrences != manifest.starting_clusters:
        raise ValueError("support occurrence campaign is not one item per occurrence")
    return report


def _held_row(
    occurrence: Occurrence,
    decision: ConsensusDecision,
    *,
    reason: str,
    details: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "campaign_id": decision.campaign_id,
        "item_id": decision.item_id,
        "occurrence_id": occurrence.occurrence_id,
        "source": occurrence.source,
        "source_id": occurrence.source_id,
        "source_segment_index": occurrence.source_segment_index,
        "taxon": occurrence.taxon,
        "expression_start": occurrence.span_start,
        "expression_end": occurrence.span_end,
        "expression_text": occurrence.surface_form,
        "reason": reason,
        "details": list(details),
        "consensus": decision.model_dump(mode="json", exclude_none=True),
        "candidate": (
            occurrence.phenotype_expression_candidate.model_dump(mode="json")
            if occurrence.phenotype_expression_candidate is not None
            else None
        ),
    }


def _assertion_for(
    occurrence: Occurrence,
    decision: ConsensusDecision,
) -> dict[str, Any]:
    candidate = occurrence.phenotype_expression_candidate
    if candidate is None:
        raise ValueError(f"{occurrence.occurrence_id}: missing expression candidate")
    proposed = ProposedSignature.model_validate_json(decision.normalized_signature or "")
    if proposed.kind != "annotation_expression" or proposed.expression != candidate.signature:
        raise ValueError(f"{occurrence.occurrence_id}: consensus expression signature drift")
    expression = candidate.signature
    if expression.developmental_stage_ids:
        raise ValueError(
            f"{occurrence.occurrence_id}: runner cannot materialize stage IDs without evidence"
        )
    assertion: dict[str, Any] = {
        "po_id": expression.bearer_id,
        "pato_id": expression.quality_id,
        "negated": expression.negated,
        "negation_scope": "quality" if expression.negated else "",
        "organ": occurrence.organ,
        "source_text": candidate.expression_text,
        "source_start": candidate.expression_start,
        "source_end": candidate.expression_end,
        "value_low": expression.value_low,
        "value_high": expression.value_high,
        "value_low_inclusive": expression.value_low_inclusive,
        "value_high_inclusive": expression.value_high_inclusive,
        "unit": expression.unit,
        "value_text": "",
        "value_operator": expression.value_operator,
        "value_terms": list(expression.value_terms),
        "part_restrictions": [
            row.model_dump(mode="json") for row in expression.part_restrictions
        ],
        "bearer_context_qualities": [],
        "developmental_stage_contexts": [],
        "developmental_stage_operator": "atomic",
        "frequency_qualifier": "unspecified",
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": "",
        "season_contexts": [],
        "season_operator": "atomic",
        "normalization_status": "compositional",
        "mapping_provenance": [
            f"llm_consensus:{decision.campaign_id}",
            f"llm_review_item:{decision.item_id}",
            f"llm_signature:{decision.signature_sha256}",
            f"support_class_campaign:{candidate.support_class_campaign_id}",
            f"support_class_signature:{candidate.support_class_signature_sha256}",
            f"support_proposal:{candidate.support_proposal_key}",
            f"bearer_method:{candidate.bearer_method}",
        ],
        "raw_entity_text": candidate.bearer_text,
        "raw_quality_text": candidate.expression_text,
        "extractor": EXTRACTOR,
        "composition": {
            "status": "accept",
            "confidence": 1.0,
            "reasons": ["two_family_llm_exact_expression_consensus"],
        },
    }
    if candidate.bearer_start is not None:
        assertion["bearer_start"] = candidate.bearer_start
        assertion["bearer_end"] = candidate.bearer_end
    return assertion


def _statement_for(record: dict[str, Any], assertion: dict[str, Any]) -> tuple[dict, dict]:
    probe = dict(record)
    existing = list(record.get("assertions", []) or [])
    probe["assertions"] = [*existing, assertion]
    upgraded = ensure_source_statements(probe)
    materialized = upgraded["assertions"][-1]
    statement_id = materialized.get("source_statement_id")
    matches = [
        row
        for row in (upgraded.get("source_statements", []) or [])
        if row.get("statement_id") == statement_id
    ]
    if len(matches) != 1:
        raise ValueError(f"source statement {statement_id!r} was not materialized exactly once")
    return materialized, matches[0]


def materialize_support_occurrence_consensus(
    *,
    manifest_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    candidate_report_path: Path,
    stage13_path: Path,
    proposals_path: Path,
    held_path: Path,
    report_path: Path,
    combinations_path: Path = Path("config/valid_combinations.tsv"),
    registry_path: Path = Path("config/flopo_id_registry.tsv"),
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
) -> dict[str, Any]:
    """Revalidate a complete occurrence campaign and emit one outcome per review item."""

    paths = (
        manifest_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
        candidate_report_path,
        stage13_path,
        proposals_path,
        held_path,
        report_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("support occurrence materialization paths must be distinct")
    manifest = CampaignManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    candidate_report = _verify_candidate_report(
        candidate_report_path,
        manifest=manifest,
        stage13_path=stage13_path,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    review_report = campaign_report(
        manifest,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
    )
    if not review_report["ok"]:
        raise ValueError("support occurrence review campaign is incomplete or unconserved")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    decisions = {row.item_id: row for row in read_jsonl(consensus_path, ConsensusDecision)}
    occurrences = sorted(context.occurrences.values(), key=lambda row: row.occurrence_id)
    actionable: defaultdict[SegmentKey, list[tuple[Occurrence, ConsensusDecision]]] = (
        defaultdict(list)
    )
    held: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for occurrence in occurrences:
        decision = decisions[occurrence.cluster_id]
        if (
            decision.status == "llm_consensus"
            and decision.disposition == "annotation_expression"
            and decision.validation_passed
        ):
            _assertion_for(occurrence, decision)
            actionable[_segment_key(occurrence)].append((occurrence, decision))
            counts["consensus_candidates"] += 1
        else:
            held.append(
                _held_row(
                    occurrence,
                    decision,
                    reason="campaign_exception",
                    details=decision.reasons,
                )
            )
            counts["campaign_exception_held"] += 1

    combos = load_combinations(combinations_path)
    registry = load_eq_registry(registry_path)
    signature_registry = load_signature_registry(registry_path)
    attribute_ids = load_pato_attribute_terms(pato_lexicon_path)
    pato_ids = load_catalog_ids(pato_lexicon_path)
    po_ids = load_catalog_ids(po_lexicon_path)
    flopo_ids = load_flopo_ids(registry_path)
    flopo_ids.update(
        occurrence.phenotype_expression_candidate.signature.bearer_id
        for occurrence in occurrences
        if occurrence.phenotype_expression_candidate is not None
    )
    proposals: list[dict[str, Any]] = []
    matched: Counter[SegmentKey] = Counter()

    with stage13_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _segment_key(record)
            rows = actionable.get(key, [])
            if not rows:
                continue
            matched[key] += 1
            if matched[key] != 1:
                raise ValueError(f"duplicate Stage 13 segment identity at line {line_number}: {key}")
            text = str(record.get("text", "") or "")
            unresolved_ranges = Counter(
                (int(span.get("start", -1)), int(span.get("end", -1)))
                for span in (record.get("unresolved_spans", []) or [])
                if isinstance(span, dict)
            )
            used_clear_ranges: set[tuple[int, int]] = set()
            for occurrence, decision in sorted(rows, key=lambda row: row[0].span_start):
                candidate = occurrence.phenotype_expression_candidate
                assert candidate is not None
                if (
                    text[candidate.expression_start : candidate.expression_end]
                    != candidate.expression_text
                ):
                    raise ValueError(f"{occurrence.occurrence_id}: Stage 13 expression drift")
                clear_ranges = set(candidate.clear_unresolved_spans)
                if not clear_ranges or any(unresolved_ranges[item] != 1 for item in clear_ranges):
                    raise ValueError(
                        f"{occurrence.occurrence_id}: unresolved clear allow-list drift"
                    )
                overlap = used_clear_ranges.intersection(clear_ranges)
                if overlap:
                    raise ValueError(
                        f"{occurrence.occurrence_id}: duplicate clear ranges {sorted(overlap)}"
                    )
                used_clear_ranges.update(clear_ranges)
                assertion = _assertion_for(occurrence, decision)
                expression = candidate.signature
                local_combos = dict(combos)
                local_combos[(expression.bearer_id, expression.quality_id)] = Combination(
                    status="allowed", source=f"llm_consensus:{decision.campaign_id}"
                )
                gate = check_assertion(
                    text,
                    assertion,
                    local_combos,
                    registry,
                    signature_registry,
                    attribute_ids,
                    taxon_provenance=record.get("taxon") if "taxon" in record else None,
                    pato_catalog_ids=pato_ids,
                    flopo_catalog_ids=flopo_ids,
                    po_catalog_ids=po_ids,
                )
                if gate.status != "accepted" or gate.po_pato_status != "allowed":
                    held.append(
                        _held_row(
                            occurrence,
                            decision,
                            reason="post_consensus_gate_held",
                            details=gate.reasons,
                        )
                    )
                    counts["post_consensus_gate_held"] += 1
                    continue
                assertion["gate"] = asdict(gate)
                assertion, source_statement = _statement_for(record, assertion)
                proposals.append(
                    {
                        "source": occurrence.source,
                        "source_id": occurrence.source_id,
                        "source_segment_index": occurrence.source_segment_index,
                        "taxon": occurrence.taxon,
                        "assertion": assertion,
                        "source_statement": source_statement,
                        "apply": {
                            "clear_unresolved_spans": [
                                {"start": start, "end": end}
                                for start, end in sorted(clear_ranges)
                            ]
                        },
                    }
                )
                counts["proposals"] += 1

    unmatched = sorted(set(actionable) - set(matched))
    if unmatched:
        raise ValueError(f"reviewed occurrences miss Stage 13 segments: {unmatched[:3]}")
    proposals.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["taxon"],
            row["assertion"]["source_start"],
        )
    )
    held.sort(key=lambda row: row["occurrence_id"])
    terminal = len(proposals) + len(held)
    if terminal != manifest.starting_occurrences:
        raise ValueError(
            f"support occurrence conservation failure: {terminal} != "
            f"{manifest.starting_occurrences}"
        )
    _write_immutable_rows(proposals_path, proposals)
    _write_immutable_rows(held_path, held)
    result = {
        "schema_version": "flopo-support-occurrence-materialization-v1",
        "campaign_id": manifest.campaign_id,
        "support_class_campaign_id": candidate_report["support_class_campaign_id"],
        "starting_occurrences": manifest.starting_occurrences,
        "proposals": len(proposals),
        "held": len(held),
        "candidate_exclusions": candidate_report["excluded_occurrences"],
        "conserved": terminal == manifest.starting_occurrences,
        "counts": dict(sorted(counts.items())),
        "review_report": review_report,
        "candidate_report_sha256": sha256_file(candidate_report_path).sha256,
        "artifacts": {
            "stage13": sha256_file(stage13_path).model_dump(mode="json"),
            "proposals": sha256_file(proposals_path).model_dump(mode="json"),
            "held": sha256_file(held_path).model_dump(mode="json"),
        },
        "provenance": {
            "review_kind": "two_family_llm_exact_expression_consensus",
            "human_reviewed": False,
            "configuration_allow_list_modified": False,
        },
    }
    _write_immutable_report(report_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--consensus", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--stage13", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--combinations", type=Path, default=Path("config/valid_combinations.tsv"))
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    args = parser.parse_args()
    result = materialize_support_occurrence_consensus(
        manifest_path=args.manifest,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        consensus_path=args.consensus,
        ledger_path=args.ledger,
        candidate_report_path=args.candidate_report,
        stage13_path=args.stage13,
        proposals_path=args.proposals,
        held_path=args.held,
        report_path=args.report,
        combinations_path=args.combinations,
        registry_path=args.registry,
        po_lexicon_path=args.po_lexicon,
        pato_lexicon_path=args.pato_lexicon,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
