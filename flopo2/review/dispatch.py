"""Resumable, hash-bound dispatch to Claude and Codex command-line providers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import httpx
from pydantic import Field

from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file, write_jsonl
from flopo2.review.models import (
    AdversarialBatchResponse,
    AdversarialVerdict,
    CampaignManifest,
    ModelSpec,
    ReviewBatchResponse,
    ReviewDecision,
    Sha256,
    StrictModel,
    canonical_json,
)
from flopo2.review.responses import response_schema


Runner = Callable[..., subprocess.CompletedProcess[str]]


class DispatchBinding(StrictModel):
    schema_version: Literal["flopo-dispatch-binding-v2"] = "flopo-dispatch-binding-v2"
    runner_protocol: Literal["flopo-read-only-dispatch-v2"] = "flopo-read-only-dispatch-v2"
    campaign_id: str = Field(pattern=r"^campaign_[0-9a-f]{24}$")
    manifest_sha256: Sha256
    batch_id: str = Field(pattern=r"^batch_[0-9]{5}$")
    batch_sha256: Sha256
    batch_index_sha256: Sha256
    reviewer_id: str
    provider: str
    model: str
    model_family: str
    reasoning_effort: str
    role: Literal["reviewer", "adjudicator"]
    backend: Literal["claude", "codex", "openrouter"]
    prompt_id: str
    prompt_sha256: Sha256
    expected_item_ids: tuple[str, ...]
    response_schema_sha256: Sha256
    assembled_prompt_sha256: Sha256
    read_only_policy_sha256: Sha256


class CompletionCheckpoint(StrictModel):
    schema_version: Literal["flopo-dispatch-completion-v2"] = (
        "flopo-dispatch-completion-v2"
    )
    campaign_id: str
    batch_id: str
    reviewer_id: str
    binding_sha256: Sha256
    raw_response_sha256: Sha256
    normalized_sha256: Sha256
    provider_envelope_sha256: Sha256
    decision_count: int = Field(ge=0)
    completed_at: datetime


class ProviderEnvelope(StrictModel):
    schema_version: Literal["flopo-provider-envelope-v1"] = "flopo-provider-envelope-v1"
    campaign_id: str
    batch_id: str
    reviewer_id: str
    backend: Literal["claude", "codex", "openrouter"]
    requested_model: str
    returned_model: str = ""
    model_verification: Literal["command_pinned", "provider_reported_match"]
    reasoning_effort: str
    provider_request_id: str = ""
    request_parameters_sha256: Sha256
    provider_output_sha256: Sha256
    raw_response_sha256: Sha256
    started_at: datetime
    completed_at: datetime


def _digest_text(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_batch(
    batch_path: Path,
    index_path: Path,
    manifest: CampaignManifest,
    *,
    role: str,
) -> tuple[dict, str]:
    try:
        packet = json.loads(batch_path.read_text(encoding="utf-8"))
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid review batch input: {exc}") from exc
    packet_schema = (
        "flopo-review-batch-v2" if role == "reviewer" else "flopo-adversarial-batch-v1"
    )
    index_schema = (
        "flopo-review-batch-index-v2"
        if role == "reviewer"
        else "flopo-adversarial-batch-index-v1"
    )
    if packet.get("schema_version") != packet_schema:
        raise ValueError("unsupported review batch schema")
    if packet.get("campaign_id") != manifest.campaign_id:
        raise ValueError("review batch belongs to another campaign")
    if index.get("schema_version") != index_schema:
        raise ValueError("unsupported review batch index schema")
    if index.get("campaign_id") != manifest.campaign_id:
        raise ValueError("review batch index belongs to another campaign")
    if index.get("cluster_sha256") != manifest.clusters.sha256:
        raise ValueError("review batch index is not bound to the campaign cluster inventory")
    if role == "adjudicator":
        if index.get("evidence_sha256") != manifest.evidence_registry.sha256:
            raise ValueError("adversarial index is not bound to the evidence registry")
        if packet.get("candidate_set_sha256") != index.get("candidate_set_sha256"):
            raise ValueError("adversarial batch candidate set does not match its index")
    batch_sha256 = sha256_file(batch_path).sha256
    indexed = [
        row
        for row in index.get("batches", [])
        if row.get("batch_id") == packet.get("batch_id")
    ]
    if len(indexed) != 1 or indexed[0].get("sha256") != batch_sha256:
        raise ValueError("review batch hash does not match its immutable index")
    items = packet.get("items")
    if not isinstance(items, list) or packet.get("item_count") != len(items):
        raise ValueError("review batch item count is invalid")
    identifiers = [
        str(item.get("cluster_id", "")) for item in items if isinstance(item, dict)
    ]
    if len(identifiers) != len(items) or any(not value for value in identifiers):
        raise ValueError("review batch contains an invalid item")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("review batch contains duplicate items")
    return packet, batch_sha256


def _backend_for(model: ModelSpec, requested: str) -> Literal["claude", "codex", "openrouter"]:
    if requested not in {"auto", "claude", "codex", "openrouter"}:
        raise ValueError("backend must be auto, claude, codex, or openrouter")
    provider = model.provider.casefold()
    if "anthropic" in provider or "claude" in provider:
        inferred: Literal["claude", "codex", "openrouter"] = "claude"
    elif "openai" in provider or "codex" in provider:
        inferred = "codex"
    elif "openrouter" in provider:
        inferred = "openrouter"
    else:
        raise ValueError(f"cannot infer CLI backend from provider {model.provider!r}")
    if inferred == "openrouter" and requested == "auto":
        raise ValueError("OpenRouter dispatch must be explicitly requested with --backend openrouter")
    if requested != "auto" and requested != inferred:
        raise ValueError(
            f"backend {requested!r} does not match configured provider {model.provider!r}"
        )
    return inferred


def _assemble_prompt(
    base_prompt: str,
    packet: dict,
    binding: dict[str, Any],
    *,
    role: str,
    workspace_readable: bool,
    embedded_response_schema: dict[str, Any] | None = None,
) -> str:
    packet_items = packet.get("items", [])
    reusable_class_only = role == "reviewer" and bool(packet_items) and all(
        item.get("reusable_flopo_class_candidate") is not None for item in packet_items
    )
    expression_only = role == "reviewer" and bool(packet_items) and all(
        item.get("phenotype_expression_candidate") is not None
        and item.get("reusable_flopo_class_candidate") is None
        and item.get("qualitative_relation_candidate") is None
        and item.get("support_class_candidate") is None
        for item in packet_items
    )
    if reusable_class_only:
        kind_contract = (
            "For an accepted exact class candidate set `disposition` to exactly "
            "`reusable_flopo_class`; never use `accept`, `accepted`, or a `decision` field. "
            "Copy the runner candidate's expression, label, definition, parents, and authority "
            "evidence exactly into `proposed_signature`; never repair or embellish them. An "
            "accepted signature contains exactly `kind`, `expression`, `label`, `definition`, "
            "`parent_ids`, and `authoritative_evidence_ids`. A hold signature contains exactly "
            "`kind`, `reason`, and `missing_evidence`. Never put a reason or missing-evidence "
            "field inside an accepted class signature. "
        )
        signature_contract = (
            "The strict schema provides separate closed accepted-class and hold signature "
            "objects; emit only the fields in the selected object. "
        )
    elif expression_only:
        kind_contract = (
            "For an accepted exact occurrence set `disposition` to exactly "
            "`annotation_expression`. Copy the runner candidate's expression exactly into a "
            "`proposed_signature` containing only `kind` and `expression`; never repair or "
            "embellish it. A hold signature contains exactly `kind`, `reason`, and "
            "`missing_evidence`. "
        )
        signature_contract = (
            "The strict schema provides separate closed accepted-expression and hold signature "
            "objects; emit only the fields in the selected object. "
        )
    else:
        kind_contract = (
            "For an accepted qualitative candidate set `disposition` to exactly "
            "`structured_qualitative_relation`; never use `accept`, `accepted`, or a `decision` "
            "field. In particular, a structured_qualitative_relation signature contains only "
            "kind and qualitative_relation, with authoritative_evidence_ids and all other "
            "arrays empty. "
        )
        signature_contract = (
            "The strict schema exposes nullable and array fields for every signature variant: "
            "populate only the fields allowed for the selected kind; set every unused nullable "
            "field to null and every unused array field to []. "
        )
    common = (
        "Return one top-level JSON object with exactly `schema_version` and `decisions`; set "
        "`schema_version` to `flopo-review-batch-response-v1`, and put one structured decision "
        "for every item in the `decisions` array, in the supplied order. Return no additional "
        "items or top-level keys. Copy every campaign, reviewer, provider, model, model-family, "
        "reasoning-effort, prompt ID, and prompt hash field exactly from DISPATCH_BINDING into "
        "each decision object—not into the top-level wrapper. Thus every decision must contain "
        "`campaign_id`, its packet `item_id`, `reviewer_id`, `provider`, `model`, `model_family`, "
        "`reasoning_effort`, `prompt_id`, and `prompt_sha256`. Do not claim human review or attach "
        "curator metadata. Never fabricate a decision, identifier, "
        "evidence ID, or source. Every decision uses `schema_version` "
        "`flopo-review-decision-v1`, the field `disposition`, a numeric `confidence` from 0 to 1, "
        "and a top-level boolean `validation_passed`. "
        + kind_contract
        + "Keep `confidence` and `validation_passed` outside "
        "`proposed_signature`. "
        + signature_contract
        + "Even when evidence is "
        "insufficient, return exactly one hold decision for the item; never omit or duplicate it. "
    )
    evidence_access = (
        "You may use only read-only file inspection to verify the frozen paths in the campaign "
        "manifest; do not inspect unrelated workspace files. "
        if workspace_readable
        else "You have no workspace tools; rely only on evidence embedded in the packet. "
    )
    instructions = (
        common
        + evidence_access
        + (
            "If evidence is insufficient, use the typed hold disposition."
            if role == "reviewer"
            else "Inspect the complete agreed proposal and both reviews in the adversarial packet; "
            "return block whenever evidence or universal semantics are insufficient."
        )
    )
    schema_section = (
        f"\n\nRESPONSE_JSON_SCHEMA\n{canonical_json(embedded_response_schema)}"
        if embedded_response_schema is not None
        else ""
    )
    return (
        "FLOPO MACHINE REVIEW\n\n"
        f"DISPATCH_BINDING\n{canonical_json(binding)}\n\n"
        f"REVIEW_INSTRUCTIONS\n{instructions}\n\n"
        f"CAMPAIGN_PROMPT\n{base_prompt.rstrip()}\n\n"
        f"IMMUTABLE_BATCH\n{canonical_json(packet)}"
        f"{schema_section}\n"
    )


def _bind_response_schema_to_packet(
    schema: dict[str, Any], packet: dict[str, Any], *, role: str
) -> None:
    """Constrain provider output to the immutable packet's exact cardinality and kind."""

    items = packet.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("review packet has no items")
    decisions_schema = schema.get("properties", {}).get("decisions")
    if not isinstance(decisions_schema, dict):
        raise ValueError("provider response schema has no decisions array")
    decisions_schema["minItems"] = len(items)
    decisions_schema["maxItems"] = len(items)

    qualitative_only = role == "reviewer" and all(
        item.get("qualitative_relation_candidate") is not None
        and item.get("phenotype_expression_candidate") is None
        and item.get("support_class_candidate") is None
        for item in items
    )
    reusable_class_only = role == "reviewer" and all(
        item.get("reusable_flopo_class_candidate") is not None
        and item.get("qualitative_relation_candidate") is None
        and item.get("phenotype_expression_candidate") is None
        and item.get("support_class_candidate") is None
        for item in items
    )
    expression_only = role == "reviewer" and all(
        item.get("phenotype_expression_candidate") is not None
        and item.get("reusable_flopo_class_candidate") is None
        and item.get("qualitative_relation_candidate") is None
        and item.get("support_class_candidate") is None
        for item in items
    )
    if not qualitative_only and not reusable_class_only and not expression_only:
        return
    if qualitative_only:
        allowed = ["structured_qualitative_relation", "hold"]
    elif reusable_class_only:
        allowed = ["reusable_flopo_class", "hold"]
    else:
        allowed = ["annotation_expression", "hold"]
    definitions = schema.get("$defs", {})
    signature_definition = definitions.get("ProposedSignature", {})
    signature_properties = signature_definition.get("properties", {})
    decision_properties = definitions.get("ReviewDecision", {}).get("properties", {})
    kind_schema = signature_properties.get("kind")
    disposition_schema = decision_properties.get("disposition")
    if not isinstance(kind_schema, dict) or not isinstance(disposition_schema, dict):
        raise ValueError("review schema cannot be narrowed to qualitative decisions")
    kind_schema["enum"] = allowed
    disposition_schema["enum"] = allowed
    if reusable_class_only or expression_only:
        accepted_fields = (
            (
                "kind",
                "expression",
                "label",
                "definition",
                "parent_ids",
                "authoritative_evidence_ids",
            )
            if reusable_class_only
            else ("kind", "expression")
        )
        accepted_kind = (
            "reusable_flopo_class" if reusable_class_only else "annotation_expression"
        )
        hold_fields = ("kind", "reason", "missing_evidence")

        def variant(fields: tuple[str, ...], kind: str) -> dict[str, Any]:
            properties = {
                field: deepcopy(signature_properties[field]) for field in fields
            }
            properties["kind"] = {"const": kind, "type": "string"}
            return {
                "additionalProperties": False,
                "properties": properties,
                "required": list(fields),
                "type": "object",
            }

        signature_definition.clear()
        signature_definition.update(
            {
                "anyOf": [
                    variant(accepted_fields, accepted_kind),
                    variant(hold_fields, "hold"),
                ],
                "title": "ProposedSignature",
            }
        )
        return
    permitted_fields = (
        {"kind", "qualitative_relation", "reason", "missing_evidence"}
        if qualitative_only
        else {
            "kind",
            "expression",
            "label",
            "definition",
            "parent_ids",
            "authoritative_evidence_ids",
            "reason",
            "missing_evidence",
        }
    )
    signature_definition["properties"] = {
        key: value
        for key, value in signature_properties.items()
        if key in permitted_fields
    }
    required = signature_definition.get("required")
    if not isinstance(required, list):
        raise ValueError("review signature schema has no required-field list")
    signature_definition["required"] = [
        field for field in required if field in permitted_fields
    ]


