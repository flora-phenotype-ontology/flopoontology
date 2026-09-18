"""Runner-owned inventory for the immutable Stage-15 ``negated_context`` review campaign.

The 448 ``negated_context`` unresolved spans that survive to Stage 15 are semantically
heterogeneous: bare quality negation ("non ramifiée"), full bearer/part absence ("sans poils"),
negated numerical comparators that are really upper bounds ("ne dépassant pas 5 mm"), coordinated
or hedged negation ("peu ou pas ramifiée"), scope-restricted negation ("non ramifiée sauf …"),
and false cues where the negation governs a neighbouring word ("non glandulaires brun-jaune", span
= "brun").  Flattening any of these into atomic quality negation is wrong under open-world
semantics, so this builder classifies each span conservatively and only proposes an *admissible*
exact expression when the negation cleanly governs the single quality and a bearer is
deterministically recoverable.

The generic review records (:mod:`flopo2.review.models`) cannot carry the negation-specific
distinction between bearer-present quality negation and full bearer absence, nor the runner's
cue evidence.  This module therefore encodes a canonical, runner-owned ``NEGATION_REVIEW_PAYLOAD``
JSON object inside each occurrence context *and* freezes a separate typed candidate inventory that
is bound into the campaign manifest as a ``sources`` artifact.  Reviewers may copy the admitted
expression exactly or hold; they can never rewrite the classification, scope, bearer, identifiers,
or source offsets, because admission is re-derived from the frozen candidate, not from model text.

This module never runs an LLM and never mutates Stage 15.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal

from pydantic import Field, StringConstraints, model_validator

from flopo2.extract.context_recovery import _baseline_bearer, _lexical_bearer
from flopo2.extract.measurement import parse_measurements
from flopo2.review.inventory import (
    _artifact_at,
    _evidence_record,
    _reference_record,
    _review_context,
    _temp_path,
    _validate_distinct_paths,
    derivation_spec,
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
    ModelSpec,
    Occurrence,
    PhenotypeExpression,
    PromptSpec,
    ProposedSignature,
    Sha256,
    StrictModel,
    canonical_json,
    normalized_text,
)
from flopo2.verify.missing_bearers import _po_exact_forms, _po_forms


NEGATION_PROTOCOL = "flopo-negation-context-review-v1"
REVIEW_REASON = "negated_context"
CANDIDATE_SCHEMA_VERSION = "flopo-negation-candidate-v1"
REPORT_SCHEMA_VERSION = "flopo-negation-candidate-report-v1"
PAYLOAD_MARKER = "<<<NEGATION_REVIEW_PAYLOAD>>>"

Classification = Literal[
    "quality_negation",
    "bearer_absence",
    "numeric_upper_bound",
    "mixed_negation_disjunction",
    "compound_scope",
    "false_cue",
    "undetermined",
]
NegationScope = Literal["quality", "absence", "numeric_bound", "none"]
ADMISSIBLE: frozenset[str] = frozenset(
    {"quality_negation", "bearer_absence", "numeric_upper_bound"}
)
HELD_ONLY: frozenset[str] = frozenset(
    {"mixed_negation_disjunction", "compound_scope", "false_cue", "undetermined"}
)
_SCOPE_FOR: dict[str, NegationScope] = {
    "quality_negation": "quality",
    "bearer_absence": "absence",
    "numeric_upper_bound": "numeric_bound",
}

SegmentKey = tuple[str, str, int, str]

# Clause boundaries used to bound the search for the governing negation cue.
_CLAUSE_BOUNDARY = ".;:()\n"
_CLAUSE_WINDOW = 72

# The gate lexicons are the source of truth for what a negation / upper-bound cue is; import them so
# the runner never drifts from the deterministic post-consensus gate.
from flopo2.verify.gates import NEGATION_EVIDENCE, UPPER_BOUND_EVIDENCE  # noqa: E402

# A negation cue that denotes non-existence of the bearer/part rather than a bearer-present quality.
_ABSENCE_CUE = re.compile(
    r"(?<!\w)(?:without|lacking|devoid|no|non-existent|sans|d[ée]pourvu(?:e|es|s)?|"
    r"absent(?:e|es|s)?|d[ée]nu[ée]s?|ni)(?!\w)|"
    r"\b(?:e|un)(?:branched|armed|lobed|stalked|winged|awned|spotted)\b",
    re.IGNORECASE,
)
# Coordinated / hedged negation whose scope cannot be flattened to atomic quality negation.
_DISJUNCTION_CUE = re.compile(
    r"\b(?:ou|or)\b|peu\s+ou\s+pas|little\s+or\s+not|not\s+or\s+|"
    r"plus\s+ou\s+moins|more\s+or\s+less|avec\s+ou\s+sans|with\s+or\s+without|"
    r"±|\bnot\s+always\b|pas\s+toujours",
    re.IGNORECASE,
)
# Scope-restricting or exceptive constructions.
_EXCEPTION_CUE = re.compile(
    r"\b(?:sauf|except|excepté|hormis|mais|but|apart\s+from|sinon|si\s+ce\s+n)\b",
    re.IGNORECASE,
)
# Degree adverbs sitting between the cue and the quality: the negation scopes the degree, not the
# bare quality ("non longuement acuminées" ≠ "not acuminate").
_DEGREE_ADVERB = re.compile(
    r"\b(?:longuement|largement|fortement|enti[èe]rement|compl[èe]tement|nettement|"
    r"distinctement|profond[ée]ment|deeply|strongly|entirely|wholly|fully|markedly|"
    r"distinctly|conspicuously|longly|broadly|densely|sparsely)\b",
    re.IGNORECASE,
)
# Frequency / habituality between the cue and the quality: not a universal phenotype negation.
_FREQUENCY_ADVERB = re.compile(
    r"\b(?:rarement|g[ée]n[ée]ralement|souvent|parfois|toujours|habituellement|"
    r"rarely|generally|often|sometimes|always|usually|occasionally|frequently)\b",
    re.IGNORECASE,
)
_CONDITIONAL_PREFIX = re.compile(
    r"\b(?:quand|lorsque|lorsqu['’e]?|when|if)\b[^,;:.!?()]{0,32}$",
    re.IGNORECASE,
)
# A contrastive correction such as ``puberulent (and not pubescent)`` is not a clean standalone
# atomic assertion: the negation is part of a terminology/degree contrast and the local bearer can
# sit outside the parenthesis.  Keep it for review instead of falling back to the organ heading.
_CORRECTION_PREFIX = re.compile(
    r"(?:\b(?:et|and|but|mais)\s+)?non\s*$|\b(?:and|et)\s+not\s*$",
    re.IGNORECASE,
)
# Two malformed Gabon source rows contain ``Petit arbre général non ramifié``.  ``général`` is not
# the adverb ``généralement`` and may be OCR/truncation rather than an asserted universal negation.
_MALFORMED_NEGATION_PREFIX = re.compile(r"\bg[ée]n[ée]ral\s*$", re.IGNORECASE)
# These source constructions negate a compound coating/colour phrase rather than the isolated
# PATO colour captured by the baseline (``not white waxy`` is not evidence for a non-white
# rhizome). Keep this deliberately closed to the attested residual families.
_COMPOUND_TAIL = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:waxy|gland[- ]dotted|olivaceous)\b",
    re.IGNORECASE,
)
# Attested post-quality modifiers whose omission would widen an absence expression.  For example,
# ``sans cambium jaune habituel développé`` is not simply absence of every yellow cambium.
_SCOPED_POST_QUALITY = re.compile(
    r"^\s*(?:habituel(?:le|les|s)?|usual|normally\s+developed|d[ée]velopp[ée](?:e?s?)?)\b",
    re.IGNORECASE,
)
_OPTIONAL_BOUND_SCOPE = re.compile(
    r"\bnon[- ]stipitate\s+(?:or|to)\s+up\s+to\b|"
    r"\b(?:with\s+or\s+without|avec\s+ou\s+sans)\b",
    re.IGNORECASE,
)
# Connector / function words that are allowed to sit between the cue and the quality without
# implying a distinct negated target.
_CONNECTOR_WORDS = frozenset(
    {
        "et",
        "and",
        "ni",
        "nor",
        "the",
        "a",
        "an",
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "de",
        "du",
        "of",
        "to",
        "au",
        "aux",
        "que",
        "qui",
    }
)
_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


class NegationCandidate(StrictModel):
    """Runner-owned exact negation candidate for one Stage-15 span.

    ``admit`` requires a fully-typed ``admitted_expression`` and an admissible classification with a
    concrete scope; ``hold`` requires the expression to be absent.  The self-validating hashes let a
    materializer trust the frozen inventory without re-deriving the classifier.
    """

    schema_version: Literal["flopo-negation-candidate-v1"] = CANDIDATE_SCHEMA_VERSION
    occurrence_id: Annotated[str, StringConstraints(pattern=r"^occ_[0-9a-f]{24}$")]
    cluster_id: Annotated[str, StringConstraints(pattern=r"^cluster_[0-9a-f]{24}$")]
    source: str
    source_id: str
    source_segment_index: int = Field(ge=0)
    taxon: str = ""
    language: str = ""
    organ: str = ""
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    surface_form: str = Field(min_length=1)
    quality_pato_id: Annotated[str, StringConstraints(pattern=r"^PATO_\d+$")]
    classification: Classification
    admission: Literal["admit", "hold"]
    negation_scope: NegationScope
    hold_reason: str = ""
    cue_text: str = Field(min_length=1)
    cue_start: int = Field(ge=0)
    cue_end: int = Field(gt=0)
    bearer_id: str = ""
    bearer_text: str = ""
    bearer_start: int | None = Field(default=None, ge=0)
    bearer_end: int | None = Field(default=None, gt=0)
    source_text: str = Field(min_length=1)
    source_start: int = Field(ge=0)
    source_end: int = Field(gt=0)
    admitted_expression: PhenotypeExpression | None = None
    admitted_signature_sha256: str = ""
    clear_span: tuple[int, int]
    bearer_method: str = ""
    payload_sha256: Sha256

    @model_validator(mode="after")
    def validate_candidate(self) -> "NegationCandidate":
        if self.span_end <= self.span_start:
            raise ValueError("negation span offsets are reversed")
        if self.clear_span != (self.span_start, self.span_end):
            raise ValueError("cleared range must equal the exact reviewed span")
        if not (self.cue_start < self.cue_end <= self.source_end):
            raise ValueError("cue offsets must be ordered inside the source evidence")
        if not (self.source_start <= self.cue_start and self.source_end >= self.span_end):
            raise ValueError("source evidence must cover the cue and the reviewed span")
        if self.source_end <= self.source_start:
            raise ValueError("source evidence offsets are reversed")
        if (self.bearer_start is None) != (self.bearer_end is None):
            raise ValueError("bearer offsets must be paired")
        if self.bearer_id:
            if not self.bearer_text or not self.bearer_method:
                raise ValueError("a resolved bearer requires text and a binding method")
            if self.bearer_method == "organ_heading":
                if self.bearer_start is not None:
                    raise ValueError("an organ-heading bearer must not fabricate source offsets")
            elif self.bearer_start is None:
                raise ValueError("an explicit bearer requires exact source offsets")
        elif any(
            (
                self.bearer_text,
                self.bearer_method,
                self.bearer_start is not None,
                self.bearer_end is not None,
            )
        ):
            raise ValueError("bearer evidence cannot exist without a bearer identifier")
        if self.admission == "admit":
            if self.classification not in ADMISSIBLE:
                raise ValueError("only admissible classifications may carry an admission")
            if self.negation_scope != _SCOPE_FOR[self.classification]:
                raise ValueError("admitted scope does not match its classification")
            if self.admitted_expression is None:
                raise ValueError("an admitted candidate requires an exact expression")
            if not self.bearer_id:
                raise ValueError("an admitted candidate requires a resolved bearer")
            if self.bearer_id != self.admitted_expression.bearer_id:
                raise ValueError("admitted bearer does not match the expression bearer")
            if self.quality_pato_id != self.admitted_expression.quality_id:
                raise ValueError("admitted quality does not match the reviewed PATO id")
            expected_negated = self.classification != "numeric_upper_bound"
            if self.admitted_expression.negated != expected_negated:
                raise ValueError("admitted negation flag disagrees with the classification")
            normalized, digest = annotation_signature(self.admitted_expression)
            if self.admitted_signature_sha256 != digest:
                raise ValueError("admitted signature hash does not match the expression")
            if self.hold_reason:
                raise ValueError("an admitted candidate must not carry a hold reason")
        else:
            if self.admitted_expression is not None or self.admitted_signature_sha256:
                raise ValueError("a held candidate must not carry an admitted expression")
            if self.negation_scope not in {"quality", "absence", "numeric_bound", "none"}:
                raise ValueError("held candidate scope is malformed")
            if not self.hold_reason:
                raise ValueError("a held candidate must record a hold reason")
        expected = negation_review_payload(self)
        if self.payload_sha256 != hashlib.sha256(canonical_json(expected).encode()).hexdigest():
            raise ValueError("payload hash does not match the canonical review payload")
        return self


def annotation_signature(expression: PhenotypeExpression) -> tuple[str, str]:
    """Return the canonical annotation-expression signature and its hash.

    This mirrors :pyattr:`ReviewDecision.signature_sha256` so a reviewer copying the admitted
    expression produces exactly this hash and the materializer can bind consensus to the runner
    candidate byte-for-byte.
    """

    proposed = ProposedSignature(kind="annotation_expression", expression=expression)
    normalized = canonical_json(
        proposed.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    )
    return normalized, hashlib.sha256(normalized.encode()).hexdigest()


def negation_review_payload(candidate: "NegationCandidate") -> dict[str, Any]:
    """Canonical runner-owned payload embedded in the reviewed context and frozen per candidate."""

    payload: dict[str, Any] = {
        "protocol": NEGATION_PROTOCOL,
        "classification": candidate.classification,
        "negation_scope": candidate.negation_scope,
        "admission": candidate.admission,
        "quality_pato_id": candidate.quality_pato_id,
        "surface_form": candidate.surface_form,
        "span": [candidate.span_start, candidate.span_end],
        "cue_text": candidate.cue_text,
        "cue_span": [candidate.cue_start, candidate.cue_end],
        "source_text": candidate.source_text,
        "source_span": [candidate.source_start, candidate.source_end],
        "clear_span": [candidate.clear_span[0], candidate.clear_span[1]],
        "instruction": (
            "Copy admitted_expression EXACTLY as an annotation_expression, or hold. Do not alter "
            "identifiers, offsets, scope, or negation. Negated comparators are upper bounds, not "
            "logical complements; never flatten coordinated, hedged, scope-restricted, or "
            "false-cue negation into atomic quality negation."
        ),
    }
    if candidate.hold_reason:
        payload["hold_reason"] = candidate.hold_reason
    if candidate.bearer_id:
        payload["bearer_id"] = candidate.bearer_id
    if candidate.bearer_text:
        payload["bearer_text"] = candidate.bearer_text
    if candidate.bearer_method:
        payload["bearer_method"] = candidate.bearer_method
    if candidate.admitted_expression is not None:
        payload["admitted_expression"] = candidate.admitted_expression.model_dump(
            mode="json", exclude_none=True, exclude_defaults=True
        )
        payload["admitted_signature_sha256"] = candidate.admitted_signature_sha256
    return payload


def _clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(0, start - _CLAUSE_WINDOW)
    for boundary in _CLAUSE_BOUNDARY:
        found = text.rfind(boundary, left, start)
        if found >= 0:
            left = max(left, found + 1)
    right = len(text)
    for boundary in _CLAUSE_BOUNDARY + ",":
        found = text.find(boundary, end, min(len(text), end + _CLAUSE_WINDOW))
        if found >= 0:
            right = min(right, found)
    while left < start and text[left] in " \t":
        left += 1
    return left, right


def _rightmost_cue(text: str, clause_left: int, span_start: int) -> re.Match[str] | None:
    pre = text[clause_left:span_start]
    match = None
    for candidate in NEGATION_EVIDENCE.finditer(pre):
        match = candidate
    return match


def _has_intervening_target(between: str) -> bool:
    """True when a distinct content word sits between the cue and the reviewed quality."""

    for word in _WORD.findall(between):
        lowered = word.casefold()
        if lowered in _CONNECTOR_WORDS:
            continue
        if _DEGREE_ADVERB.fullmatch(word) or _FREQUENCY_ADVERB.fullmatch(word):
            continue
        return True
    return False


def _numeric_upper_bound(
    text: str, language: str, span_start: int, span_end: int, pato_id: str
) -> Any | None:
    for row in parse_measurements(text, language or ""):
        if (
            getattr(row, "attribute_id", "") == pato_id
            and getattr(row, "value_high", None) is not None
            and getattr(row, "value_low", None) is None
            and not (row.end <= span_start or row.start >= span_end)
        ):
            return row
    return None


def _major_clause_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Return the punctuation-bounded member around a span, retaining comma coordination."""

    boundaries = ";:.!?()\n"
    left = 0
    for boundary in boundaries:
        found = text.rfind(boundary, 0, start)
        if found >= 0:
            left = max(left, found + 1)
    right = len(text)
    for boundary in boundaries:
        found = text.find(boundary, end)
        if found >= 0:
            right = min(right, found)
    return left, right


