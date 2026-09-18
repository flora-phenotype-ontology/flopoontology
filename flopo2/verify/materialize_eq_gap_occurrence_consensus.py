"""Materialize exact-colour occurrence consensus as source-bound Stage proposals.

Every admitted assertion must have separate two-family occurrence agreement and an exact binding
to a previously machine-reviewed EQ class.  The class allocation is injected into deterministic
gates only in memory; no human-curated allow-list or registry file is modified.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file
from flopo2.review.models import CampaignManifest, ConsensusDecision, Occurrence, ProposedSignature
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


EXTRACTOR = "llm_consensus_exact_colour_eq_occurrence_v1"
OBO = "http://purl.obolibrary.org/obo/"
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


def _artifact_matches(record: dict[str, Any], path: Path, label: str) -> None:
    actual = sha256_file(path)
    if (actual.sha256, actual.bytes) != (record.get("sha256"), record.get("bytes")):
        raise ValueError(f"{label} hash does not match the occurrence candidate report")


def _allocations(path: Path) -> dict[str, dict[str, str]]:
    required = {
        "proposal_key",
        "flopo_id",
        "eq_signature",
        "signature_sha256",
        "campaign_id",
        "occurrence_count",
    }
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("EQ allocation ledger has an unsupported schema")
        rows = [{key: str(value or "") for key, value in row.items()} for row in reader]
    result: dict[str, dict[str, str]] = {}
    identifiers: set[str] = set()
    signatures: set[str] = set()
    for number, row in enumerate(rows, 2):
        key = row["proposal_key"]
        identifier = row["flopo_id"]
        signature = row["eq_signature"]
        if not key or key in result:
            raise ValueError(f"{path}:{number}: duplicate or blank proposal key")
        if not identifier.startswith("FLOPO_") or identifier in identifiers:
            raise ValueError(f"{path}:{number}: invalid or duplicate allocated FLOPO ID")
        if not signature.startswith("EQ|PO_") or signature in signatures:
            raise ValueError(f"{path}:{number}: invalid or duplicate EQ signature")
        result[key] = row
        identifiers.add(identifier)
        signatures.add(signature)
    return result


def _verify_candidate_report(
    path: Path,
    *,
    manifest: CampaignManifest,
    stage_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    allocation_path: Path,
    module_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid EQ occurrence candidate report {path}: {error}") from error
    if report.get("schema_version") != "flopo-eq-gap-occurrence-candidate-report-v1":
        raise ValueError("unsupported EQ occurrence candidate report")
    if report.get("campaign_id") != manifest.campaign_id:
        raise ValueError("EQ occurrence candidate report belongs to another campaign")
    conservation = report.get("conservation", {})
    required = (
        "one_cluster_per_occurrence",
        "accepted_occurrences_accounted",
        "current_stage_exact_span_rebinding",
        "class_allocations_match_consensus",
    )
    if not all(conservation.get(key) for key in required):
        raise ValueError("EQ occurrence candidate extraction is not conserved")
    actual_stage = sha256_file(stage_path)
    if (actual_stage.sha256, actual_stage.bytes) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("current stage does not match occurrence campaign baseline")
    if (report["stage"]["sha256"], report["stage"]["bytes"]) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("EQ occurrence report stage binding drift")
    for expected, actual_path, key in (
        (manifest.occurrences, occurrence_path, "occurrences"),
        (manifest.clusters, cluster_path, "clusters"),
        (manifest.evidence_registry, evidence_path, "evidence_registry"),
    ):
        if (report[key]["sha256"], report[key]["bytes"]) != (
            expected.sha256,
            expected.bytes,
        ):
            raise ValueError(f"EQ occurrence report {key} binding drift")
        _artifact_matches(report[key], actual_path, key)
    _artifact_matches(report["class_allocations"], allocation_path, "class allocations")
    _artifact_matches(report["class_module"], module_path, "class module")
    if int(report.get("review_candidates", -1)) != manifest.starting_occurrences:
        raise ValueError("EQ occurrence candidate count drift")
    if manifest.starting_occurrences != manifest.starting_clusters:
        raise ValueError("EQ occurrence campaign is not one item per occurrence")
    allocations = _allocations(allocation_path)
    if int(report.get("accepted_class_occurrences", -1)) != sum(
        int(row["occurrence_count"]) for row in allocations.values()
    ):
        raise ValueError("EQ accepted-class occurrence count drift")
    return report, allocations


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


def _assertion_for(occurrence: Occurrence, decision: ConsensusDecision) -> dict[str, Any]:
    candidate = occurrence.phenotype_expression_candidate
    if candidate is None:
        raise ValueError(f"{occurrence.occurrence_id}: missing expression candidate")
    proposed = ProposedSignature.model_validate_json(decision.normalized_signature or "")
    if proposed.kind != "annotation_expression" or proposed.expression != candidate.signature:
        raise ValueError(f"{occurrence.occurrence_id}: consensus expression signature drift")
    expression = candidate.signature
    if (
        expression.value_operator != "atomic"
        or expression.value_terms
        or expression.negated
        or expression.developmental_stage_ids
        or expression.part_restrictions
        or expression.value_low is not None
        or expression.value_high is not None
        or expression.unit
    ):
        raise ValueError(f"{occurrence.occurrence_id}: unsupported EQ expression")
    if not all(
        (
            candidate.eq_class_proposal_key,
            candidate.eq_class_id,
            candidate.eq_class_campaign_id,
            candidate.eq_class_signature_sha256,
        )
    ):
        raise ValueError(f"{occurrence.occurrence_id}: incomplete EQ-class provenance")
    assertion: dict[str, Any] = {
        "po_id": expression.bearer_id,
        "pato_id": expression.quality_id,
        "negated": False,
        "negation_scope": "",
        "organ": occurrence.organ,
        "source_text": candidate.expression_text,
        "source_start": candidate.expression_start,
        "source_end": candidate.expression_end,
        "value_low": None,
        "value_high": None,
        "value_low_inclusive": True,
        "value_high_inclusive": True,
        "unit": "",
        "value_text": candidate.expression_text,
        "value_operator": "atomic",
        "value_terms": [],
        "part_restrictions": [],
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
            f"eq_class_campaign:{candidate.eq_class_campaign_id}",
            f"eq_class_proposal:{candidate.eq_class_proposal_key}",
            f"eq_class_id:{candidate.eq_class_id}",
            f"eq_class_signature:{candidate.eq_class_signature_sha256}",
            f"bearer_method:{candidate.bearer_method}",
        ],
        "raw_quality_text": candidate.expression_text,
        "extractor": EXTRACTOR,
        "composition": {
            "status": "accept",
            "confidence": 1.0,
            "reasons": ["two_family_llm_exact_colour_occurrence_consensus"],
        },
    }
    if candidate.bearer_start is not None:
        assertion.update(
            {
                "raw_entity_text": candidate.bearer_text,
                "bearer_start": candidate.bearer_start,
                "bearer_end": candidate.bearer_end,
            }
        )
    ensure_annotation_class_iri(assertion)
    return assertion


def _statement_for(record: dict[str, Any], assertion: dict[str, Any]) -> tuple[dict, dict]:
    probe = dict(record)
    probe["assertions"] = [*(record.get("assertions", []) or []), assertion]
    upgraded = ensure_source_statements(probe)
    materialized = upgraded["assertions"][-1]
    statement_id = materialized.get("source_statement_id")
    matches = [
        row
        for row in upgraded.get("source_statements", []) or []
        if row.get("statement_id") == statement_id
    ]
    if len(matches) != 1:
        raise ValueError(f"source statement {statement_id!r} was not materialized exactly once")
    return materialized, matches[0]


def materialize_eq_gap_occurrence_consensus(
    *,
    manifest_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    candidate_report_path: Path,
    class_allocation_path: Path,
    class_module_path: Path,
    stage_path: Path,
    proposals_path: Path,
    held_path: Path,
    report_path: Path,
    combinations_path: Path = Path("config/valid_combinations.tsv"),
    registry_path: Path = Path("config/flopo_id_registry.tsv"),
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
) -> dict[str, Any]:
    paths = (
        manifest_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
        candidate_report_path,
        class_allocation_path,
        class_module_path,
        stage_path,
        proposals_path,
        held_path,
        report_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("EQ occurrence materialization paths must be distinct")
    manifest = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    candidate_report, allocations = _verify_candidate_report(
        candidate_report_path,
        manifest=manifest,
        stage_path=stage_path,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
        allocation_path=class_allocation_path,
        module_path=class_module_path,
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
        raise ValueError("EQ occurrence review campaign is incomplete or unconserved")
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
        candidate = occurrence.phenotype_expression_candidate
        if candidate is None or candidate.eq_class_proposal_key not in allocations:
            raise ValueError(f"{occurrence.occurrence_id}: unknown accepted EQ allocation")
        allocation = allocations[candidate.eq_class_proposal_key]
        expression = candidate.signature
        expected_signature = f"EQ|{expression.bearer_id}|{expression.quality_id}"
        if any(
            (
                candidate.eq_class_id != allocation["flopo_id"],
                candidate.eq_class_campaign_id != allocation["campaign_id"],
                candidate.eq_class_signature_sha256 != allocation["signature_sha256"],
                allocation["eq_signature"] != expected_signature,
            )
        ):
            raise ValueError(f"{occurrence.occurrence_id}: EQ allocation binding drift")
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

    combinations = load_combinations(combinations_path)
    registry = load_eq_registry(registry_path)
    signature_registry = load_signature_registry(registry_path)
    attribute_ids = load_pato_attribute_terms(pato_lexicon_path)
    pato_ids = load_catalog_ids(pato_lexicon_path)
    po_ids = load_catalog_ids(po_lexicon_path)
    flopo_ids = load_flopo_ids(registry_path)
    proposals: list[dict[str, Any]] = []
    matched: Counter[SegmentKey] = Counter()
    with stage_path.open(encoding="utf-8") as handle:
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
                raise ValueError(f"duplicate stage segment identity at line {line_number}: {key}")
            text = str(record.get("text", "") or "")
            unresolved_ranges = Counter(
                (int(span.get("start", -1)), int(span.get("end", -1)))
                for span in (record.get("unresolved_spans", []) or [])
                if isinstance(span, dict)
            )
            used_clear_ranges: set[tuple[int, int]] = set()
            for occurrence, decision in sorted(rows, key=lambda row: row[0].span_start):
                candidate = occurrence.phenotype_expression_candidate
                assert candidate is not None and candidate.eq_class_proposal_key is not None
                allocation = allocations[candidate.eq_class_proposal_key]
                if (
                    text[candidate.expression_start : candidate.expression_end]
                    != candidate.expression_text
                ):
                    raise ValueError(f"{occurrence.occurrence_id}: stage expression drift")
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
                pair = (expression.bearer_id, expression.quality_id)
                eq_signature = f"EQ|{pair[0]}|{pair[1]}"
                class_iri = OBO + allocation["flopo_id"]
                local_combinations = dict(combinations)
                local_combinations[pair] = Combination(
                    status="allowed", source=f"llm_consensus:{candidate.eq_class_campaign_id}"
                )
                local_registry = dict(registry)
                local_registry[pair] = (class_iri, False)
                local_signatures = dict(signature_registry)
                local_signatures[eq_signature] = (class_iri, False)
                local_flopo_ids = {*flopo_ids, allocation["flopo_id"]}
                gate = check_assertion(
                    text,
                    assertion,
                    local_combinations,
                    local_registry,
                    local_signatures,
                    attribute_ids,
                    taxon_provenance=record.get("taxon") if "taxon" in record else None,
                    pato_catalog_ids=pato_ids,
                    flopo_catalog_ids=local_flopo_ids,
                    po_catalog_ids=po_ids,
                )
                if (
                    gate.status != "accepted"
                    or gate.po_pato_status != "allowed"
                    or gate.flopo_status != "existing"
                    or gate.flopo_iri != class_iri
                ):
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
                        "machine_review": {
                            "campaign_id": decision.campaign_id,
                            "item_id": decision.item_id,
                            "occurrence_id": occurrence.occurrence_id,
                            "status": decision.status,
                            "disposition": decision.disposition,
                            "signature_sha256": decision.signature_sha256,
                            "reviewer_ids": list(decision.reviewer_ids),
                            "validation_passed": decision.validation_passed,
                            "eq_class_id": allocation["flopo_id"],
                            "eq_class_campaign_id": allocation["campaign_id"],
                        },
                    }
                )
                counts["proposals"] += 1
                counts["clear_targets"] += len(clear_ranges)
    unmatched = sorted(set(actionable) - set(matched))
    if unmatched:
        raise ValueError(f"reviewed EQ occurrences miss stage segments: {unmatched[:3]}")
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
    if len(proposals) + len(held) != manifest.starting_occurrences:
        raise ValueError("EQ occurrence materialization conservation failure")
    _write_immutable_rows(proposals_path, proposals)
    _write_immutable_rows(held_path, held)
    result = {
        "schema_version": "flopo-eq-occurrence-consensus-materialization-v1",
        "campaign_id": manifest.campaign_id,
        "class_campaign_id": candidate_report["class_campaign_id"],
        "starting_occurrences": manifest.starting_occurrences,
        "proposals": len(proposals),
        "held": len(held),
        "conserved": len(proposals) + len(held) == manifest.starting_occurrences,
        "counts": dict(sorted(counts.items())),
        "candidate_report_sha256": sha256_file(candidate_report_path).sha256,
        "campaign_report": review_report,
        "artifacts": {
            "stage": sha256_file(stage_path).model_dump(mode="json"),
            "class_allocations": sha256_file(class_allocation_path).model_dump(mode="json"),
            "class_module": sha256_file(class_module_path).model_dump(mode="json"),
            "proposals": sha256_file(proposals_path).model_dump(mode="json"),
            "held": sha256_file(held_path).model_dump(mode="json"),
        },
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if report_path.exists() and report_path.read_text(encoding="utf-8") != payload:
        raise FileExistsError(f"refusing to replace changed materialization report: {report_path}")
    if not report_path.exists():
        atomic_write_text(report_path, payload)
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
    parser.add_argument("--class-allocations", type=Path, required=True)
    parser.add_argument("--class-module", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    args = parser.parse_args()
    result = materialize_eq_gap_occurrence_consensus(
        manifest_path=args.manifest,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        consensus_path=args.consensus,
        ledger_path=args.ledger,
        candidate_report_path=args.candidate_report,
        class_allocation_path=args.class_allocations,
        class_module_path=args.class_module,
        stage_path=args.stage,
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
