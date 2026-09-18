"""Strict records exchanged by the machine-review campaign.

The models intentionally have no curator or human-review fields.  Pydantic's forbidden
extra-field policy makes outputs containing ``reviewed``, ``curator_orcid``, or any other
unrecognised metadata invalid rather than silently discarding it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
OntologyId = Annotated[
    str,
    StringConstraints(pattern=r"^(?:PO|PATO|FLOPO)_\d+$"),
]
MachineStatus = Literal["llm_consensus", "llm_disputed", "held"]
Disposition = Literal[
    "existing_term_mapping",
    "annotation_expression",
    "structured_qualitative_relation",
    "reusable_flopo_class",
    "reusable_flopo_support_class",
    "upstream_po_proposal",
    "upstream_pato_proposal",
    "non_phenotype",
    "hold",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ArtifactHash(StrictModel):
    path: str = Field(min_length=1)
    sha256: Sha256
    bytes: int = Field(ge=0)


class PromptSpec(ArtifactHash):
    prompt_id: str = Field(min_length=1)


class ModelSpec(StrictModel):
    reviewer_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    role: Literal["reviewer", "adjudicator"]
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "high"
    descriptor_sha256: Sha256

    @model_validator(mode="after")
    def verify_descriptor_hash(self) -> "ModelSpec":
        descriptor = {
            "reviewer_id": self.reviewer_id,
            "provider": self.provider,
            "model": self.model,
            "model_family": self.model_family,
            "role": self.role,
            "reasoning_effort": self.reasoning_effort,
        }
        expected = hashlib.sha256(canonical_json(descriptor).encode()).hexdigest()
        if self.descriptor_sha256 != expected:
            raise ValueError("descriptor_sha256 does not match the pinned model descriptor")
        return self


class DerivationSpec(StrictModel):
    protocol: Literal[
        "flopo-exact-semantic-context-clustering-v2",
        "flopo-support-class-candidate-clustering-v1",
        "flopo-support-occurrence-review-v1",
        "flopo-exact-colour-eq-gap-class-review-v1",
        "flopo-exact-colour-eq-gap-occurrence-review-v1",
    ] = "flopo-exact-semantic-context-clustering-v2"
    descriptor_sha256: Sha256

    @model_validator(mode="after")
    def verify_descriptor_hash(self) -> "DerivationSpec":
        descriptor = {"protocol": self.protocol}
        expected = hashlib.sha256(canonical_json(descriptor).encode()).hexdigest()
        if self.descriptor_sha256 != expected:
            raise ValueError("derivation descriptor hash does not match protocol")
        return self


class CampaignManifest(StrictModel):
    schema_version: Literal["flopo-llm-campaign-v2"] = "flopo-llm-campaign-v2"
    campaign_id: str = Field(pattern=r"^campaign_[0-9a-f]{24}$")
    created_at: datetime
    input: ArtifactHash
    ontologies: tuple[ArtifactHash, ...]
    authorities: tuple[ArtifactHash, ...] = ()
    sources: tuple[ArtifactHash, ...] = ()
    prompts: tuple[PromptSpec, ...]
    models: tuple[ModelSpec, ...]
    derivation: DerivationSpec
    occurrences: ArtifactHash
    clusters: ArtifactHash
    evidence_registry: ArtifactHash
    starting_occurrences: int = Field(ge=0)
    starting_clusters: int = Field(ge=0)

    @field_validator("ontologies", "authorities", "sources", "prompts", "models")
    @classmethod
    def require_unique_entries(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        identities: list[str] = []
        for value in values:
            identities.append(
                getattr(value, "prompt_id", None)
                or getattr(value, "reviewer_id", None)
                or getattr(value, "path")
            )
        if len(identities) != len(set(identities)):
            raise ValueError("manifest entries must have unique identifiers")
        return values

    @model_validator(mode="after")
    def verify_campaign_id(self) -> "CampaignManifest":
        seed = {
            "input": self.input.sha256,
            "ontologies": [row.sha256 for row in self.ontologies],
            "authorities": [row.sha256 for row in self.authorities],
            "prompts": [(row.prompt_id, row.sha256) for row in self.prompts],
            "models": [(row.reviewer_id, row.descriptor_sha256) for row in self.models],
            "derivation": self.derivation.descriptor_sha256,
        }
        if self.sources:
            seed["sources"] = [row.sha256 for row in self.sources]
        digest = hashlib.sha256(canonical_json(seed).encode()).hexdigest()[:24]
        if self.campaign_id != f"campaign_{digest}":
            raise ValueError("campaign_id does not match the frozen campaign inputs")
        return self


class ReviewerProvenance(StrictModel):
    reviewer_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"]
    prompt_id: str = Field(min_length=1)
    prompt_sha256: Sha256


class SignaturePartRestriction(StrictModel):
    property: Literal["BFO_0000051"] = "BFO_0000051"
    filler_class: OntologyId
    qualities: tuple[OntologyId, ...] = Field(min_length=1)

    @field_validator("filler_class")
    @classmethod
    def require_anatomical_filler(cls, value: str) -> str:
        if not value.startswith(("PO_", "FLOPO_")):
            raise ValueError("part filler must be a PO or FLOPO class")
        return value

    @field_validator("qualities")
    @classmethod
    def require_quality_fillers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.startswith(("PATO_", "FLOPO_")) for item in value):
            raise ValueError("part qualities must be PATO or FLOPO classes")
        if len(value) != len(set(value)):
            raise ValueError("part qualities must be unique")
        return value


class PhenotypeExpression(StrictModel):
    bearer_id: OntologyId
    quality_id: OntologyId
    value_operator: Literal["atomic", "all_of", "one_of"] = "atomic"
    value_terms: tuple[OntologyId, ...] = ()
    negated: bool = False
    developmental_stage_ids: tuple[OntologyId, ...] = ()
    part_restrictions: tuple[SignaturePartRestriction, ...] = ()
    value_low: float | None = None
    value_high: float | None = None
    value_low_inclusive: bool = True
    value_high_inclusive: bool = True
    unit: str = ""

    @field_validator("bearer_id")
    @classmethod
    def require_bearer_namespace(cls, value: str) -> str:
        if not value.startswith(("PO_", "FLOPO_")):
            raise ValueError("bearer must be a PO or FLOPO class")
        return value

    @field_validator("quality_id", "value_terms")
    @classmethod
    def require_quality_namespace(cls, value):
        values = (value,) if isinstance(value, str) else value
        if any(not item.startswith(("PATO_", "FLOPO_")) for item in values):
            raise ValueError("qualities must be PATO or FLOPO classes")
        return value

    @field_validator("developmental_stage_ids")
    @classmethod
    def require_stage_namespace(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.startswith(("PO_", "FLOPO_")) for item in value):
            raise ValueError("developmental stages must be PO or FLOPO classes")
        return value

    @model_validator(mode="after")
    def validate_operator_arity(self) -> "PhenotypeExpression":
        if self.value_operator in {"all_of", "one_of"} and len(self.value_terms) < 2:
            raise ValueError("logical value operators require at least two terms")
        if self.value_operator in {"all_of", "one_of"} and len(self.value_terms) != len(
            set(self.value_terms)
        ):
            raise ValueError("logical value terms must be distinct")
        if self.value_operator == "atomic" and len(self.value_terms) > 1:
            raise ValueError("atomic expressions have at most one value term")
        bounds = tuple(value for value in (self.value_low, self.value_high) if value is not None)
        if any(not math.isfinite(value) for value in bounds):
            raise ValueError("numeric phenotype bounds must be finite")
        if (
            self.value_low is not None
            and self.value_high is not None
            and self.value_low > self.value_high
        ):
            raise ValueError("numeric phenotype bounds must not be reversed")
        if bool(bounds) != bool(self.unit):
            raise ValueError("numeric phenotype bounds and unit must be supplied together")
        if not bounds and (
            not self.value_low_inclusive or not self.value_high_inclusive
        ):
            raise ValueError("bound inclusivity requires a numeric phenotype bound")
        return self


class QualitativeRelationSignature(StrictModel):
    bearer_id: OntologyId
    attribute_id: OntologyId
    interpretation: Literal[
        "continuum", "taxon_level_alternatives", "temporal_transition"
    ]
    from_value: OntologyId
    to_value: OntologyId

    @field_validator("bearer_id")
    @classmethod
    def require_bearer_namespace(cls, value: str) -> str:
        if not value.startswith(("PO_", "FLOPO_")):
            raise ValueError("bearer must be a PO or FLOPO class")
        return value

    @field_validator("attribute_id", "from_value", "to_value")
    @classmethod
    def require_quality_namespace(cls, value: str) -> str:
        if not value.startswith(("PATO_", "FLOPO_")):
            raise ValueError("qualitative attributes and values must be PATO or FLOPO classes")
        return value

    @model_validator(mode="after")
    def require_distinct_endpoints(self) -> "QualitativeRelationSignature":
        if self.from_value == self.to_value:
            raise ValueError("qualitative relation endpoints must be distinct")
        if not self.attribute_id.startswith("PATO_"):
            raise ValueError("qualitative relation attribute must be a PATO class")
        return self


class QualitativeRelationCandidate(StrictModel):
    """Runner-derived candidate embedded in a source-bound review item."""

    signature: QualitativeRelationSignature
    bearer_method: str = Field(min_length=1)
    bearer_text: str = ""
    bearer_start: int | None = Field(default=None, ge=0)
    bearer_end: int | None = Field(default=None, gt=0)
    expression_start: int = Field(ge=0)
    expression_end: int = Field(gt=0)
    expression_text: str = Field(min_length=1)
    from_text: str = Field(min_length=1)
    from_start: int = Field(ge=0)
    from_end: int = Field(gt=0)
    connector_text: str = Field(min_length=1)
    connector_start: int = Field(ge=0)
    connector_end: int = Field(gt=0)
    to_text: str = Field(min_length=1)
    to_start: int = Field(ge=0)
    to_end: int = Field(gt=0)
    clear_unresolved_spans: tuple[tuple[int, int], ...] = ()

    @model_validator(mode="after")
    def validate_ranges(self) -> "QualitativeRelationCandidate":
        if (self.bearer_start is None) != (self.bearer_end is None):
            raise ValueError("qualitative candidate bearer offsets must be paired")
        if self.bearer_start is not None and not (
            self.bearer_text and self.bearer_start < self.bearer_end
        ):
            raise ValueError("qualitative candidate bearer evidence is malformed")
        if not (
            self.expression_start <= self.from_start < self.from_end
            <= self.connector_start < self.connector_end
            <= self.to_start < self.to_end <= self.expression_end
        ):
            raise ValueError("qualitative candidate evidence is not in source order")
        if any(start < 0 or end <= start for start, end in self.clear_unresolved_spans):
            raise ValueError("qualitative candidate clear ranges are malformed")
        if len(self.clear_unresolved_spans) != len(set(self.clear_unresolved_spans)):
            raise ValueError("qualitative candidate clear ranges must be unique")
        return self


class SupportClassSignature(StrictModel):
    """Exact semantics proposed for a provisional FLOPO-local anatomy class."""

    label: str = Field(min_length=1)
    definition: str = Field(min_length=12)
    parent_ids: tuple[OntologyId, ...] = Field(min_length=1)
    part_of_ids: tuple[OntologyId, ...] = ()

    @field_validator("parent_ids", "part_of_ids")
    @classmethod
    def require_po_anatomy_targets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not identifier.startswith("PO_") for identifier in value):
            raise ValueError("support-class parents and parthood targets must be PO classes")
        if len(value) != len(set(value)):
            raise ValueError("support-class ontology identifiers must be unique")
        return value


class SupportClassCandidate(StrictModel):
    """Runner-bound local anatomy proposal with machine-curation provenance."""

    proposal_key: str = Field(pattern=r"^FLOPO_LOCAL:[a-z0-9_]+$")
    signature: SupportClassSignature
    routing_keys: tuple[str, ...] = Field(min_length=1)
    source_register_ids: tuple[str, ...] = Field(min_length=1)
    authority_evidence_ids: tuple[str, ...] = Field(min_length=1)
    occurrence_count: int = Field(gt=0)
    source_claims: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "routing_keys", "source_register_ids", "authority_evidence_ids", "source_claims"
    )
    @classmethod
    def require_unique_nonblank_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("support-class candidate values must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("support-class candidate values must be unique")
        return value


class PhenotypeExpressionCandidate(StrictModel):
    """Runner-bound exact source assertion proposed for occurrence-level review."""

    signature: PhenotypeExpression
    bearer_method: str = Field(min_length=1)
    bearer_text: str = ""
    bearer_start: int | None = Field(default=None, ge=0)
    bearer_end: int | None = Field(default=None, gt=0)
    expression_start: int = Field(ge=0)
    expression_end: int = Field(gt=0)
    expression_text: str = Field(min_length=1)
    clear_unresolved_spans: tuple[tuple[int, int], ...] = Field(min_length=1)
    support_proposal_key: str | None = Field(
        default=None, pattern=r"^FLOPO_LOCAL:[a-z0-9_]+$"
    )
    support_class_campaign_id: str | None = Field(
        default=None, pattern=r"^campaign_[0-9a-f]{24}$"
    )
    support_class_signature_sha256: Sha256 | None = None
    eq_class_proposal_key: str | None = Field(
        default=None, pattern=r"^eqgap_[0-9a-f]{24}$"
    )
    eq_class_id: OntologyId | None = None
    eq_class_campaign_id: str | None = Field(
        default=None, pattern=r"^campaign_[0-9a-f]{24}$"
    )
    eq_class_signature_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "PhenotypeExpressionCandidate":
        if (self.bearer_start is None) != (self.bearer_end is None):
            raise ValueError("expression candidate bearer offsets must be paired")
        if self.bearer_start is not None and not (
            self.bearer_text and self.bearer_start < self.bearer_end
        ):
            raise ValueError("expression candidate bearer evidence is malformed")
        if any(start < 0 or end <= start for start, end in self.clear_unresolved_spans):
            raise ValueError("expression candidate clear ranges are malformed")
        if len(self.clear_unresolved_spans) != len(set(self.clear_unresolved_spans)):
            raise ValueError("expression candidate clear ranges must be unique")
        if self.expression_end <= self.expression_start:
            raise ValueError("expression candidate range is malformed")
        if any(
            start < self.expression_start or end > self.expression_end
            for start, end in self.clear_unresolved_spans
        ):
            raise ValueError("expression clear ranges must be inside the reviewed expression")
        support_binding = (
            self.support_proposal_key,
            self.support_class_campaign_id,
            self.support_class_signature_sha256,
        )
        if any(value is not None for value in support_binding) and not all(
            value is not None for value in support_binding
        ):
            raise ValueError("support-class expression provenance must be supplied together")
        eq_binding = (
            self.eq_class_proposal_key,
            self.eq_class_id,
            self.eq_class_campaign_id,
            self.eq_class_signature_sha256,
        )
        if any(value is not None for value in eq_binding) and not all(
            value is not None for value in eq_binding
        ):
            raise ValueError("EQ-class expression provenance must be supplied together")
        if self.eq_class_id is not None and not self.eq_class_id.startswith("FLOPO_"):
            raise ValueError("EQ-class provenance must identify a FLOPO class")
        return self


class ReusableFlopoClassCandidate(StrictModel):
    """Runner-bound exact EQ class proposed for machine-reviewed FLOPO extension."""

    proposal_key: str = Field(pattern=r"^eqgap_[0-9a-f]{24}$")
    signature: PhenotypeExpression
    label: str = Field(min_length=1)
    definition: str = Field(min_length=12)
    parent_ids: tuple[OntologyId, ...] = Field(min_length=1)
    authoritative_evidence_ids: tuple[str, ...] = Field(min_length=1)
    occurrence_count: int = Field(gt=0)
    source_occurrence_membership_sha256: Sha256

    @field_validator("parent_ids")
    @classmethod
    def require_flopo_parents(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not identifier.startswith("FLOPO_") for identifier in value):
            raise ValueError("reusable FLOPO class parents must be FLOPO classes")
        if len(value) != len(set(value)):
            raise ValueError("reusable FLOPO class parents must be unique")
        return value

    @field_validator("authoritative_evidence_ids")
    @classmethod
    def require_unique_authority_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not identifier.strip() for identifier in value):
            raise ValueError("class authority evidence IDs must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("class authority evidence IDs must be unique")
        return value


class ProposedSignature(StrictModel):
    """Provider-compatible tagged union with disposition-specific local invariants.

    OpenAI strict structured output rejects JSON Schema ``oneOf``.  All possible fields therefore
    appear in one closed object; this validator enforces the exact allowed/required field set for
    the selected ``kind`` and rejects payload smuggling through unused fields.
    """

    kind: Disposition
    target_id: OntologyId | None = None
    target_scope: Literal["anatomy", "quality", "phenotype"] | None = None
    expression: PhenotypeExpression | None = None
    qualitative_relation: QualitativeRelationSignature | None = None
    support_class: SupportClassSignature | None = None
    label: str | None = None
    definition: str | None = None
    parent_ids: tuple[OntologyId, ...] = ()
    part_of_ids: tuple[OntologyId, ...] = ()
    authoritative_evidence_ids: tuple[str, ...] = ()
    category: Literal["noise", "habitat", "geology", "abundance", "tokenization"] | None = None
    explanation: str | None = None
    reason: str | None = None
    missing_evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_variant(self) -> "ProposedSignature":
        scalar_values = {
            "target_id": self.target_id,
            "target_scope": self.target_scope,
            "expression": self.expression,
            "qualitative_relation": self.qualitative_relation,
            "support_class": self.support_class,
            "label": self.label,
            "definition": self.definition,
            "category": self.category,
            "explanation": self.explanation,
            "reason": self.reason,
        }
        sequence_values = {
            "parent_ids": self.parent_ids,
            "part_of_ids": self.part_of_ids,
            "authoritative_evidence_ids": self.authoritative_evidence_ids,
            "missing_evidence": self.missing_evidence,
        }
        required: dict[str, set[str]] = {
            "existing_term_mapping": {"target_id", "target_scope"},
            "annotation_expression": {"expression"},
            "structured_qualitative_relation": {"qualitative_relation"},
            "reusable_flopo_class": {
                "label",
                "definition",
                "expression",
                "parent_ids",
                "authoritative_evidence_ids",
            },
            "reusable_flopo_support_class": {"support_class"},
            "upstream_po_proposal": {
                "label",
                "definition",
                "parent_ids",
                "authoritative_evidence_ids",
            },
            "upstream_pato_proposal": {
                "label",
                "definition",
                "parent_ids",
                "authoritative_evidence_ids",
            },
            "non_phenotype": {"category", "explanation"},
            "hold": {"reason"},
        }
        allowed = set(required[self.kind])
        if self.kind == "upstream_po_proposal":
            allowed.add("part_of_ids")
        if self.kind == "hold":
            allowed.add("missing_evidence")
        populated = {
            key for key, value in scalar_values.items() if value is not None
        } | {key for key, value in sequence_values.items() if value}
        missing = required[self.kind] - populated
        unexpected = populated - allowed
        if missing:
            raise ValueError(f"{self.kind} signature is missing fields: {sorted(missing)}")
        if unexpected:
            raise ValueError(f"{self.kind} signature has unrelated fields: {sorted(unexpected)}")
        if self.label is not None and not self.label.strip():
            raise ValueError("proposal label must not be blank")
        if self.definition is not None and len(self.definition.strip()) < 12:
            raise ValueError("proposal definition is too short")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("hold reason must not be blank")
        if self.explanation is not None and not self.explanation.strip():
            raise ValueError("non-phenotype explanation must not be blank")
        return self


class ReviewDecision(ReviewerProvenance):
    schema_version: Literal["flopo-review-decision-v1"] = "flopo-review-decision-v1"
    campaign_id: str = Field(pattern=r"^campaign_[0-9a-f]{24}$")
    item_id: str = Field(pattern=r"^cluster_[0-9a-f]{24}$")
    disposition: Disposition
    proposed_signature: ProposedSignature
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    validation_passed: bool

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("evidence IDs must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique")
        return value

    @property
    def normalized_signature(self) -> str:
        return canonical_json(
            self.proposed_signature.model_dump(
                mode="json", exclude_none=True, exclude_defaults=True
            )
        )

    @property
    def signature_sha256(self) -> str:
        return hashlib.sha256(self.normalized_signature.encode()).hexdigest()


class AdversarialVerdict(ReviewerProvenance):
    schema_version: Literal["flopo-adversarial-verdict-v1"] = (
        "flopo-adversarial-verdict-v1"
    )
    campaign_id: str = Field(pattern=r"^campaign_[0-9a-f]{24}$")
    item_id: str = Field(pattern=r"^cluster_[0-9a-f]{24}$")
    candidate_signature_sha256: Sha256
    verdict: Literal["no_blocker", "block"]
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    validation_passed: bool


class ReviewBatchResponse(StrictModel):
    schema_version: Literal["flopo-review-batch-response-v1"] = (
        "flopo-review-batch-response-v1"
    )
    decisions: tuple[ReviewDecision, ...]


class AdversarialBatchResponse(StrictModel):
    schema_version: Literal["flopo-adversarial-batch-response-v1"] = (
        "flopo-adversarial-batch-response-v1"
    )
    decisions: tuple[AdversarialVerdict, ...]


class Occurrence(StrictModel):
    schema_version: Literal["flopo-review-occurrence-v2"] = "flopo-review-occurrence-v2"
    occurrence_id: str = Field(pattern=r"^occ_[0-9a-f]{24}$")
    evidence_id: str = Field(pattern=r"^evidence_[0-9a-f]{24}$")
    cluster_id: str = Field(pattern=r"^cluster_[0-9a-f]{24}$")
    semantic_fingerprint: Sha256
    source: str
    source_id: str
    source_segment_index: int
    taxon: str = ""
    organ: str = ""
    language: str = ""
    segment_char_start: int = Field(ge=0)
    segment_char_end: int = Field(ge=0)
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    surface_form: str
    normalized_form: str
    reason: str
    candidate_pato_id: str = ""
    pending_bearer: str = ""
    promoted_po_ids: tuple[str, ...] = ()
    extractor: str
    context: str
    qualitative_relation_candidate: QualitativeRelationCandidate | None = None
    support_class_candidate: SupportClassCandidate | None = None
    phenotype_expression_candidate: PhenotypeExpressionCandidate | None = None
    reusable_flopo_class_candidate: ReusableFlopoClassCandidate | None = None


class EvidenceRecord(StrictModel):
    schema_version: Literal["flopo-evidence-record-v1"] = "flopo-evidence-record-v1"
    evidence_id: str = Field(pattern=r"^evidence_[0-9a-f]{24}$")
    kind: Literal["occurrence", "ontology", "authority", "source_inventory"]
    occurrence_id: Annotated[str, StringConstraints(pattern=r"^occ_[0-9a-f]{24}$")] | None = None
    item_id: Annotated[str, StringConstraints(pattern=r"^cluster_[0-9a-f]{24}$")] | None = None
    payload_sha256: Sha256
    locator: str = Field(min_length=1)
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_occurrence_route(self) -> "EvidenceRecord":
        if self.kind == "occurrence" and (not self.occurrence_id or not self.item_id):
            raise ValueError("occurrence evidence requires occurrence_id and item_id")
        if self.kind in {"ontology", "authority", "source_inventory"} and (
            self.occurrence_id or self.item_id
        ):
            raise ValueError("reference evidence must not claim occurrence routing")
        return self


class ContextSample(StrictModel):
    evidence_id: str = Field(pattern=r"^evidence_[0-9a-f]{24}$")
    occurrence_id: str = Field(pattern=r"^occ_[0-9a-f]{24}$")
    context: str = Field(min_length=1)
    context_sha256: Sha256


class Cluster(StrictModel):
    schema_version: Literal["flopo-review-cluster-v2"] = "flopo-review-cluster-v2"
    cluster_id: str = Field(pattern=r"^cluster_[0-9a-f]{24}$")
    normalized_form: str
    reason: str
    candidate_pato_id: str = ""
    language: str = ""
    organ: str = ""
    pending_bearer: str = ""
    promoted_po_ids: tuple[str, ...] = ()
    semantic_fingerprint: Sha256
    occurrence_count: int = Field(gt=0)
    occurrence_membership_sha256: Sha256
    context_samples: tuple[ContextSample, ...] = Field(min_length=1)
    qualitative_relation_candidate: QualitativeRelationCandidate | None = None
    support_class_candidate: SupportClassCandidate | None = None
    phenotype_expression_candidate: PhenotypeExpressionCandidate | None = None
    reusable_flopo_class_candidate: ReusableFlopoClassCandidate | None = None


class ConsensusDecision(StrictModel):
    schema_version: Literal["flopo-consensus-decision-v1"] = "flopo-consensus-decision-v1"
    campaign_id: str = Field(pattern=r"^campaign_[0-9a-f]{24}$")
    item_id: str = Field(pattern=r"^cluster_[0-9a-f]{24}$")
    status: MachineStatus
    disposition: Disposition | None = None
    normalized_signature: str | None = None
    signature_sha256: Sha256 | None = None
    reviewer_ids: tuple[str, ...] = ()
    adjudicator_id: str | None = None
    reasons: tuple[str, ...]
    validation_passed: bool

    @field_validator("normalized_signature")
    @classmethod
    def require_canonical_signature(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = json.loads(value)
        if canonical_json(parsed) != value:
            raise ValueError("normalized_signature is not canonical JSON")
        return value


class LedgerEntry(StrictModel):
    schema_version: Literal["flopo-conservation-ledger-v1"] = (
        "flopo-conservation-ledger-v1"
    )
    campaign_id: str = Field(pattern=r"^campaign_[0-9a-f]{24}$")
    occurrence_id: str = Field(pattern=r"^occ_[0-9a-f]{24}$")
    item_id: str = Field(pattern=r"^cluster_[0-9a-f]{24}$")
    status: MachineStatus
    disposition: Disposition | None = None
    signature_sha256: Sha256 | None = None
    reasons: tuple[str, ...]


def canonical_json(value: Any) -> str:
    """Return the one permitted JSON representation for semantic signatures."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("signature must contain only finite JSON values") from exc


def normalized_text(value: object) -> str:
    """Normalize surface forms for clustering without applying semantic rewrites."""

    import unicodedata

    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold()).strip()