def _same_quality_sibling(text: str, start: int, end: int) -> bool:
    """Detect a coordinated positive sibling of the exact reviewed value.

    ``robust stems, not branched and thinner stems ... branched`` describes two subsets.  A plain
    negative assertion on every stem would discard that restriction even though the cue itself is
    adjacent to the marked value.
    """

    major_left, major_right = _major_clause_bounds(text, start, end)
    surface = text[start:end].strip()
    if not surface:
        return False
    tail = text[end : min(major_right, end + 160)]
    return bool(
        re.search(
            rf"\b(?:and|et|or|ou)\b[^;:.!?()]{{0,128}}(?<!\w){re.escape(surface)}(?!\w)",
            tail,
            re.IGNORECASE,
        )
    )


def classify_span(record: dict[str, Any], span: dict[str, Any]) -> dict[str, Any]:
    """Classify a single ``negated_context`` span without resolving its bearer.

    Returns a dictionary carrying the classification, scope, governing cue evidence, and the source
    span (cue → quality) used for a candidate assertion.  The result is intentionally conservative:
    anything coordinated, hedged, scope-restricted, degree/frequency-modified, or governed by a
    neighbouring word is held rather than flattened.
    """

    text = str(record.get("text", "") or "")
    start, end = int(span["start"]), int(span["end"])
    pato_id = str(span.get("candidate_pato_id", "") or "")
    language = str(record.get("language", "") or "")
    clause_left, clause_right = _clause_bounds(text, start, end)

    upper = _numeric_upper_bound(text, language, start, end, pato_id)
    bound_match = None
    for candidate in UPPER_BOUND_EVIDENCE.finditer(text[clause_left:clause_right]):
        bound_match = candidate
    if upper is not None and bound_match is not None:
        cue_start = clause_left + bound_match.start()
        cue_end = clause_left + bound_match.end()
        # The residual corpus contains a repeated ``non-stipitate or up to N long stipitate``
        # family and several ``with or without PART up to N`` descriptions.  The bound applies to
        # an optional/nested part, not to the enclosing record organ.  Detect coordination in a
        # tight window around the parsed measurement before offering a numeric candidate.
        major_left, major_right = _major_clause_bounds(text, start, end)
        numeric_window = text[
            max(major_left, int(upper.start) - 96) : min(major_right, int(upper.end) + 40)
        ]
        if _DISJUNCTION_CUE.search(numeric_window) or _OPTIONAL_BOUND_SCOPE.search(numeric_window):
            return _hold_result(
                text,
                cue_start,
                start,
                end,
                "mixed_negation_disjunction",
                "coordinated_optional_numeric_bearer",
                cue_start,
                cue_end,
            )
        source_start = min(cue_start, int(upper.start))
        source_end = max(end, int(upper.end))
        return {
            "classification": "numeric_upper_bound",
            "negation_scope": "numeric_bound",
            "cue_text": text[cue_start:cue_end],
            "cue_start": cue_start,
            "cue_end": cue_end,
            "source_text": text[source_start:source_end],
            "source_start": source_start,
            "source_end": source_end,
            "measurement": upper,
        }

    cue = _rightmost_cue(text, clause_left, start)
    if cue is None:
        # The record-level ``negated_context`` tag did not originate in this clause: the cue governs
        # a different span. Hold as a false cue rather than inventing negation for this quality.
        return _hold_result(text, clause_left, start, end, "false_cue", "cue_not_in_clause")

    cue_start = clause_left + cue.start()
    cue_end = clause_left + cue.end()
    between = text[cue_end:start]
    governed = text[cue_start:end]
    # Coordination and exceptions are scanned over the whole governing clause, because the hedge can
    # sit either side of the cue ("peu ou pas ramifiée", "non ramifiée ou légèrement ramifiée").
    clause_window = text[clause_left:clause_right]

    if _DISJUNCTION_CUE.search(clause_window):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "mixed_negation_disjunction",
            "coordinated_or_hedged_negation",
            cue_start,
            cue_end,
        )
    if _EXCEPTION_CUE.search(clause_window):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "scope_restricted_or_exceptive",
            cue_start,
            cue_end,
        )
    if _DEGREE_ADVERB.search(between):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "negation_scopes_degree_modifier",
            cue_start,
            cue_end,
        )
    if _FREQUENCY_ADVERB.search(between):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "frequency_modified_negation",
            cue_start,
            cue_end,
        )
    prefix = text[max(clause_left, cue_start - 40) : cue_start]
    if _FREQUENCY_ADVERB.search(prefix):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "frequency_modified_negation",
            cue_start,
            cue_end,
        )
    if _CONDITIONAL_PREFIX.search(prefix):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "conditional_negation_scope",
            cue_start,
            cue_end,
        )
    if _CORRECTION_PREFIX.search(prefix):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "contrastive_or_metalinguistic_negation",
            cue_start,
            cue_end,
        )
    if _MALFORMED_NEGATION_PREFIX.search(prefix):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "malformed_or_truncated_negation_context",
            cue_start,
            cue_end,
        )
    if _COMPOUND_TAIL.search(text[end:clause_right]):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "negation_scopes_compound_quality",
            cue_start,
            cue_end,
        )
    if _SCOPED_POST_QUALITY.search(text[end:clause_right]):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "post_quality_scope_modifier",
            cue_start,
            cue_end,
        )
    if _same_quality_sibling(text, start, end):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "compound_scope",
            "negation_restricted_to_coordinated_subset",
            cue_start,
            cue_end,
        )
    if _has_intervening_target(between):
        # ``sans poils blancs`` / ``without erect hairs`` is an absence of a qualified part. The
        # intervening noun is therefore the absent bearer, not a false cue. Numeric spans and
        # coordinated sibling descriptions remain false cues (``without scales 2 mm thick``;
        # ``sans gibbosités et pubescent``).
        absence_cue = bool(_ABSENCE_CUE.fullmatch(text[cue_start:cue_end]))
        numeric_surface = bool(re.search(r"\d", text[start:end]))
        coordinated = bool(re.search(r"\b(?:and|et|or|ou|nor|ni)\b", between, re.I))
        if not absence_cue or numeric_surface or coordinated:
            return _hold_result(
                text,
                cue_start,
                start,
                end,
                "false_cue",
                "cue_governs_neighbouring_word",
                cue_start,
                cue_end,
            )

    source_text = text[cue_start:end]
    if not NEGATION_EVIDENCE.search(source_text):
        return _hold_result(
            text,
            cue_start,
            start,
            end,
            "undetermined",
            "negation_cue_binding_unverified",
            cue_start,
            cue_end,
        )

    classification = "bearer_absence" if _ABSENCE_CUE.search(governed) else "quality_negation"
    return {
        "classification": classification,
        "negation_scope": _SCOPE_FOR[classification],
        "cue_text": text[cue_start:cue_end],
        "cue_start": cue_start,
        "cue_end": cue_end,
        "source_text": source_text,
        "source_start": cue_start,
        "source_end": end,
        "measurement": None,
    }


