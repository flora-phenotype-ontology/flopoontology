"""Runner-owned evidence, catalog, and semantic validation for machine reviews.

Model output is a proposal, never an attestation.  This module derives the validation result from
the frozen campaign artifacts and rejects stale identifiers, invented evidence, malformed nested
expressions, blocklisted combinations, and unsafe proposal metadata before consensus is possible.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from flopo2.owl.annotation_class import canonical_part_restrictions
from flopo2.review.io import read_jsonl, sha256_file, stable_id
from flopo2.review.models import (
    AdversarialVerdict,
    ArtifactHash,
    CampaignManifest,
    Cluster,
    EvidenceRecord,
    Occurrence,
    PhenotypeExpression,
    QualitativeRelationSignature,
    ReusableFlopoClassCandidate,
    ReviewDecision,
    SupportClassSignature,
    canonical_json,
    normalized_text,
)


@dataclass(frozen=True)
class CatalogSnapshot:
    po_ids: frozenset[str]
    pato_ids: frozenset[str]
    flopo_ids: frozenset[str]
    pato_attribute_ids: frozenset[str]
    combinations: dict[tuple[str, str], str]
    po_normalized_forms: frozenset[str]
    flopo_normalized_forms: frozenset[str]

    def contains(self, identifier: str) -> bool:
        if identifier.startswith("PO_"):
            return identifier in self.po_ids
        if identifier.startswith("PATO_"):
            return identifier in self.pato_ids
        if identifier.startswith("FLOPO_"):
            return identifier in self.flopo_ids
        return False


@dataclass(frozen=True)
class ValidationContext:
    occurrences: dict[str, Occurrence]
    clusters: dict[str, Cluster]
    evidence: dict[str, EvidenceRecord]
    catalog: CatalogSnapshot


@dataclass(frozen=True)
class LocalValidation:
    passed: bool
    reasons: tuple[str, ...]


def _artifact_path(artifact: ArtifactHash) -> Path:
    """Resolve a frozen artifact without changing its evidence locator.

    Campaign evidence IDs include the original path, so publishing a reviewed result must not
    rewrite a completed manifest merely because a live catalog advances.  When the declared path
    no longer has the frozen bytes, use the content-addressed review store.  The fallback is
    accepted only after exact size and SHA-256 verification.
    """

    declared = Path(artifact.path)
    candidates = [declared]
    configured = os.environ.get("FLOPO_REVIEW_ARTIFACT_ROOT", "").strip()
    root = Path(configured) if configured else Path("scratchpad/flopo-review-artifacts/sha256")
    candidates.append(root / artifact.sha256)
    for candidate in candidates:
        try:
            actual = sha256_file(candidate)
        except OSError:
            continue
        if (actual.sha256, actual.bytes) == (artifact.sha256, artifact.bytes):
            return candidate
    raise ValueError(
        f"frozen artifact is unavailable or changed: {artifact.path} ({artifact.sha256})"
    )


def _live_catalog(manifest: CampaignManifest) -> CatalogSnapshot:
    po_ids: set[str] = set()
    pato_ids: set[str] = set()
    flopo_ids: set[str] = set()
    pato_attribute_ids: set[str] = set()
    combinations: dict[tuple[str, str], str] = {}
    po_normalized_forms: set[str] = set()
    flopo_normalized_forms: set[str] = set()
    id_pattern = re.compile(r"\b(?:PO|PATO|FLOPO)_\d+\b")
    for artifact in manifest.ontologies:
        path = _artifact_path(artifact)
        name = Path(artifact.path).name
        if name in {"po_lexicon.tsv", "pato_lexicon.tsv"}:
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
                ids = {row.get("id", "") for row in rows}
            (po_ids if name.startswith("po_") else pato_ids).update(item for item in ids if item)
            if name.startswith("po_"):
                for row in rows:
                    for value in (row.get("label", ""), *(row.get("synonyms", "") or "").split("|")):
                        if normalized := normalized_text(value):
                            po_normalized_forms.add(normalized)
            if name.startswith("pato_"):
                pato_attribute_ids.update(
                    row.get("id", "")
                    for row in rows
                    if "attribute_slim" in (row.get("slim") or "").split("|")
                )
        elif name == "flopo_id_registry.tsv":
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    iri = row.get("flopo_iri", "")
                    if "/FLOPO_" in iri:
                        flopo_ids.add(iri.rsplit("/", 1)[-1])
                    if normalized := normalized_text(row.get("label", "")):
                        flopo_normalized_forms.add(normalized)
        elif name == "valid_combinations.tsv":
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    combinations[(row.get("po_id", ""), row.get("pato_id", ""))] = row.get(
                        "status", ""
                    )
        elif path.suffix == ".obo":
            with path.open(encoding="utf-8", errors="replace") as handle:
                current_identifier = ""
                for line in handle:
                    if line.startswith("id: "):
                        identifier = line[4:].strip().replace(":", "_")
                        current_identifier = identifier
                        if identifier.startswith("PO_"):
                            po_ids.add(identifier)
                        elif identifier.startswith("PATO_"):
                            pato_ids.add(identifier)
                    elif line.startswith("name: ") and current_identifier.startswith("PO_"):
                        po_normalized_forms.add(normalized_text(line[6:].strip()))
                    elif line.startswith("synonym: ") and current_identifier.startswith("PO_"):
                        match = re.match(r'^synonym: "((?:[^"\\]|\\.)*)"', line)
                        if match:
                            po_normalized_forms.add(normalized_text(match.group(1)))
        elif path.suffix in {".owl", ".ttl", ".ofn"}:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    for identifier in id_pattern.findall(line):
                        if identifier.startswith("FLOPO_"):
                            flopo_ids.add(identifier)
                        elif identifier.startswith("PO_"):
                            po_ids.add(identifier)
                        elif identifier.startswith("PATO_"):
                            pato_ids.add(identifier)
    return CatalogSnapshot(
        po_ids=frozenset(po_ids),
        pato_ids=frozenset(pato_ids),
        flopo_ids=frozenset(flopo_ids),
        pato_attribute_ids=frozenset(pato_attribute_ids),
        combinations=combinations,
        po_normalized_forms=frozenset(po_normalized_forms),
        flopo_normalized_forms=frozenset(flopo_normalized_forms),
    )


def _evidence_payload(occurrence: Occurrence) -> dict:
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
    return payload


def load_validation_context(
    manifest: CampaignManifest,
    *,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
) -> ValidationContext:
    for expected, path in (
        (manifest.occurrences, occurrence_path),
        (manifest.clusters, cluster_path),
        (manifest.evidence_registry, evidence_path),
    ):
        actual = sha256_file(path)
        if (actual.sha256, actual.bytes) != (expected.sha256, expected.bytes):
            raise ValueError(f"campaign artifact hash mismatch: {path}")

    occurrence_rows = list(read_jsonl(occurrence_path, Occurrence))
    cluster_rows = list(read_jsonl(cluster_path, Cluster))
    evidence_rows = list(read_jsonl(evidence_path, EvidenceRecord))
    if len(occurrence_rows) != manifest.starting_occurrences:
        raise ValueError("occurrence count does not match campaign manifest")
    if len(cluster_rows) != manifest.starting_clusters:
        raise ValueError("cluster count does not match campaign manifest")

    def unique(rows, field: str, label: str):
        result = {}
        for row in rows:
            key = getattr(row, field)
            if key in result:
                raise ValueError(f"duplicate {label}: {key}")
            result[key] = row
        return result

    occurrences = unique(occurrence_rows, "occurrence_id", "occurrence")
    clusters = unique(cluster_rows, "cluster_id", "cluster")
    evidence = unique(evidence_rows, "evidence_id", "evidence record")
    if sum(row.kind == "occurrence" for row in evidence.values()) != len(occurrences):
        raise ValueError("evidence registry must contain exactly one row per occurrence")
    expected_references = {
        stable_id("evidence", (kind, artifact.path, artifact.sha256)): (kind, artifact)
        for kind, artifacts in (
            ("ontology", manifest.ontologies),
            ("authority", manifest.authorities),
            ("source_inventory", manifest.sources),
        )
        for artifact in artifacts
    }
    for artifact in (*manifest.ontologies, *manifest.authorities, *manifest.sources):
        _artifact_path(artifact)
    actual_references = {
        identifier: row
        for identifier, row in evidence.items()
        if row.kind in {"ontology", "authority", "source_inventory"}
    }
    if set(actual_references) != set(expected_references):
        raise ValueError("reference evidence registry does not match campaign manifest")
    for identifier, (kind, artifact) in expected_references.items():
        row = actual_references[identifier]
        if (
            row.kind != kind
            or row.payload_sha256 != artifact.sha256
            or row.locator != artifact.path
        ):
            raise ValueError(f"reference evidence hash mismatch: {identifier}")

    members: defaultdict[str, list[Occurrence]] = defaultdict(list)
    for occurrence in occurrence_rows:
        if occurrence.cluster_id not in clusters:
            raise ValueError(f"occurrence targets unknown cluster: {occurrence.cluster_id}")
        members[occurrence.cluster_id].append(occurrence)
        record = evidence.get(occurrence.evidence_id)
        expected_hash = hashlib.sha256(canonical_json(_evidence_payload(occurrence)).encode()).hexdigest()
        if (
            record is None
            or record.kind != "occurrence"
            or record.occurrence_id != occurrence.occurrence_id
            or record.item_id != occurrence.cluster_id
            or record.payload_sha256 != expected_hash
        ):
            raise ValueError(f"evidence registry mismatch: {occurrence.evidence_id}")

    for cluster_id, cluster in clusters.items():
        rows = members.get(cluster_id, [])
        if len(rows) != cluster.occurrence_count:
            raise ValueError(f"cluster occurrence count mismatch: {cluster_id}")
        if any(row.semantic_fingerprint != cluster.semantic_fingerprint for row in rows):
            raise ValueError(f"cluster is not semantically homogeneous: {cluster_id}")
        if any(
            row.qualitative_relation_candidate != cluster.qualitative_relation_candidate
            for row in rows
        ):
            raise ValueError(f"cluster qualitative candidate mismatch: {cluster_id}")
        if any(
            row.support_class_candidate != cluster.support_class_candidate for row in rows
        ):
            raise ValueError(f"cluster support candidate mismatch: {cluster_id}")
        if any(
            row.phenotype_expression_candidate != cluster.phenotype_expression_candidate
            for row in rows
        ):
            raise ValueError(f"cluster expression candidate mismatch: {cluster_id}")
        if any(
            row.reusable_flopo_class_candidate != cluster.reusable_flopo_class_candidate
            for row in rows
        ):
            raise ValueError(f"cluster reusable class candidate mismatch: {cluster_id}")
        membership = tuple(sorted(row.occurrence_id for row in rows))
        membership_hash = hashlib.sha256(canonical_json(membership).encode()).hexdigest()
        if membership_hash != cluster.occurrence_membership_sha256:
            raise ValueError(f"cluster membership hash mismatch: {cluster_id}")
        for sample in cluster.context_samples:
            occurrence = occurrences.get(sample.occurrence_id)
            if (
                occurrence is None
                or occurrence.cluster_id != cluster_id
                or occurrence.evidence_id != sample.evidence_id
                or occurrence.context != sample.context
                or hashlib.sha256(sample.context.encode()).hexdigest() != sample.context_sha256
            ):
                raise ValueError(f"cluster context sample mismatch: {cluster_id}")
    return ValidationContext(
        occurrences=occurrences,
        clusters=clusters,
        evidence=evidence,
        catalog=_live_catalog(manifest),
    )


def _validate_evidence(item_id: str, evidence_ids: tuple[str, ...], context: ValidationContext):
    reasons: list[str] = []
    rows = [context.evidence.get(identifier) for identifier in evidence_ids]
    if any(row is None for row in rows):
        reasons.append("unknown_evidence_id")
    if not any(row is not None and row.kind == "occurrence" and row.item_id == item_id for row in rows):
        reasons.append("no_item_bound_occurrence_evidence")
    if any(
        row is not None and row.kind == "occurrence" and row.item_id != item_id
        for row in rows
    ):
        reasons.append("cross_item_evidence")
    return reasons


def _validate_expression(expression: PhenotypeExpression, context: ValidationContext) -> list[str]:
    reasons: list[str] = []
    identifiers = [expression.bearer_id, expression.quality_id, *expression.value_terms]
    identifiers.extend(expression.developmental_stage_ids)
    for part in expression.part_restrictions:
        identifiers.append(part.filler_class)
        identifiers.extend(part.qualities)
    if any(not context.catalog.contains(identifier) for identifier in identifiers):
        reasons.append("signature_uses_unknown_ontology_id")
    try:
        canonical_part_restrictions(
            {
                "part_restrictions": [
                    row.model_dump(mode="json") for row in expression.part_restrictions
                ]
            }
        )
    except ValueError:
        reasons.append("invalid_part_restriction")
    pairs = [(expression.bearer_id, expression.quality_id)]
    pairs.extend(
        (part.filler_class, quality)
        for part in expression.part_restrictions
        for quality in part.qualities
    )
    for pair in pairs:
        status = context.catalog.combinations.get(pair, "novel")
        if status in {"blocked", "blocklisted", "invalid"}:
            reasons.append("signature_uses_blocklisted_combination")
            break
    has_numeric_value = expression.value_low is not None or expression.value_high is not None
    is_attribute = expression.quality_id in context.catalog.pato_attribute_ids
    has_logical_values = (
        expression.value_operator in {"all_of", "one_of"}
        and len(expression.value_terms) >= 2
    )
    if is_attribute and not has_numeric_value and not has_logical_values:
        reasons.append("attribute_expression_missing_value")
    if has_numeric_value and expression.quality_id not in context.catalog.pato_attribute_ids:
        reasons.append("numeric_expression_quality_not_pato_attribute")
    if has_numeric_value and (
        expression.value_operator != "atomic"
        or expression.value_terms
        or expression.part_restrictions
    ):
        reasons.append("numeric_expression_has_unsupported_logical_components")
    if expression.value_terms and not is_attribute:
        reasons.append("logical_expression_quality_not_pato_attribute")
    if expression.value_operator in {"all_of", "one_of"} and not has_logical_values:
        reasons.append("logical_expression_missing_distinct_values")
    return reasons


def _validate_qualitative_relation(
    item_id: str,
    signature: QualitativeRelationSignature,
    context: ValidationContext,
) -> list[str]:
    reasons: list[str] = []
    cluster = context.clusters[item_id]
    candidate = cluster.qualitative_relation_candidate
    if candidate is None:
        return ["item_has_no_qualitative_relation_candidate"]
    if signature != candidate.signature:
        reasons.append("qualitative_signature_differs_from_runner_candidate")
    identifiers = (
        signature.bearer_id,
        signature.attribute_id,
        signature.from_value,
        signature.to_value,
    )
    if any(not context.catalog.contains(identifier) for identifier in identifiers):
        reasons.append("qualitative_signature_uses_unknown_ontology_id")
    if signature.attribute_id not in context.catalog.pato_attribute_ids:
        reasons.append("qualitative_signature_attribute_not_pato_attribute")
    status = context.catalog.combinations.get(
        (signature.bearer_id, signature.attribute_id), "novel"
    )
    if status in {"blocked", "blocklisted", "invalid"}:
        reasons.append("qualitative_signature_uses_blocklisted_combination")
    return reasons


def _validate_support_class(
    item_id: str,
    signature: SupportClassSignature,
    context: ValidationContext,
) -> list[str]:
    reasons: list[str] = []
    candidate = context.clusters[item_id].support_class_candidate
    if candidate is None:
        return ["item_has_no_support_class_candidate"]
    if signature != candidate.signature:
        reasons.append("support_class_signature_differs_from_runner_candidate")
    identifiers = (*signature.parent_ids, *signature.part_of_ids)
    if any(identifier not in context.catalog.po_ids for identifier in identifiers):
        reasons.append("support_class_uses_unknown_po_id")
    normalized_label = normalized_text(signature.label)
    if normalized_label in context.catalog.po_normalized_forms:
        reasons.append("support_class_label_collides_with_live_po_form")
    if normalized_label in context.catalog.flopo_normalized_forms:
        reasons.append("support_class_label_collides_with_live_flopo_form")
    if _definition_is_circular(signature.label, signature.definition):
        reasons.append("circular_definition")
    return reasons


def _definition_is_circular(label: str, definition: str) -> bool:
    label_norm = normalized_text(label)
    definition_norm = normalized_text(definition).strip(" .")
    templates = {
        label_norm,
        f"a quality described as {label_norm}",
        f"an anatomical entity described as {label_norm}",
        f"a phenotype described as {label_norm}",
    }
    return definition_norm in templates


def _validate_reusable_flopo_class_candidate(
    item_id: str, decision: ReviewDecision, context: ValidationContext
) -> list[str]:
    candidate: ReusableFlopoClassCandidate | None = (
        context.clusters[item_id].reusable_flopo_class_candidate
    )
    if candidate is None:
        return ["item_has_no_reusable_flopo_class_candidate"]
    signature = decision.proposed_signature
    expected = {
        "expression": candidate.signature,
        "label": candidate.label,
        "definition": candidate.definition,
        "parent_ids": candidate.parent_ids,
        "authoritative_evidence_ids": candidate.authoritative_evidence_ids,
    }
    actual = {
        "expression": signature.expression,
        "label": signature.label,
        "definition": signature.definition,
        "parent_ids": signature.parent_ids,
        "authoritative_evidence_ids": signature.authoritative_evidence_ids,
    }
    reasons: list[str] = []
    if actual != expected:
        reasons.append("reusable_flopo_class_signature_differs_from_runner_candidate")
    if any(
        (row := context.evidence.get(identifier)) is None
        or row.kind not in {"ontology", "authority"}
        for identifier in candidate.authoritative_evidence_ids
    ):
        reasons.append("reusable_flopo_class_authority_binding_invalid")
    if not set(candidate.authoritative_evidence_ids).issubset(decision.evidence_ids):
        reasons.append("reusable_flopo_class_authority_evidence_not_cited")
    return reasons


def validate_review_decision(
    decision: ReviewDecision, context: ValidationContext
) -> LocalValidation:
    reasons = _validate_evidence(decision.item_id, decision.evidence_ids, context)
    signature = decision.proposed_signature
    if signature.kind != decision.disposition:
        reasons.append("disposition_signature_kind_mismatch")
    if not decision.validation_passed:
        reasons.append("reviewer_withheld_validation")

    if signature.kind == "existing_term_mapping":
        assert signature.target_id is not None and signature.target_scope is not None
        if not context.catalog.contains(signature.target_id):
            reasons.append("mapping_target_not_live")
        expected_scope = (
            "anatomy"
            if signature.target_id.startswith("PO_")
            else "quality"
            if signature.target_id.startswith("PATO_")
            else "phenotype"
        )
        if signature.target_scope != expected_scope:
            reasons.append("mapping_scope_namespace_mismatch")
    elif signature.kind == "annotation_expression":
        assert signature.expression is not None
        reasons.extend(_validate_expression(signature.expression, context))
        candidate = context.clusters[decision.item_id].phenotype_expression_candidate
        if candidate is not None and signature.expression != candidate.signature:
            reasons.append("expression_signature_differs_from_runner_candidate")
    elif signature.kind == "structured_qualitative_relation":
        assert signature.qualitative_relation is not None
        reasons.extend(
            _validate_qualitative_relation(
                decision.item_id, signature.qualitative_relation, context
            )
        )
    elif signature.kind == "reusable_flopo_support_class":
        assert signature.support_class is not None
        candidate = context.clusters[decision.item_id].support_class_candidate
        reasons.extend(
            _validate_support_class(decision.item_id, signature.support_class, context)
        )
        if candidate is not None:
            if any(
                (row := context.evidence.get(identifier)) is None or row.kind != "authority"
                for identifier in candidate.authority_evidence_ids
            ):
                reasons.append("support_class_authority_binding_invalid")
            if not set(candidate.authority_evidence_ids).issubset(decision.evidence_ids):
                reasons.append("support_class_authority_evidence_not_cited")
    elif signature.kind == "reusable_flopo_class":
        assert signature.expression is not None
        assert signature.label is not None and signature.definition is not None
        reasons.extend(_validate_expression(signature.expression, context))
        if any(not context.catalog.contains(parent) for parent in signature.parent_ids):
            reasons.append("flopo_parent_not_live")
        if _definition_is_circular(signature.label, signature.definition):
            reasons.append("circular_definition")
        if (
            context.clusters[decision.item_id].reusable_flopo_class_candidate
            is not None
        ):
            reasons.extend(
                _validate_reusable_flopo_class_candidate(
                    decision.item_id, decision, context
                )
            )
        for identifier in signature.authoritative_evidence_ids:
            row = context.evidence.get(identifier)
            if (
                row is None
                or row.kind not in {"ontology", "authority"}
                or identifier not in decision.evidence_ids
            ):
                reasons.append("unverified_authoritative_evidence")
                break
    elif signature.kind == "upstream_po_proposal":
        assert signature.label is not None and signature.definition is not None
        if any(not parent.startswith("PO_") or parent not in context.catalog.po_ids for parent in signature.parent_ids):
            reasons.append("po_parent_not_live")
        if any(not parent.startswith("PO_") or parent not in context.catalog.po_ids for parent in signature.part_of_ids):
            reasons.append("po_part_of_target_not_live")
        if _definition_is_circular(signature.label, signature.definition):
            reasons.append("circular_definition")
        if any(
            (row := context.evidence.get(identifier)) is None
            or row.kind != "authority"
            or identifier not in decision.evidence_ids
            for identifier in signature.authoritative_evidence_ids
        ):
            reasons.append("unverified_authoritative_evidence")
    elif signature.kind == "upstream_pato_proposal":
        assert signature.label is not None and signature.definition is not None
        if any(
            not parent.startswith("PATO_") or parent not in context.catalog.pato_ids
            for parent in signature.parent_ids
        ):
            reasons.append("pato_parent_not_live")
        if _definition_is_circular(signature.label, signature.definition):
            reasons.append("circular_definition")
        if any(
            (row := context.evidence.get(identifier)) is None
            or row.kind != "authority"
            or identifier not in decision.evidence_ids
            for identifier in signature.authoritative_evidence_ids
        ):
            reasons.append("unverified_authoritative_evidence")
    elif signature.kind == "non_phenotype":
        pass
    # Hold signatures are intentionally locally valid but can never become consensus admission.
    return LocalValidation(passed=not reasons, reasons=tuple(dict.fromkeys(reasons)))


def validate_adversarial_verdict(
    verdict: AdversarialVerdict,
    context: ValidationContext,
    *,
    candidate_signature_sha256: str,
) -> LocalValidation:
    reasons = _validate_evidence(verdict.item_id, verdict.evidence_ids, context)
    if verdict.candidate_signature_sha256 != candidate_signature_sha256:
        reasons.append("adversarial_candidate_hash_mismatch")
    if not verdict.validation_passed:
        reasons.append("adversary_withheld_validation")
    return LocalValidation(passed=not reasons, reasons=tuple(dict.fromkeys(reasons)))
