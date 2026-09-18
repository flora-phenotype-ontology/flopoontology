"""Build exact occurrence-review packets for machine-reviewed FLOPO support classes.

Class-level consensus establishes only that a local anatomical class is reusable.  It does not
establish that every flora span routed to that class describes a phenotype of that bearer.  This
builder therefore rebinds every occurrence belonging to an accepted class to the immutable Stage
13 source and creates one review item per occurrence.  The proposed phenotype expression is
runner-owned: reviewers may copy it exactly or hold it, but may not silently rewrite attachment,
quality, numeric bounds, or source ranges.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from flopo2.extract.measurement import parse_measurements
from flopo2.review.inventory import (
    _artifact_at,
    _evidence_record,
    _reference_record,
    _review_context,
    _temp_path,
    _validate_distinct_paths,
    model_spec,
)
from flopo2.review.io import (
    atomic_write_text,
    read_jsonl,
    sha256_file,
    stable_id,
    write_immutable_json,
    write_jsonl,
)
from flopo2.review.models import (
    CampaignManifest,
    Cluster,
    ConsensusDecision,
    ContextSample,
    DerivationSpec,
    ModelSpec,
    Occurrence,
    PhenotypeExpression,
    PhenotypeExpressionCandidate,
    PromptSpec,
    ProposedSignature,
    canonical_json,
    normalized_text,
)
from flopo2.review.report import campaign_report
from flopo2.review.validation import load_validation_context


DERIVATION_PROTOCOL = "flopo-support-occurrence-review-v1"
REVIEW_REASON = "support_class_occurrence_attachment"
SegmentKey = tuple[str, str, int, str]


def derivation_spec() -> DerivationSpec:
    descriptor = {"protocol": DERIVATION_PROTOCOL}
    return DerivationSpec(
        protocol=DERIVATION_PROTOCOL,
        descriptor_sha256=hashlib.sha256(canonical_json(descriptor).encode()).hexdigest(),
    )


def _segment_key(row: dict[str, Any] | Occurrence) -> SegmentKey:
    if isinstance(row, Occurrence):
        return row.source, row.source_id, row.source_segment_index, row.taxon
    return (
        str(row.get("source", "") or ""),
        str(row.get("source_id", "") or ""),
        int(row.get("source_segment_index", 0) or 0),
        str(row.get("taxon", "") or ""),
    )


def _read_json(path: Path, schema_version: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON artifact {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != schema_version:
        raise ValueError(f"unsupported or malformed artifact: {path}")
    return value


def _artifact_matches(record: dict[str, Any], path: Path, label: str) -> None:
    actual = sha256_file(path)
    if (actual.sha256, actual.bytes) != (record.get("sha256"), record.get("bytes")):
        raise ValueError(f"{label} hash does not match frozen materialization output")


def _allocations(path: Path) -> dict[str, dict[str, str]]:
    required = {
        "proposal_key",
        "flopo_id",
        "label",
        "signature_sha256",
        "campaign_id",
        "item_id",
        "consensus_signature_sha256",
        "reviewer_ids",
        "adjudicator_id",
        "occurrence_count",
    }
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("support allocation registry has an unsupported schema")
        rows = [{key: str(value or "") for key, value in row.items()} for row in reader]
    result: dict[str, dict[str, str]] = {}
    flopo_ids: set[str] = set()
    for number, row in enumerate(rows, 2):
        key = row["proposal_key"]
        flopo_id = row["flopo_id"]
        if not key or key in result:
            raise ValueError(f"{path}:{number}: duplicate or blank proposal key")
        if not flopo_id.startswith("FLOPO_") or flopo_id in flopo_ids:
            raise ValueError(f"{path}:{number}: invalid or duplicate allocated FLOPO ID")
        try:
            count = int(row["occurrence_count"])
        except ValueError as error:
            raise ValueError(f"{path}:{number}: invalid occurrence count") from error
        if count < 1:
            raise ValueError(f"{path}:{number}: occurrence count must be positive")
        result[key] = row
        flopo_ids.add(flopo_id)
    return result


def _verify_support_review(
    *,
    manifest: CampaignManifest,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    allocation_path: Path,
    module_path: Path,
    materialization_report_path: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, Occurrence]]:
    report = _read_json(
        materialization_report_path, "flopo-support-consensus-materialization-v1"
    )
    if report.get("campaign_id") != manifest.campaign_id:
        raise ValueError("support materialization belongs to another campaign")
    if not report.get("class_conserved") or not report.get("occurrence_conserved"):
        raise ValueError("support materialization is not conserved")
    if not report.get("review_report", {}).get("ok"):
        raise ValueError("support materialization did not record a complete review campaign")
    _artifact_matches(report["artifacts"]["allocations"], allocation_path, "allocations")
    _artifact_matches(report["artifacts"]["module"], module_path, "support module")

    review_report = campaign_report(
        manifest,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
    )
    if not review_report["ok"]:
        raise ValueError("support-class review campaign is incomplete or unconserved")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    decisions = {row.item_id: row for row in read_jsonl(consensus_path, ConsensusDecision)}
    allocation_rows = _allocations(allocation_path)
    expected_keys: set[str] = set()
    for item_id, cluster in context.clusters.items():
        candidate = cluster.support_class_candidate
        if candidate is None:
            raise ValueError(f"{item_id}: support review item lacks its runner candidate")
        decision = decisions[item_id]
        actionable = (
            decision.status == "llm_consensus"
            and decision.disposition == "reusable_flopo_support_class"
            and decision.validation_passed
            and decision.adjudicator_id is not None
        )
        if not actionable:
            continue
        signature = ProposedSignature.model_validate_json(decision.normalized_signature or "")
        if (
            signature.kind != "reusable_flopo_support_class"
            or signature.support_class != candidate.signature
        ):
            raise ValueError(f"{item_id}: accepted support signature drift")
        expected_keys.add(candidate.proposal_key)
        allocation = allocation_rows.get(candidate.proposal_key)
        candidate_hash = hashlib.sha256(
            canonical_json(candidate.signature.model_dump(mode="json")).encode()
        ).hexdigest()
        if allocation is None or any(
            (
                allocation["campaign_id"] != manifest.campaign_id,
                allocation["item_id"] != item_id,
                allocation["signature_sha256"] != candidate_hash,
                allocation["consensus_signature_sha256"] != decision.signature_sha256,
                allocation["adjudicator_id"] != decision.adjudicator_id,
                int(allocation["occurrence_count"]) != candidate.occurrence_count,
                set(filter(None, allocation["reviewer_ids"].split("|")))
                != set(decision.reviewer_ids),
            )
        ):
            raise ValueError(f"{item_id}: allocation does not match accepted class consensus")
    if set(allocation_rows) != expected_keys:
        raise ValueError("support allocations do not exactly equal actionable class consensus")
    if int(report.get("accepted_classes", -1)) != len(allocation_rows):
        raise ValueError("support materialization accepted-class count drift")
    if int(report.get("accepted_occurrences", -1)) != sum(
        int(row["occurrence_count"]) for row in allocation_rows.values()
    ):
        raise ValueError("support materialization accepted-occurrence count drift")
    return allocation_rows, context.occurrences


def _stage_records(stage13_path: Path, keys: set[SegmentKey]) -> dict[SegmentKey, dict[str, Any]]:
    records: dict[SegmentKey, dict[str, Any]] = {}
    with stage13_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{stage13_path}:{line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{stage13_path}:{line_number}: row is not an object")
            key = _segment_key(row)
            if key not in keys:
                continue
            if key in records:
                raise ValueError(f"duplicate Stage 13 segment identity: {key}")
            records[key] = row
    missing = sorted(keys - set(records))
    if missing:
        raise ValueError(f"accepted support occurrences miss Stage 13 segments: {missing[:3]}")
    return records


def _exact_unresolved(record: dict[str, Any], source: Occurrence) -> dict[str, Any]:
    matches = [
        span
        for span in (record.get("unresolved_spans", []) or [])
        if isinstance(span, dict)
        and int(span.get("start", -1)) == source.span_start
        and int(span.get("end", -1)) == source.span_end
        and str(span.get("surface_form", "") or "") == source.surface_form
        and str(span.get("candidate_pato_id", "") or "") == source.candidate_pato_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{source.occurrence_id}: source span matched {len(matches)} Stage 13 unresolved rows"
        )
    return matches[0]


def _expression_candidate(
    record: dict[str, Any],
    source: Occurrence,
    allocation: dict[str, str],
) -> PhenotypeExpressionCandidate:
    text = str(record.get("text", "") or "")
    if text[source.span_start : source.span_end] != source.surface_form:
        raise ValueError(f"{source.occurrence_id}: Stage 13 source text drift")
    _exact_unresolved(record, source)
    measurements = [
        row
        for row in parse_measurements(text, str(record.get("language", "") or ""))
        if row.start == source.span_start
        and row.end == source.span_end
        and row.attribute_id == source.candidate_pato_id
    ]
    if len(measurements) > 1:
        raise ValueError(f"{source.occurrence_id}: ambiguous deterministic measurement parse")
    measurement = measurements[0] if measurements else None
    signature = PhenotypeExpression(
        bearer_id=allocation["flopo_id"],
        quality_id=source.candidate_pato_id,
        value_low=measurement.value_low if measurement else None,
        value_high=measurement.value_high if measurement else None,
        value_low_inclusive=(measurement.value_low_inclusive if measurement else True),
        value_high_inclusive=(measurement.value_high_inclusive if measurement else True),
        unit=measurement.unit_text if measurement else "",
    )
    candidate = source.support_class_candidate
    if candidate is None:
        raise ValueError(f"{source.occurrence_id}: support source has no class candidate")
    return PhenotypeExpressionCandidate(
        signature=signature,
        bearer_method="machine_reviewed_support_class_routing",
        expression_start=source.span_start,
        expression_end=source.span_end,
        expression_text=source.surface_form,
        clear_unresolved_spans=((source.span_start, source.span_end),),
        support_proposal_key=candidate.proposal_key,
        support_class_campaign_id=allocation["campaign_id"],
        support_class_signature_sha256=allocation["signature_sha256"],
    )


def _build_occurrence(
    record: dict[str, Any],
    source: Occurrence,
    allocation: dict[str, str],
) -> Occurrence:
    candidate = _expression_candidate(record, source, allocation)
    text = str(record.get("text", "") or "")
    context = _review_context(text, source.span_start, source.span_end)
    fingerprint_payload = {
        "protocol": DERIVATION_PROTOCOL,
        "source_occurrence_id": source.occurrence_id,
        "source_context": context,
        "organ": record.get("organ", ""),
        "language": record.get("language", ""),
        "candidate": candidate.model_dump(mode="json"),
        "unresolved_span": _exact_unresolved(record, source),
    }
    fingerprint = hashlib.sha256(canonical_json(fingerprint_payload).encode()).hexdigest()
    cluster_id = stable_id(
        "cluster",
        (
            DERIVATION_PROTOCOL,
            source.source,
            source.source_id,
            source.source_segment_index,
            source.taxon,
            source.span_start,
            source.span_end,
            source.occurrence_id,
            fingerprint,
        ),
    )
    occurrence_id = stable_id(
        "occ", (DERIVATION_PROTOCOL, source.occurrence_id, cluster_id, fingerprint)
    )
    evidence_id = stable_id("evidence", (occurrence_id, cluster_id, fingerprint, context))
    return Occurrence(
        occurrence_id=occurrence_id,
        evidence_id=evidence_id,
        cluster_id=cluster_id,
        semantic_fingerprint=fingerprint,
        source=source.source,
        source_id=source.source_id,
        source_segment_index=source.source_segment_index,
        taxon=source.taxon,
        organ=str(record.get("organ", "") or ""),
        language=str(record.get("language", "") or ""),
        segment_char_start=int(record.get("char_start", 0) or 0),
        segment_char_end=int(record.get("char_end", len(text)) or len(text)),
        span_start=source.span_start,
        span_end=source.span_end,
        surface_form=source.surface_form,
        normalized_form=normalized_text(source.surface_form),
        reason=REVIEW_REASON,
        candidate_pato_id=source.candidate_pato_id,
        pending_bearer=source.support_class_candidate.signature.label,
        promoted_po_ids=(),
        extractor=source.extractor,
        context=context,
        phenotype_expression_candidate=candidate,
    )


def _cluster(occurrence: Occurrence) -> Cluster:
    membership = (occurrence.occurrence_id,)
    return Cluster(
        cluster_id=occurrence.cluster_id,
        normalized_form=occurrence.normalized_form,
        reason=occurrence.reason,
        candidate_pato_id=occurrence.candidate_pato_id,
        language=occurrence.language,
        organ=normalized_text(occurrence.organ),
        pending_bearer=occurrence.pending_bearer,
        promoted_po_ids=(),
        semantic_fingerprint=occurrence.semantic_fingerprint,
        occurrence_count=1,
        occurrence_membership_sha256=hashlib.sha256(
            canonical_json(membership).encode()
        ).hexdigest(),
        context_samples=(
            ContextSample(
                evidence_id=occurrence.evidence_id,
                occurrence_id=occurrence.occurrence_id,
                context=occurrence.context,
                context_sha256=hashlib.sha256(occurrence.context.encode()).hexdigest(),
            ),
        ),
        phenotype_expression_candidate=occurrence.phenotype_expression_candidate,
    )


def build_support_occurrence_inventory(
    *,
    stage13_path: Path,
    support_manifest_path: Path,
    support_occurrence_path: Path,
    support_cluster_path: Path,
    support_evidence_path: Path,
    support_consensus_path: Path,
    support_ledger_path: Path,
    support_allocation_path: Path,
    support_module_path: Path,
    support_materialization_report_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    exclusion_path: Path,
    report_path: Path,
    manifest_path: Path,
    ontology_paths: Iterable[Path],
    prompt_paths: dict[str, Path],
    models: Iterable[ModelSpec],
    created_at: datetime | None = None,
) -> CampaignManifest:
    """Create a one-item-per-span expression-review campaign for accepted support classes."""

    ontology_paths = tuple(ontology_paths)
    if support_module_path.resolve() not in {path.resolve() for path in ontology_paths}:
        raise ValueError("accepted support module must be one of the frozen ontology inputs")
    source_paths = (
        support_manifest_path,
        support_occurrence_path,
        support_cluster_path,
        support_evidence_path,
        support_consensus_path,
        support_ledger_path,
        support_allocation_path,
        support_materialization_report_path,
    )
    _validate_distinct_paths(
        stage13_path,
        *source_paths,
        occurrence_path,
        cluster_path,
        evidence_path,
        exclusion_path,
        report_path,
        manifest_path,
        *ontology_paths,
        *prompt_paths.values(),
    )
    support_manifest = CampaignManifest.model_validate_json(
        support_manifest_path.read_text(encoding="utf-8")
    )
    allocation_rows, support_occurrences = _verify_support_review(
        manifest=support_manifest,
        occurrence_path=support_occurrence_path,
        cluster_path=support_cluster_path,
        evidence_path=support_evidence_path,
        consensus_path=support_consensus_path,
        ledger_path=support_ledger_path,
        allocation_path=support_allocation_path,
        module_path=support_module_path,
        materialization_report_path=support_materialization_report_path,
    )
    selected_sources = [
        row
        for row in support_occurrences.values()
        if row.support_class_candidate is not None
        and row.support_class_candidate.proposal_key in allocation_rows
    ]
    expected = sum(int(row["occurrence_count"]) for row in allocation_rows.values())
    if len(selected_sources) != expected:
        raise ValueError("accepted class occurrence inventory does not match allocations")
    records = _stage_records(stage13_path, {_segment_key(row) for row in selected_sources})
    occurrences: list[Occurrence] = []
    exclusions: list[dict[str, Any]] = []
    by_proposal: Counter[str] = Counter()
    for source in sorted(selected_sources, key=lambda row: row.occurrence_id):
        candidate = source.support_class_candidate
        assert candidate is not None
        allocation = allocation_rows[candidate.proposal_key]
        try:
            occurrence = _build_occurrence(records[_segment_key(source)], source, allocation)
        except ValueError as error:
            # A malformed ontology identifier cannot enter a typed review item. Preserve it as a
            # terminal exclusion; source drift and ambiguous Stage 13 matches fail above instead.
            if "qualities must be PATO or FLOPO classes" not in str(error):
                raise
            exclusions.append(
                {
                    "source_occurrence_id": source.occurrence_id,
                    "proposal_key": candidate.proposal_key,
                    "source": source.source,
                    "source_id": source.source_id,
                    "source_segment_index": source.source_segment_index,
                    "taxon": source.taxon,
                    "start": source.span_start,
                    "end": source.span_end,
                    "surface_form": source.surface_form,
                    "reason": "invalid_quality_identifier",
                    "detail": str(error),
                }
            )
            continue
        occurrences.append(occurrence)
        by_proposal[candidate.proposal_key] += 1
    occurrences.sort(key=lambda row: row.cluster_id)
    clusters = [_cluster(row) for row in occurrences]

    input_hash = sha256_file(stage13_path)
    ontology_hashes = tuple(sha256_file(path) for path in ontology_paths)
    source_hashes = tuple(sha256_file(path) for path in source_paths)
    authority_hashes = support_manifest.authorities
    prompts = tuple(
        PromptSpec(prompt_id=prompt_id, **sha256_file(path).model_dump())
        for prompt_id, path in sorted(prompt_paths.items())
    )
    model_rows = tuple(models)
    derivation = derivation_spec()
    campaign_seed = {
        "input": input_hash.sha256,
        "ontologies": [row.sha256 for row in ontology_hashes],
        "authorities": [row.sha256 for row in authority_hashes],
        "prompts": [(row.prompt_id, row.sha256) for row in prompts],
        "models": [(row.reviewer_id, row.descriptor_sha256) for row in model_rows],
        "derivation": derivation.descriptor_sha256,
        "sources": [row.sha256 for row in source_hashes],
    }
    campaign_id = stable_id("campaign", campaign_seed)
    if manifest_path.exists():
        existing = CampaignManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if existing.campaign_id != campaign_id:
            raise FileExistsError(f"refusing to replace immutable manifest: {manifest_path}")
        for expected_artifact, path in (
            (existing.occurrences, occurrence_path),
            (existing.clusters, cluster_path),
            (existing.evidence_registry, evidence_path),
        ):
            actual = sha256_file(path)
            if (actual.sha256, actual.bytes) != (
                expected_artifact.sha256,
                expected_artifact.bytes,
            ):
                raise ValueError(f"immutable campaign artifact no longer matches: {path}")
        return existing
    for path in (occurrence_path, cluster_path, evidence_path, exclusion_path, report_path):
        if path.exists():
            raise FileExistsError(f"refusing to replace pre-existing campaign artifact: {path}")

    evidence_rows = [
        *(_evidence_record(row) for row in occurrences),
        *(_reference_record(row, "ontology") for row in ontology_hashes),
        *(_reference_record(row, "authority") for row in authority_hashes),
        *(_reference_record(row, "source_inventory") for row in source_hashes),
    ]
    temporary = {
        occurrence_path: _temp_path(occurrence_path),
        cluster_path: _temp_path(cluster_path),
        evidence_path: _temp_path(evidence_path),
    }
    installed: list[Path] = []
    try:
        write_jsonl(temporary[occurrence_path], occurrences)
        write_jsonl(temporary[cluster_path], clusters)
        write_jsonl(temporary[evidence_path], evidence_rows)
        manifest = CampaignManifest(
            campaign_id=campaign_id,
            created_at=created_at or datetime.now(timezone.utc),
            input=input_hash,
            ontologies=ontology_hashes,
            authorities=authority_hashes,
            sources=source_hashes,
            prompts=prompts,
            models=model_rows,
            derivation=derivation,
            occurrences=_artifact_at(temporary[occurrence_path], occurrence_path),
            clusters=_artifact_at(temporary[cluster_path], cluster_path),
            evidence_registry=_artifact_at(temporary[evidence_path], evidence_path),
            starting_occurrences=len(occurrences),
            starting_clusters=len(clusters),
        )
        for destination, source in temporary.items():
            os.replace(source, destination)
            installed.append(destination)
        exclusion_payload = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in sorted(exclusions, key=lambda row: row["source_occurrence_id"])
        )
        atomic_write_text(exclusion_path, exclusion_payload)
        report = {
            "schema_version": "flopo-support-occurrence-candidate-report-v1",
            "campaign_id": manifest.campaign_id,
            "support_class_campaign_id": support_manifest.campaign_id,
            "stage13": input_hash.model_dump(mode="json"),
            "support_materialization_report": sha256_file(
                support_materialization_report_path
            ).model_dump(mode="json"),
            "support_allocations": sha256_file(support_allocation_path).model_dump(mode="json"),
            "support_module": sha256_file(support_module_path).model_dump(mode="json"),
            "accepted_class_occurrences": expected,
            "review_candidates": len(occurrences),
            "excluded_occurrences": len(exclusions),
            "candidate_occurrences": dict(sorted(by_proposal.items())),
            "occurrences": manifest.occurrences.model_dump(mode="json"),
            "clusters": manifest.clusters.model_dump(mode="json"),
            "evidence_registry": manifest.evidence_registry.model_dump(mode="json"),
            "exclusions": sha256_file(exclusion_path).model_dump(mode="json"),
            "conservation": {
                "one_cluster_per_occurrence": len(occurrences) == len(clusters),
                "accepted_occurrences_accounted": len(occurrences) + len(exclusions) == expected,
                "stage13_exact_span_rebinding": True,
                "support_allocations_match_consensus": True,
            },
        }
        atomic_write_text(
            report_path,
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        write_immutable_json(manifest_path, manifest)
        return manifest
    except BaseException:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        if not manifest_path.exists():
            for path in installed:
                path.unlink(missing_ok=True)
            exclusion_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage13", type=Path, required=True)
    parser.add_argument("--support-manifest", type=Path, required=True)
    parser.add_argument("--support-occurrences", type=Path, required=True)
    parser.add_argument("--support-clusters", type=Path, required=True)
    parser.add_argument("--support-evidence", type=Path, required=True)
    parser.add_argument("--support-consensus", type=Path, required=True)
    parser.add_argument("--support-ledger", type=Path, required=True)
    parser.add_argument("--support-allocations", type=Path, required=True)
    parser.add_argument("--support-module", type=Path, required=True)
    parser.add_argument("--support-materialization-report", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, action="append", required=True)
    parser.add_argument("--prompt", nargs=2, action="append", required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--created-at")
    args = parser.parse_args()
    raw_models = json.loads(args.models.read_text(encoding="utf-8"))
    models = [model_spec(**row) for row in raw_models if row.get("role") == "reviewer"]
    created_at = (
        datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
        if args.created_at
        else None
    )
    manifest = build_support_occurrence_inventory(
        stage13_path=args.stage13,
        support_manifest_path=args.support_manifest,
        support_occurrence_path=args.support_occurrences,
        support_cluster_path=args.support_clusters,
        support_evidence_path=args.support_evidence,
        support_consensus_path=args.support_consensus,
        support_ledger_path=args.support_ledger,
        support_allocation_path=args.support_allocations,
        support_module_path=args.support_module,
        support_materialization_report_path=args.support_materialization_report,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        exclusion_path=args.exclusions,
        report_path=args.report,
        manifest_path=args.manifest,
        ontology_paths=args.ontology,
        prompt_paths={key: Path(value) for key, value in args.prompt},
        models=models,
        created_at=created_at,
    )
    print(manifest.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