def _hold_result(
    text: str,
    fallback_cue_start: int,
    start: int,
    end: int,
    classification: str,
    hold_reason: str,
    cue_start: int | None = None,
    cue_end: int | None = None,
) -> dict[str, Any]:
    if cue_start is None:
        cue_start, cue_end = start, end
    return {
        "classification": classification,
        "negation_scope": "none",
        "hold_reason": hold_reason,
        "cue_text": text[cue_start:cue_end],
        "cue_start": cue_start,
        "cue_end": cue_end,
        "source_text": text[min(cue_start, start) : end],
        "source_start": min(cue_start, start),
        "source_end": end,
        "measurement": None,
    }


def _resolve_bearer(
    record: dict[str, Any],
    span: dict[str, Any],
    clause_left: int,
    clause_right: int,
    *,
    classification: str,
    po_ids: frozenset[str],
    blocked: frozenset[tuple[str, str]],
    pato_id: str,
    exact_po_forms: dict[tuple[str, ...], set[str]],
    candidate_po_forms: dict[tuple[str, ...], set[str]],
) -> tuple[str, str, int | None, int | None, str, str]:
    """Return an unambiguous same-clause bearer, or an empty id with a hold reason.

    Reuse the production context-recovery binders: one unique PO lexical form is preferred, with
    the audited baseline local/heading mapping as a fallback for quality and numeric assertions.
    Absence requires an explicit lexical part bearer; falling back to the outer organ would change
    ``without white hairs`` into absence of a non-white leaf. Conflicting binders fail closed.
    """

    del clause_left, clause_right  # binding helpers independently enforce their local windows
    lexical = _lexical_bearer(record, span, exact_po_forms, candidate_po_forms)
    baseline = None if classification == "bearer_absence" else _baseline_bearer(record, span)
    if lexical is not None and baseline is not None and lexical.po_id != baseline.po_id:
        return "", "", None, None, "", "bearer_ambiguous"
    match = lexical or baseline
    if match is None:
        reason = (
            "absent_part_bearer_unresolved"
            if classification == "bearer_absence"
            else "bearer_unresolved"
        )
        return "", "", None, None, "", reason
    text = str(record.get("text", "") or "")
    # A lexical noun following the value is a bearer only in a direct adjective–noun construction
    # (``not black petals``).  A downstream noun reached through a predicate or preposition, as in
    # ``non ramifiée couronnée par une rosette``, cannot steal the negated quality.
    if lexical is not None and match is lexical and int(lexical.start) >= int(span["end"]):
        bridge = text[int(span["end"]) : int(lexical.start)]
        if not re.fullmatch(
            r"\s*(?:(?:the|a|an|le|la|les|un|une|des|du|de\s+la)\s+)?",
            bridge,
            re.IGNORECASE,
        ):
            return "", "", None, None, "", "bearer_not_directly_governed"
    bearer = str(match.po_id)
    if bearer not in po_ids:
        return "", "", None, None, "", "bearer_not_in_catalog"
    if (bearer, pato_id) in blocked:
        return "", "", None, None, "", "bearer_quality_blocklisted"
    method = str(match.method)
    bearer_text = str(match.surface)
    # ``organ_heading`` is a non-verbatim record-field basis. The underlying helper intentionally
    # uses the quality offsets as a sentinel; never publish those as fabricated bearer offsets.
    if method == "organ_heading":
        return bearer, bearer_text, None, None, method, ""
    a_start, a_end = int(match.start), int(match.end)
    if not (0 <= a_start < a_end <= len(text)) or text[a_start:a_end] != bearer_text:
        return "", "", None, None, "", "bearer_offset_mismatch"
    return bearer, bearer_text, a_start, a_end, method, ""


