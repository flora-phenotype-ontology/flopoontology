"""Lossless occurrence inventory and conservative review clustering."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from flopo2.review.io import sha256_file, stable_id, write_immutable_json, write_jsonl
from flopo2.review.models import (
    CampaignManifest,
    Cluster,
    ContextSample,
    DerivationSpec,
    EvidenceRecord,
    ModelSpec,
    Occurrence,
    PhenotypeExpressionCandidate,
    PromptSpec,
    QualitativeRelationCandidate,
    ReusableFlopoClassCandidate,
    SupportClassCandidate,
    canonical_json,
    normalized_text,
)


DERIVATION_PROTOCOL = "flopo-exact-semantic-context-clustering-v2"


def derivation_spec() -> DerivationSpec:
    descriptor = {"protocol": DERIVATION_PROTOCOL}
    return DerivationSpec(
        protocol=DERIVATION_PROTOCOL,
        descriptor_sha256=hashlib.sha256(canonical_json(descriptor).encode()).hexdigest(),
    )


def model_spec(
    *,
    reviewer_id: str,
    provider: str,
    model: str,
    model_family: str,
    role: str,
    reasoning_effort: str = "high",
) -> ModelSpec:
    descriptor = {
        "reviewer_id": reviewer_id,
        "provider": provider,
        "model": model,
        "model_family": model_family,
        "role": role,
        "reasoning_effort": reasoning_effort,
    }
    return ModelSpec(
        **descriptor,
        descriptor_sha256=hashlib.sha256(canonical_json(descriptor).encode()).hexdigest(),
    )


def _semantic_assertions(record: dict) -> list[dict]:
    """Retain attachment/logical semantics while dropping volatile pipeline provenance."""

    fields = (
        "po_id",
        "pato_id",
        "source_start",
        "source_end",
        "bearer_start",
        "bearer_end",
        "negated",
        "negation_scope",
        "value_operator",
        "value_terms",
        "bearer_context_qualities",
        "developmental_stage_contexts",
        "developmental_stage_operator",
        "season_contexts",
        "season_operator",
        "part_restrictions",
    )
    return [
        {key: assertion.get(key) for key in fields if key in assertion}
        for assertion in (record.get("assertions", []) or [])
        if isinstance(assertion, dict)
    ]


def _semantic_span_payload(span: dict) -> dict:
    ignored = {"start", "end", "surface_form", "extractor"}
    return {key: span[key] for key in sorted(span) if key not in ignored}


def _semantic_fingerprint(record: dict, span: dict, context: str) -> str:
    """Hash every local feature that can change attachment or logical interpretation."""

    payload = {
        "protocol": DERIVATION_PROTOCOL,
        "marked_context": normalized_text(context),
        "organ": normalized_text(record.get("organ")),
        "language": str(record.get("language", "") or ""),
        "span_semantics": _semantic_span_payload(span),
        "assertions": _semantic_assertions(record),
        "term_mentions": record.get("term_mentions", []) or [],
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _cluster_key(
    record: dict, span: dict, semantic_fingerprint: str
) -> tuple[str, str, str, str, str, str, tuple[str, ...], str]:
    """Return a conservative semantic-review grouping key.

    A surface form alone is not a safe assertion-review unit: the same adjective may attach to
    different anatomical headings or retain a different unresolved bearer.  Keep those contexts
    separate while still clustering repeated occurrences of the same review problem.
    """

    return (
        normalized_text(span.get("surface_form")),
        str(span.get("reason", "") or ""),
        str(span.get("candidate_pato_id", "") or ""),
        str(record.get("language", "") or ""),
        normalized_text(record.get("organ")),
        normalized_text(span.get("pending_bearer")),
        tuple(sorted({str(value) for value in (span.get("promoted_po_ids", []) or []) if value})),
        semantic_fingerprint,
    )


def _validate_span(record: dict, span: dict, line_number: int) -> tuple[int, int, str]:
    try:
        start, end = int(span["start"]), int(span["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"line {line_number}: unresolved span has invalid offsets") from exc
    text = str(record.get("text", "") or "")
    surface = str(span.get("surface_form", "") or "")
    if start < 0 or end <= start or end > len(text):
        raise ValueError(f"line {line_number}: unresolved span offsets are out of bounds")
    if text[start:end] != surface:
        raise ValueError(f"line {line_number}: unresolved span is not verbatim at {start}:{end}")
    for required in ("reason", "extractor"):
        if not str(span.get(required, "") or "").strip():
            raise ValueError(f"line {line_number}: unresolved span has no {required}")
    return start, end, surface


def _review_context(text: str, start: int, end: int, radius: int = 240) -> str:
    """Return a bounded verbatim context with the target occurrence visibly marked."""

    left = max(0, start - radius)
    right = min(len(text), end + radius)
    # Prefer natural statement boundaries without allowing pathological flora blocks to be copied
    # once per unresolved occurrence.
    for boundary in ".;:\n":
        found = text.rfind(boundary, left, start)
        if found >= 0:
            left = max(left, found + 1)
    right_candidates = [
        found
        for boundary in ".;\n"
        if (found := text.find(boundary, end, right)) >= 0
    ]
    if right_candidates:
        right = min(right_candidates) + 1
    return f"{text[left:start]}[[{text[start:end]}]]{text[end:right]}".strip()


def _read_occurrences(stage13_path: Path) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    duplicate_ordinals: defaultdict[tuple[object, ...], int] = defaultdict(int)
    with stage13_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{stage13_path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{stage13_path}:{line_number}: record must be an object")
            text = str(record.get("text", "") or "")
            for span in record.get("unresolved_spans", []) or []:
                if not isinstance(span, dict):
                    raise ValueError(f"{stage13_path}:{line_number}: span must be an object")
                start, end, surface = _validate_span(record, span, line_number)
                candidate = None
                support_candidate = None
                expression_candidate = None
                reusable_class_candidate = None
                if span.get("qualitative_relation_candidate") is not None:
                    candidate = QualitativeRelationCandidate.model_validate(
                        span["qualitative_relation_candidate"]
                    )
                    if (
                        (candidate.expression_start, candidate.expression_end)
                        != (start, end)
                        or candidate.expression_text != surface
                        or text[start:end] != candidate.expression_text
                    ):
                        raise ValueError(
                            f"{stage13_path}:{line_number}: qualitative candidate does not "
                            "match its review span"
                        )
                    for prefix in ("from", "connector", "to"):
                        candidate_start = getattr(candidate, f"{prefix}_start")
                        candidate_end = getattr(candidate, f"{prefix}_end")
                        candidate_text = getattr(candidate, f"{prefix}_text")
                        if text[candidate_start:candidate_end] != candidate_text:
                            raise ValueError(
                                f"{stage13_path}:{line_number}: qualitative {prefix} evidence "
                                "is not verbatim"
                            )
                    if (
                        candidate.bearer_start is not None
                        and text[candidate.bearer_start:candidate.bearer_end]
                        != candidate.bearer_text
                    ):
                        raise ValueError(
                            f"{stage13_path}:{line_number}: qualitative bearer evidence is "
                            "not verbatim"
                        )
                if span.get("support_class_candidate") is not None:
                    support_candidate = SupportClassCandidate.model_validate(
                        span["support_class_candidate"]
                    )
                if span.get("phenotype_expression_candidate") is not None:
                    expression_candidate = PhenotypeExpressionCandidate.model_validate(
                        span["phenotype_expression_candidate"]
                    )
                    if (
                        (expression_candidate.expression_start, expression_candidate.expression_end)
                        != (start, end)
                        or expression_candidate.expression_text != surface
                    ):
                        raise ValueError(
                            f"{stage13_path}:{line_number}: phenotype expression candidate "
                            "does not match its review span"
                        )
                if span.get("reusable_flopo_class_candidate") is not None:
                    reusable_class_candidate = ReusableFlopoClassCandidate.model_validate(
                        span["reusable_flopo_class_candidate"]
                    )
                context = _review_context(text, start, end)
                semantic_fingerprint = _semantic_fingerprint(record, span, context)
                cluster_key = _cluster_key(record, span, semantic_fingerprint)
                cluster_id = stable_id("cluster", cluster_key)
                identity = (
                    record.get("source", ""),
                    record.get("source_id", ""),
                    int(record.get("source_segment_index", 0) or 0),
                    start,
                    end,
                    surface,
                    span.get("reason", ""),
                    span.get("candidate_pato_id", ""),
                    span.get("extractor", ""),
                )
                ordinal = duplicate_ordinals[identity]
                duplicate_ordinals[identity] += 1
                occurrence_id = stable_id("occ", (*identity, ordinal))
                evidence_id = stable_id(
                    "evidence", (occurrence_id, cluster_id, semantic_fingerprint, context)
                )
                occurrences.append(
                    Occurrence(
                        occurrence_id=occurrence_id,
                        evidence_id=evidence_id,
                        cluster_id=cluster_id,
                        semantic_fingerprint=semantic_fingerprint,
                        source=str(record.get("source", "") or ""),
                        source_id=str(record.get("source_id", "") or ""),
                        source_segment_index=int(record.get("source_segment_index", 0) or 0),
                        taxon=str(record.get("taxon", "") or ""),
                        organ=str(record.get("organ", "") or ""),
                        language=str(record.get("language", "") or ""),
                        segment_char_start=int(record.get("char_start", 0) or 0),
                        segment_char_end=int(record.get("char_end", len(text)) or len(text)),
                        span_start=start,
                        span_end=end,
                        surface_form=surface,
                        normalized_form=cluster_key[0],
                        reason=cluster_key[1],
                        candidate_pato_id=cluster_key[2],
                        pending_bearer=cluster_key[5],
                        promoted_po_ids=cluster_key[6],
                        extractor=str(span.get("extractor", "") or ""),
                        context=context,
                        qualitative_relation_candidate=candidate,
                        support_class_candidate=support_candidate,
                        phenotype_expression_candidate=expression_candidate,
                        reusable_flopo_class_candidate=reusable_class_candidate,
                    )
                )
    ids = [row.occurrence_id for row in occurrences]
    if len(ids) != len(set(ids)):
        raise ValueError("occurrence identifier collision")
    return occurrences


def _clusters(occurrences: Iterable[Occurrence], sample_size: int = 8) -> list[Cluster]:
    groups: defaultdict[str, list[Occurrence]] = defaultdict(list)
    for occurrence in occurrences:
        groups[occurrence.cluster_id].append(occurrence)
    result: list[Cluster] = []
    for cluster_id, members in sorted(groups.items()):
        first = members[0]
        if any(row.semantic_fingerprint != first.semantic_fingerprint for row in members):
            raise ValueError(f"semantic heterogeneity escaped cluster key: {cluster_id}")
        if any(
            row.qualitative_relation_candidate != first.qualitative_relation_candidate
            for row in members
        ):
            raise ValueError(f"qualitative candidate heterogeneity escaped cluster key: {cluster_id}")
        if any(
            row.support_class_candidate != first.support_class_candidate for row in members
        ):
            raise ValueError(f"support candidate heterogeneity escaped cluster key: {cluster_id}")
        if any(
            row.phenotype_expression_candidate != first.phenotype_expression_candidate
            for row in members
        ):
            raise ValueError(f"expression candidate heterogeneity escaped cluster key: {cluster_id}")
        if any(
            row.reusable_flopo_class_candidate != first.reusable_flopo_class_candidate
            for row in members
        ):
            raise ValueError(
                f"reusable class candidate heterogeneity escaped cluster key: {cluster_id}"
            )
        # Spread samples through source order, retaining deterministic output.
        if len(members) <= sample_size:
            selected = members
        else:
            indices = sorted({round(i * (len(members) - 1) / (sample_size - 1)) for i in range(sample_size)})
            selected = [members[index] for index in indices]
        membership = tuple(sorted(member.occurrence_id for member in members))
        result.append(
            Cluster(
                cluster_id=cluster_id,
                normalized_form=first.normalized_form,
                reason=first.reason,
                candidate_pato_id=first.candidate_pato_id,
                language=first.language,
                organ=normalized_text(first.organ),
                pending_bearer=first.pending_bearer,
                promoted_po_ids=first.promoted_po_ids,
                semantic_fingerprint=first.semantic_fingerprint,
                occurrence_count=len(members),
                occurrence_membership_sha256=hashlib.sha256(
                    canonical_json(membership).encode()
                ).hexdigest(),
                context_samples=tuple(
                    ContextSample(
                        evidence_id=member.evidence_id,
                        occurrence_id=member.occurrence_id,
                        context=member.context,
                        context_sha256=hashlib.sha256(member.context.encode()).hexdigest(),
                    )
                    for member in selected
                ),
                qualitative_relation_candidate=first.qualitative_relation_candidate,
                support_class_candidate=first.support_class_candidate,
                phenotype_expression_candidate=first.phenotype_expression_candidate,
                reusable_flopo_class_candidate=first.reusable_flopo_class_candidate,
            )
        )
    return result


def _evidence_record(occurrence: Occurrence) -> EvidenceRecord:
    payload = {
        "occurrence_id": occurrence.occurrence_id,
        "item_id": occurrence.cluster_id,
        "source": occurrence.source,
        "source_id": occurrence.source_id,
        "source_segment_index": occurrence.source_segment_index,
        "span_start": occurrence.span_start,
        "span_end": occurrence.span_end,
        "surface_form": occurrence.surface_form,
        "context": occurrence.context,
        "semantic_fingerprint": occurrence.semantic_fingerprint,
    }
    if occurrence.qualitative_relation_candidate is not None:
        payload["qualitative_relation_candidate"] = (
            occurrence.qualitative_relation_candidate.model_dump(mode="json")
        )
    if occurrence.support_class_candidate is not None:
        payload["support_class_candidate"] = occurrence.support_class_candidate.model_dump(
            mode="json"
        )
    if occurrence.phenotype_expression_candidate is not None:
        payload["phenotype_expression_candidate"] = (
            occurrence.phenotype_expression_candidate.model_dump(mode="json")
        )
    if occurrence.reusable_flopo_class_candidate is not None:
        payload["reusable_flopo_class_candidate"] = (
            occurrence.reusable_flopo_class_candidate.model_dump(mode="json")
        )
    return EvidenceRecord(
        evidence_id=occurrence.evidence_id,
        kind="occurrence",
        occurrence_id=occurrence.occurrence_id,
        item_id=occurrence.cluster_id,
        payload_sha256=hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
        locator=(
            f"{occurrence.source}:{occurrence.source_id}:"
            f"{occurrence.source_segment_index}:{occurrence.span_start}-{occurrence.span_end}"
        ),
        description="Verbatim flora occurrence context",
    )


def _reference_record(artifact, kind: str) -> EvidenceRecord:
    evidence_id = stable_id("evidence", (kind, artifact.path, artifact.sha256))
    return EvidenceRecord(
        evidence_id=evidence_id,
        kind=kind,
        occurrence_id=None,
        item_id=None,
        payload_sha256=artifact.sha256,
        locator=artifact.path,
        description=(
            "Frozen ontology or terminology snapshot"
            if kind == "ontology"
            else "Frozen authoritative curation source"
            if kind == "authority"
            else "Frozen machine-curation source inventory"
        ),
    )


def _artifact_at(path: Path, destination: Path):
    row = sha256_file(path)
    return row.model_copy(update={"path": str(destination)})


def _temp_path(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".building",
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _validate_distinct_paths(*paths: Path) -> None:
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError("campaign inputs and outputs must resolve to distinct paths")


def build_inventory(
    *,
    stage13_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    manifest_path: Path,
    ontology_paths: Iterable[Path],
    authority_paths: Iterable[Path] = (),
    prompt_paths: dict[str, Path],
    models: Iterable[ModelSpec],
    created_at: datetime | None = None,
) -> CampaignManifest:
    """Create a frozen manifest plus one occurrence row per starting unresolved span."""

    ontology_paths = tuple(ontology_paths)
    authority_paths = tuple(authority_paths)
    _validate_distinct_paths(
        stage13_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        manifest_path,
        *ontology_paths,
        *authority_paths,
        *prompt_paths.values(),
    )
    input_hash = sha256_file(stage13_path)
    ontology_hashes = tuple(sha256_file(path) for path in ontology_paths)
    authority_hashes = tuple(sha256_file(path) for path in authority_paths)
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
    }
    campaign_id = stable_id("campaign", campaign_seed)
    existing: CampaignManifest | None = None
    if manifest_path.exists():
        existing = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if existing.campaign_id != campaign_id:
            raise FileExistsError(f"refusing to replace immutable manifest: {manifest_path}")
        for expected, path in (
            (existing.occurrences, occurrence_path),
            (existing.clusters, cluster_path),
            (existing.evidence_registry, evidence_path),
        ):
            actual = sha256_file(path)
            if (actual.sha256, actual.bytes) != (expected.sha256, expected.bytes):
                raise ValueError(f"immutable campaign artifact no longer matches manifest: {path}")
        return existing
    for path in (occurrence_path, cluster_path, evidence_path):
        if path.exists():
            raise FileExistsError(f"refusing to replace pre-existing campaign artifact: {path}")
    occurrences = _read_occurrences(stage13_path)
    clusters = _clusters(occurrences)
    evidence = [
        *(_evidence_record(row) for row in occurrences),
        *(_reference_record(row, "ontology") for row in ontology_hashes),
        *(_reference_record(row, "authority") for row in authority_hashes),
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
        write_jsonl(temporary[evidence_path], evidence)
        manifest = CampaignManifest(
            campaign_id=campaign_id,
            created_at=created_at or datetime.now(timezone.utc),
            input=input_hash,
            ontologies=ontology_hashes,
            authorities=authority_hashes,
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
        write_immutable_json(manifest_path, manifest)
        return manifest
    except BaseException:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        if not manifest_path.exists():
            for path in installed:
                path.unlink(missing_ok=True)
        raise