def _validate_response(response, binding: DispatchBinding) -> tuple:
    decisions = response.decisions
    item_ids = [row.item_id for row in decisions]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("provider response contains duplicate decisions")
    if tuple(item_ids) != binding.expected_item_ids:
        missing = sorted(set(binding.expected_item_ids) - set(item_ids))
        unexpected = sorted(set(item_ids) - set(binding.expected_item_ids))
        raise ValueError(
            "provider response is not an exact ordered batch: "
            f"missing={missing}, unexpected={unexpected}"
        )
    expected = {
        "campaign_id": binding.campaign_id,
        "reviewer_id": binding.reviewer_id,
        "provider": binding.provider,
        "model": binding.model,
        "model_family": binding.model_family,
        "reasoning_effort": binding.reasoning_effort,
        "prompt_id": binding.prompt_id,
        "prompt_sha256": binding.prompt_sha256,
    }
    for decision in decisions:
        for field, value in expected.items():
            if getattr(decision, field) != value:
                raise ValueError(
                    f"{decision.item_id}: response {field} does not match dispatch binding"
                )
    return decisions


def _parse_provider_response(role: str, payload: str):
    if role == "reviewer":
        return ReviewBatchResponse.model_validate_json(payload)
    return AdversarialBatchResponse.model_validate_json(payload)


