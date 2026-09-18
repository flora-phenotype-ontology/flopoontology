"""Build one exact occurrence-review item per accepted exact-colour EQ class occurrence.

Class consensus establishes that an EQ class is reusable; it does not establish that every source
span is attached to the proposed bearer.  This builder verifies the complete class-review chain,
rebinds each accepted class occurrence to the current stage, and freezes a runner-owned atomic
phenotype expression for independent occurrence review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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
    ReusableFlopoClassCandidate,
    canonical_json,
    normalized_text,
)
from flopo2.review.report import campaign_report
from flopo2.review.validation import load_validation_context


DERIVATION_PROTOCOL = "flopo-exact-colour-eq-gap-occurrence-review-v1"
REVIEW_REASON = "exact_colour_eq_occurrence_attachment"
CLASS_REPORT_SCHEMA = "flopo-eq-class-consensus-materialization-v1"
OCCURRENCE_REPORT_SCHEMA = "flopo-eq-gap-occurrence-candidate-report-v1"
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


def _read_object(path: Path, schema_version: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON artifact {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != schema_version:
        raise ValueError(f"unsupported or malformed artifact: {path}")
    return value


def _read_objects(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: row is not an object")
            rows.append(row)
    return rows


def _artifact_matches(record: dict[str, Any], path: Path, label: str) -> None:
    actual = sha256_file(path)
    if (actual.sha256, actual.bytes) != (record.get("sha256"), record.get("bytes")):
        raise ValueError(f"{label} hash does not match the frozen class-review chain")


def _allocations(path: Path) -> dict[str, dict[str, str]]:
    required = {
        "proposal_key",
        "flopo_id",
        "label",
        "eq_signature",
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
        try:
            count = int(row["occurrence_count"])
        except ValueError as error:
            raise ValueError(f"{path}:{number}: invalid occurrence count") from error
        if count < 1:
            raise ValueError(f"{path}:{number}: occurrence count must be positive")
        result[key] = row
        identifiers.add(identifier)
        signatures.add(signature)
    return result


def _verify_class_review(
    *,
    manifest: CampaignManifest,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    candidate_report_path: Path,
    allocation_path: Path,
    module_path: Path,
    materialization_report_path: Path,
) -> tuple[
    dict[str, dict[str, str]],
    dict[str, ReusableFlopoClassCandidate],
    dict[tuple[str, str], ReusableFlopoClassCandidate],
]:
    materialization = _read_object(materialization_report_path, CLASS_REPORT_SCHEMA)
    if materialization.get("campaign_id") != manifest.campaign_id:
        raise ValueError("EQ-class materialization belongs to another campaign")
    if not materialization.get("class_conserved") or not materialization.get(
        "occurrence_conserved"
    ):
        raise ValueError("EQ-class materialization is not conserved")
    if not materialization.get("review_report", {}).get("ok"):
        raise ValueError("EQ-class materialization lacks a complete review campaign")
    _artifact_matches(materialization["artifacts"]["allocations"], allocation_path, "allocations")
    _artifact_matches(materialization["artifacts"]["module"], module_path, "EQ module")

    candidate_report = _read_object(
        candidate_report_path, "flopo-eq-gap-class-candidate-report-v1"
    )
    if candidate_report.get("campaign_id") != manifest.campaign_id:
        raise ValueError("EQ-class candidate report belongs to another campaign")
    review_report = campaign_report(
        manifest,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
    )
    if not review_report["ok"]:
        raise ValueError("EQ-class review campaign is incomplete or unconserved")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    decisions = {row.item_id: row for row in read_jsonl(consensus_path, ConsensusDecision)}
    allocation_rows = _allocations(allocation_path)
    expected_keys: set[str] = set()
    accepted_by_key: dict[str, ReusableFlopoClassCandidate] = {}
    accepted_by_pair: dict[tuple[str, str], ReusableFlopoClassCandidate] = {}
    for item_id, cluster in context.clusters.items():
        candidate = cluster.reusable_flopo_class_candidate
        if candidate is None:
            raise ValueError(f"{item_id}: EQ review item lacks its runner candidate")
        decision = decisions[item_id]
        actionable = (
            decision.status == "llm_consensus"
            and decision.disposition == "reusable_flopo_class"
            and decision.validation_passed
            and decision.adjudicator_id is not None
        )
        if not actionable:
            continue
        signature = ProposedSignature.model_validate_json(decision.normalized_signature or "")
        if (
            signature.kind != "reusable_flopo_class"
            or signature.expression != candidate.signature
            or signature.label != candidate.label
            or signature.definition != candidate.definition
            or signature.parent_ids != candidate.parent_ids
            or signature.authoritative_evidence_ids
            != candidate.authoritative_evidence_ids
        ):
            raise ValueError(f"{item_id}: accepted EQ-class signature drift")
        expected_keys.add(candidate.proposal_key)
        allocation = allocation_rows.get(candidate.proposal_key)
        candidate_hash = hashlib.sha256(
            canonical_json(candidate.model_dump(mode="json")).encode()
        ).hexdigest()
        eq_signature = (
            f"EQ|{candidate.signature.bearer_id}|{candidate.signature.quality_id}"
        )
        if allocation is None or any(
            (
                allocation["campaign_id"] != manifest.campaign_id,
                allocation["item_id"] != item_id,
                allocation["eq_signature"] != eq_signature,
                allocation["signature_sha256"] != candidate_hash,
                allocation["consensus_signature_sha256"] != decision.signature_sha256,
                allocation["adjudicator_id"] != decision.adjudicator_id,
                int(allocation["occurrence_count"]) != candidate.occurrence_count,
                set(filter(None, allocation["reviewer_ids"].split("|")))
                != set(decision.reviewer_ids),
            )
        ):
            raise ValueError(f"{item_id}: EQ allocation does not match class consensus")
        pair = (candidate.signature.bearer_id, candidate.signature.quality_id)
        if pair in accepted_by_pair:
            raise ValueError(f"duplicate accepted EQ candidate pair: {pair}")
        accepted_by_key[candidate.proposal_key] = candidate
        accepted_by_pair[pair] = candidate
    if set(allocation_rows) != expected_keys:
        raise ValueError("EQ allocations do not exactly equal actionable class consensus")
    if int(materialization.get("accepted_classes", -1)) != len(allocation_rows):
        raise ValueError("EQ materialization accepted-class count drift")
    return allocation_rows, accepted_by_key, accepted_by_pair


def _stage_records(stage_path: Path, keys: set[SegmentKey]) -> dict[SegmentKey, dict[str, Any]]:
    records: dict[SegmentKey, dict[str, Any]] = {}
    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{stage_path}:{line_number}: invalid JSON") from error
            if not isinstance(row, dict):
                raise ValueError(f"{stage_path}:{line_number}: row is not an object")
            key = _segment_key(row)
            if key not in keys:
                continue
            if key in records:
                raise ValueError(f"duplicate stage segment identity: {key}")
            records[key] = row
    missing = sorted(keys - set(records))
    if missing:
        raise ValueError(f"accepted EQ occurrences miss current stage segments: {missing[:3]}")
    return records


def _clear_unresolved(record: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Bind every declared clear target to one current unresolved component span.

    Exact-colour candidates cover a whole standardized compound such as ``greenish-white``
    while the baseline unresolved inventory deliberately retains its component span (for
    example, ``white``).  The source inventory therefore freezes the component ranges that an
    accepted occurrence may clear.  Requiring the whole compound itself to be unresolved would
    reject every genuine candidate and would not match the later materialization gate.
    """

    text = str(record.get("text", "") or "")
    raw_clear = source.get(
        "clear_unresolved_spans",
        [[int(source.get("start", -1)), int(source.get("end", -1))]],
    )
    if not isinstance(raw_clear, list) or not raw_clear:
        raise ValueError(f"{source.get('occurrence_id')}: missing clear targets")
    unresolved = [
        span for span in (record.get("unresolved_spans", []) or []) if isinstance(span, dict)
    ]
    matched: list[dict[str, Any]] = []
    ranges: set[tuple[int, int]] = set()
    for raw_range in raw_clear:
        if (
            not isinstance(raw_range, (list, tuple))
            or len(raw_range) != 2
            or not all(isinstance(value, int) for value in raw_range)
        ):
            raise ValueError(f"{source.get('occurrence_id')}: malformed clear target")
        start, end = raw_range
        if start < 0 or end <= start or end > len(text) or (start, end) in ranges:
            raise ValueError(f"{source.get('occurrence_id')}: invalid clear target")
        ranges.add((start, end))
        matches = [
            span
            for span in unresolved
            if int(span.get("start", -1)) == start
            and int(span.get("end", -1)) == end
            and str(span.get("surface_form", "") or "") == text[start:end]
        ]
        if len(matches) != 1:
            raise ValueError(
                f"{source.get('occurrence_id')}: clear target {(start, end)} matched "
                f"{len(matches)} stage rows"
            )
        matched.append(matches[0])
    return tuple(matched)


