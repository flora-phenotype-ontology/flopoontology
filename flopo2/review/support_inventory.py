"""Freeze evidence-backed FLOPO-local anatomy candidates for independent LLM review.

The group curation and bearer occurrence ledger are machine-generated source inventories, not
authoritative evidence and not approvals.  A candidate enters this campaign only when an explicit
proposal-to-evidence map names locally archived, checksum-verified authority files.  Unsupported
and malformed proposals are conserved in the exclusion ledger.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from flopo2.review.inventory import (
    _artifact_at,
    _reference_record,
    _temp_path,
    _validate_distinct_paths,
    model_spec,
)
from flopo2.review.io import (
    atomic_write_text,
    sha256_file,
    stable_id,
    write_immutable_json,
    write_jsonl,
)
from flopo2.review.models import (
    CampaignManifest,
    Cluster,
    ContextSample,
    DerivationSpec,
    EvidenceRecord,
    ModelSpec,
    Occurrence,
    PromptSpec,
    SupportClassCandidate,
    SupportClassSignature,
    canonical_json,
    normalized_text,
)


DERIVATION_PROTOCOL = "flopo-support-class-candidate-clustering-v1"
LOCAL_DECISION = "propose_flopo_local_bearer"


def derivation_spec() -> DerivationSpec:
    descriptor = {"protocol": DERIVATION_PROTOCOL}
    return DerivationSpec(
        protocol=DERIVATION_PROTOCOL,
        descriptor_sha256=hashlib.sha256(canonical_json(descriptor).encode()).hexdigest(),
    )


def _split(value: object) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in str(value or "").split("|") if item.strip()))


def _routing_key(group_key: object, candidate_po_id: object) -> tuple[str, str]:
    return str(group_key or "").strip(), str(candidate_po_id or "").strip()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: row must be an object")
            rows.append(row)
    return rows


def _load_evidence_catalog(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    result: dict[str, dict[str, str]] = {}
    for number, row in enumerate(rows, 2):
        identifier = str(row.get("evidence_id", "") or "").strip()
        if not identifier:
            raise ValueError(f"{path}:{number}: blank evidence_id")
        if identifier in result:
            raise ValueError(f"{path}:{number}: duplicate evidence_id {identifier}")
        result[identifier] = {key: str(value or "") for key, value in row.items()}
    return result


def _load_evidence_map(path: Path) -> dict[str, tuple[str, ...]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    result: defaultdict[str, list[str]] = defaultdict(list)
    for number, row in enumerate(rows, 2):
        proposal_key = str(row.get("proposal_key", "") or "").strip()
        evidence_id = str(row.get("evidence_id", "") or "").strip()
        if not proposal_key or not evidence_id:
            raise ValueError(f"{path}:{number}: proposal_key and evidence_id are required")
        if evidence_id in result[proposal_key]:
            raise ValueError(f"{path}:{number}: duplicate proposal/evidence mapping")
        result[proposal_key].append(evidence_id)
    return {key: tuple(values) for key, values in result.items()}


def _proposal_signature(row: dict[str, Any]) -> SupportClassSignature:
    part_of_ids = _split(row.get("part_of_target_ids"))
    relation = str(row.get("parthood_relation", "") or "").strip()
    if relation not in {"", "none", "part_of"}:
        raise ValueError(f"unsupported support-class relation: {relation!r}")
    if relation in {"", "none"} and part_of_ids:
        raise ValueError("support-class proposal has parthood targets without part_of")
    return SupportClassSignature(
        label=str(row.get("preferred_label", "") or "").strip(),
        definition=str(row.get("definition", "") or "").strip(),
        parent_ids=_split(row.get("direct_superclass_ids")),
        part_of_ids=part_of_ids if relation == "part_of" else (),
    )


def _group_proposals(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    exclusions: list[dict[str, Any]] = []
    for number, row in enumerate(_read_jsonl(path), 1):
        if str(row.get("decision", "") or "").strip() != LOCAL_DECISION:
            continue
        proposal_key = str(row.get("proposal_key", "") or "").strip()
        if not proposal_key:
            exclusions.append({"row": number, "reason": "missing_proposal_key"})
            continue
        grouped[proposal_key].append(row)

    proposals: dict[str, dict[str, Any]] = {}
    for proposal_key, rows in sorted(grouped.items()):
        try:
            signatures = {_proposal_signature(row) for row in rows}
        except ValueError as error:
            exclusions.append(
                {"proposal_key": proposal_key, "reason": "invalid_signature", "detail": str(error)}
            )
            continue
        if len(signatures) != 1:
            exclusions.append(
                {"proposal_key": proposal_key, "reason": "conflicting_group_signatures"}
            )
            continue
        routing_keys = tuple(
            sorted(
                {
                    _routing_key(row.get("src_group_key"), row.get("src_candidate_po_id"))
                    for row in rows
                }
            )
        )
        expected_count = sum(int(row.get("src_evidence_count", 0) or 0) for row in rows)
        if not routing_keys or any(not key[0] for key in routing_keys) or expected_count < 1:
            exclusions.append({"proposal_key": proposal_key, "reason": "invalid_routing_inventory"})
            continue
        claims = tuple(
            dict.fromkeys(
                str(source.get("claim", "") or "").strip()
                for row in rows
                for source in (row.get("_sources_used", []) or [])
                if isinstance(source, dict) and str(source.get("claim", "") or "").strip()
            )
        )
        proposals[proposal_key] = {
            "signature": next(iter(signatures)),
            "routing_keys": routing_keys,
            "expected_count": expected_count,
            "machine_source_claims": claims,
        }
    return proposals, exclusions


def _archived_authorities(
    proposal_key: str,
    evidence_ids: tuple[str, ...],
    evidence_catalog: dict[str, dict[str, str]],
) -> tuple[tuple[Path, ...], tuple[str, ...], tuple[str, ...]]:
    paths: list[Path] = []
    claims: list[str] = []
    for evidence_id in evidence_ids:
        row = evidence_catalog.get(evidence_id)
        if row is None:
            raise ValueError(f"{proposal_key}: unknown evidence ID {evidence_id}")
        local_file = Path(row.get("local_file", ""))
        expected_sha = row.get("sha256", "").strip()
        claim = row.get("claims_verified", "").strip()
        if not str(local_file) or not local_file.is_file() or len(expected_sha) != 64 or not claim:
            raise ValueError(f"{proposal_key}: evidence {evidence_id} is not archived and verified")
        actual_sha = sha256_file(local_file).sha256
        if actual_sha != expected_sha:
            raise ValueError(f"{proposal_key}: evidence checksum drift for {evidence_id}")
        paths.append(local_file)
        claims.append(f"{evidence_id}: {claim}")
    if not paths:
        raise ValueError(f"{proposal_key}: no frozen authority evidence")
    return tuple(paths), evidence_ids, tuple(claims)


def _marked_context(text: str, start: int, end: int) -> str:
    return f"{text[:start]}[[{text[start:end]}]]{text[end:]}".strip()


def _selected_samples(members: list[Occurrence], limit: int = 12) -> list[Occurrence]:
    if len(members) <= limit:
        return members
    indices = sorted({round(index * (len(members) - 1) / (limit - 1)) for index in range(limit)})
    return [members[index] for index in indices]


def _evidence_payload(occurrence: Occurrence) -> dict[str, Any]:
    return {
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
        "support_class_candidate": occurrence.support_class_candidate.model_dump(mode="json"),
    }


def build_support_inventory(
    *,
    curation_path: Path,
    bearer_occurrence_path: Path,
    evidence_map_path: Path,
    evidence_catalog_path: Path,
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
    """Build an immutable class-review campaign and lossless exclusion ledger."""

    ontology_paths = tuple(ontology_paths)
    source_paths = (bearer_occurrence_path, evidence_map_path, evidence_catalog_path)
    _validate_distinct_paths(
        curation_path,
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
    proposals, exclusions = _group_proposals(curation_path)
    evidence_map = _load_evidence_map(evidence_map_path)
    evidence_catalog = _load_evidence_catalog(evidence_catalog_path)

    candidate_authorities: dict[str, tuple[tuple[Path, ...], tuple[str, ...], tuple[str, ...]]] = {}
    for proposal_key in sorted(proposals):
        mapped = evidence_map.get(proposal_key, ())
        try:
            candidate_authorities[proposal_key] = _archived_authorities(
                proposal_key, mapped, evidence_catalog
            )
        except ValueError as error:
            exclusions.append(
                {
                    "proposal_key": proposal_key,
                    "reason": "authority_evidence_not_verified",
                    "detail": str(error),
                }
            )

    eligible = set(candidate_authorities)
    routing_to_proposal: dict[tuple[str, str], str] = {}
    for proposal_key in sorted(eligible):
        for key in proposals[proposal_key]["routing_keys"]:
            previous = routing_to_proposal.setdefault(key, proposal_key)
            if previous != proposal_key:
                raise ValueError(f"routing key {key!r} targets multiple support proposals")

    raw_members: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(bearer_occurrence_path):
        routing = row.get("routing")
        if not isinstance(routing, dict):
            raise ValueError("bearer occurrence has no routing object")
        key = _routing_key(routing.get("group_key"), routing.get("candidate_po_id"))
        proposal_key = routing_to_proposal.get(key)
        if proposal_key is not None:
            raw_members[proposal_key].append(row)

    authority_paths = tuple(
        dict.fromkeys(
            path
            for proposal_key in sorted(eligible)
            for path in candidate_authorities[proposal_key][0]
        )
    )
    authority_hashes = tuple(sha256_file(path) for path in authority_paths)
    authority_ids = {
        artifact.path: stable_id("evidence", ("authority", artifact.path, artifact.sha256))
        for artifact in authority_hashes
    }

    occurrences: list[Occurrence] = []
    clusters: list[Cluster] = []
    for proposal_key in sorted(eligible):
        proposal = proposals[proposal_key]
        members = raw_members.get(proposal_key, [])
        expected_count = proposal["expected_count"]
        if len(members) != expected_count:
            raise ValueError(
                f"{proposal_key}: expected {expected_count} occurrences, found {len(members)}"
            )
        authority_paths_for_candidate, source_register_ids, verified_claims = (
            candidate_authorities[proposal_key]
        )
        candidate_without_count = {
            "proposal_key": proposal_key,
            "signature": proposal["signature"].model_dump(mode="json"),
            "routing_keys": [f"{left}|{right}" for left, right in proposal["routing_keys"]],
            "source_register_ids": list(source_register_ids),
            "authority_evidence_ids": [
                authority_ids[str(path)] for path in authority_paths_for_candidate
            ],
            "source_claims": list(verified_claims),
        }
        candidate = SupportClassCandidate(
            **candidate_without_count,
            occurrence_count=len(members),
        )
        semantic_fingerprint = hashlib.sha256(
            canonical_json(
                {"protocol": DERIVATION_PROTOCOL, "candidate": candidate.model_dump(mode="json")}
            ).encode()
        ).hexdigest()
        cluster_id = stable_id(
            "cluster", (DERIVATION_PROTOCOL, proposal_key, semantic_fingerprint)
        )
        cluster_members: list[Occurrence] = []
        for row in members:
            quality = row.get("quality")
            if not isinstance(quality, dict):
                raise ValueError(f"{proposal_key}: occurrence has no quality object")
            text = str(row.get("text", "") or "")
            start = int(quality.get("start", -1))
            end = int(quality.get("end", -1))
            surface = str(quality.get("surface_form", "") or "")
            if not (0 <= start < end <= len(text)) or text[start:end] != surface:
                raise ValueError(f"{proposal_key}: occurrence quality span is not verbatim")
            original_id = str(row.get("occurrence_id", "") or "")
            occurrence_id = stable_id("occ", (DERIVATION_PROTOCOL, proposal_key, original_id))
            context = _marked_context(text, start, end)
            evidence_id = stable_id(
                "evidence", (occurrence_id, cluster_id, semantic_fingerprint, context)
            )
            occurrence = Occurrence(
                occurrence_id=occurrence_id,
                evidence_id=evidence_id,
                cluster_id=cluster_id,
                semantic_fingerprint=semantic_fingerprint,
                source=str(row.get("source", "") or ""),
                source_id=str(row.get("source_id", "") or ""),
                source_segment_index=int(row.get("source_segment_index", 0) or 0),
                taxon=str(row.get("taxon", "") or ""),
                organ=str(row.get("organ", "") or ""),
                language=str(row.get("language", "") or ""),
                segment_char_start=int(row.get("segment_document_start", 0) or 0),
                segment_char_end=int(row.get("segment_document_end", len(text)) or len(text)),
                span_start=start,
                span_end=end,
                surface_form=surface,
                normalized_form=normalized_text(surface),
                reason="missing_or_unsupported_bearer",
                candidate_pato_id=str(quality.get("candidate_pato_id", "") or ""),
                pending_bearer=candidate.signature.label,
                promoted_po_ids=(),
                extractor=str(quality.get("extractor", "") or "bearer_occurrence_inventory"),
                context=context,
                support_class_candidate=candidate,
            )
            occurrences.append(occurrence)
            cluster_members.append(occurrence)
        membership = tuple(sorted(row.occurrence_id for row in cluster_members))
        samples = _selected_samples(cluster_members)
        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                normalized_form=normalized_text(candidate.signature.label),
                reason="missing_anatomy_support_class",
                language="multilingual",
                organ="mixed",
                pending_bearer=candidate.signature.label,
                semantic_fingerprint=semantic_fingerprint,
                occurrence_count=len(cluster_members),
                occurrence_membership_sha256=hashlib.sha256(
                    canonical_json(membership).encode()
                ).hexdigest(),
                context_samples=tuple(
                    ContextSample(
                        evidence_id=row.evidence_id,
                        occurrence_id=row.occurrence_id,
                        context=row.context,
                        context_sha256=hashlib.sha256(row.context.encode()).hexdigest(),
                    )
                    for row in samples
                ),
                support_class_candidate=candidate,
            )
        )

    occurrences.sort(key=lambda row: (row.cluster_id, row.occurrence_id))
    clusters.sort(key=lambda row: row.cluster_id)
    ontology_hashes = tuple(sha256_file(path) for path in ontology_paths)
    source_hashes = tuple(sha256_file(path) for path in source_paths)
    prompts = tuple(
        PromptSpec(prompt_id=prompt_id, **sha256_file(path).model_dump())
        for prompt_id, path in sorted(prompt_paths.items())
    )
    model_rows = tuple(models)
    derivation = derivation_spec()
    input_hash = sha256_file(curation_path)
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
    for path in (
        occurrence_path,
        cluster_path,
        evidence_path,
        exclusion_path,
        report_path,
    ):
        if path.exists():
            raise FileExistsError(f"refusing to replace pre-existing campaign artifact: {path}")

    evidence_rows = [
        *(
            EvidenceRecord(
                evidence_id=row.evidence_id,
                kind="occurrence",
                occurrence_id=row.occurrence_id,
                item_id=row.cluster_id,
                payload_sha256=hashlib.sha256(
                    canonical_json(_evidence_payload(row)).encode()
                ).hexdigest(),
                locator=(
                    f"{row.source}:{row.source_id}:{row.source_segment_index}:"
                    f"{row.span_start}-{row.span_end}"
                ),
                description="Verbatim flora occurrence supporting a local anatomy proposal",
            )
            for row in occurrences
        ),
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
            for row in sorted(
                exclusions,
                key=lambda row: (str(row.get("proposal_key", "")), str(row.get("reason", ""))),
            )
        )
        atomic_write_text(exclusion_path, exclusion_payload)
        report = {
            "schema_version": "flopo-support-class-candidate-report-v1",
            "campaign_id": manifest.campaign_id,
            "curation": sha256_file(curation_path).model_dump(),
            "bearer_occurrences": sha256_file(bearer_occurrence_path).model_dump(),
            "evidence_map": sha256_file(evidence_map_path).model_dump(),
            "evidence_catalog": sha256_file(evidence_catalog_path).model_dump(),
            "eligible_classes": len(clusters),
            "eligible_occurrences": len(occurrences),
            "excluded_classes": len(exclusions),
            "candidate_occurrences": {
                row.support_class_candidate.proposal_key: row.occurrence_count for row in clusters
            },
            "occurrences": manifest.occurrences.model_dump(),
            "clusters": manifest.clusters.model_dump(),
            "evidence_registry": manifest.evidence_registry.model_dump(),
            "exclusions": sha256_file(exclusion_path).model_dump(),
            "conservation": {
                "eligible_plus_excluded_equals_local_proposals": (
                    len(clusters) + len(exclusions) == len(proposals)
                ),
                "occurrence_counts_match_group_inventory": True,
                "all_authority_files_hash_verified": True,
            },
        }
        atomic_write_text(
            report_path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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
    parser.add_argument("--curation", type=Path, required=True)
    parser.add_argument("--bearer-occurrences", type=Path, required=True)
    parser.add_argument("--evidence-map", type=Path, required=True)
    parser.add_argument("--evidence-catalog", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, action="append", required=True)
    parser.add_argument("--prompt", action="append", required=True)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    prompt_paths: dict[str, Path] = {}
    for item in args.prompt:
        if "=" not in item:
            parser.error("--prompt expects ID=PATH")
        identifier, path = item.split("=", 1)
        prompt_paths[identifier] = Path(path)
    raw_models = json.loads(args.models.read_text(encoding="utf-8"))
    models = [model_spec(**row) for row in raw_models]
    manifest = build_support_inventory(
        curation_path=args.curation,
        bearer_occurrence_path=args.bearer_occurrences,
        evidence_map_path=args.evidence_map,
        evidence_catalog_path=args.evidence_catalog,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        exclusion_path=args.exclusions,
        report_path=args.report,
        manifest_path=args.manifest,
        ontology_paths=args.ontology,
        prompt_paths=prompt_paths,
        models=models,
    )
    print(manifest.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
