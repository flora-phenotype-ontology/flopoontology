"""Build hash-bound adversarial packets from exact, locally valid reviewer agreement."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from flopo2.review.consensus import _load_unique, _validate_provenance
from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import CampaignManifest, ReviewDecision, canonical_json
from flopo2.review.validation import load_validation_context, validate_review_decision


def _candidate(reviewers: list[ReviewDecision], cluster: dict) -> dict | None:
    if len(reviewers) != 2:
        return None
    first, second = reviewers
    if (
        first.reviewer_id == second.reviewer_id
        or first.model_family.casefold() == second.model_family.casefold()
        or first.disposition not in {
            "reusable_flopo_class",
            "reusable_flopo_support_class",
        }
        or second.disposition != first.disposition
        or first.normalized_signature != second.normalized_signature
    ):
        return None
    return {
        "cluster_id": first.item_id,
        "candidate_signature": json.loads(first.normalized_signature),
        "candidate_signature_sha256": first.signature_sha256,
        "reviewers": [
            {
                "reviewer_id": row.reviewer_id,
                "provider": row.provider,
                "model": row.model,
                "model_family": row.model_family,
                "reasoning_effort": row.reasoning_effort,
                "rationale": row.rationale,
                "confidence": row.confidence,
                "evidence_ids": list(row.evidence_ids),
            }
            for row in sorted(reviewers, key=lambda row: row.reviewer_id)
        ],
        "cluster": cluster,
    }


def build_adversarial_batches(
    *,
    manifest: CampaignManifest,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    review_paths: Iterable[Path],
    output_dir: Path,
    batch_size: int = 10,
    max_bytes: int = 120_000,
) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if max_bytes < 4_096:
        raise ValueError("max_bytes must be at least 4096")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    paths = tuple(review_paths)
    reviews = _load_unique(paths, ReviewDecision, lambda row: (row.item_id, row.reviewer_id))
    grouped: defaultdict[str, list[ReviewDecision]] = defaultdict(list)
    for review in reviews:
        _validate_provenance(review, manifest, expected_role="reviewer")
        if review.item_id not in context.clusters:
            raise ValueError(f"review decision targets unknown item: {review.item_id}")
        validation = validate_review_decision(review, context)
        if validation.passed:
            grouped[review.item_id].append(review)

    candidates = []
    for item_id in sorted(grouped):
        candidate = _candidate(
            grouped[item_id], context.clusters[item_id].model_dump(mode="json")
        )
        if candidate is not None:
            candidates.append(candidate)
    candidate_set_sha256 = hashlib.sha256(canonical_json(candidates).encode()).hexdigest()
    reference_evidence = [
        {
            "evidence_id": stable_id(
                "evidence", (kind, artifact.path, artifact.sha256)
            ),
            "kind": kind,
            "path": artifact.path,
            "sha256": artifact.sha256,
            "bytes": artifact.bytes,
        }
        for kind, artifacts in (
            ("ontology", manifest.ontologies),
            ("authority", manifest.authorities),
            ("source_inventory", manifest.sources),
        )
        for artifact in artifacts
    ]

    groups: list[list[dict]] = []
    current: list[dict] = []
    for candidate in candidates:
        proposed = [*current, candidate]
        probe = {
            "schema_version": "flopo-adversarial-batch-v1",
            "campaign_id": manifest.campaign_id,
            "batch_id": "batch_99999",
            "item_count": len(proposed),
            "candidate_set_sha256": candidate_set_sha256,
            "reference_evidence": reference_evidence,
            "items": proposed,
        }
        size = len((json.dumps(probe, ensure_ascii=False, sort_keys=True) + "\n").encode())
        if current and (len(proposed) > batch_size or size > max_bytes):
            groups.append(current)
            current = [candidate]
        else:
            current = proposed
        if len(current) == 1:
            probe["item_count"] = 1
            probe["items"] = [candidate]
            if len((json.dumps(probe, ensure_ascii=False, sort_keys=True) + "\n").encode()) > max_bytes:
                raise ValueError(f"adversarial candidate {candidate['cluster_id']} is too large")
    if current:
        groups.append(current)

    output_dir.mkdir(parents=True, exist_ok=True)
    packets = []
    for number, members in enumerate(groups, 1):
        packet = {
            "schema_version": "flopo-adversarial-batch-v1",
            "campaign_id": manifest.campaign_id,
            "batch_id": f"batch_{number:05d}",
            "item_count": len(members),
            "candidate_set_sha256": candidate_set_sha256,
            "reference_evidence": reference_evidence,
            "items": members,
        }
        payload = json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path = output_dir / f"batch-{number:05d}.json"
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise FileExistsError(f"refusing to replace changed adversarial batch: {path}")
        atomic_write_text(path, payload)
        artifact = sha256_file(path)
        packets.append(
            {
                "batch_id": packet["batch_id"],
                "path": str(path),
                "sha256": artifact.sha256,
                "bytes": artifact.bytes,
                "item_count": len(members),
                "first_item_id": members[0]["cluster_id"],
                "last_item_id": members[-1]["cluster_id"],
            }
        )
    index = {
        "schema_version": "flopo-adversarial-batch-index-v1",
        "campaign_id": manifest.campaign_id,
        "cluster_sha256": manifest.clusters.sha256,
        "evidence_sha256": manifest.evidence_registry.sha256,
        "candidate_set_sha256": candidate_set_sha256,
        "review_artifacts": [sha256_file(path).model_dump() for path in paths],
        "batch_size": batch_size,
        "max_bytes": max_bytes,
        "batch_count": len(packets),
        "item_count": len(candidates),
        "batches": packets,
    }
    index_path = output_dir / "index.json"
    payload = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if index_path.exists() and index_path.read_text(encoding="utf-8") != payload:
        raise FileExistsError("refusing to replace changed adversarial batch index")
    atomic_write_text(index_path, payload)
    return index