def _expression_candidate(
    record: dict[str, Any],
    source: dict[str, Any],
    candidate: ReusableFlopoClassCandidate,
    allocation: dict[str, str],
) -> PhenotypeExpressionCandidate:
    text = str(record.get("text", "") or "")
    start = int(source.get("start", -1))
    end = int(source.get("end", -1))
    surface = str(source.get("surface_form", "") or "")
    if not (0 <= start < end <= len(text)) or text[start:end] != surface:
        raise ValueError(f"{source.get('occurrence_id')}: current stage source text drift")
    _clear_unresolved(record, source)
    raw_clear = source.get("clear_unresolved_spans", [[start, end]])
    clear_ranges = tuple((int(row[0]), int(row[1])) for row in raw_clear)
    bearer_start = source.get("bearer_start")
    bearer_end = source.get("bearer_end")
    bearer_text = str(source.get("bearer_text", "") or "")
    if bearer_start is not None or bearer_end is not None:
        if (
            not isinstance(bearer_start, int)
            or not isinstance(bearer_end, int)
            or text[bearer_start:bearer_end] != bearer_text
        ):
            raise ValueError(f"{source.get('occurrence_id')}: bearer evidence drift")
    candidate_hash = hashlib.sha256(
        canonical_json(candidate.model_dump(mode="json")).encode()
    ).hexdigest()
    return PhenotypeExpressionCandidate(
        signature=PhenotypeExpression(
            bearer_id=candidate.signature.bearer_id,
            quality_id=candidate.signature.quality_id,
        ),
        bearer_method=str(source.get("bearer_method", "") or "exact_colour_eq_inventory"),
        bearer_text=bearer_text,
        bearer_start=bearer_start,
        bearer_end=bearer_end,
        expression_start=start,
        expression_end=end,
        expression_text=surface,
        clear_unresolved_spans=clear_ranges,
        eq_class_proposal_key=candidate.proposal_key,
        eq_class_id=allocation["flopo_id"],
        eq_class_campaign_id=allocation["campaign_id"],
        eq_class_signature_sha256=candidate_hash,
    )


