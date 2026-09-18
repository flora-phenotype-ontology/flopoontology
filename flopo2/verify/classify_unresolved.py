"""Classify unresolved flora spans into actionable recovery work packages.

The extraction pipeline deliberately retains possible phenotype spans whenever a safe
annotation cannot yet be produced.  The eight baseline ``reason`` values are useful for
validation, but too broad for planning curation and model work.  This module adds a
read-only, lossless classification layer over those spans.

Where available, it reuses the detailed audit products from the explicit-disjunction,
residual-logic, hyphen/slash, and developmental-stage recovery passes.  Remaining bearer
and negation cases are separated with deterministic source-context rules.  It never
changes assertions, unresolved spans, ontology files, or registries.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from flopo2.extract import baseline


NUMERIC_TRAIT_IDS = frozenset(
    {
        "PATO_0000119",  # height
        "PATO_0000122",  # length
        "PATO_0000915",  # width
        "PATO_0000921",  # thickness
        "PATO_0001334",  # diameter
    }
)

COMPOUND_DASHES = "-–—"
SPAN_FIELDS = (
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "language",
    "span_start",
    "span_end",
    "surface_form",
    "candidate_pato_id",
    "original_reason",
    "initiative",
    "subtype",
    "actionability",
    "priority",
    "classification_basis",
    "reference_detail",
    "context",
)


@dataclass(frozen=True)
class ReferenceDecision:
    status: str
    route: str
    reason: str


@dataclass(frozen=True)
class HyphenForm:
    family: str
    subtype: str
    action: str
    note: str


@dataclass(frozen=True)
class Classification:
    initiative: str
    subtype: str
    actionability: str
    priority: str
    basis: str
    detail: str = ""


def _integer(value: object, default: int = -1) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _fold(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _span_key(record: dict, start: object, end: object) -> tuple[str, str, int, int, int]:
    return (
        str(record.get("source", "") or ""),
        str(record.get("source_id", "") or ""),
        _integer(record.get("source_segment_index"), 0),
        _integer(start),
        _integer(end),
    )


def _decision_key(row: dict[str, str]) -> tuple[str, str, int, int, int]:
    return (
        str(row.get("source", "") or ""),
        str(row.get("source_id", "") or ""),
        _integer(row.get("source_segment_index"), 0),
        _integer(row.get("expression_start")),
        _integer(row.get("expression_end")),
    )


def load_decisions(path: Path | None) -> dict[tuple[str, str, int, int, int], tuple[ReferenceDecision, ...]]:
    """Load expression-level audit decisions indexed by exact source offsets."""

    if path is None:
        return {}
    rows: dict[tuple[str, str, int, int, int], set[ReferenceDecision]] = defaultdict(set)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            key = _decision_key(row)
            if key[-2] < 0 or key[-1] < 0:
                continue
            rows[key].add(
                ReferenceDecision(
                    status=str(row.get("status", "") or ""),
                    route=str(row.get("route", "") or ""),
                    reason=str(row.get("reason", "") or ""),
                )
            )
    return {
        key: tuple(sorted(values, key=lambda item: (item.route, item.reason, item.status)))
        for key, values in rows.items()
    }


def load_hyphen_forms(path: Path | None) -> dict[str, HyphenForm]:
    if path is None:
        return {}
    forms: dict[str, HyphenForm] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            form = _fold(row.get("form", ""))
            if not form:
                continue
            forms[form] = HyphenForm(
                family=str(row.get("family", "") or ""),
                subtype=str(row.get("subtype", "") or ""),
                action=str(row.get("action", "") or ""),
                note=str(row.get("note", "") or ""),
            )
    return forms


def _stage_key(record: dict, span: dict) -> tuple[str, str, int, str, str, str]:
    return (
        str(record.get("source", "") or ""),
        str(record.get("source_id", "") or ""),
        _integer(record.get("source_segment_index"), 0),
        _fold(record.get("organ", "")),
        _fold(span.get("surface_form", "")),
        str(span.get("candidate_pato_id", "") or ""),
    )


def _stage_audit_key(row: dict[str, str]) -> tuple[str, str, int, str, str, str]:
    return (
        str(row.get("source", "") or ""),
        str(row.get("source_id", "") or ""),
        _integer(row.get("source_segment_index"), 0),
        _fold(row.get("organ", "")),
        _fold(row.get("surface_form", "")),
        str(row.get("candidate_pato_id", "") or ""),
    )


def load_stage_dispositions(path: Path | None) -> dict[tuple[str, str, int, str, str, str], deque[str]]:
    """Load retained developmental-stage audit dispositions as occurrence queues."""

    if path is None:
        return {}
    dispositions: dict[tuple[str, str, int, str, str, str], deque[str]] = defaultdict(deque)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            disposition = str(row.get("disposition", "") or "")
            if not disposition or disposition.startswith("recovered"):
                continue
            dispositions[_stage_audit_key(row)].append(disposition)
    return dict(dispositions)


def _word_character(char: str) -> bool:
    return char.isalpha() or char.isdigit() or char in COMPOUND_DASHES or char in "/'’"


def _grow_compound(text: str, left: int, right: int) -> tuple[int, int]:
    while left > 0 and _word_character(text[left - 1]):
        left -= 1
    while right < len(text) and _word_character(text[right]):
        right += 1
    return left, right


def compound_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Return the maximal hyphen/slash token containing a component span."""

    left, right = _grow_compound(text, start, end)
    for _ in range(4):
        grew = False
        suffix = text[right:]
        if right > 0 and text[right - 1] in COMPOUND_DASHES:
            match = re.match(r"^[ \t]+(?=[^\W\d])", suffix)
            if match:
                left, right = _grow_compound(text, left, right + match.end())
                grew = True
        if left > 0:
            match = re.search(
                rf"[^\W\d][\w'’]*[{re.escape(COMPOUND_DASHES)}][ \t]+$",
                text[:left],
            )
            if match:
                left, right = _grow_compound(text, match.start(), right)
                grew = True
        if not grew:
            break
    return left, right


