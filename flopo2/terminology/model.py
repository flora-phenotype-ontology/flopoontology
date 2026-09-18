"""Data contracts shared by terminology ingestion, alignment, and extraction."""

from __future__ import annotations

from dataclasses import asdict, dataclass


REGISTRY_FIELDS = (
    "term_id",
    "surface_form",
    "normalized_form",
    "language",
    "semantic_role",
    "category",
    "organ_context",
    "definition",
    "source_id",
    "source_record_id",
    "source_version",
    "source_url",
    "license",
    "translation_group",
    "target_id",
    "target_label",
    "target_namespace",
    "mapping_relation",
    "mapping_confidence",
    "mapping_method",
    "review_status",
    "curator_orcid",
    "mapping_date",
    "component_ids",
    "logical_operator",
    "attribute_id",
    "candidate_ids",
    "candidate_labels",
    "candidate_scores",
    "corpus_frequency",
    "evidence",
    "notes",
)


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    parser: str
    path: str
    language: str = ""
    version: str = ""
    source_url: str = ""
    license: str = ""
    license_status: str = "unknown"
    redistributable: bool = False
    definition_policy: str = "exclude"
    enabled: bool = True
    notes: str = ""


@dataclass(frozen=True)
class GlossaryTerm:
    term_id: str
    surface_form: str
    language: str
    semantic_role: str
    source_id: str
    source_record_id: str
    source_version: str = ""
    source_url: str = ""
    license: str = ""
    category: str = ""
    organ_context: str = ""
    definition: str = ""
    translation_group: str = ""
    target_id: str = ""
    target_label: str = ""
    target_namespace: str = ""
    mapping_relation: str = ""
    mapping_confidence: float = 0.0
    mapping_method: str = ""
    review_status: str = "unreviewed"
    curator_orcid: str = ""
    mapping_date: str = ""
    component_ids: tuple[str, ...] = ()
    logical_operator: str = ""
    attribute_id: str = ""
    evidence: str = ""
    notes: str = ""


@dataclass
class RegistryEntry:
    term_id: str = ""
    surface_form: str = ""
    normalized_form: str = ""
    language: str = ""
    semantic_role: str = "ambiguous"
    category: str = ""
    organ_context: str = ""
    definition: str = ""
    source_id: str = ""
    source_record_id: str = ""
    source_version: str = ""
    source_url: str = ""
    license: str = ""
    translation_group: str = ""
    target_id: str = ""
    target_label: str = ""
    target_namespace: str = ""
    mapping_relation: str = "flopo:unmapped"
    mapping_confidence: float = 0.0
    mapping_method: str = ""
    review_status: str = "unreviewed"
    curator_orcid: str = ""
    mapping_date: str = ""
    component_ids: str = ""
    logical_operator: str = ""
    attribute_id: str = ""
    candidate_ids: str = ""
    candidate_labels: str = ""
    candidate_scores: str = ""
    corpus_frequency: int = 0
    evidence: str = ""
    notes: str = ""

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "RegistryEntry":
        values = {name: row.get(name, "") for name in REGISTRY_FIELDS}
        try:
            values["mapping_confidence"] = float(values["mapping_confidence"] or 0.0)
        except ValueError:
            values["mapping_confidence"] = 0.0
        try:
            values["corpus_frequency"] = int(values["corpus_frequency"] or 0)
        except ValueError:
            values["corpus_frequency"] = 0
        return cls(**values)

    def to_row(self) -> dict[str, str | int | float]:
        values = asdict(self)
        values["mapping_confidence"] = (
            f"{self.mapping_confidence:.4f}".rstrip("0").rstrip(".")
            if self.mapping_confidence
            else "0"
        )
        return {name: values[name] for name in REGISTRY_FIELDS}

    @property
    def components(self) -> tuple[str, ...]:
        return tuple(part for part in self.component_ids.split("|") if part)

    @property
    def candidate_id_list(self) -> tuple[str, ...]:
        return tuple(part for part in self.candidate_ids.split("|") if part)

    @property
    def is_curated(self) -> bool:
        return self.review_status in {"reviewed", "accepted"}


@dataclass(frozen=True)
class Candidate:
    target_id: str
    label: str
    namespace: str
    score: float
    mapping_relation: str = ""
    registry_term_ids: tuple[str, ...] = ()
    review_status: str = ""
    evidence: tuple[str, ...] = ()
    lexical_score: float = 0.0
    definition_score: float = 0.0
    dense_score: float = 0.0
    role_score: float = 0.0
    organ_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def relation(self) -> str:
        return self.mapping_relation

    @property
    def mapping_status(self) -> str:
        return self.review_status


@dataclass(frozen=True)
class TermMention:
    mention_id: str
    start: int
    end: int
    surface_form: str
    normalized_form: str
    language: str
    semantic_roles: tuple[str, ...]
    registry_term_ids: tuple[str, ...]
    candidates: tuple[Candidate, ...] = ()
    longest_match: bool = True
    overlap_group: int = 0
    match_type: str = "exact"
    organ_context: str = ""
    logical_operator: str = ""
    component_ids: tuple[str, ...] = ()
    attribute_id: str = ""

    def to_dict(self) -> dict:
        row = asdict(self)
        row["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return row