def _build_occurrence(
    record: dict[str, Any],
    source: dict[str, Any],
    candidate: ReusableFlopoClassCandidate,
    allocation: dict[str, str],
) -> Occurrence:
    expression = _expression_candidate(record, source, candidate, allocation)
    text = str(record.get("text", "") or "")
    context = _review_context(text, expression.expression_start, expression.expression_end)
    fingerprint_payload = {
        "protocol": DERIVATION_PROTOCOL,
        "source_occurrence_id": source.get("occurrence_id"),
        "source_context": context,
        "organ": record.get("organ", ""),
        "language": record.get("language", ""),
        "candidate": expression.model_dump(mode="json"),
        "unresolved_spans": _clear_unresolved(record, source),
    }
    fingerprint = hashlib.sha256(canonical_json(fingerprint_payload).encode()).hexdigest()
    cluster_id = stable_id(
        "cluster",
        (
            DERIVATION_PROTOCOL,
            source.get("source"),
            source.get("source_id"),
            source.get("source_segment_index"),
            source.get("taxon"),
            source.get("start"),
            source.get("end"),
            source.get("occurrence_id"),
            fingerprint,
        ),
    )
    occurrence_id = stable_id(
        "occ", (DERIVATION_PROTOCOL, source.get("occurrence_id"), cluster_id, fingerprint)
    )
    evidence_id = stable_id("evidence", (occurrence_id, cluster_id, fingerprint, context))
    return Occurrence(
        occurrence_id=occurrence_id,
        evidence_id=evidence_id,
        cluster_id=cluster_id,
        semantic_fingerprint=fingerprint,
        source=str(source.get("source", "") or ""),
        source_id=str(source.get("source_id", "") or ""),
        source_segment_index=int(source.get("source_segment_index", 0) or 0),
        taxon=str(source.get("taxon", "") or ""),
        organ=str(record.get("organ", "") or ""),
        language=str(record.get("language", "") or ""),
        segment_char_start=int(record.get("char_start", 0) or 0),
        segment_char_end=int(record.get("char_end", len(text)) or len(text)),
        span_start=expression.expression_start,
        span_end=expression.expression_end,
        surface_form=expression.expression_text,
        normalized_form=normalized_text(expression.expression_text),
        reason=REVIEW_REASON,
        candidate_pato_id=candidate.signature.quality_id,
        pending_bearer=candidate.signature.bearer_id,
        extractor=str(source.get("extractor", "") or "exact_colour_eq_gap_inventory_v1"),
        context=context,
        phenotype_expression_candidate=expression,
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


def build_eq_gap_occurrence_inventory(
    *,
    stage_path: Path,
    class_manifest_path: Path,
    class_occurrence_path: Path,
    class_cluster_path: Path,
    class_evidence_path: Path,
    class_consensus_path: Path,
    class_ledger_path: Path,
    class_candidate_report_path: Path,
    class_allocation_path: Path,
    class_module_path: Path,
    class_materialization_report_path: Path,
    source_occurrence_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    report_path: Path,
    manifest_path: Path,
    ontology_paths: Iterable[Path],
    prompt_paths: dict[str, Path],
    models: Iterable[ModelSpec],
    created_at: datetime | None = None,
) -> CampaignManifest:
    ontology_paths = tuple(ontology_paths)
    if class_module_path.resolve() not in {path.resolve() for path in ontology_paths}:
        raise ValueError("accepted EQ module must be a frozen ontology input")
    source_paths = (
        class_manifest_path,
        class_occurrence_path,
        class_cluster_path,
        class_evidence_path,
        class_consensus_path,
        class_ledger_path,
        class_candidate_report_path,
        class_allocation_path,
        class_materialization_report_path,
        source_occurrence_path,
    )
    _validate_distinct_paths(
        stage_path,
        *source_paths,
        occurrence_path,
        cluster_path,
        evidence_path,
        report_path,
        manifest_path,
        *ontology_paths,
        *prompt_paths.values(),
    )
    class_manifest = CampaignManifest.model_validate_json(
        class_manifest_path.read_text(encoding="utf-8")
    )
    allocations, accepted_by_key, accepted_by_pair = _verify_class_review(
        manifest=class_manifest,
        occurrence_path=class_occurrence_path,
        cluster_path=class_cluster_path,
        evidence_path=class_evidence_path,
        consensus_path=class_consensus_path,
        ledger_path=class_ledger_path,
        candidate_report_path=class_candidate_report_path,
        allocation_path=class_allocation_path,
        module_path=class_module_path,
        materialization_report_path=class_materialization_report_path,
    )
    class_candidate_report = _read_object(
        class_candidate_report_path, "flopo-eq-gap-class-candidate-report-v1"
    )
    _artifact_matches(
        class_candidate_report["source_occurrences"],
        source_occurrence_path,
        "source occurrence inventory",
    )
    raw_occurrences = _read_objects(source_occurrence_path)
    selected: list[tuple[dict[str, Any], ReusableFlopoClassCandidate]] = []
    membership: defaultdict[str, list[str]] = defaultdict(list)
    for row in raw_occurrences:
        pair = (str(row.get("po_id", "")), str(row.get("pato_id", "")))
        candidate = accepted_by_pair.get(pair)
        if candidate is None:
            continue
        source_id = str(row.get("occurrence_id", "") or "")
        membership[candidate.proposal_key].append(source_id)
        selected.append((row, candidate))
    for proposal_key, candidate in accepted_by_key.items():
        identifiers = sorted(membership.get(proposal_key, []))
        digest = hashlib.sha256(canonical_json(identifiers).encode()).hexdigest()
        if (
            len(identifiers) != candidate.occurrence_count
            or digest != candidate.source_occurrence_membership_sha256
        ):
            raise ValueError(f"{proposal_key}: accepted source occurrence membership drift")
    expected = sum(int(row["occurrence_count"]) for row in allocations.values())
    if len(selected) != expected:
        raise ValueError("accepted EQ occurrence inventory does not match allocations")
    records = _stage_records(stage_path, {_segment_key(row) for row, _ in selected})
    occurrences = [
        _build_occurrence(
            records[_segment_key(source)],
            source,
            candidate,
            allocations[candidate.proposal_key],
        )
        for source, candidate in sorted(
            selected, key=lambda row: str(row[0].get("occurrence_id", ""))
        )
    ]
    occurrences.sort(key=lambda row: row.cluster_id)
    clusters = [_cluster(row) for row in occurrences]

    input_hash = sha256_file(stage_path)
    ontology_hashes = tuple(sha256_file(path) for path in ontology_paths)
    source_hashes = tuple(sha256_file(path) for path in source_paths)
    prompts = tuple(
        PromptSpec(prompt_id=prompt_id, **sha256_file(path).model_dump())
        for prompt_id, path in sorted(prompt_paths.items())
    )
    model_rows = tuple(models)
    derivation = derivation_spec()
    campaign_seed = {
        "input": input_hash.sha256,
        "ontologies": [row.sha256 for row in ontology_hashes],
        "authorities": [],
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
    for path in (occurrence_path, cluster_path, evidence_path, report_path):
        if path.exists():
            raise FileExistsError(f"refusing to replace pre-existing campaign artifact: {path}")

    evidence_rows = [
        *(_evidence_record(row) for row in occurrences),
        *(_reference_record(row, "ontology") for row in ontology_hashes),
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
        by_class = Counter(
            row.phenotype_expression_candidate.eq_class_proposal_key
            for row in occurrences
            if row.phenotype_expression_candidate is not None
        )
        report = {
            "schema_version": OCCURRENCE_REPORT_SCHEMA,
            "campaign_id": manifest.campaign_id,
            "class_campaign_id": class_manifest.campaign_id,
            "stage": input_hash.model_dump(mode="json"),
            "class_materialization_report": sha256_file(
                class_materialization_report_path
            ).model_dump(mode="json"),
            "class_allocations": sha256_file(class_allocation_path).model_dump(mode="json"),
            "class_module": sha256_file(class_module_path).model_dump(mode="json"),
            "source_occurrences": sha256_file(source_occurrence_path).model_dump(mode="json"),
            "accepted_class_occurrences": expected,
            "review_candidates": len(occurrences),
            "candidate_occurrences": dict(sorted(by_class.items())),
            "occurrences": manifest.occurrences.model_dump(mode="json"),
            "clusters": manifest.clusters.model_dump(mode="json"),
            "evidence_registry": manifest.evidence_registry.model_dump(mode="json"),
            "conservation": {
                "one_cluster_per_occurrence": len(occurrences) == len(clusters),
                "accepted_occurrences_accounted": len(occurrences) == expected,
                "current_stage_exact_span_rebinding": True,
                "class_allocations_match_consensus": True,
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
            report_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--class-manifest", type=Path, required=True)
    parser.add_argument("--class-occurrences", type=Path, required=True)
    parser.add_argument("--class-clusters", type=Path, required=True)
    parser.add_argument("--class-evidence", type=Path, required=True)
    parser.add_argument("--class-consensus", type=Path, required=True)
    parser.add_argument("--class-ledger", type=Path, required=True)
    parser.add_argument("--class-candidate-report", type=Path, required=True)
    parser.add_argument("--class-allocations", type=Path, required=True)
    parser.add_argument("--class-module", type=Path, required=True)
    parser.add_argument("--class-materialization-report", type=Path, required=True)
    parser.add_argument("--source-occurrences", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
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
    manifest = build_eq_gap_occurrence_inventory(
        stage_path=args.stage,
        class_manifest_path=args.class_manifest,
        class_occurrence_path=args.class_occurrences,
        class_cluster_path=args.class_clusters,
        class_evidence_path=args.class_evidence,
        class_consensus_path=args.class_consensus,
        class_ledger_path=args.class_ledger,
        class_candidate_report_path=args.class_candidate_report,
        class_allocation_path=args.class_allocations,
        class_module_path=args.class_module,
        class_materialization_report_path=args.class_materialization_report,
        source_occurrence_path=args.source_occurrences,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
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