def _read_normalized(role: str, path: Path) -> tuple:
    model = ReviewDecision if role == "reviewer" else AdversarialVerdict
    return tuple(read_jsonl(path, model))


def _checkpoint_is_valid(directory: Path, binding: DispatchBinding) -> bool:
    completion_path = directory / "completion.json"
    binding_path = directory / "binding.json"
    raw_path = directory / "raw-response.json"
    normalized_path = directory / "decisions.jsonl"
    required = (completion_path, binding_path, raw_path, normalized_path)
    envelope_path = directory / "provider-envelope.json"
    required = (*required, envelope_path)
    if not all(path.is_file() for path in required):
        return False
    try:
        completion = CompletionCheckpoint.model_validate_json(
            completion_path.read_text(encoding="utf-8")
        )
        stored_binding = DispatchBinding.model_validate_json(
            binding_path.read_text(encoding="utf-8")
        )
        if stored_binding != binding:
            return False
        if completion.campaign_id != binding.campaign_id:
            return False
        if completion.batch_id != binding.batch_id:
            return False
        if completion.reviewer_id != binding.reviewer_id:
            return False
        if completion.binding_sha256 != sha256_file(binding_path).sha256:
            return False
        if completion.raw_response_sha256 != sha256_file(raw_path).sha256:
            return False
        if completion.normalized_sha256 != sha256_file(normalized_path).sha256:
            return False
        if completion.provider_envelope_sha256 != sha256_file(envelope_path).sha256:
            return False
        envelope = ProviderEnvelope.model_validate_json(envelope_path.read_text(encoding="utf-8"))
        if (
            envelope.campaign_id != binding.campaign_id
            or envelope.batch_id != binding.batch_id
            or envelope.reviewer_id != binding.reviewer_id
            or envelope.requested_model != binding.model
            or envelope.reasoning_effort != binding.reasoning_effort
            or envelope.raw_response_sha256 != sha256_file(raw_path).sha256
        ):
            return False
        decisions = _read_normalized(binding.role, normalized_path)
        envelope = (
            ReviewBatchResponse(decisions=decisions)
            if binding.role == "reviewer"
            else AdversarialBatchResponse(decisions=decisions)
        )
        _validate_response(envelope, binding)
        return completion.decision_count == len(decisions)
    except (OSError, ValueError):
        return False