def _admitted_expression(
    classification: str, bearer_id: str, pato_id: str, measurement: Any | None
) -> PhenotypeExpression:
    if classification == "numeric_upper_bound":
        assert measurement is not None
        return PhenotypeExpression(
            bearer_id=bearer_id,
            quality_id=pato_id,
            negated=False,
            value_low=None,
            value_high=float(measurement.value_high),
            value_high_inclusive=bool(getattr(measurement, "value_high_inclusive", True)),
            unit=str(getattr(measurement, "unit_text", "") or ""),
        )
    return PhenotypeExpression(bearer_id=bearer_id, quality_id=pato_id, negated=True)


def _segment_key(record: dict[str, Any]) -> SegmentKey:
    return (
        str(record.get("source", "") or ""),
        str(record.get("source_id", "") or ""),
        int(record.get("source_segment_index", 0) or 0),
        str(record.get("taxon", "") or ""),
    )


def _identity(record: dict[str, Any], span: dict[str, Any], ordinal: int) -> tuple[Any, ...]:
    return (
        NEGATION_PROTOCOL,
        record.get("source", ""),
        record.get("source_id", ""),
        int(record.get("source_segment_index", 0) or 0),
        int(span["start"]),
        int(span["end"]),
        str(span.get("surface_form", "") or ""),
        str(span.get("candidate_pato_id", "") or ""),
        str(span.get("extractor", "") or ""),
        ordinal,
    )


