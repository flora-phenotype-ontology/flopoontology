"""Build immutable, provider-neutral LLM review batches from a frozen campaign."""

from __future__ import annotations

import json
from pathlib import Path

from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file, stable_id
from flopo2.review.models import CampaignManifest, Cluster


_REASON_PRIORITY = {
    "missing_or_unsupported_bearer": 0,
    "developmental_stage_context": 1,
    "negated_context": 2,
    "explicit_disjunction": 3,
    "same_attribute_composite_or_transition": 4,
    "unsupported_same_attribute_neighbor": 5,
    "unsupported_alternative_or_transition": 6,
    "hyphenated_or_slash_compound": 7,
}


def _reference_evidence(manifest: CampaignManifest) -> list[dict]:
    return [
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


def build_batches(
    manifest: CampaignManifest,
    cluster_path: Path,
    output_dir: Path,
    *,
    batch_size: int = 20,
    max_bytes: int = 120_000,
    order: str = "priority",
) -> dict:
    """Write deterministic review packets without invoking or trusting a model provider."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if max_bytes < 4_096:
        raise ValueError("max_bytes must be at least 4096")
    if order not in {"priority", "cluster_id"}:
        raise ValueError("order must be 'priority' or 'cluster_id'")
    if sha256_file(cluster_path).sha256 != manifest.clusters.sha256:
        raise ValueError("cluster inventory hash does not match immutable campaign manifest")
    clusters = list(read_jsonl(cluster_path, Cluster))
    if len(clusters) != manifest.starting_clusters:
        raise ValueError("cluster count does not match immutable campaign manifest")
    identifiers = [row.cluster_id for row in clusters]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate cluster identifier")
    if order == "priority":
        clusters.sort(
            key=lambda row: (
                _REASON_PRIORITY.get(row.reason, len(_REASON_PRIORITY)),
                -row.occurrence_count,
                row.cluster_id,
            )
        )
    else:
        clusters.sort(key=lambda row: row.cluster_id)
    reference_evidence = _reference_evidence(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_groups: list[list[Cluster]] = []
    current: list[Cluster] = []
    for cluster in clusters:
        candidate = [*current, cluster]
        probe = {
            "schema_version": "flopo-review-batch-v2",
            "campaign_id": manifest.campaign_id,
            "batch_id": "batch_99999",
            "item_count": len(candidate),
            "reference_evidence": reference_evidence,
            "items": [row.model_dump(mode="json") for row in candidate],
        }
        encoded_bytes = len(
            (json.dumps(probe, ensure_ascii=False, sort_keys=True) + "\n").encode()
        )
        if current and (len(candidate) > batch_size or encoded_bytes > max_bytes):
            packet_groups.append(current)
            current = [cluster]
        else:
            current = candidate
        if len(current) == 1:
            single = {**probe, "item_count": 1, "items": [cluster.model_dump(mode="json")]}
            if len((json.dumps(single, ensure_ascii=False, sort_keys=True) + "\n").encode()) > max_bytes:
                raise ValueError(f"cluster {cluster.cluster_id} exceeds max_bytes by itself")
    if current:
        packet_groups.append(current)

    packets = []
    for index, members in enumerate(packet_groups, 1):
        packet = {
            "schema_version": "flopo-review-batch-v2",
            "campaign_id": manifest.campaign_id,
            "batch_id": f"batch_{index:05d}",
            "item_count": len(members),
            "reference_evidence": reference_evidence,
            "items": [row.model_dump(mode="json") for row in members],
        }
        path = output_dir / f"batch-{index:05d}.json"
        payload = json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise FileExistsError(f"refusing to replace changed review batch: {path}")
        atomic_write_text(path, payload)
        packets.append(
            {
                "batch_id": packet["batch_id"],
                "path": str(path),
                "sha256": sha256_file(path).sha256,
                "item_count": len(members),
                "occurrence_count": sum(row.occurrence_count for row in members),
                "first_item_id": members[0].cluster_id,
                "last_item_id": members[-1].cluster_id,
                "bytes": sha256_file(path).bytes,
            }
        )
    index_payload = {
        "schema_version": "flopo-review-batch-index-v2",
        "campaign_id": manifest.campaign_id,
        "cluster_sha256": manifest.clusters.sha256,
        "batch_size": batch_size,
        "max_bytes": max_bytes,
        "order": order,
        "batch_count": len(packets),
        "item_count": len(clusters),
        "occurrence_count": sum(row.occurrence_count for row in clusters),
        "batches": packets,
    }
    index_path = output_dir / "index.json"
    payload = json.dumps(index_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if index_path.exists() and index_path.read_text(encoding="utf-8") != payload:
        raise FileExistsError(f"refusing to replace changed review batch index: {index_path}")
    atomic_write_text(index_path, payload)
    return index_payload


def build_stratified_pilot_batch(
    manifest: CampaignManifest,
    cluster_path: Path,
    output_dir: Path,
    *,
    per_reason: int = 1,
    max_bytes: int = 120_000,
) -> dict:
    """Build one bounded packet from the highest-volume exact cluster in every reason family."""

    if per_reason < 1:
        raise ValueError("per_reason must be positive")
    if sha256_file(cluster_path).sha256 != manifest.clusters.sha256:
        raise ValueError("cluster inventory hash does not match immutable campaign manifest")
    grouped: dict[str, list[Cluster]] = {}
    for cluster in read_jsonl(cluster_path, Cluster):
        grouped.setdefault(cluster.reason, []).append(cluster)
    selected: list[Cluster] = []
    for reason in sorted(
        grouped,
        key=lambda value: (_REASON_PRIORITY.get(value, len(_REASON_PRIORITY)), value),
    ):
        members = sorted(
            grouped[reason], key=lambda row: (-row.occurrence_count, row.cluster_id)
        )
        selected.extend(members[:per_reason])
    packet = {
        "schema_version": "flopo-review-batch-v2",
        "campaign_id": manifest.campaign_id,
        "batch_id": "batch_90001",
        "item_count": len(selected),
        "reference_evidence": _reference_evidence(manifest),
        "items": [row.model_dump(mode="json") for row in selected],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "batch-90001.json"
    payload = json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    payload_bytes = len(payload.encode())
    if payload_bytes > max_bytes:
        raise ValueError(f"stratified pilot is {payload_bytes} bytes, above {max_bytes}")
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise FileExistsError(f"refusing to replace changed pilot batch: {path}")
    atomic_write_text(path, payload)
    artifact = sha256_file(path)
    index = {
        "schema_version": "flopo-review-batch-index-v2",
        "campaign_id": manifest.campaign_id,
        "cluster_sha256": manifest.clusters.sha256,
        "batch_size": len(selected),
        "max_bytes": max_bytes,
        "order": "stratified_pilot",
        "scope": "pilot",
        "batch_count": 1,
        "item_count": len(selected),
        "occurrence_count": sum(row.occurrence_count for row in selected),
        "batches": [
            {
                "batch_id": packet["batch_id"],
                "path": str(path),
                "sha256": artifact.sha256,
                "bytes": artifact.bytes,
                "item_count": len(selected),
                "occurrence_count": sum(row.occurrence_count for row in selected),
                "first_item_id": selected[0].cluster_id,
                "last_item_id": selected[-1].cluster_id,
            }
        ],
    }
    index_path = output_dir / "index.json"
    index_payload = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if index_path.exists() and index_path.read_text(encoding="utf-8") != index_payload:
        raise FileExistsError("refusing to replace changed pilot batch index")
    atomic_write_text(index_path, index_payload)
    return index
