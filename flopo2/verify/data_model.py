"""Validate extracted FLOPO JSONL against the trait data-model contract.

The pipeline uses compact wire names (``po_id``/``pato_id``), while the generated LinkML
Pydantic model uses the descriptive names ``anatomical_entity``/``quality``.  This validator
adapts the wire representation to that generated model and then applies the invariants that are
necessarily cross-record or source-dependent: ontology membership, verbatim provenance spans,
categorical-value logic, measurement ranges, composition/gate consistency, and terminology
mention offsets.

Examples::

    python -m flopo2.verify.data_model scratchpad/flora-gated.jsonl --stage gated
    python -m flopo2.verify.data_model scratchpad/flora-gated.jsonl \
        --stage gated --db scratchpad/flora.sqlite
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flopo2.extract.compose import _clause_around
from flopo2.extract.measurement import is_supported_length_unit
from flopo2.owl.annotation_class import ANNOTATION_CLASS_BASE, annotation_class_iri
from flopo2.schema.flopo_trait_models import (
    SourceStatement,
    TermCandidate,
    TermMention,
    TraitAssertion,
    TraitExtraction,
    UnresolvedTraitSpan,
)


PO_ID = re.compile(r"^PO(?::|_)\d+$")
PATO_ID = re.compile(r"^PATO(?::|_)\d+$")
FLOPO_ID = re.compile(r"^FLOPO(?::|_)\d+$")
VALUE_PREFIXES = ("PATO_", "PATO:", "FLOPO_", "FLOPO:")
VALID_COMPOSITION_STATUSES = {"accept", "review"}
VALID_GATE_STATUSES = {"accepted", "review", "blocked"}
MANUAL_REVIEW_PATO_IDS = {"PATO_0000389", "PATO_0000455", "PATO_0002147"}
# Reuse the gate lexicon so the data-model validator and the gate never drift on which negation or
# upper-bound cues count as source evidence.
from flopo2.verify.gates import NEGATION_EVIDENCE, UPPER_BOUND_EVIDENCE  # noqa: E402


@dataclass(frozen=True)
class ValidationIssue:
    line: int
    assertion: int | None
    code: str
    message: str


def _load_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {row.get("id", "") for row in csv.DictReader(fh, delimiter="\t") if row.get("id")}


def _load_flopo_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    identifiers: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            value = row.get("flopo_id") or row.get("id") or row.get("flopo_iri") or ""
            value = value.rsplit("/", 1)[-1].replace(":", "_")
            if FLOPO_ID.fullmatch(value):
                identifiers.add(value)
    return identifiers


def _load_attribute_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {
            row.get("id", "")
            for row in csv.DictReader(fh, delimiter="\t")
            if "attribute_slim" in (row.get("slim") or "").split("|")
        }


def _has_real_disjunction(source_text: str) -> bool:
    source_text = re.sub(
        r"\bmore\s+or\s+less\b|\bplus\s+ou\s+moins\b",
        "",
        source_text,
        flags=re.IGNORECASE,
    )
    return re.search(r"\b(?:or|ou)\b", source_text, re.IGNORECASE) is not None


def _optional(value: Any) -> Any:
    """Translate the wire format's empty-string sentinel to LinkML's absent value."""

    return None if value == "" else value


def _int_span(start: Any, end: Any) -> bool:
    """True when both offsets are usable integers (not bools/None)."""

    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
    )


def _valid_span(text: str, start: Any, end: Any, expected: str) -> bool:
    """True when ``[start, end)`` are ordered, in range, and select ``expected`` verbatim."""

    return _int_span(start, end) and 0 <= start <= end <= len(text) and text[start:end] == expected


def _phrase_occurrences(text: str, phrase: str, *, case_insensitive: bool = False) -> int:
    """Count complete-token occurrences without conflating e.g. leaf and leaflet."""

    if not phrase:
        return 0
    left_guard = r"(?<!\w)" if phrase[0].isalnum() or phrase[0] == "_" else ""
    right_guard = r"(?!\w)" if phrase[-1].isalnum() or phrase[-1] == "_" else ""
    flags = re.IGNORECASE if case_insensitive else 0
    return len(re.findall(left_guard + re.escape(phrase) + right_guard, text, flags))


def _covers_evidence(
    *,
    text_value: str,
    span: tuple[Any, Any],
    statement_start: int,
    statement_end: int,
    statement_text: str,
    segment_text: str,
    case_insensitive: bool = False,
) -> str | None:
    """Classify one evidence phrase against a linked statement's ``[start, end)`` interval.

    Exact offsets are authoritative: an interval outside the statement is reported as ``"outside"``
    regardless of whether the same wording repeats inside it.  Invalid or half-populated offsets
    are ``"invalid"`` and never fall back to a coincidental duplicate.  Without offsets the phrase
    is resolved occurrence-safely inside the statement text: a unique occurrence is ``covered``
    (``None``), a repeated occurrence is ``"ambiguous"`` (never silently anchored to the first
    substring), and an absent phrase is ``"omitted"``.
    """

    if not text_value:
        return None
    start, end = span
    if start is not None or end is not None:
        if not _valid_span(segment_text, start, end, text_value):
            return "invalid"
        if statement_start <= int(start) and int(end) <= statement_end:
            return None
        return "outside"
    if case_insensitive:
        occurrences = len(re.findall(re.escape(text_value), statement_text, re.IGNORECASE))
    else:
        occurrences = statement_text.count(text_value)
    if occurrences == 1:
        return None
    if occurrences > 1:
        return "ambiguous"
    return "omitted"


def _pydantic_assertion(assertion: dict[str, Any]) -> TraitAssertion:
    values = assertion.get("value_terms", assertion.get("value_term_ids", []))
    payload = {
        "phenotype_class_iri": _optional(assertion.get("phenotype_class_iri")),
        "anatomical_entity": assertion.get("po_id", ""),
        "quality": assertion.get("pato_id", ""),
        "trait": _optional(assertion.get("trait")),
        "raw_entity_text": _optional(assertion.get("raw_entity_text")),
        "raw_quality_text": _optional(assertion.get("raw_quality_text")),
        "bearer_start": assertion.get("bearer_start"),
        "bearer_end": assertion.get("bearer_end"),
        "entity_mention_id": _optional(assertion.get("entity_mention_id")),
        "quality_mention_ids": assertion.get("quality_mention_ids") or None,
        "value_text": _optional(assertion.get("value_text")),
        "value_operator": assertion.get("value_operator") or "atomic",
        "value_terms": values or None,
        "bearer_context_qualities": assertion.get("bearer_context_qualities") or None,
        "developmental_stage_contexts": (
            assertion.get("developmental_stage_contexts") or None
        ),
        "developmental_stage_operator": (
            assertion.get("developmental_stage_operator") or "atomic"
        ),
        "value_low": assertion.get("value_low"),
        "value_high": assertion.get("value_high"),
        "value_low_inclusive": bool(assertion.get("value_low_inclusive", True)),
        "value_high_inclusive": bool(assertion.get("value_high_inclusive", True)),
        "unit": _optional(assertion.get("unit")),
        "modifier": _optional(assertion.get("modifier")),
        "source_statement_id": _optional(assertion.get("source_statement_id")),
        "frequency_qualifier": assertion.get("frequency_qualifier") or "unspecified",
        "epistemic_modality": assertion.get("epistemic_modality") or "asserted",
        "value_qualifier": assertion.get("value_qualifier") or "exact",
        "degree_qualifier": assertion.get("degree_qualifier") or "unmodified",
        "modality_text": _optional(assertion.get("modality_text")),
        "modality_start": assertion.get("modality_start"),
        "modality_end": assertion.get("modality_end"),
        "season_contexts": assertion.get("season_contexts") or None,
        "season_operator": assertion.get("season_operator") or "atomic",
        "negated": bool(assertion.get("negated", False)),
        "negation_scope": _optional(assertion.get("negation_scope")),
        "cardinality": _optional(assertion.get("cardinality")),
        "source_text": assertion.get("source_text", ""),
        "source_start": assertion.get("source_start"),
        "source_end": assertion.get("source_end"),
        "extractor": _optional(assertion.get("extractor")),
        "confidence": assertion.get("confidence"),
        "normalization_status": _optional(assertion.get("normalization_status")),
        "mapping_provenance": assertion.get("mapping_provenance") or None,
    }
    return TraitAssertion.model_validate(payload)


def _pydantic_mention(mention: dict[str, Any]) -> TermMention:
    """Validate schema fields while tolerating internal retrieval-score diagnostics."""

    candidate_fields = set(TermCandidate.model_fields)
    mention_fields = set(TermMention.model_fields)
    payload = {key: value for key, value in mention.items() if key in mention_fields}
    payload["candidates"] = [
        {key: value for key, value in candidate.items() if key in candidate_fields}
        for candidate in mention.get("candidates", []) or []
    ]
    if not payload["candidates"]:
        payload["candidates"] = None
    if payload.get("logical_operator") == "":
        payload["logical_operator"] = None
    return TermMention.model_validate(payload)


def _add(
    issues: list[ValidationIssue],
    line: int,
    code: str,
    message: str,
    assertion: int | None = None,
) -> None:
    issues.append(ValidationIssue(line, assertion, code, message))


def _validate_mention(
    mention: Any,
    text: str,
    line_number: int,
    mention_ids: set[str],
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(mention, dict):
        _add(issues, line_number, "mention_not_object", "term mention must be an object")
        return
    try:
        parsed = _pydantic_mention(mention)
    except Exception as exc:
        _add(issues, line_number, "mention_schema", str(exc))
        return

    if parsed.mention_id in mention_ids:
        _add(issues, line_number, "duplicate_mention_id", parsed.mention_id)
    mention_ids.add(parsed.mention_id)
    if parsed.start < 0 or parsed.end < parsed.start or parsed.end > len(text):
        _add(
            issues,
            line_number,
            "mention_offsets",
            f"{parsed.mention_id}: [{parsed.start}, {parsed.end}) outside text length {len(text)}",
        )
    elif text[parsed.start : parsed.end] != parsed.surface_form:
        _add(
            issues,
            line_number,
            "mention_not_verbatim",
            f"{parsed.mention_id}: offsets do not select surface_form",
        )
    for candidate in parsed.candidates or []:
        if not math.isfinite(candidate.score) or not 0.0 <= candidate.score <= 1.0:
            _add(
                issues,
                line_number,
                "candidate_score",
                f"{parsed.mention_id}: score {candidate.score!r} is outside [0,1]",
            )


def _validate_unresolved_span(
    row: Any,
    text: str,
    line_number: int,
    po_ids: set[str],
    pato_ids: set[str],
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(row, dict):
        _add(issues, line_number, "unresolved_span_not_object", "span must be an object")
        return
    try:
        parsed = UnresolvedTraitSpan.model_validate(row)
    except Exception as exc:
        _add(issues, line_number, "unresolved_span_schema", str(exc))
        return
    if parsed.start < 0 or parsed.end < parsed.start or parsed.end > len(text):
        _add(
            issues,
            line_number,
            "unresolved_span_offsets",
            f"[{parsed.start}, {parsed.end}) outside text length {len(text)}",
        )
    elif text[parsed.start:parsed.end] != parsed.surface_form:
        _add(
            issues,
            line_number,
            "unresolved_span_not_verbatim",
            repr(parsed.surface_form),
        )
    if not parsed.reason.strip():
        _add(issues, line_number, "unresolved_span_missing_reason", "reason is empty")
    if not parsed.extractor.strip():
        _add(issues, line_number, "unresolved_span_missing_extractor", "extractor is empty")
    candidate = parsed.candidate_pato_id or ""
    if candidate and not PATO_ID.fullmatch(candidate):
        _add(issues, line_number, "invalid_unresolved_pato_id", candidate)
    elif candidate and pato_ids and candidate not in pato_ids:
        _add(issues, line_number, "unknown_unresolved_pato_id", candidate)
    for promoted_po_id in parsed.promoted_po_ids or []:
        if not PO_ID.fullmatch(promoted_po_id):
            _add(issues, line_number, "invalid_promoted_po_id", promoted_po_id)
        elif po_ids and promoted_po_id not in po_ids:
            _add(issues, line_number, "unknown_promoted_po_id", promoted_po_id)


def _validate_source_statement(
    row: Any,
    text: str,
    line_number: int,
    statement_ids: set[str],
    statement_texts: dict[str, str],
    statement_spans: dict[str, tuple[int, int]],
    issues: list[ValidationIssue],
    segment_char_start: int | None = None,
) -> None:
    if not isinstance(row, dict):
        _add(issues, line_number, "source_statement_not_object", "statement must be an object")
        return
    try:
        parsed = SourceStatement.model_validate(row)
    except Exception as exc:
        _add(issues, line_number, "source_statement_schema", str(exc))
        return
    if parsed.statement_id in statement_ids:
        _add(issues, line_number, "duplicate_source_statement_id", parsed.statement_id)
    statement_ids.add(parsed.statement_id)
    statement_texts[parsed.statement_id] = parsed.verbatim_text
    statement_spans[parsed.statement_id] = (parsed.start, parsed.end)
    if (
        parsed.start < 0
        or parsed.end < parsed.start
        or parsed.end > len(text)
        or text[parsed.start:parsed.end] != parsed.verbatim_text
    ):
        _add(
            issues,
            line_number,
            "source_statement_not_verbatim",
            f"{parsed.statement_id}: [{parsed.start}, {parsed.end})",
        )
    if (parsed.document_start is None) != (parsed.document_end is None):
        _add(
            issues,
            line_number,
            "incomplete_source_statement_document_offsets",
            parsed.statement_id,
        )
    elif (
        parsed.document_start is not None
        and isinstance(segment_char_start, int)
        and not isinstance(segment_char_start, bool)
        and (
            parsed.document_start != segment_char_start + parsed.start
            or parsed.document_end != segment_char_start + parsed.end
        )
    ):
        _add(
            issues,
            line_number,
            "source_statement_document_offset_mismatch",
            f"{parsed.statement_id}: document=[{parsed.document_start}, {parsed.document_end}), "
            f"expected=[{segment_char_start + parsed.start}, {segment_char_start + parsed.end})",
        )


def _validate_assertion(
    assertion: Any,
    text: str,
    line_number: int,
    assertion_number: int,
    mention_ids: set[str],
    statement_ids: set[str],
    source_statements_present: bool,
    po_ids: set[str],
    flopo_bearer_ids: set[str],
    pato_ids: set[str],
    attribute_pato_ids: set[str],
    stage: str,
    require_annotation_class: bool,
    issues: list[ValidationIssue],
    statement_texts: dict[str, str] | None = None,
    statement_spans: dict[str, tuple[int, int]] | None = None,
    strict_source_statements: bool = False,
) -> str:
    if not isinstance(assertion, dict):
        _add(
            issues,
            line_number,
            "assertion_not_object",
            "trait assertion must be an object",
            assertion_number,
        )
        return ""
    try:
        parsed = _pydantic_assertion(assertion)
    except Exception as exc:
        _add(issues, line_number, "assertion_schema", str(exc), assertion_number)
        return ""

    stored_class_iri = parsed.phenotype_class_iri or ""
    if require_annotation_class and not stored_class_iri:
        _add(
            issues,
            line_number,
            "missing_phenotype_class_iri",
            "materialized annotation has no annotation-extension class IRI",
            assertion_number,
        )
    if stored_class_iri:
        if not stored_class_iri.startswith(ANNOTATION_CLASS_BASE + "FAC_"):
            _add(
                issues,
                line_number,
                "invalid_phenotype_class_namespace",
                stored_class_iri,
                assertion_number,
            )
        if parsed.cardinality:
            _add(
                issues,
                line_number,
                "phenotype_class_omits_cardinality",
                f"cardinality={parsed.cardinality!r}",
                assertion_number,
            )
        else:
            try:
                expected_class_iri = annotation_class_iri(assertion)
            except ValueError as exc:
                _add(
                    issues,
                    line_number,
                    "phenotype_class_expression_error",
                    str(exc),
                    assertion_number,
                )
            else:
                if stored_class_iri != expected_class_iri:
                    _add(
                        issues,
                        line_number,
                        "phenotype_class_iri_mismatch",
                        f"stored={stored_class_iri!r}, expected={expected_class_iri!r}",
                        assertion_number,
                    )

    if PO_ID.fullmatch(parsed.anatomical_entity):
        if po_ids and parsed.anatomical_entity not in po_ids:
            _add(
                issues,
                line_number,
                "unknown_po_id",
                parsed.anatomical_entity,
                assertion_number,
            )
    elif FLOPO_ID.fullmatch(parsed.anatomical_entity):
        if flopo_bearer_ids and parsed.anatomical_entity not in flopo_bearer_ids:
            _add(
                issues,
                line_number,
                "unknown_flopo_bearer_id",
                parsed.anatomical_entity,
                assertion_number,
            )
    else:
        _add(
            issues,
            line_number,
            "invalid_anatomical_entity_id",
            parsed.anatomical_entity,
            assertion_number,
        )
    if not PATO_ID.fullmatch(parsed.quality):
        _add(issues, line_number, "invalid_pato_id", parsed.quality, assertion_number)
    elif pato_ids and parsed.quality not in pato_ids:
        _add(issues, line_number, "unknown_pato_id", parsed.quality, assertion_number)

    if not parsed.source_text or parsed.source_text not in text:
        _add(
            issues,
            line_number,
            "source_span_not_verbatim",
            repr(parsed.source_text[:120]),
            assertion_number,
        )
    source_start = parsed.source_start
    source_end = parsed.source_end
    if source_start is not None or source_end is not None:
        if (
            source_start is None
            or source_end is None
            or source_start < 0
            or source_end < source_start
            or source_end > len(text)
            or text[source_start:source_end] != parsed.source_text
        ):
            _add(
                issues,
                line_number,
                "invalid_source_offsets",
                f"source_start={source_start!r}, source_end={source_end!r}",
                assertion_number,
            )
    gate_status_hint = (assertion.get("gate") or {}).get("status", "")
    if (
        stage == "gated"
        and gate_status_hint == "accepted"
        and source_start is None
        and source_end is None
        and parsed.source_text
        and text.count(parsed.source_text) > 1
    ):
        _add(
            issues,
            line_number,
            "ambiguous_source_span_without_offsets",
            repr(parsed.source_text[:120]),
            assertion_number,
        )

    raw_entity_text = parsed.raw_entity_text or ""
    bearer_start = parsed.bearer_start
    bearer_end = parsed.bearer_end
    bearer_has_any_offset = bearer_start is not None or bearer_end is not None
    bearer_provenance = tuple(parsed.mapping_provenance or ())
    bearer_is_context_only = any(
        marker in provenance
        for provenance in bearer_provenance
        for marker in (
            "bearer:organ_heading",
            "bearer_basis:record_organ_field_nonverbatim",
        )
    )
    bearer_occurrences = (
        0
        if bearer_is_context_only
        else _phrase_occurrences(text, raw_entity_text, case_insensitive=True)
    )
    if bearer_has_any_offset and (
        not raw_entity_text or not _valid_span(text, bearer_start, bearer_end, raw_entity_text)
    ):
        _add(
            issues,
            line_number,
            "invalid_bearer_offsets",
            f"bearer_start={bearer_start!r}, bearer_end={bearer_end!r}, "
            f"raw_entity_text={raw_entity_text!r}",
            assertion_number,
        )
    elif strict_source_statements and raw_entity_text and not bearer_has_any_offset and bearer_occurrences:
        _add(
            issues,
            line_number,
            (
                "ambiguous_bearer_evidence_without_offsets"
                if bearer_occurrences > 1
                else "missing_bearer_offsets"
            ),
            repr(raw_entity_text),
            assertion_number,
        )

    modality_text = parsed.modality_text or ""
    modality_start = parsed.modality_start
    modality_end = parsed.modality_end
    modality_has_any_offset = modality_start is not None or modality_end is not None
    modality_occurrences = _phrase_occurrences(text, modality_text)
    if modality_has_any_offset and (
        not modality_text
        or not _valid_span(text, modality_start, modality_end, modality_text)
    ):
        _add(
            issues,
            line_number,
            "invalid_modality_offsets",
            f"modality_start={modality_start!r}, modality_end={modality_end!r}, "
            f"modality_text={modality_text!r}",
            assertion_number,
        )
    elif (
        strict_source_statements
        and modality_text
        and not modality_has_any_offset
        and modality_occurrences
    ):
        _add(
            issues,
            line_number,
            (
                "ambiguous_modality_evidence_without_offsets"
                if modality_occurrences > 1
                else "missing_modality_offsets"
            ),
            repr(modality_text),
            assertion_number,
        )
    if stage == "gated" and gate_status_hint == "accepted" and not parsed.extractor:
        _add(
            issues,
            line_number,
            "missing_extractor_provenance",
            "accepted assertion has no extractor identifier",
            assertion_number,
        )

    if (source_statements_present or strict_source_statements) and not parsed.source_statement_id:
        _add(
            issues,
            line_number,
            "missing_source_statement_reference",
            "assertion is not linked to a retained source statement",
            assertion_number,
        )
    elif parsed.source_statement_id and parsed.source_statement_id not in statement_ids:
        _add(
            issues,
            line_number,
            "unknown_source_statement_reference",
            parsed.source_statement_id,
            assertion_number,
        )

    # Interval-aware statement coverage.  A linked statement's retained [start, end) interval must
    # contain every piece of evidence the assertion draws on.  Coverage runs whenever the linked
    # statement EXISTS (even if empty), so a too-narrow statement fails rather than passing on a
    # coincidental substring match elsewhere in the segment.
    statement_id = parsed.source_statement_id or ""
    statement_span = (statement_spans or {}).get(statement_id)
    if statement_id and statement_span is not None:
        statement_start, statement_end = statement_span
        statement_text = (statement_texts or {}).get(statement_id, "")
        if not statement_text or statement_end <= statement_start:
            _add(
                issues,
                line_number,
                "empty_linked_source_statement",
                statement_id,
                assertion_number,
            )

        evidence_items: list[tuple[str, str, str, tuple[Any, Any], bool]] = [
            (
                "assertion_evidence_outside_statement_interval",
                "source_statement_omits_assertion_evidence",
                parsed.source_text or "",
                (parsed.source_start, parsed.source_end),
                False,
            ),
            (
                "modality_cue_outside_statement_interval",
                "source_statement_omits_modality_cue",
                parsed.modality_text or "",
                (parsed.modality_start, parsed.modality_end),
                False,
            ),
        ]
        # A translated / non-verbatim bearer label is provenance context, not statement evidence;
        # a case-normalized bearer (raw_entity_text=leaflets vs source Leaflets) still counts.
        raw_entity_text = parsed.raw_entity_text or ""
        bearer_span = (parsed.bearer_start, parsed.bearer_end)
        bearer_is_verbatim = not bearer_is_context_only and bool(raw_entity_text) and (
            (
                _int_span(*bearer_span)
                and _valid_span(text, bearer_span[0], bearer_span[1], raw_entity_text)
            )
            or raw_entity_text in text
            or re.search(re.escape(raw_entity_text), text, re.IGNORECASE) is not None
        )
        if bearer_is_verbatim:
            evidence_items.append(
                (
                    "bearer_evidence_outside_statement_interval",
                    "source_statement_omits_bearer_evidence",
                    raw_entity_text,
                    bearer_span,
                    True,
                )
            )
        evidence_items.extend(
            (
                "season_context_outside_statement_interval",
                "source_statement_omits_season_cue",
                season.season_text or "",
                (season.start, season.end),
                False,
            )
            for season in parsed.season_contexts or []
        )
        evidence_items.extend(
            (
                "developmental_stage_outside_statement_interval",
                "source_statement_omits_developmental_stage_cue",
                context.stage_text or "",
                (context.start, context.end),
                False,
            )
            for context in parsed.developmental_stage_contexts or []
        )
        for outside_code, omit_code, text_value, span, case_insensitive in evidence_items:
            tag = _covers_evidence(
                text_value=text_value,
                span=span,
                statement_start=statement_start,
                statement_end=statement_end,
                statement_text=statement_text,
                segment_text=text,
                case_insensitive=case_insensitive,
            )
            if tag == "outside":
                _add(issues, line_number, outside_code, repr(text_value), assertion_number)
            elif tag == "omitted":
                _add(issues, line_number, omit_code, repr(text_value), assertion_number)
            elif tag == "ambiguous":
                _add(
                    issues,
                    line_number,
                    "ambiguous_unanchored_evidence",
                    repr(text_value),
                    assertion_number,
                )

    if parsed.modality_text and parsed.modality_text not in text:
        _add(
            issues,
            line_number,
            "modality_cue_not_verbatim",
            repr(parsed.modality_text),
            assertion_number,
        )
    qualifier_requires_cue = (
        parsed.frequency_qualifier not in {"unspecified", "universal"}
        or parsed.epistemic_modality != "asserted"
        or parsed.value_qualifier != "exact"
        or parsed.degree_qualifier != "unmodified"
    )
    if qualifier_requires_cue and not parsed.modality_text:
        _add(
            issues,
            line_number,
            "qualified_assertion_missing_modality_cue",
            "non-default modality must retain its exact lexical cue",
            assertion_number,
        )
    for season in parsed.season_contexts or []:
        if not season.season_term and season.start_month is None and season.end_month is None:
            _add(
                issues,
                line_number,
                "season_context_missing_term_or_months",
                repr(season.season_text),
                assertion_number,
            )
        if (season.start_month is None) != (season.end_month is None):
            _add(
                issues,
                line_number,
                "incomplete_season_month_range",
                repr(season.season_text),
                assertion_number,
            )
        for month in (season.start_month, season.end_month):
            if month is not None and not 1 <= month <= 12:
                _add(
                    issues,
                    line_number,
                    "season_month_out_of_range",
                    repr(month),
                    assertion_number,
                )
        if season.start is not None or season.end is not None:
            if (
                season.start is None
                or season.end is None
                or season.start < 0
                or season.end < season.start
                or season.end > len(text)
                or text[season.start:season.end] != season.season_text
            ):
                _add(
                    issues,
                    line_number,
                    "season_span_not_verbatim",
                    repr(season.season_text),
                    assertion_number,
                )
        elif season.season_text not in text:
            _add(
                issues,
                line_number,
                "season_text_not_verbatim",
                repr(season.season_text),
                assertion_number,
            )
    season_count = len(parsed.season_contexts or [])
    if parsed.season_operator in {"one_of", "all_of"} and season_count < 2:
        _add(
            issues,
            line_number,
            "season_operator_missing_components",
            f"{parsed.season_operator} requires at least two season contexts",
            assertion_number,
        )
    elif parsed.season_operator == "atomic" and season_count > 1:
        _add(
            issues,
            line_number,
            "atomic_season_has_multiple_contexts",
            repr(season_count),
            assertion_number,
        )

    for context in parsed.developmental_stage_contexts or []:
        stage_term = context.stage_term.replace(":", "_")
        if PO_ID.fullmatch(stage_term):
            if po_ids and stage_term not in po_ids:
                _add(
                    issues,
                    line_number,
                    "unknown_developmental_stage_po_id",
                    context.stage_term,
                    assertion_number,
                )
        elif FLOPO_ID.fullmatch(stage_term):
            if flopo_bearer_ids and stage_term not in flopo_bearer_ids:
                _add(
                    issues,
                    line_number,
                    "unknown_developmental_stage_flopo_id",
                    context.stage_term,
                    assertion_number,
                )
        else:
            _add(
                issues,
                line_number,
                "invalid_developmental_stage_id",
                context.stage_term,
                assertion_number,
            )
        if context.start is not None or context.end is not None:
            if (
                context.start is None
                or context.end is None
                or context.start < 0
                or context.end < context.start
                or context.end > len(text)
                or text[context.start:context.end] != context.stage_text
            ):
                _add(
                    issues,
                    line_number,
                    "developmental_stage_span_not_verbatim",
                    repr(context.stage_text),
                    assertion_number,
                )
        elif context.stage_text not in text:
            _add(
                issues,
                line_number,
                "developmental_stage_text_not_verbatim",
                repr(context.stage_text),
                assertion_number,
            )
    stage_context_count = len(parsed.developmental_stage_contexts or [])
    if (
        parsed.developmental_stage_operator in {"one_of", "all_of"}
        and stage_context_count < 2
    ):
        _add(
            issues,
            line_number,
            "developmental_stage_operator_missing_components",
            f"{parsed.developmental_stage_operator} requires at least two contexts",
            assertion_number,
        )
    elif parsed.developmental_stage_operator == "atomic" and stage_context_count > 1:
        _add(
            issues,
            line_number,
            "atomic_developmental_stage_has_multiple_contexts",
            repr(stage_context_count),
            assertion_number,
        )

    negation_scope = (
        str(getattr(parsed.negation_scope, "value", parsed.negation_scope))
        if parsed.negation_scope is not None
        else ""
    )
    if parsed.negated and not negation_scope:
        _add(
            issues,
            line_number,
            "negated_assertion_missing_scope",
            "negated assertions must distinguish quality negation from EQ absence",
            assertion_number,
        )
    elif not parsed.negated and negation_scope:
        _add(
            issues,
            line_number,
            "negation_scope_without_negation",
            negation_scope,
            assertion_number,
        )
    if parsed.negated and not NEGATION_EVIDENCE.search(parsed.source_text):
        _add(
            issues,
            line_number,
            "negation_cue_not_in_source_span",
            repr(parsed.source_text),
            assertion_number,
        )
    if (
        parsed.value_low is None
        and parsed.value_high is not None
        and not UPPER_BOUND_EVIDENCE.search(parsed.source_text)
    ):
        _add(
            issues,
            line_number,
            "upper_bound_cue_not_in_source_span",
            repr(parsed.source_text),
            assertion_number,
        )
    for flag_name, bound in (
        ("value_low_inclusive", parsed.value_low),
        ("value_high_inclusive", parsed.value_high),
    ):
        flag = getattr(parsed, flag_name, True)
        if flag is None:
            flag = True
        if flag is False and bound is None:
            _add(
                issues,
                line_number,
                "bound_inclusivity_without_bound",
                flag_name,
                assertion_number,
            )

    values = list(parsed.value_terms or [])
    if parsed.value_operator in {"all_of", "one_of"} and len(set(values)) < 2:
        _add(
            issues,
            line_number,
            "logical_value_missing_components",
            f"{parsed.value_operator} requires at least two distinct values",
            assertion_number,
        )
    if parsed.value_operator == "atomic" and len(set(values)) > 1:
        _add(
            issues,
            line_number,
            "atomic_value_has_multiple_components",
            repr(values),
            assertion_number,
        )
    if (
        parsed.value_operator == "atomic"
        and len(set(values)) == 1
        and attribute_pato_ids
        and parsed.quality != values[0]
        and parsed.quality not in attribute_pato_ids
    ):
        _add(
            issues,
            line_number,
            "atomic_value_top_level_incompatible",
            f"quality={parsed.quality!r}, value={values[0]!r}",
            assertion_number,
        )
    if (
        parsed.value_operator in {"one_of", "all_of"}
        and attribute_pato_ids
        and parsed.quality not in attribute_pato_ids
    ):
        _add(
            issues,
            line_number,
            "logical_value_top_level_not_attribute",
            parsed.quality,
            assertion_number,
        )
    source_context = _clause_around(
        text,
        parsed.source_text,
        parsed.source_start,
        parsed.source_end,
    )
    if (
        parsed.value_operator == "atomic"
        and _has_real_disjunction(source_context)
        and (gate_status_hint == "accepted" or _has_real_disjunction(parsed.source_text))
    ):
        _add(
            issues,
            line_number,
            (
                "atomic_source_contains_disjunction"
                if _has_real_disjunction(parsed.source_text)
                else "accepted_atomic_clause_contains_disjunction"
            ),
            repr(source_context),
            assertion_number,
        )
    for value in values:
        if not isinstance(value, str) or not value.startswith(VALUE_PREFIXES):
            _add(
                issues,
                line_number,
                "invalid_value_term",
                repr(value),
                assertion_number,
            )
        elif PATO_ID.fullmatch(value) and pato_ids and value not in pato_ids:
            _add(
                issues,
                line_number,
                "unknown_value_pato_id",
                value,
                assertion_number,
            )

    context_qualities = list(parsed.bearer_context_qualities or [])
    normalized_primary = {
        str(value).replace(":", "_")
        for value in (values or [parsed.quality])
    }
    for value in context_qualities:
        normalized = str(value).replace(":", "_")
        if not PATO_ID.fullmatch(value):
            _add(
                issues,
                line_number,
                "invalid_bearer_context_quality",
                repr(value),
                assertion_number,
            )
        elif pato_ids and normalized not in pato_ids:
            _add(
                issues,
                line_number,
                "unknown_bearer_context_quality",
                value,
                assertion_number,
            )
        if normalized in normalized_primary:
            _add(
                issues,
                line_number,
                "bearer_context_duplicates_primary_quality",
                value,
                assertion_number,
            )

    bounds = [value for value in (parsed.value_low, parsed.value_high) if value is not None]
    if any(not math.isfinite(value) for value in bounds):
        _add(issues, line_number, "nonfinite_measurement", repr(bounds), assertion_number)
    if (
        parsed.value_low is not None
        and parsed.value_high is not None
        and parsed.value_low > parsed.value_high
    ):
        _add(
            issues,
            line_number,
            "reversed_measurement_range",
            f"{parsed.value_low} > {parsed.value_high}",
            assertion_number,
        )
    if bounds and not parsed.unit:
        _add(
            issues,
            line_number,
            "measurement_missing_unit",
            repr(bounds),
            assertion_number,
        )
    elif bounds and not is_supported_length_unit(parsed.unit):
        _add(
            issues,
            line_number,
            "unsupported_measurement_unit",
            repr(parsed.unit),
            assertion_number,
        )
    elif parsed.unit and not bounds:
        _add(
            issues,
            line_number,
            "measurement_unit_without_value",
            repr(parsed.unit),
            assertion_number,
        )
    if bounds and attribute_pato_ids and parsed.quality not in attribute_pato_ids:
        _add(
            issues,
            line_number,
            "numeric_quality_not_pato_attribute",
            parsed.quality,
            assertion_number,
        )
    if parsed.confidence is not None and (
        not math.isfinite(parsed.confidence) or not 0.0 <= parsed.confidence <= 1.0
    ):
        _add(
            issues,
            line_number,
            "confidence_out_of_range",
            repr(parsed.confidence),
            assertion_number,
        )

    references = [parsed.entity_mention_id] if parsed.entity_mention_id else []
    references.extend(parsed.quality_mention_ids or [])
    for reference in references:
        if reference not in mention_ids:
            _add(
                issues,
                line_number,
                "unknown_mention_reference",
                reference,
                assertion_number,
            )

    composition = assertion.get("composition") or {}
    composition_status = composition.get("status", "")
    if stage in {"composed", "gated"} and composition_status not in VALID_COMPOSITION_STATUSES:
        _add(
            issues,
            line_number,
            "missing_or_invalid_composition",
            repr(composition_status),
            assertion_number,
        )

    gate = assertion.get("gate") or {}
    gate_status = gate.get("status", "")
    if stage == "gated":
        if gate_status not in VALID_GATE_STATUSES:
            _add(
                issues,
                line_number,
                "missing_or_invalid_gate",
                repr(gate_status),
                assertion_number,
            )
        if gate_status == "accepted" and composition_status != "accept":
            _add(
                issues,
                line_number,
                "accepted_without_composition",
                repr(composition_status),
                assertion_number,
            )
        unsafe_ids = MANUAL_REVIEW_PATO_IDS.intersection({parsed.quality, *values})
        if gate_status == "accepted" and unsafe_ids:
            _add(
                issues,
                line_number,
                "accepted_manual_review_pato_id",
                repr(sorted(unsafe_ids)),
                assertion_number,
            )
        if gate_status == "accepted" and parsed.cardinality:
            _add(
                issues,
                line_number,
                "accepted_unrepresented_context",
                f"cardinality={parsed.cardinality!r}",
                assertion_number,
            )
    return gate_status


def validate_jsonl(
    path: Path,
    *,
    stage: str = "extracted",
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    catalog_check: bool = True,
    require_annotation_class: bool = False,
    strict_source_statements: bool = False,
    max_examples: int = 30,
) -> dict[str, Any]:
    """Return a machine-readable validation report for a pipeline JSONL artifact.

    ``strict_source_statements`` controls the retained-provenance contract and defaults to
    ``False`` to preserve compatibility with legacy extracted input that predates first-class
    source statements. Compatibility path: legacy artifacts validate with the default; a record
    that already carries ``source_statements`` still requires every assertion to link one, and the
    gated/materialized stage should pass ``strict_source_statements=True`` (CLI:
    ``--strict-source-statements``) so every assertion must reference a retained statement. Narrow
    linked statements preserved on upgrade are not grandfathered: interval-aware coverage then
    routes them to review rather than letting them pass silently.
    """

    if stage not in {"extracted", "composed", "gated"}:
        raise ValueError(f"unknown stage: {stage}")
    po_ids = _load_ids(po_lexicon) if catalog_check else set()
    pato_ids = _load_ids(pato_lexicon) if catalog_check else set()
    flopo_bearer_ids = _load_flopo_ids(flopo_registry) if catalog_check else set()
    attribute_pato_ids = _load_attribute_ids(pato_lexicon) if catalog_check else set()
    issues: list[ValidationIssue] = []
    segments = assertions = mentions = source_statements = unresolved_spans = extraction_errors = 0
    gate_statuses: Counter[str] = Counter()
    annotation_class_iris: set[str] = set()
    unresolved_reasons: Counter[str] = Counter()
    source_positions: Counter[tuple[str, str]] = Counter()
    segment_identities: set[tuple[str, str, int]] = set()

    with Path(path).open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                _add(issues, line_number, "invalid_json", str(exc))
                continue
            if not isinstance(obj, dict):
                _add(issues, line_number, "segment_not_object", "JSONL row must be an object")
                continue
            segments += 1
            text = obj.get("text")
            if not isinstance(text, str) or not text.strip():
                _add(issues, line_number, "missing_segment_text", repr(text))
                text = text if isinstance(text, str) else ""
            if not isinstance(obj.get("source"), str) or not obj.get("source"):
                _add(issues, line_number, "missing_source", repr(obj.get("source")))
            if not isinstance(obj.get("source_id"), str) or not obj.get("source_id"):
                _add(issues, line_number, "missing_source_id", repr(obj.get("source_id")))
            source_key = (obj.get("source", ""), obj.get("source_id", ""))
            inferred_source_index = source_positions[source_key]
            source_positions[source_key] += 1
            source_segment_index = obj.get("source_segment_index", inferred_source_index)
            if (
                not isinstance(source_segment_index, int)
                or isinstance(source_segment_index, bool)
                or source_segment_index < 0
            ):
                _add(
                    issues,
                    line_number,
                    "invalid_source_segment_index",
                    repr(source_segment_index),
                )
            else:
                identity = (*source_key, source_segment_index)
                if identity in segment_identities:
                    _add(
                        issues,
                        line_number,
                        "duplicate_source_segment_index",
                        repr(identity),
                    )
                segment_identities.add(identity)
            if "char_start" in obj or "char_end" in obj:
                start = obj.get("char_start")
                end = obj.get("char_end")
                if (
                    not isinstance(start, int)
                    or isinstance(start, bool)
                    or not isinstance(end, int)
                    or isinstance(end, bool)
                    or start < 0
                    or end < start
                ):
                    _add(
                        issues,
                        line_number,
                        "invalid_segment_offsets",
                        f"char_start={start!r}, char_end={end!r}",
                    )
            if obj.get("extract_error"):
                extraction_errors += 1

            row_mentions = obj.get("term_mentions", []) or []
            if not isinstance(row_mentions, list):
                _add(issues, line_number, "mentions_not_list", repr(type(row_mentions)))
                row_mentions = []
            mention_ids: set[str] = set()
            for mention in row_mentions:
                _validate_mention(mention, text, line_number, mention_ids, issues)
                mentions += 1

            row_unresolved = obj.get("unresolved_spans", []) or []
            if not isinstance(row_unresolved, list):
                _add(issues, line_number, "unresolved_spans_not_list", repr(type(row_unresolved)))
                row_unresolved = []
            for unresolved in row_unresolved:
                _validate_unresolved_span(
                    unresolved,
                    text,
                    line_number,
                    po_ids,
                    pato_ids,
                    issues,
                )
                unresolved_spans += 1
                if isinstance(unresolved, dict):
                    unresolved_reasons[str(unresolved.get("reason", "") or "<missing>")] += 1

            row_source_statements = obj.get("source_statements", []) or []
            if not isinstance(row_source_statements, list):
                _add(
                    issues,
                    line_number,
                    "source_statements_not_list",
                    repr(type(row_source_statements)),
                )
                row_source_statements = []
            statement_ids: set[str] = set()
            statement_texts: dict[str, str] = {}
            statement_spans: dict[str, tuple[int, int]] = {}
            raw_char_start = obj.get("char_start")
            segment_char_start = (
                raw_char_start
                if isinstance(raw_char_start, int) and not isinstance(raw_char_start, bool)
                else None
            )
            for statement in row_source_statements:
                _validate_source_statement(
                    statement,
                    text,
                    line_number,
                    statement_ids,
                    statement_texts,
                    statement_spans,
                    issues,
                    segment_char_start,
                )
                source_statements += 1

            row_assertions = obj.get("assertions")
            if not isinstance(row_assertions, list):
                _add(issues, line_number, "assertions_not_list", repr(type(row_assertions)))
                row_assertions = []
            for assertion_number, assertion in enumerate(row_assertions):
                if isinstance(assertion, dict) and not str(
                    assertion.get("cardinality", "") or ""
                ).strip():
                    try:
                        annotation_class_iris.add(annotation_class_iri(assertion))
                    except ValueError:
                        pass
                status = _validate_assertion(
                    assertion,
                    text,
                    line_number,
                    assertion_number,
                    mention_ids,
                    statement_ids,
                    bool(row_source_statements),
                    po_ids,
                    flopo_bearer_ids,
                    pato_ids,
                    attribute_pato_ids,
                    stage,
                    require_annotation_class,
                    issues,
                    statement_texts,
                    statement_spans,
                    strict_source_statements,
                )
                if status:
                    gate_statuses[status] += 1
                assertions += 1

            if (
                stage == "gated"
                and "taxon" in obj
                and not str(obj.get("taxon") or "").strip()
                and any(
                    (assertion.get("gate") or {}).get("status") == "accepted"
                    for assertion in row_assertions
                    if isinstance(assertion, dict)
                )
            ):
                _add(
                    issues,
                    line_number,
                    "accepted_without_taxon_provenance",
                    repr(obj.get("taxon")),
                )

            try:
                TraitExtraction.model_validate(
                    {
                        "source_segment_index": source_segment_index,
                        "taxon_name": obj.get("taxon") or None,
                        "organ_hint": obj.get("organ") or None,
                        "source_statements": row_source_statements or None,
                        "unresolved_spans": row_unresolved or None,
                        "assertions": [],
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive around generated model
                _add(issues, line_number, "extraction_schema", str(exc))

    by_code = Counter(issue.code for issue in issues)
    return {
        "path": str(path),
        "stage": stage,
        "require_annotation_class": require_annotation_class,
        "strict_source_statements": strict_source_statements,
        "segments": segments,
        "assertions": assertions,
        "annotation_classes": len(annotation_class_iris),
        "term_mentions": mentions,
        "source_statements": source_statements,
        "unresolved_spans": unresolved_spans,
        "unresolved_reasons": dict(sorted(unresolved_reasons.items())),
        "records_with_extract_error": extraction_errors,
        "gate_statuses": dict(sorted(gate_statuses.items())),
        "errors": len(issues),
        "errors_by_code": dict(sorted(by_code.items())),
        "error_examples": [asdict(issue) for issue in issues[:max_examples]],
        "ok": not issues,
    }


def validate_sqlite(path: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Check SQLite integrity, referential integrity, and optional JSONL count agreement."""

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        foreign_key_rows = [list(row) for row in conn.execute("PRAGMA foreign_key_check")]
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        segment_columns = {row[1] for row in conn.execute("PRAGMA table_info(text_segment)")}
        assertion_columns = {row[1] for row in conn.execute("PRAGMA table_info(trait_assertion)")}
        unresolved_columns = {row[1] for row in conn.execute("PRAGMA table_info(unresolved_span)")}
        required_segment = {"source_segment_index", "taxon", "text"}
        required_assertion = {
            "source_text",
            "source_start",
            "source_end",
            "extractor",
            "gate_status",
            "trait",
            "modifier",
            "cardinality",
            "confidence",
            "source_statement_id",
            "frequency_qualifier",
            "epistemic_modality",
            "value_qualifier",
            "degree_qualifier",
            "modality_text",
            "bearer_start",
            "bearer_end",
            "modality_start",
            "modality_end",
            "season_contexts",
            "season_operator",
            "phenotype_class_iri",
            "negation_scope",
            "developmental_stage_contexts",
            "developmental_stage_operator",
        }
        required_unresolved = {
            "original_reason",
            "negation_residual_reason",
            "negation_residual_detail",
            "partial_promotion",
            "pending_bearer",
            "promoted_po_ids",
        }
        schema_errors = [
            *(f"text_segment missing column {name}" for name in sorted(required_segment - segment_columns)),
            *(
                f"trait_assertion missing column {name}"
                for name in sorted(required_assertion - assertion_columns)
            ),
            *(
                f"unresolved_span missing column {name}"
                for name in sorted(required_unresolved - unresolved_columns)
            ),
            *(
                "database missing table source_statement"
                for _ in [0]
                if "source_statement" not in tables
            ),
            *(
                "database missing table annotation_class"
                for _ in [0]
                if "annotation_class" not in tables
            ),
            *("database missing table unresolved_span" for _ in [0] if "unresolved_span" not in tables),
        ]
        segments = conn.execute("SELECT COUNT(*) FROM text_segment").fetchone()[0]
        assertions = conn.execute("SELECT COUNT(*) FROM trait_assertion").fetchone()[0]
        source_statement_count = (
            conn.execute("SELECT COUNT(*) FROM source_statement").fetchone()[0]
            if "source_statement" in tables
            else None
        )
        unresolved = (
            conn.execute("SELECT COUNT(*) FROM unresolved_span").fetchone()[0]
            if "unresolved_span" in tables
            else None
        )
        annotation_classes = (
            conn.execute("SELECT COUNT(*) FROM annotation_class").fetchone()[0]
            if "annotation_class" in tables
            else None
        )
        unresolved_reasons = (
            dict(conn.execute(
                "SELECT reason, COUNT(*) FROM unresolved_span GROUP BY reason ORDER BY reason"
            ).fetchall())
            if "unresolved_span" in tables
            else {}
        )
        accepted = conn.execute("SELECT COUNT(*) FROM v_accepted_assertions").fetchone()[0]
        review = conn.execute("SELECT COUNT(*) FROM v_review_queue").fetchone()[0]
        accepted_missing_extractor = accepted_invalid_source_offsets = accepted_missing_taxon = None
        assertion_source_statement_mismatch = invalid_source_statement_offsets = None
        invalid_bearer_offsets = invalid_modality_offsets = None
        evidence_outside_source_statement = None
        unresolved_invalid_source_offsets = unresolved_missing_extractor = None
        invalid_annotation_class_ids = representable_missing_annotation_class = None
        all_missing_annotation_class = None
        if not schema_errors:
            accepted_missing_extractor = conn.execute(
                "SELECT COUNT(*) FROM trait_assertion "
                "WHERE gate_status='accepted' AND trim(extractor)=''"
            ).fetchone()[0]
            accepted_invalid_source_offsets = conn.execute(
                """
                SELECT COUNT(*)
                FROM trait_assertion AS assertion
                JOIN text_segment AS segment USING(segment_id)
                WHERE assertion.gate_status='accepted'
                  AND (
                    assertion.source_start IS NULL
                    OR assertion.source_end IS NULL
                    OR assertion.source_start < 0
                    OR assertion.source_end < assertion.source_start
                    OR assertion.source_end > length(segment.text)
                    OR substr(
                      segment.text,
                      assertion.source_start + 1,
                      assertion.source_end - assertion.source_start
                    ) <> assertion.source_text
                  )
                """
            ).fetchone()[0]
            accepted_missing_taxon = conn.execute(
                """
                SELECT COUNT(*)
                FROM trait_assertion AS assertion
                JOIN text_segment AS segment USING(segment_id)
                WHERE assertion.gate_status='accepted' AND trim(segment.taxon)=''
                """
            ).fetchone()[0]
            assertion_source_statement_mismatch = conn.execute(
                """
                SELECT COUNT(*)
                FROM trait_assertion AS assertion
                JOIN source_statement AS statement
                  ON statement.statement_id = assertion.source_statement_id
                WHERE assertion.segment_id <> statement.segment_id
                """
            ).fetchone()[0]
            invalid_source_statement_offsets = conn.execute(
                """
                SELECT COUNT(*)
                FROM source_statement AS statement
                JOIN text_segment AS segment USING(segment_id)
                WHERE statement.char_start < 0
                   OR statement.char_end < statement.char_start
                   OR statement.char_end > length(segment.text)
                   OR substr(
                     segment.text,
                     statement.char_start + 1,
                     statement.char_end - statement.char_start
                   ) <> statement.verbatim_text
                """
            ).fetchone()[0]
            invalid_bearer_offsets = conn.execute(
                """
                SELECT COUNT(*)
                FROM trait_assertion AS assertion
                JOIN text_segment AS segment USING(segment_id)
                WHERE (assertion.bearer_start IS NULL) <> (assertion.bearer_end IS NULL)
                   OR (
                     assertion.bearer_start IS NOT NULL
                     AND (
                       trim(assertion.raw_entity_text)=''
                       OR assertion.bearer_start < 0
                       OR assertion.bearer_end < assertion.bearer_start
                       OR assertion.bearer_end > length(segment.text)
                       OR substr(
                         segment.text,
                         assertion.bearer_start + 1,
                         assertion.bearer_end - assertion.bearer_start
                       ) <> assertion.raw_entity_text
                     )
                   )
                """
            ).fetchone()[0]
            invalid_modality_offsets = conn.execute(
                """
                SELECT COUNT(*)
                FROM trait_assertion AS assertion
                JOIN text_segment AS segment USING(segment_id)
                WHERE (assertion.modality_start IS NULL) <> (assertion.modality_end IS NULL)
                   OR (
                     assertion.modality_start IS NOT NULL
                     AND (
                       trim(assertion.modality_text)=''
                       OR assertion.modality_start < 0
                       OR assertion.modality_end < assertion.modality_start
                       OR assertion.modality_end > length(segment.text)
                       OR substr(
                         segment.text,
                         assertion.modality_start + 1,
                         assertion.modality_end - assertion.modality_start
                       ) <> assertion.modality_text
                     )
                   )
                """
            ).fetchone()[0]
            evidence_outside_source_statement = conn.execute(
                """
                SELECT COUNT(*)
                FROM trait_assertion AS assertion
                JOIN source_statement AS statement
                  ON statement.statement_id = assertion.source_statement_id
                WHERE (
                    assertion.source_start IS NOT NULL
                    AND (
                      assertion.source_start < statement.char_start
                      OR assertion.source_end > statement.char_end
                    )
                  )
                  OR (
                    assertion.bearer_start IS NOT NULL
                    AND (
                      assertion.bearer_start < statement.char_start
                      OR assertion.bearer_end > statement.char_end
                    )
                  )
                  OR (
                    assertion.modality_start IS NOT NULL
                    AND (
                      assertion.modality_start < statement.char_start
                      OR assertion.modality_end > statement.char_end
                    )
                  )
                """
            ).fetchone()[0]
            unresolved_invalid_source_offsets = conn.execute(
                """
                SELECT COUNT(*)
                FROM unresolved_span AS unresolved
                JOIN text_segment AS segment USING(segment_id)
                WHERE unresolved.char_start < 0
                   OR unresolved.char_end < unresolved.char_start
                   OR unresolved.char_end > length(segment.text)
                   OR substr(
                     segment.text,
                     unresolved.char_start + 1,
                     unresolved.char_end - unresolved.char_start
                   ) <> unresolved.surface_form
                """
            ).fetchone()[0]
            unresolved_missing_extractor = conn.execute(
                "SELECT COUNT(*) FROM unresolved_span WHERE trim(extractor)=''"
            ).fetchone()[0]
            invalid_annotation_class_ids = conn.execute(
                """
                SELECT COUNT(*) FROM annotation_class
                WHERE phenotype_class_iri <>
                  'https://w3id.org/flopo/annotation-class/FAC_' ||
                  substr(expression_sha256, 1, 32)
                """
            ).fetchone()[0]
            representable_missing_annotation_class = conn.execute(
                """
                SELECT COUNT(*) FROM trait_assertion
                WHERE (phenotype_class_iri IS NULL OR trim(phenotype_class_iri)='')
                  AND trim(cardinality)=''
                """
            ).fetchone()[0]
            all_missing_annotation_class = conn.execute(
                """
                SELECT COUNT(*) FROM trait_assertion
                WHERE phenotype_class_iri IS NULL OR trim(phenotype_class_iri)=''
                """
            ).fetchone()[0]

    count_errors: list[str] = []
    if expected is not None:
        if segments != expected["segments"]:
            count_errors.append(f"segments: database={segments}, jsonl={expected['segments']}")
        if assertions != expected["assertions"]:
            count_errors.append(f"assertions: database={assertions}, jsonl={expected['assertions']}")
        if (
            "annotation_classes" in expected
            and annotation_classes != expected["annotation_classes"]
        ):
            count_errors.append(
                "annotation_classes: "
                f"database={annotation_classes}, jsonl={expected['annotation_classes']}"
            )
        if "unresolved_spans" in expected and unresolved != expected["unresolved_spans"]:
            count_errors.append(
                f"unresolved_spans: database={unresolved}, jsonl={expected['unresolved_spans']}"
            )
        if (
            "source_statements" in expected
            and source_statement_count != expected["source_statements"]
        ):
            count_errors.append(
                "source_statements: "
                f"database={source_statement_count}, jsonl={expected['source_statements']}"
            )
    provenance_errors = {
        "accepted_missing_extractor": accepted_missing_extractor,
        "accepted_invalid_source_offsets": accepted_invalid_source_offsets,
        "accepted_missing_taxon": accepted_missing_taxon,
        "assertion_source_statement_mismatch": assertion_source_statement_mismatch,
        "invalid_source_statement_offsets": invalid_source_statement_offsets,
        "invalid_bearer_offsets": invalid_bearer_offsets,
        "invalid_modality_offsets": invalid_modality_offsets,
        "evidence_outside_source_statement": evidence_outside_source_statement,
        "unresolved_invalid_source_offsets": unresolved_invalid_source_offsets,
        "unresolved_missing_extractor": unresolved_missing_extractor,
        "invalid_annotation_class_ids": invalid_annotation_class_ids,
        "representable_missing_annotation_class": representable_missing_annotation_class,
    }
    if expected and expected.get("require_annotation_class"):
        provenance_errors["all_missing_annotation_class"] = all_missing_annotation_class
    ok = (
        integrity_rows == ["ok"]
        and not foreign_key_rows
        and not schema_errors
        and not count_errors
        and all(value == 0 for value in provenance_errors.values())
    )
    return {
        "path": str(path),
        "integrity_check": integrity_rows,
        "foreign_key_errors": foreign_key_rows,
        "schema_errors": schema_errors,
        "segments": segments,
        "assertions": assertions,
        "source_statements": source_statement_count,
        "unresolved_spans": unresolved,
        "annotation_classes": annotation_classes,
        "assertions_without_annotation_class": all_missing_annotation_class,
        "unresolved_reasons": unresolved_reasons,
        "accepted_assertions": accepted,
        "review_queue_assertions": review,
        **provenance_errors,
        "count_errors": count_errors,
        "ok": ok,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate extracted FLOPO trait JSONL.")
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--stage",
        choices=["extracted", "composed", "gated"],
        default="extracted",
    )
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--flopo-registry",
        type=Path,
        default=Path("config/flopo_id_registry.tsv"),
    )
    parser.add_argument("--no-catalog-check", action="store_true")
    parser.add_argument(
        "--require-annotation-class",
        action="store_true",
        help="Require every assertion to link to its stable FAC class IRI.",
    )
    parser.add_argument(
        "--strict-source-statements",
        "--require-source-statements",
        action="store_true",
        help=(
            "Require every assertion to reference a retained source statement (the "
            "gated/materialized provenance contract). Off by default for legacy extracted input."
        ),
    )
    parser.add_argument("--max-examples", type=int, default=30)
    parser.add_argument("--db", type=Path, help="also verify a SQLite database loaded from input")
    parser.add_argument("-o", "--out", type=Path, help="write the JSON report")
    args = parser.parse_args()

    report = validate_jsonl(
        args.input,
        stage=args.stage,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
        flopo_registry=args.flopo_registry,
        catalog_check=not args.no_catalog_check,
        require_annotation_class=args.require_annotation_class,
        strict_source_statements=args.strict_source_statements,
        max_examples=args.max_examples,
    )
    if args.db:
        report["database"] = validate_sqlite(args.db, report)
        report["ok"] = report["ok"] and report["database"]["ok"]
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