def _build_records(
    stage15_path: Path,
    *,
    po_ids: frozenset[str],
    blocked: frozenset[tuple[str, str]],
    exact_po_forms: dict[tuple[str, ...], set[str]],
    candidate_po_forms: dict[tuple[str, ...], set[str]],
) -> tuple[list[Occurrence], list[NegationCandidate], Counter[str]]:
    occurrences: list[Occurrence] = []
    candidates: list[NegationCandidate] = []
    counts: Counter[str] = Counter()
    seen_identity: Counter[tuple[Any, ...]] = Counter()
    with stage15_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{stage15_path}:{line_number}: invalid JSON") from error
            if not isinstance(record, dict):
                raise ValueError(f"{stage15_path}:{line_number}: record is not an object")
            text = str(record.get("text", "") or "")
            for span in record.get("unresolved_spans", []) or []:
                if not isinstance(span, dict) or span.get("reason") != REVIEW_REASON:
                    continue
                start, end = int(span["start"]), int(span["end"])
                surface = str(span.get("surface_form", "") or "")
                pato_id = str(span.get("candidate_pato_id", "") or "")
                if text[start:end] != surface:
                    raise ValueError(
                        f"{stage15_path}:{line_number}: negated span not verbatim at {start}:{end}"
                    )
                if not pato_id.startswith("PATO_"):
                    raise ValueError(
                        f"{stage15_path}:{line_number}: negated span lacks a PATO candidate"
                    )
                base = _identity(record, span, 0)[:-1]
                ordinal = seen_identity[base]
                seen_identity[base] += 1
                identity = (*base, ordinal)
                occurrence_id = stable_id("occ", identity)
                cluster_id = stable_id("cluster", identity)

                result = classify_span(record, span)
                classification = result["classification"]
                admission = "hold"
                hold_reason = result.get("hold_reason", "")
                bearer_id = bearer_text = ""
                bearer_start = bearer_end = None
                bearer_method = ""
                admitted = None
                admitted_sha = ""
                scope = result["negation_scope"]
                if classification in ADMISSIBLE:
                    clause_left, clause_right = _clause_bounds(text, start, end)
                    (
                        bearer_id,
                        bearer_text,
                        bearer_start,
                        bearer_end,
                        bearer_method,
                        bearer_hold,
                    ) = _resolve_bearer(
                        record,
                        span,
                        clause_left,
                        clause_right,
                        classification=classification,
                        po_ids=po_ids,
                        blocked=blocked,
                        pato_id=pato_id,
                        exact_po_forms=exact_po_forms,
                        candidate_po_forms=candidate_po_forms,
                    )
                    if bearer_id:
                        # Absence evidence must retain the explicit absent-part bearer even when it
                        # follows the colour/quality span (``no white hairs``).
                        if classification == "bearer_absence" and bearer_start is not None:
                            result["source_start"] = min(result["source_start"], bearer_start)
                            result["source_end"] = max(result["source_end"], bearer_end)
                            result["source_text"] = text[
                                result["source_start"] : result["source_end"]
                            ]
                        admitted = _admitted_expression(
                            classification, bearer_id, pato_id, result.get("measurement")
                        )
                        _, admitted_sha = annotation_signature(admitted)
                        admission = "admit"
                        scope = _SCOPE_FOR[classification]
                    else:
                        admission = "hold"
                        hold_reason = bearer_hold
                        scope = "none"
                counts[f"{classification}:{admission}"] += 1

                fingerprint_payload = {
                    "protocol": NEGATION_PROTOCOL,
                    "occurrence_id": occurrence_id,
                    "classification": classification,
                    "admission": admission,
                    "negation_scope": scope,
                    "quality_pato_id": pato_id,
                    "span": [start, end],
                    "source_span": [result["source_start"], result["source_end"]],
                    "admitted_signature": admitted_sha,
                    "bearer_id": bearer_id,
                }
                fingerprint = hashlib.sha256(
                    canonical_json(fingerprint_payload).encode()
                ).hexdigest()

                # Build the candidate first so its canonical payload can be embedded in the context.
                fields = dict(
                    occurrence_id=occurrence_id,
                    cluster_id=cluster_id,
                    source=str(record.get("source", "") or ""),
                    source_id=str(record.get("source_id", "") or ""),
                    source_segment_index=int(record.get("source_segment_index", 0) or 0),
                    taxon=str(record.get("taxon", "") or ""),
                    language=str(record.get("language", "") or ""),
                    organ=str(record.get("organ", "") or ""),
                    span_start=start,
                    span_end=end,
                    surface_form=surface,
                    quality_pato_id=pato_id,
                    classification=classification,
                    admission=admission,
                    negation_scope=scope,
                    hold_reason=hold_reason,
                    cue_text=result["cue_text"],
                    cue_start=result["cue_start"],
                    cue_end=result["cue_end"],
                    bearer_id=bearer_id,
                    bearer_text=bearer_text,
                    bearer_start=bearer_start,
                    bearer_end=bearer_end,
                    bearer_method=bearer_method,
                    source_text=result["source_text"],
                    source_start=result["source_start"],
                    source_end=result["source_end"],
                    admitted_expression=admitted,
                    admitted_signature_sha256=admitted_sha,
                    clear_span=(start, end),
                )
                payload = negation_review_payload(_ProxyCandidate(fields))
                payload_sha = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
                candidate = NegationCandidate(payload_sha256=payload_sha, **fields)
                candidates.append(candidate)

                marked = _review_context(text, start, end)
                context = f"{marked}\n\n{PAYLOAD_MARKER}\n{canonical_json(payload)}"
                evidence_id = stable_id(
                    "evidence", (occurrence_id, cluster_id, fingerprint, context)
                )
                occurrences.append(
                    Occurrence(
                        occurrence_id=occurrence_id,
                        evidence_id=evidence_id,
                        cluster_id=cluster_id,
                        semantic_fingerprint=fingerprint,
                        source=candidate.source,
                        source_id=candidate.source_id,
                        source_segment_index=candidate.source_segment_index,
                        taxon=candidate.taxon,
                        organ=candidate.organ,
                        language=candidate.language,
                        segment_char_start=int(record.get("char_start", 0) or 0),
                        segment_char_end=int(record.get("char_end", len(text)) or len(text)),
                        span_start=start,
                        span_end=end,
                        surface_form=surface,
                        normalized_form=normalized_text(surface),
                        reason=REVIEW_REASON,
                        candidate_pato_id=pato_id,
                        pending_bearer=bearer_id,
                        promoted_po_ids=(),
                        extractor=str(span.get("extractor", "") or ""),
                        context=context,
                    )
                )
    order = sorted(range(len(occurrences)), key=lambda index: occurrences[index].cluster_id)
    occurrences = [occurrences[index] for index in order]
    candidates = [candidates[index] for index in order]
    ids = [row.occurrence_id for row in occurrences]
    if len(ids) != len(set(ids)):
        raise ValueError("negation occurrence identifier collision")
    return occurrences, candidates, counts