def normalise_compound(value: str) -> str:
    return re.sub(rf"[\s{re.escape(COMPOUND_DASHES)}]+", " ", value.casefold()).strip()


def _decision_details(decisions: Iterable[ReferenceDecision]) -> tuple[set[str], set[str]]:
    routes = {decision.route for decision in decisions if decision.route}
    reasons = {decision.reason for decision in decisions if decision.reason}
    return routes, reasons


def _contains_any(values: set[str], fragments: Iterable[str]) -> bool:
    return any(fragment in value for fragment in fragments for value in values)


def classify_explicit_disjunction(
    span: dict,
    decisions: Iterable[ReferenceDecision],
) -> Classification:
    routes, reasons = _decision_details(decisions)
    detail = "|".join(sorted(routes | reasons))
    pato_id = str(span.get("candidate_pato_id", "") or "")
    basis = "explicit_disjunction_audit" if detail else "reason_fallback"

    if pato_id in NUMERIC_TRAIT_IDS:
        return Classification(
            "logical_expression_parser",
            "numeric_trait_disjunction",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if _contains_any(reasons, ("blocked_local", "heading_only", "multiple_local_bearers")):
        return Classification(
            "bearer_ontology_and_attachment",
            "disjunction_bearer_unresolved",
            "batch_ontology_then_rerun",
            "2_ontology_batch",
            basis,
            detail,
        )
    if _contains_any(reasons, ("different_explicit_bearers", "mixed_attribute_families")):
        return Classification(
            "semantic_decomposition_or_manual_review",
            "coordination_is_not_one_same_trait_union",
            "manual_or_multi_assertion_decomposition",
            "4_manual_review",
            basis,
            detail,
        )
    if _contains_any(reasons, ("non_distinct_operands",)):
        return Classification(
            "source_normalization",
            "degenerate_repeated_disjunct",
            "automatic_cleanup_rule",
            "1_quick_win",
            basis,
            detail,
        )
    if _contains_any(reasons, ("transition_context",)):
        return Classification(
            "logical_expression_parser",
            "qualitative_range_or_transition",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if _contains_any(reasons, ("developmental_stage_context",)):
        return Classification(
            "context_annotation_model",
            "stage_scoped_disjunction",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if _contains_any(reasons, ("locative_subregion_scope",)):
        return Classification(
            "bearer_ontology_and_attachment",
            "locative_subregion_disjunction",
            "relation_and_bearer_model_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if _contains_any(reasons, ("comparative_context",)):
        return Classification(
            "semantic_decomposition_or_manual_review",
            "comparative_not_value_union",
            "manual_occurrence_review",
            "4_manual_review",
            basis,
            detail,
        )
    if _contains_any(
        reasons,
        (
            "ungrounded_operand",
            "modified_or_ungrounded",
            "incomplete_adjacent_alternative",
            "unsupported_same_attribute_preceding_value",
            "modified_first_operand",
            "qualified_or_incomplete_final_operand",
            "nonexhaustive_same_family_alternative",
        ),
    ):
        return Classification(
            "lexicon_or_ontology_term",
            "disjunction_operand_not_normalized",
            "batch_vocabulary_curation_then_rerun",
            "2_ontology_batch",
            basis,
            detail,
        )
    return Classification(
        "logical_expression_parser",
        "explicit_disjunction_pending_complete_grounding",
        "schema_or_parser_extension",
        "3_model_extension",
        basis,
        detail,
    )


def classify_residual_logic(
    original_reason: str,
    decisions: Iterable[ReferenceDecision],
) -> Classification:
    routes, reasons = _decision_details(decisions)
    detail = "|".join(sorted(routes | reasons))
    basis = "residual_logic_audit" if detail else "reason_fallback"

    if "bearer_review" in routes:
        return Classification(
            "bearer_ontology_and_attachment",
            "logical_expression_bearer_unresolved",
            "batch_ontology_then_rerun",
            "2_ontology_batch",
            basis,
            detail,
        )
    if "locative_context" in routes:
        return Classification(
            "bearer_ontology_and_attachment",
            "locative_or_subregion_relation",
            "relation_and_bearer_model_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if "numeric_or_cardinality_context" in routes:
        return Classification(
            "logical_expression_parser",
            "numeric_or_cardinality_expression",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if "temporal_or_developmental" in routes:
        return Classification(
            "context_annotation_model",
            "temporal_or_developmental_transition",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if "modality_or_negation" in routes:
        return Classification(
            "context_annotation_model",
            "modality_or_negation_scope",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if "qualitative_range_or_transition" in routes:
        if _contains_any(reasons, ("not_fully_grounded", "ungrounded")):
            return Classification(
                "lexicon_or_ontology_term",
                "qualitative_range_endpoint_not_normalized",
                "batch_vocabulary_curation_then_rerun",
                "2_ontology_batch",
                basis,
                detail,
            )
        return Classification(
            "logical_expression_parser",
            "qualitative_range_or_transition",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            detail,
        )
    if routes & {
        "adjacent_or_composite_review",
        "unmodeled_same_attribute_neighbor",
        "hyphen_or_slash_expression",
    }:
        return Classification(
            "lexicon_or_ontology_term",
            "same_attribute_compound_or_neighbor_not_normalized",
            "batch_vocabulary_curation_then_rerun",
            "2_ontology_batch",
            basis,
            detail,
        )
    if "logical_expression_review" in routes:
        return Classification(
            "logical_expression_parser",
            "incomplete_or_mixed_logical_expression",
            "parser_extension_then_targeted_review",
            "3_model_extension",
            basis,
            detail,
        )
    fallback = {
        "same_attribute_composite_or_transition": (
            "lexicon_or_ontology_term",
            "same_attribute_compound_or_transition",
            "batch_vocabulary_curation_then_rerun",
            "2_ontology_batch",
        ),
        "unsupported_same_attribute_neighbor": (
            "lexicon_or_ontology_term",
            "same_attribute_neighbor_not_normalized",
            "batch_vocabulary_curation_then_rerun",
            "2_ontology_batch",
        ),
        "unsupported_alternative_or_transition": (
            "logical_expression_parser",
            "alternative_or_transition_unclassified",
            "parser_extension_then_targeted_review",
            "3_model_extension",
        ),
    }
    initiative, subtype, actionability, priority = fallback[original_reason]
    return Classification(initiative, subtype, actionability, priority, basis, detail)


def classify_hyphen(form: HyphenForm | None, token: str) -> Classification:
    if form is None:
        return Classification(
            "lexicon_or_ontology_term",
            "hyphen_or_slash_form_not_in_inventory",
            "batch_vocabulary_curation_then_rerun",
            "2_ontology_batch",
            "compound_fallback",
            token,
        )
    family = form.family
    detail = "|".join(value for value in (family, form.subtype, form.action) if value)
    if family == "F1_atomic_pato":
        return Classification(
            "source_normalization",
            "existing_atomic_pato_whole_token",
            "automatic_compound_lexing_rule",
            "1_quick_win",
            "hyphen_form_audit",
            detail,
        )
    if family == "F2_atomic_flopo":
        return Classification(
            "bearer_ontology_and_attachment",
            "existing_flopo_value_needs_safe_bearer",
            "bearer_rule_then_reuse_existing_flopo",
            "2_ontology_batch",
            "hyphen_form_audit",
            detail,
        )
    if family == "F3_ocr_rejoin":
        return Classification(
            "source_normalization",
            "ocr_or_tokenization_reconstruction",
            "automatic_cleanup_rule",
            "1_quick_win",
            "hyphen_form_audit",
            detail,
        )
    if family == "F11_singleton":
        # A leading bare dash normally elides the first component of the preceding alternative:
        # ``oblong-ovate to -elliptic`` means ``... to oblong-elliptic``. Reconstructing that
        # inherited prefix is logical coordination work, not an OCR spelling repair and not an
        # unconditional assertion of the visible suffix alone.
        return Classification(
            "logical_expression_parser",
            "elliptical_compound_shorthand",
            "reconstruct_elided_prefix_then_parse_expression",
            "3_model_extension",
            "hyphen_form_audit",
            detail,
        )
    if family == "F8_numeric_morphology":
        return Classification(
            "logical_expression_parser",
            "numeric_prefixed_morphology",
            "schema_or_parser_extension",
            "3_model_extension",
            "hyphen_form_audit",
            detail,
        )
    if family == "F10_slash":
        return Classification(
            "semantic_decomposition_or_manual_review",
            "slash_alternative_pattern_or_fraction",
            "manual_occurrence_review",
            "4_manual_review",
            "hyphen_form_audit",
            detail,
        )
    if family == "F12_cross_attr_other":
        return Classification(
            "semantic_decomposition_or_manual_review",
            "cross_attribute_compound",
            "manual_or_multi_assertion_decomposition",
            "4_manual_review",
            "hyphen_form_audit",
            detail,
        )
    return Classification(
        "lexicon_or_ontology_term",
        "reusable_hyphenated_descriptor_term",
        "batch_vocabulary_curation_then_rerun",
        "2_ontology_batch",
        "hyphen_form_audit",
        detail,
    )


def classify_stage(disposition: str) -> Classification:
    basis = "developmental_stage_audit" if disposition else "reason_fallback"
    if disposition == "retained_no_bearer":
        return Classification(
            "bearer_ontology_and_attachment",
            "stage_expression_missing_bearer",
            "batch_ontology_then_rerun",
            "2_ontology_batch",
            basis,
            disposition,
        )
    if disposition == "r2_not_atomic_safe":
        return Classification(
            "logical_expression_parser",
            "complex_stage_scoped_expression",
            "schema_or_parser_extension",
            "3_model_extension",
            basis,
            disposition,
        )
    if disposition == "r2_member_conditioned":
        subtype = "stage_conditioned_coordination_member"
    elif disposition == "r2_disjunction_clause":
        subtype = "stage_scoped_disjunction"
    elif disposition == "r2_transition_clause":
        subtype = "stage_transition"
    elif disposition:
        subtype = "developmental_stage_scope_ambiguous"
    else:
        subtype = "developmental_stage_context_unclassified"
    return Classification(
        "context_annotation_model",
        subtype,
        "schema_or_parser_extension",
        "3_model_extension",
        basis,
        disposition,
    )


_INDUMENT_BEARER = re.compile(
    r"\b(?:hairs?|trichomes?|poils?|tomentum|pubescence|velours|bristles?|awns?|"
    r"ar[êe]tes?)\b",
    re.IGNORECASE,
)
_MARKING_BEARER = re.compile(
    r"\b(?:spots?|patch(?:es)?|blotches?|streaks?|bands?|mottl(?:e|ed|es|ing)|"
    r"taches?|bandes?|stries?|mouchet[ée](?:e?s?)?)\b",
    re.IGNORECASE,
)
_SUBREGION_BEARER = re.compile(
    r"\b(?:apex|base|tip|margin|margins|edge|edges|surface|surfaces|face|faces|"
    r"throat|throats|centre|center|sommet|sommets|marge|marges|bord|bords|"
    r"gorge|gorges|dessus|dessous|int[ée]rieur(?:e|es|s)?|"
    r"ext[ée]rieur(?:e|es|s)?)\b",
    re.IGNORECASE,
)
_LOCAL_ANATOMY = re.compile(
    r"\b(?:lobes?|scales?|paillettes?|axes?|axis|walls?|parois?|paraphyses?|"
    r"acumens?|locules?|loges?|angles?|articles?|rhizophores?|sporocarps?|"
    r"sporocarpes?|pulp|pulpe|veins?|nerves?|nervures?)\b",
    re.IGNORECASE,
)
_GENERIC_SECTION_HEADINGS = frozenset(
    {
        "",
        "description",
        "descriptions",
        "general description",
        "diagnosis",
        "dimensions",
        "habit",
        "port",
    }
)
_QUALIFIED_BEARER_HEADING = re.compile(
    r"(?<!\w)(?:male|female|staminate|pistillate|fertile|sterile|m[âa]le|femelle|"
    r"fructif(?:erous|ère|ères)|♂|♀)(?!\w)",
    re.IGNORECASE,
)


def _clause(record: dict, span: dict) -> str:
    text = str(record.get("text", "") or "")
    clause, _left = baseline._clause_at(text, _integer(span.get("start"), 0))
    return clause


def _pattern_matches(patterns: Iterable[tuple], clause: str) -> list[tuple]:
    return [row for row in patterns if row[1].search(clause)]


def classify_missing_bearer(record: dict, span: dict) -> Classification:
    clause = _clause(record, span)
    pato_id = str(span.get("candidate_pato_id", "") or "")
    local = _pattern_matches(baseline.LOCAL_BEARER_PATTERNS, clause)
    contextual = _pattern_matches(baseline.CONTEXTUAL_BEARER_PATTERNS, clause)
    unresolved = [pattern for pattern in baseline.UNRESOLVED_BEARER_PATTERNS if pattern.search(clause)]
    organ = str(record.get("organ", "") or "")
    heading_po = baseline._organ_to_po(organ)

    if _MARKING_BEARER.search(clause):
        subtype = "marking_or_pattern_bearer_relation"
    elif _INDUMENT_BEARER.search(clause):
        subtype = "indument_or_trichome_bearer_relation"
    elif _SUBREGION_BEARER.search(clause):
        subtype = "local_subregion_bearer_or_parthood"
    elif _LOCAL_ANATOMY.search(clause):
        subtype = "missing_local_anatomy_bearer"
    elif len({row[0] for row in local}) > 1:
        return Classification(
            "semantic_decomposition_or_manual_review",
            "multiple_candidate_bearers",
            "manual_attachment_review",
            "4_manual_review",
            "bearer_context_rule",
            f"local_po_candidates={len({row[0] for row in local})}",
        )
    elif contextual and all(pato_id not in row[2] for row in contextual):
        subtype = "contextual_bearer_quality_mismatch"
    elif unresolved:
        subtype = "unsupported_local_bearer"
    elif local:
        subtype = "local_bearer_attachment_ambiguous"
    elif not heading_po and _fold(organ) in _GENERIC_SECTION_HEADINGS:
        return Classification(
            "bearer_ontology_and_attachment",
            "free_text_description_requires_local_bearer",
            "local_bearer_parser_extension",
            "3_model_extension",
            "bearer_context_rule",
            f"organ={organ or '<empty>'};local=0;blocked=0",
        )
    elif not heading_po and _QUALIFIED_BEARER_HEADING.search(organ):
        return Classification(
            "context_annotation_model",
            "sex_or_state_qualified_bearer_heading",
            "qualified_bearer_context_rule",
            "3_model_extension",
            "bearer_context_rule",
            f"organ={organ};local=0;blocked=0",
        )
    elif not heading_po:
        subtype = "organ_heading_not_grounded_to_po"
    else:
        subtype = "elliptical_or_coordinated_bearer_scope"
    return Classification(
        "bearer_ontology_and_attachment",
        subtype,
        "batch_ontology_and_attachment_rules",
        "2_ontology_batch",
        "bearer_context_rule",
        f"heading_po={heading_po};local={len(local)};contextual={len(contextual)};blocked={len(unresolved)}",
    )


_NEGATION_CUE = re.compile(
    r"(?<!\w)(?:not|never|no|without|non|sans|ni|pas|jamais)(?!\w)",
    re.IGNORECASE,
)


def classify_negation(record: dict, span: dict) -> Classification:
    residual_reason = str(span.get("negation_residual_reason", "") or "")
    pending_bearer = str(span.get("pending_bearer", "") or "")
    detail = residual_reason or str(span.get("negation_residual_detail", "") or "")
    if pending_bearer or "bearer" in residual_reason:
        return Classification(
            "bearer_ontology_and_attachment",
            "negated_expression_pending_local_bearer",
            "batch_ontology_then_rerun",
            "2_ontology_batch",
            "negation_residual_metadata",
            pending_bearer or detail,
        )
    if residual_reason:
        return Classification(
            "semantic_decomposition_or_manual_review",
            "reviewed_negation_hold_or_partial_residual",
            "manual_occurrence_review",
            "4_manual_review",
            "negation_residual_metadata",
            detail,
        )
    clause = _clause(record, span)
    cue_count = len(_NEGATION_CUE.findall(clause))
    bearer_class = classify_missing_bearer(record, span)
    if bearer_class.subtype not in {
        "elliptical_or_coordinated_bearer_scope",
        "organ_heading_not_grounded_to_po",
    }:
        return Classification(
            "bearer_ontology_and_attachment",
            "negation_bearer_or_scope_unresolved",
            "batch_ontology_then_negation_rerun",
            "2_ontology_batch",
            "negation_context_rule",
            f"cues={cue_count};{bearer_class.subtype}",
        )
    return Classification(
        "context_annotation_model",
        "negated_quality_class_description",
        "negation_parser_and_scope_rule",
        "3_model_extension",
        "negation_context_rule",
        f"cues={cue_count}",
    )


def classify_span(
    record: dict,
    span: dict,
    *,
    explicit_decisions: dict[tuple[str, str, int, int, int], tuple[ReferenceDecision, ...]],
    logical_decisions: dict[tuple[str, str, int, int, int], tuple[ReferenceDecision, ...]],
    hyphen_forms: dict[str, HyphenForm],
    stage_dispositions: dict[tuple[str, str, int, str, str, str], deque[str]],
) -> tuple[Classification, str]:
    reason = str(span.get("reason", "") or "")
    key = _span_key(record, span.get("start"), span.get("end"))
    if reason == "explicit_disjunction":
        return classify_explicit_disjunction(span, explicit_decisions.get(key, ())), ""
    if reason in {
        "same_attribute_composite_or_transition",
        "unsupported_same_attribute_neighbor",
        "unsupported_alternative_or_transition",
    }:
        return classify_residual_logic(reason, logical_decisions.get(key, ())), ""
    if reason == "hyphenated_or_slash_compound":
        text = str(record.get("text", "") or "")
        start = _integer(span.get("start"), 0)
        end = _integer(span.get("end"), start)
        left, right = compound_bounds(text, start, end)
        token = text[left:right]
        form = hyphen_forms.get(normalise_compound(token))
        return classify_hyphen(form, token), token
    if reason == "developmental_stage_context":
        queue = stage_dispositions.get(_stage_key(record, span))
        disposition = queue.popleft() if queue else ""
        return classify_stage(disposition), ""
    if reason == "missing_or_unsupported_bearer":
        return classify_missing_bearer(record, span), ""
    if reason == "negated_context":
        return classify_negation(record, span), ""
    return (
        Classification(
            "semantic_decomposition_or_manual_review",
            "unknown_residual_reason",
            "manual_occurrence_review",
            "4_manual_review",
            "unknown_fallback",
            reason,
        ),
        "",
    )


def _context(text: str, start: int, end: int, radius: int = 90) -> str:
    snippet = text[max(0, start - radius) : min(len(text), end + radius)]
    return re.sub(r"\s+", " ", snippet).strip()


def _percentage(count: int, total: int) -> str:
    return f"{100 * count / total:.1f}%" if total else "0.0%"


def _markdown_table(headers: list[str], rows: Iterable[Iterable[object]]) -> list[str]:
    output = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        output.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return output


def write_markdown(summary: dict, path: Path) -> None:
    total = int(summary["total_spans"])
    lines = [
        "# Actionable classification of unresolved FLOPO spans",
        "",
        f"Total classified spans: **{total:,}**. Classification is read-only and preserves the original evidence.",
        "",
        "## Work packages",
        "",
    ]
    initiative_rows = [
        (name, f"{count:,}", _percentage(count, total))
        for name, count in summary["by_initiative"].items()
    ]
    lines.extend(_markdown_table(["Initiative", "Spans", "Share"], initiative_rows))
    lines.extend(["", "## Largest actionable subtypes", ""])
    subtype_rows = [
        (
            subtype,
            meta["initiative"],
            meta["priority"],
            f"{meta['count']:,}",
            f"{meta['distinct_surface_forms']:,}",
            _percentage(meta["count"], total),
        )
        for subtype, meta in list(summary["subtypes"].items())[:40]
    ]
    lines.extend(
        _markdown_table(
            ["Subtype", "Initiative", "Priority", "Spans", "Observed forms", "Share"],
            subtype_rows,
        )
    )
    lines.extend(["", "## Original extraction reasons", ""])
    reason_rows = [
        (reason, f"{count:,}", _percentage(count, total))
        for reason, count in summary["by_original_reason"].items()
    ]
    lines.extend(_markdown_table(["Original reason", "Spans", "Share"], reason_rows))
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `1_quick_win`: deterministic tokenization, reuse, or cleanup work.",
            "- `2_ontology_batch`: vocabulary, bearer, parthood, or attachment curation followed by rerunning deterministic recovery.",
            "- `3_model_extension`: add or improve OWL class-expression, context, range, stage, or negation parsing.",
            "- `4_manual_review`: mixed-character coordination or occurrence-level ambiguity that should not be bulk-promoted.",
            "",
            "Counts are spans, not unique expressions. Hyphenated compounds often contribute two component spans; grouped-form curation therefore resolves more than one span per ontology decision.",
            "For disjunction/range rows, `Observed forms` counts the already-grounded component span, not necessarily the missing neighbouring operand; use the per-span context when building a vocabulary queue.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def classify_file(
    input_path: Path,
    output_tsv: Path,
    summary_path: Path,
    *,
    explicit_decisions_path: Path | None = None,
    logical_decisions_path: Path | None = None,
    hyphen_forms_path: Path | None = None,
    stage_audit_path: Path | None = None,
    markdown_path: Path | None = None,
    expected_total: int | None = None,
    seed: int = 20260719,
) -> dict:
    explicit_decisions = load_decisions(explicit_decisions_path)
    logical_decisions = load_decisions(logical_decisions_path)
    hyphen_forms = load_hyphen_forms(hyphen_forms_path)
    stage_dispositions = load_stage_dispositions(stage_audit_path)

    by_reason: Counter[str] = Counter()
    by_initiative: Counter[str] = Counter()
    by_subtype: Counter[str] = Counter()
    by_actionability: Counter[str] = Counter()
    by_priority: Counter[str] = Counter()
    by_basis: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    initiative_by_reason: dict[str, Counter[str]] = defaultdict(Counter)
    subtype_surfaces: dict[str, Counter[str]] = defaultdict(Counter)
    subtype_organs: dict[str, Counter[str]] = defaultdict(Counter)
    subtype_pato_ids: dict[str, Counter[str]] = defaultdict(Counter)
    subtype_meta: dict[str, Classification] = {}
    examples: dict[str, list[dict]] = defaultdict(list)
    example_seen: Counter[str] = Counter()
    rng = random.Random(seed)
    records = 0
    records_with_unresolved = 0
    total = 0

    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open(encoding="utf-8") as source, output_tsv.open(
        "w", encoding="utf-8", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=SPAN_FIELDS, delimiter="\t")
        writer.writeheader()
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            records += 1
            spans = record.get("unresolved_spans", []) or []
            if spans:
                records_with_unresolved += 1
            text = str(record.get("text", "") or "")
            for span in spans:
                classification, compound_token = classify_span(
                    record,
                    span,
                    explicit_decisions=explicit_decisions,
                    logical_decisions=logical_decisions,
                    hyphen_forms=hyphen_forms,
                    stage_dispositions=stage_dispositions,
                )
                total += 1
                reason = str(span.get("reason", "") or "")
                surface = str(span.get("surface_form", "") or "")
                start = _integer(span.get("start"))
                end = _integer(span.get("end"))
                by_reason[reason] += 1
                by_initiative[classification.initiative] += 1
                by_subtype[classification.subtype] += 1
                by_actionability[classification.actionability] += 1
                by_priority[classification.priority] += 1
                by_basis[classification.basis] += 1
                by_source[str(record.get("source", "") or "")] += 1
                initiative_by_reason[reason][classification.initiative] += 1
                subtype_surfaces[classification.subtype][
                    normalise_compound(compound_token) if compound_token else _fold(surface)
                ] += 1
                subtype_organs[classification.subtype][
                    str(record.get("organ", "") or "<empty>")
                ] += 1
                subtype_pato_ids[classification.subtype][
                    str(span.get("candidate_pato_id", "") or "<empty>")
                ] += 1
                subtype_meta.setdefault(classification.subtype, classification)
                context = _context(text, start, end)
                row = {
                    "source": record.get("source", ""),
                    "source_id": record.get("source_id", ""),
                    "source_segment_index": record.get("source_segment_index", 0),
                    "taxon": record.get("taxon", ""),
                    "organ": record.get("organ", ""),
                    "language": record.get("language", ""),
                    "span_start": start,
                    "span_end": end,
                    "surface_form": surface,
                    "candidate_pato_id": span.get("candidate_pato_id", ""),
                    "original_reason": reason,
                    "initiative": classification.initiative,
                    "subtype": classification.subtype,
                    "actionability": classification.actionability,
                    "priority": classification.priority,
                    "classification_basis": classification.basis,
                    "reference_detail": classification.detail,
                    "context": context,
                }
                writer.writerow(row)

                subtype = classification.subtype
                example_seen[subtype] += 1
                example = {
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "source_segment_index": row["source_segment_index"],
                    "taxon": row["taxon"],
                    "organ": row["organ"],
                    "surface_form": surface,
                    "candidate_pato_id": row["candidate_pato_id"],
                    "context": context,
                    "reference_detail": classification.detail,
                }
                if len(examples[subtype]) < 5:
                    examples[subtype].append(example)
                else:
                    position = rng.randint(1, example_seen[subtype])
                    if position <= 5:
                        examples[subtype][position - 1] = example

    if expected_total is not None and total != expected_total:
        raise ValueError(f"expected {expected_total} unresolved spans, classified {total}")

    unused_stage_rows = sum(len(queue) for queue in stage_dispositions.values())
    ordered_subtypes = sorted(by_subtype, key=lambda name: (-by_subtype[name], name))
    summary = {
        "input": str(input_path),
        "output_tsv": str(output_tsv),
        "records": records,
        "records_with_unresolved": records_with_unresolved,
        "total_spans": total,
        "accounting_ok": expected_total is None or total == expected_total,
        "by_original_reason": dict(by_reason.most_common()),
        "by_initiative": dict(by_initiative.most_common()),
        "by_priority": dict(sorted(by_priority.items())),
        "by_actionability": dict(by_actionability.most_common()),
        "by_classification_basis": dict(by_basis.most_common()),
        "by_source": dict(by_source.most_common()),
        "initiative_by_original_reason": {
            reason: dict(counts.most_common()) for reason, counts in sorted(initiative_by_reason.items())
        },
        "subtypes": {
            subtype: {
                "count": by_subtype[subtype],
                "initiative": subtype_meta[subtype].initiative,
                "actionability": subtype_meta[subtype].actionability,
                "priority": subtype_meta[subtype].priority,
                "distinct_surface_forms": len(subtype_surfaces[subtype]),
                "top_surface_forms": dict(subtype_surfaces[subtype].most_common(12)),
                "top_organs": dict(subtype_organs[subtype].most_common(12)),
                "top_candidate_pato_ids": dict(subtype_pato_ids[subtype].most_common(12)),
                "examples": examples[subtype],
            }
            for subtype in ordered_subtypes
        },
        "reference_accounting": {
            "explicit_decision_keys": len(explicit_decisions),
            "logical_decision_keys": len(logical_decisions),
            "hyphen_forms": len(hyphen_forms),
            "unused_retained_stage_audit_rows": unused_stage_rows,
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(summary, markdown_path)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify retained unresolved flora spans into actionable work packages."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output-tsv", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--explicit-decisions", type=Path)
    parser.add_argument("--logical-decisions", type=Path)
    parser.add_argument("--hyphen-forms", type=Path)
    parser.add_argument("--stage-audit", type=Path)
    parser.add_argument("--expect-total", type=int)
    parser.add_argument("--seed", type=int, default=20260719)
    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = classify_file(
        args.input,
        args.output_tsv,
        args.summary,
        explicit_decisions_path=args.explicit_decisions,
        logical_decisions_path=args.logical_decisions,
        hyphen_forms_path=args.hyphen_forms,
        stage_audit_path=args.stage_audit,
        markdown_path=args.markdown,
        expected_total=args.expect_total,
        seed=args.seed,
    )
    destination = stdout
    if destination is None:
        import sys

        destination = sys.stdout
    print(
        json.dumps(
            {
                "records": summary["records"],
                "total_spans": summary["total_spans"],
                "accounting_ok": summary["accounting_ok"],
                "by_initiative": summary["by_initiative"],
                "by_priority": summary["by_priority"],
                "output_tsv": str(args.output_tsv),
                "summary": str(args.summary),
                "markdown": str(args.markdown) if args.markdown else None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        file=destination,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