def collect_completed_decisions(
    *,
    manifest_path: Path,
    batch_index_path: Path,
    checkpoint_root: Path,
    reviewer_id: str,
    output_path: Path,
    cwd: Path,
    allow_partial: bool = False,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Collect one model's complete, hash-bound checkpoint set into JSONL.

    Consensus consumes reviewer and adjudicator JSONL files, whereas dispatch deliberately
    checkpoints one immutable batch at a time. By default this bridge refuses partial campaigns.
    An explicit partial collection still refuses corrupt checkpoints, model substitutions, and
    batch/index drift; it emits only completed batches and records every omitted item.
    """

    manifest = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    models = {row.reviewer_id: row for row in manifest.models}
    model = models.get(reviewer_id)
    if model is None:
        raise ValueError(f"reviewer {reviewer_id!r} is absent from the campaign manifest")
    role = model.role
    try:
        index = json.loads(batch_index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid review batch index: {exc}") from exc
    expected_index_schema = (
        "flopo-review-batch-index-v2"
        if role == "reviewer"
        else "flopo-adversarial-batch-index-v1"
    )
    if index.get("schema_version") != expected_index_schema:
        raise ValueError("unsupported decision batch index schema")
    if index.get("campaign_id") != manifest.campaign_id:
        raise ValueError("review batch index belongs to another campaign")
    if index.get("cluster_sha256") != manifest.clusters.sha256:
        raise ValueError("decision batch index is not bound to the campaign clusters")
    if role == "adjudicator" and index.get("evidence_sha256") != manifest.evidence_registry.sha256:
        raise ValueError("adversarial batch index is not bound to campaign evidence")
    batches = index.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ValueError("review batch index has no batches")
    if index.get("batch_count") != len(batches):
        raise ValueError("review batch index count is inconsistent")

    manifest_sha256 = sha256_file(manifest_path).sha256
    index_sha256 = sha256_file(batch_index_path).sha256
    prompt_id = "reviewer" if role == "reviewer" else "adversarial"
    prompt = next((row for row in manifest.prompts if row.prompt_id == prompt_id), None)
    if prompt is None:
        raise ValueError(f"campaign manifest has no {prompt_id} prompt")
    decisions: list[ReviewDecision | AdversarialVerdict] = []
    expected_item_ids: list[str] = []
    collected_item_ids: list[str] = []
    completed_batches: list[str] = []
    missing_batches: list[str] = []
    missing_item_ids: list[str] = []
    seen_batches: set[str] = set()
    for indexed_batch in batches:
        if not isinstance(indexed_batch, dict):
            raise ValueError("review batch index contains a malformed batch")
        batch_id = str(indexed_batch.get("batch_id", ""))
        if not batch_id or batch_id in seen_batches:
            raise ValueError("review batch index contains a missing or duplicate batch id")
        seen_batches.add(batch_id)
        declared_path = indexed_batch.get("path")
        if not isinstance(declared_path, str) or not declared_path:
            raise ValueError(f"{batch_id}: review batch index has no packet path")
        batch_path = Path(declared_path)
        if not batch_path.is_absolute():
            batch_path = cwd / batch_path
        packet, batch_sha256 = _load_batch(
            batch_path,
            batch_index_path,
            manifest,
            role=role,
        )
        item_ids = tuple(str(item["cluster_id"]) for item in packet["items"])
        expected_item_ids.extend(item_ids)
        directory = (checkpoint_root / reviewer_id / batch_id).resolve()
        binding_path = directory / "binding.json"
        try:
            binding = DispatchBinding.model_validate_json(
                binding_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            if (directory / "completion.json").exists() or not allow_partial:
                raise ValueError(f"{batch_id}: missing or invalid dispatch binding") from exc
            missing_batches.append(batch_id)
            missing_item_ids.extend(item_ids)
            continue
        expected_binding = {
            "campaign_id": manifest.campaign_id,
            "manifest_sha256": manifest_sha256,
            "batch_id": batch_id,
            "batch_sha256": batch_sha256,
            "batch_index_sha256": index_sha256,
            "reviewer_id": model.reviewer_id,
            "provider": model.provider,
            "model": model.model,
            "model_family": model.model_family,
            "reasoning_effort": model.reasoning_effort,
            "role": model.role,
            "prompt_id": prompt.prompt_id,
            "prompt_sha256": prompt.sha256,
            "expected_item_ids": item_ids,
        }
        mismatches = [
            field
            for field, expected in expected_binding.items()
            if getattr(binding, field) != expected
        ]
        if mismatches:
            raise ValueError(
                f"{batch_id}: dispatch binding differs from frozen campaign: {mismatches}"
            )
        if not _checkpoint_is_valid(directory, binding):
            if (directory / "completion.json").exists() or not allow_partial:
                raise ValueError(f"{batch_id}: review checkpoint is incomplete or corrupt")
            missing_batches.append(batch_id)
            missing_item_ids.extend(item_ids)
            continue
        decisions.extend(_read_normalized(role, directory / "decisions.jsonl"))
        completed_batches.append(batch_id)
        collected_item_ids.extend(item_ids)

    if len(expected_item_ids) != len(set(expected_item_ids)):
        raise ValueError("review batch index repeats one or more cluster ids")
    if index.get("item_count") != len(expected_item_ids):
        raise ValueError("review batch index item count is inconsistent")
    if role == "reviewer" and len(expected_item_ids) != manifest.starting_clusters:
        raise ValueError("review batches do not conserve the campaign cluster inventory")
    if role == "adjudicator" and len(expected_item_ids) > manifest.starting_clusters:
        raise ValueError("adversarial batches exceed the campaign cluster inventory")
    decision_ids = [row.item_id for row in decisions]
    if decision_ids != collected_item_ids:
        raise ValueError("collected decisions do not exactly match the indexed batch order")
    if set(collected_item_ids) & set(missing_item_ids):
        raise ValueError("partial collection assigns an item to both completed and missing batches")
    if sorted((*collected_item_ids, *missing_item_ids)) != sorted(expected_item_ids):
        raise ValueError("partial collection does not conserve the indexed item inventory")
    if not allow_partial and missing_batches:
        raise ValueError("review campaign is incomplete")
    write_jsonl(output_path, decisions)
    artifact = sha256_file(output_path)
    result = {
        "schema_version": (
            "flopo-review-collection-v1"
            if role == "reviewer"
            else "flopo-adjudication-collection-v1"
        ),
        "campaign_id": manifest.campaign_id,
        "reviewer_id": reviewer_id,
        "role": role,
        "partial": bool(missing_batches),
        "indexed_batches": len(batches),
        "completed_batches": completed_batches,
        "completed_batch_count": len(completed_batches),
        "missing_batches": missing_batches,
        "missing_batch_count": len(missing_batches),
        "indexed_items": len(expected_item_ids),
        "decisions": len(decisions),
        "missing_items": len(missing_item_ids),
        "missing_item_ids": missing_item_ids,
        "output": str(output_path),
        "sha256": artifact.sha256,
        "bytes": artifact.bytes,
    }
    # Preserve the historical aggregate key for callers of complete collection.
    result["batches"] = len(completed_batches)
    if report_path is not None:
        payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if report_path.exists() and report_path.read_text(encoding="utf-8") != payload:
            raise FileExistsError(f"refusing to replace collection report: {report_path}")
        atomic_write_text(report_path, payload)
    return result


def _archive_attempt(directory: Path) -> None:
    """Preserve every prior raw attempt before a failed/corrupt checkpoint is retried."""

    names = (
        "binding.json",
        "prompt.txt",
        "response-schema.json",
        "provider-output.txt",
        "raw-response.json",
        "provider-envelope.json",
        "decisions.jsonl",
        "failure.json",
        "completion.json",
    )
    present = [directory / name for name in names if (directory / name).exists()]
    if not present:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    archive = directory / "attempt-history" / stamp
    archive.mkdir(parents=True, exist_ok=False)
    for path in present:
        shutil.move(str(path), archive / path.name)


def _command(
    backend: str,
    model: ModelSpec,
    schema: dict,
    schema_path: Path,
    last_message_path: Path,
    cwd: Path,
    *,
    claude_executable: str,
    codex_executable: str,
) -> list[str]:
    if backend == "claude":
        return [
            claude_executable,
            "--print",
            "--model",
            model.model,
            "--effort",
            model.reasoning_effort,
            "--output-format",
            "json",
            "--json-schema",
            canonical_json(schema),
            "--permission-mode",
            "plan",
            "--tools",
            "Read,Glob,Grep",
            "--allowedTools",
            "Read,Glob,Grep",
            "--disallowedTools",
            "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
            "--no-session-persistence",
            "--safe-mode",
        ]
    return [
        codex_executable,
        "exec",
        "--ignore-user-config",
        "--strict-config",
        "--model",
        model.model,
        "--config",
        f'model_reasoning_effort="{model.reasoning_effort}"',
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(last_message_path),
        "--cd",
        str(cwd),
        "-",
    ]


def dispatch_batch(
    *,
    manifest_path: Path,
    batch_index_path: Path,
    batch_path: Path,
    reviewer_id: str,
    prompt_id: str,
    checkpoint_root: Path,
    cwd: Path,
    backend: str = "auto",
    runner: Runner = subprocess.run,
    http_client: Any | None = None,
    openrouter_api_key: str | None = None,
    timeout: float | None = None,
    max_output_tokens: int | None = None,
    openrouter_response_mode: str = "json_schema",
    claude_executable: str = "claude",
    codex_executable: str = "codex",
) -> dict[str, Any]:
    """Dispatch one direct batch or reuse its fully validated completion checkpoint."""

    if max_output_tokens is not None and max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    if openrouter_response_mode not in {"json_schema", "json_object"}:
        raise ValueError("openrouter_response_mode must be json_schema or json_object")
    manifest = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = sha256_file(manifest_path).sha256
    models = {row.reviewer_id: row for row in manifest.models}
    model = models.get(reviewer_id)
    if model is None:
        raise ValueError(f"reviewer {reviewer_id!r} is absent from the campaign manifest")
    packet, batch_hash = _load_batch(
        batch_path, batch_index_path, manifest, role=model.role
    )
    expected_prompt_id = "reviewer" if model.role == "reviewer" else "adversarial"
    if prompt_id != expected_prompt_id:
        raise ValueError(f"{model.role} dispatch must use the {expected_prompt_id} prompt")
    prompts = {row.prompt_id: row for row in manifest.prompts}
    prompt = prompts.get(prompt_id)
    if prompt is None:
        raise ValueError(f"prompt {prompt_id!r} is absent from the campaign manifest")
    prompt_path = Path(prompt.path)
    if not prompt_path.is_absolute():
        prompt_path = cwd / prompt_path
    if sha256_file(prompt_path).sha256 != prompt.sha256:
        raise ValueError("prompt file hash does not match immutable campaign manifest")
    selected_backend = _backend_for(model, backend)
    read_only_policy = {
        "runner_protocol": "flopo-read-only-dispatch-v2",
        "backend": selected_backend,
        "workspace_readable": selected_backend in {"claude", "codex"},
        "claude_tools": ["Read", "Glob", "Grep"] if selected_backend == "claude" else [],
        "sandbox": "read-only" if selected_backend == "codex" else "provider-isolated",
        "openrouter_response_mode": (
            openrouter_response_mode if selected_backend == "openrouter" else None
        ),
    }
    schema = response_schema(model.role)
    _bind_response_schema_to_packet(schema, packet, role=model.role)
    item_ids = tuple(str(item["cluster_id"]) for item in packet["items"])
    schema_payload = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    prompt_binding = {
        "campaign_id": manifest.campaign_id,
        "manifest_sha256": manifest_hash,
        "batch_id": packet["batch_id"],
        "batch_sha256": batch_hash,
        "reviewer_id": model.reviewer_id,
        "provider": model.provider,
        "model": model.model,
        "model_family": model.model_family,
        "role": model.role,
        "prompt_id": prompt.prompt_id,
        "prompt_sha256": prompt.sha256,
        "expected_item_ids": item_ids,
        "response_schema_sha256": _digest_text(schema_payload),
    }
    prompt_binding["reasoning_effort"] = model.reasoning_effort
    assembled = _assemble_prompt(
        prompt_path.read_text(encoding="utf-8"),
        packet,
        prompt_binding,
        role=model.role,
        workspace_readable=read_only_policy["workspace_readable"],
        embedded_response_schema=(
            schema
            if selected_backend == "openrouter" and openrouter_response_mode == "json_object"
            else None
        ),
    )
    binding = DispatchBinding(
        **prompt_binding,
        backend=selected_backend,
        batch_index_sha256=sha256_file(batch_index_path).sha256,
        assembled_prompt_sha256=_digest_text(assembled),
        read_only_policy_sha256=_digest_text(canonical_json(read_only_policy)),
    )
    directory = (checkpoint_root / reviewer_id / binding.batch_id).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if _checkpoint_is_valid(directory, binding):
        return {
            "status": "skipped",
            "campaign_id": binding.campaign_id,
            "batch_id": binding.batch_id,
            "reviewer_id": binding.reviewer_id,
            "decisions": len(binding.expected_item_ids),
            "directory": str(directory),
        }
    _archive_attempt(directory)
    completion_path = directory / "completion.json"
    normalized_path = directory / "decisions.jsonl"
    failure_path = directory / "failure.json"
    completion_path.unlink(missing_ok=True)
    normalized_path.unlink(missing_ok=True)
    atomic_write_text(directory / "binding.json", binding.model_dump_json(indent=2) + "\n")
    atomic_write_text(directory / "prompt.txt", assembled)
    atomic_write_text(directory / "response-schema.json", schema_payload)
    raw_path = directory / "raw-response.json"
    provider_output_path = directory / "provider-output.txt"
    envelope_path = directory / "provider-envelope.json"
    started_at = datetime.now(timezone.utc)
    returned_model = ""
    provider_request_id = ""
    parameters = {
        "backend": selected_backend,
        "model": model.model,
        "reasoning_effort": model.reasoning_effort,
        "read_only": True,
        "read_only_policy_sha256": binding.read_only_policy_sha256,
        "response_schema_sha256": binding.response_schema_sha256,
        "max_output_tokens": max_output_tokens,
        "openrouter_response_mode": openrouter_response_mode,
    }
    try:
        if selected_backend == "openrouter":
            api_key = openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                raise ValueError("OPENROUTER_API_KEY is required for explicit OpenRouter dispatch")
            client = http_client or httpx.Client()
            try:
                response_format: dict[str, Any]
                if openrouter_response_mode == "json_schema":
                    response_format = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": f"flopo_{model.role}_batch",
                            "strict": True,
                            "schema": schema,
                        },
                    }
                else:
                    response_format = {"type": "json_object"}
                request_payload: dict[str, Any] = {
                    "model": model.model,
                    "reasoning": {"effort": model.reasoning_effort},
                    "messages": [{"role": "user", "content": assembled}],
                    "response_format": response_format,
                }
                if max_output_tokens is not None:
                    request_payload["max_tokens"] = max_output_tokens
                response = client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=request_payload,
                    timeout=timeout,
                )
            finally:
                if http_client is None:
                    client.close()
            response.raise_for_status()
            provider_payload = response.json()
            returned_model = str(provider_payload.get("model", "") or "")
            provider_request_id = str(provider_payload.get("id", "") or "")
            if returned_model and returned_model != model.model:
                raise ValueError(
                    f"OpenRouter returned model {returned_model!r}, expected {model.model!r}"
                )
            atomic_write_text(
                provider_output_path,
                json.dumps(provider_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            try:
                content = provider_payload["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError("OpenRouter response has no structured message content") from exc
            if isinstance(content, dict):
                raw_payload = canonical_json(content) + "\n"
            elif isinstance(content, str):
                raw_payload = content if content.endswith("\n") else content + "\n"
            else:
                raise ValueError("OpenRouter structured message content is not JSON text or object")
            atomic_write_text(raw_path, raw_payload)
            parsed = _parse_provider_response(model.role, raw_payload)
            decisions = _validate_response(parsed, binding)
            write_jsonl(normalized_path, decisions)
        else:
            decisions = None
        with tempfile.TemporaryDirectory(prefix="flopo-review-dispatch-") as temporary:
            if selected_backend != "openrouter":
                last_message_path = Path(temporary) / "last-message.json"
                command = _command(
                    selected_backend,
                    model,
                    schema,
                    directory / "response-schema.json",
                    last_message_path,
                    cwd,
                    claude_executable=claude_executable,
                    codex_executable=codex_executable,
                )
                completed = runner(
                    command,
                    input=assembled,
                    cwd=str(cwd),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                )
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
                atomic_write_text(provider_output_path, stdout)
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"{selected_backend} exited {completed.returncode}: {stderr[-2000:]}"
                    )
                if selected_backend == "claude":
                    envelope = json.loads(stdout)
                    if not isinstance(envelope, dict) or "structured_output" not in envelope:
                        raise ValueError("Claude response has no structured_output envelope")
                    raw_payload = canonical_json(envelope["structured_output"]) + "\n"
                    provider_request_id = str(envelope.get("session_id", "") or "")
                    model_usage = envelope.get("modelUsage", {}) or {}
                    if isinstance(model_usage, dict) and len(model_usage) == 1:
                        returned_model = str(next(iter(model_usage)))
                else:
                    if not last_message_path.is_file():
                        raise ValueError("Codex did not create its structured last-message output")
                    raw_payload = last_message_path.read_text(encoding="utf-8")
                    if not raw_payload.endswith("\n"):
                        raw_payload += "\n"
                atomic_write_text(raw_path, raw_payload)
                parsed = _parse_provider_response(model.role, raw_payload)
                decisions = _validate_response(parsed, binding)
                write_jsonl(normalized_path, decisions)
        assert decisions is not None
        provider_envelope = ProviderEnvelope(
            campaign_id=binding.campaign_id,
            batch_id=binding.batch_id,
            reviewer_id=binding.reviewer_id,
            backend=binding.backend,
            requested_model=binding.model,
            returned_model=returned_model,
            model_verification=(
                "provider_reported_match"
                if returned_model == binding.model
                else "command_pinned"
            ),
            reasoning_effort=binding.reasoning_effort,
            provider_request_id=provider_request_id,
            request_parameters_sha256=_digest_text(canonical_json(parameters)),
            provider_output_sha256=sha256_file(provider_output_path).sha256,
            raw_response_sha256=sha256_file(raw_path).sha256,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )
        atomic_write_text(envelope_path, provider_envelope.model_dump_json(indent=2) + "\n")
        completion = CompletionCheckpoint(
            campaign_id=binding.campaign_id,
            batch_id=binding.batch_id,
            reviewer_id=binding.reviewer_id,
            binding_sha256=sha256_file(directory / "binding.json").sha256,
            raw_response_sha256=sha256_file(raw_path).sha256,
            normalized_sha256=sha256_file(normalized_path).sha256,
            provider_envelope_sha256=sha256_file(envelope_path).sha256,
            decision_count=len(decisions),
            completed_at=datetime.now(timezone.utc),
        )
        atomic_write_text(completion_path, completion.model_dump_json(indent=2) + "\n")
        failure_path.unlink(missing_ok=True)
        return {
            "status": "completed",
            "campaign_id": binding.campaign_id,
            "batch_id": binding.batch_id,
            "reviewer_id": binding.reviewer_id,
            "decisions": len(decisions),
            "directory": str(directory),
        }
    except Exception as exc:
        normalized_path.unlink(missing_ok=True)
        completion_path.unlink(missing_ok=True)
        failure = {
            "schema_version": "flopo-dispatch-failure-v1",
            "campaign_id": binding.campaign_id,
            "batch_id": binding.batch_id,
            "reviewer_id": binding.reviewer_id,
            "backend": binding.backend,
            "batch_sha256": binding.batch_sha256,
            "assembled_prompt_sha256": binding.assembled_prompt_sha256,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        atomic_write_text(
            failure_path,
            json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        return {
            "status": "failed",
            "campaign_id": binding.campaign_id,
            "batch_id": binding.batch_id,
            "reviewer_id": binding.reviewer_id,
            "decisions": 0,
            "error": str(exc),
            "directory": str(directory),
        }