class _ProxyCandidate:
    """Lightweight attribute view over candidate field values for payload hashing before build."""

    def __init__(self, fields: dict[str, Any]) -> None:
        self._fields = fields

    def __getattr__(self, name: str) -> Any:
        try:
            return self._fields[name]
        except KeyError as error:  # pragma: no cover - defensive
            raise AttributeError(name) from error


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
    )


def _load_catalog(
    po_lexicon_path: Path,
    combinations_path: Path,
    po_obo_path: Path,
    reviewed_bearers_path: Path,
) -> tuple[
    frozenset[str],
    frozenset[tuple[str, str]],
    dict[tuple[str, ...], set[str]],
    dict[tuple[str, ...], set[str]],
]:
    from flopo2.verify.gates import load_catalog_ids, load_combinations

    po_ids = frozenset(load_catalog_ids(po_lexicon_path))
    combos = load_combinations(combinations_path)
    blocked = frozenset(
        key
        for key, value in combos.items()
        if getattr(value, "status", "") in {"blocked", "blocklisted", "invalid"}
    )
    return (
        po_ids,
        blocked,
        _po_exact_forms(po_obo_path, reviewed_bearers_path),
        _po_forms(po_lexicon_path, reviewed_bearers_path),
    )


def build_negation_inventory(
    *,
    stage15_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    candidate_path: Path,
    report_path: Path,
    manifest_path: Path,
    ontology_paths: Iterable[Path],
    prompt_paths: dict[str, Path],
    models: Iterable[ModelSpec],
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
    po_obo_path: Path = Path("ont/plant_ontology.obo"),
    reviewed_bearers_path: Path = Path("config/reviewed_local_bearers.tsv"),
    created_at: datetime | None = None,
) -> CampaignManifest:
    """Freeze one review item per ``negated_context`` span with a runner-owned negation candidate."""

    ontology_paths = tuple(ontology_paths)
    _validate_distinct_paths(
        stage15_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        candidate_path,
        report_path,
        manifest_path,
        *ontology_paths,
        *prompt_paths.values(),
    )
    frozen_paths = {path.resolve() for path in ontology_paths}
    required_binder_inputs = {
        po_lexicon_path.resolve(),
        combinations_path.resolve(),
        po_obo_path.resolve(),
        reviewed_bearers_path.resolve(),
    }
    if not required_binder_inputs.issubset(frozen_paths):
        raise ValueError("all deterministic bearer inputs must be frozen ontology artifacts")
    po_ids, blocked, exact_po_forms, candidate_po_forms = _load_catalog(
        po_lexicon_path, combinations_path, po_obo_path, reviewed_bearers_path
    )
    occurrences, candidates, counts = _build_records(
        stage15_path,
        po_ids=po_ids,
        blocked=blocked,
        exact_po_forms=exact_po_forms,
        candidate_po_forms=candidate_po_forms,
    )
    clusters = [_cluster(row) for row in occurrences]

    # The frozen candidate inventory is content-addressed and bound into the manifest as a source.
    candidate_payload = "".join(
        row.model_dump_json(exclude_none=True) + "\n"
        for row in sorted(candidates, key=lambda row: row.occurrence_id)
    )
    if candidate_path.exists() and candidate_path.read_text(encoding="utf-8") != candidate_payload:
        raise FileExistsError(f"refusing to replace changed candidate inventory: {candidate_path}")
    atomic_write_text(candidate_path, candidate_payload)
    candidate_hash = sha256_file(candidate_path)

    input_hash = sha256_file(stage15_path)
    ontology_hashes = tuple(sha256_file(path) for path in ontology_paths)
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
        "sources": [candidate_hash.sha256],
    }
    campaign_id = stable_id("campaign", campaign_seed)
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
                raise ValueError(f"immutable campaign artifact no longer matches: {path}")
        return existing
    for path in (occurrence_path, cluster_path, evidence_path, report_path):
        if path.exists():
            raise FileExistsError(f"refusing to replace pre-existing campaign artifact: {path}")

    evidence_rows = [
        *(_evidence_record(row) for row in occurrences),
        *(_reference_record(row, "ontology") for row in ontology_hashes),
        _reference_record(candidate_hash, "source_inventory"),
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
            authorities=(),
            sources=(candidate_hash,),
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
        classification_counts: Counter[str] = Counter()
        admission_counts: Counter[str] = Counter()
        for candidate in candidates:
            classification_counts[candidate.classification] += 1
            admission_counts[candidate.admission] += 1
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "protocol": NEGATION_PROTOCOL,
            "campaign_id": manifest.campaign_id,
            "stage15": input_hash.model_dump(mode="json"),
            "negated_context_spans": len(occurrences),
            "classifications": dict(sorted(classification_counts.items())),
            "admissions": dict(sorted(admission_counts.items())),
            "classification_admission": dict(sorted(counts.items())),
            "candidate_inventory": candidate_hash.model_dump(mode="json"),
            "occurrences": manifest.occurrences.model_dump(mode="json"),
            "clusters": manifest.clusters.model_dump(mode="json"),
            "evidence_registry": manifest.evidence_registry.model_dump(mode="json"),
            "conservation": {
                "one_cluster_per_occurrence": len(occurrences) == len(clusters),
                "all_spans_classified": sum(classification_counts.values()) == len(occurrences),
                "stage15_exact_span_rebinding": True,
                "admission_requires_admissible_classification": all(
                    candidate.classification in ADMISSIBLE
                    for candidate in candidates
                    if candidate.admission == "admit"
                ),
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
    parser.add_argument("--stage15", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, action="append", required=True)
    parser.add_argument("--prompt", nargs=2, action="append", required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--combinations", type=Path, default=Path("config/valid_combinations.tsv"))
    parser.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument(
        "--reviewed-bearers",
        type=Path,
        default=Path("config/reviewed_local_bearers.tsv"),
    )
    parser.add_argument("--created-at")
    args = parser.parse_args()
    raw_models = json.loads(args.models.read_text(encoding="utf-8"))
    models = [model_spec(**row) for row in raw_models if row.get("role") == "reviewer"]
    created_at = (
        datetime.fromisoformat(args.created_at.replace("Z", "+00:00")) if args.created_at else None
    )
    manifest = build_negation_inventory(
        stage15_path=args.stage15,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        candidate_path=args.candidates,
        report_path=args.report,
        manifest_path=args.manifest,
        ontology_paths=args.ontology,
        prompt_paths={key: Path(value) for key, value in args.prompt},
        models=models,
        po_lexicon_path=args.po_lexicon,
        combinations_path=args.combinations,
        po_obo_path=args.po_obo,
        reviewed_bearers_path=args.reviewed_bearers,
        created_at=created_at,
    )
    print(manifest.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
