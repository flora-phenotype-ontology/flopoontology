"""Recover conservative logical class descriptions from residual baseline evidence.

The deterministic baseline deliberately withholds several superficially similar source
constructions under three broad reasons.  Those reasons contain genuine alternatives,
conjunctions, qualitative ranges, temporal transitions, locatives, and ambiguous lexical
compounds.  This pass promotes only the first two:

* ``or``/``ou`` becomes ``value_operator=one_of``;
* ``and``/``et`` becomes ``value_operator=all_of``; and
* every operand must be a PATO preferred label or EXACT synonym in one reviewed attribute
  family and must attach to the same explicit occurrence of a PO bearer.

Everything else remains unresolved and receives a lossless route in the audit TSV.  The
resulting logical assertion is an arbitrary OWL class description.  It receives a ``FAC_`` IRI
only in the downstream annotation-extension build and never mints a FLOPO identifier here.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from flopo2.extract import baseline
from flopo2.verify.recover_explicit_unions import (
    ATTRIBUTE_BY_FAMILY,
    ExactPatoValueLexicon,
    ValueMatch,
    _ambiguous_local_bearers,
    _bearer_scope_reason,
    _expression_bounds,
    _operand_context_reason,
    _resolve_explicit_bearer,
)


TARGET_REASONS = frozenset(
    {
        "same_attribute_composite_or_transition",
        "unsupported_same_attribute_neighbor",
        "unsupported_alternative_or_transition",
    }
)
EXTRACTOR = "deterministic_exact_pato_residual_logic_recovery"
_LOGICAL_CONNECTOR = re.compile(r"\b(?P<connector>or|ou|and|et)\b", re.IGNORECASE)
_STRICT_FILLER = re.compile(r"[\s,()\[\]{}]*")
_COMMA = re.compile(r"\s*,\s*")
_RANGE_CONNECTOR = re.compile(
    r"\b(?:to|through|vers|jusqu['’]?à|jusqu['’]?a|à|au)\b", re.IGNORECASE
)
_NUMERIC = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?:\s*[–—-]\s*\d+(?:[.,]\d+)?)?")
_TEMPORAL = re.compile(
    r"\b(?:turn(?:s|ed|ing)?|becom(?:e|es|ing)|matur(?:e|es|ing)|ripen(?:s|ed|ing)?|"
    r"later|eventually|subsequently|initially|at\s+first|when\s+(?:young|mature|ripe)|"
    r"at\s+maturity|young|immature|ripe|unripe|"
    r"dev(?:ient|enant)|puis|ensuite|ult[ée]rieurement|d['’]abord|"
    r"à\s+maturit[ée]|a\s+maturite|m[ûu]r(?:e|es|s)?)\b",
    re.IGNORECASE,
)
_TEMPORAL_TRANSITION_LEFT = re.compile(
    r"\b(?:turn(?:s|ed|ing)?|becom(?:e|es|ing)|ripen(?:s|ed|ing)?|"
    r"dev(?:ient|enant)|puis|ensuite)\s*$",
    re.IGNORECASE,
)
_TEMPORAL_TRANSITION_RIGHT = re.compile(
    r"^\s*,?\s*(?:turn(?:s|ed|ing)?|becom(?:e|es|ing)|ripen(?:s|ed|ing)?|"
    r"dev(?:ient|enant)|puis|ensuite)\b",
    re.IGNORECASE,
)
_STAGE_ATTACHMENT_LEFT = re.compile(
    r"\b(?:initially|at\s+first|when\s+(?:young|mature|ripe)|at\s+maturity|"
    r"d['’]abord|à\s+maturit[ée])(?:\s+\w+){0,2}\s*$",
    re.IGNORECASE,
)
_STAGE_ATTACHMENT_RIGHT = re.compile(
    r"^\s*(?:[,()]\s*)?(?:especially\s+)?(?:when\s+(?:young|mature|ripe|unripe)|"
    r"at\s+maturity|à\s+maturit[ée])\b",
    re.IGNORECASE,
)
_LOCATIVE = re.compile(
    r"\b(?:at|on|in|inside|outside|within|along|near|towards?|around|sur|dans|"
    r"en|vers|au|aux|à)\s+(?:the\s+|l['’]|la\s+|le\s+|les\s+|leur\s+|sa\s+)?"
    r"(?:apex|apices|base|bases|tip|tips|surface|surfaces|face|faces|side|sides|"
    r"margin|margins|edge|edges|inside|outside|interior|exterior|top|bottom|"
    r"sommet|sommets|base|bases|extr[ée]mit[ée]s?|int[ée]rieur(?:e|es|s)?|"
    r"ext[ée]rieur(?:e|es|s)?|bord|bords|marge|marges|dessus|dessous)\b",
    re.IGNORECASE,
)
_ADJACENT_RANGE_LEFT = re.compile(
    r"\b(?P<connector>to|through|vers|jusqu['’]?à|jusqu['’]?a|à|au)\s*$",
    re.IGNORECASE,
)
_ADJACENT_RANGE_RIGHT = re.compile(
    r"^\s*(?P<connector>to|through|vers|jusqu['’]?à|jusqu['’]?a|à|au)\b",
    re.IGNORECASE,
)
_ADJACENT_LOGIC_LEFT = re.compile(r"\b(?P<connector>or|ou|and|et)\s*$", re.IGNORECASE)
_ADJACENT_LOGIC_RIGHT = re.compile(r"^\s*(?P<connector>or|ou|and|et)\b", re.IGNORECASE)
_TOUCHING_COMPOUND = re.compile(r"[-–—/]\s*$|^\s*[-–—/]")
_BEARER_FAILURES = frozenset(
    {
        "blocked_local",
        "heading_only_or_missing",
        "different_explicit_bearers",
        "multiple_local_bearers",
        "distant_local_bearer",
        "unsupported_subregion_or_bearer",
        "unsupported_preceding_subregion_or_bearer",
        "intervening_relational_object_bearer",
        "qualified_bearer_subregion",
        "qualified_bearer_subset",
        "postposed_bearer_after_delimiter",
    }
)


@dataclass(frozen=True)
class LogicEdge:
    operator: str
    connector_start: int
    connector_end: int
    left: ValueMatch | None
    right: ValueMatch | None
    reason: str = ""


@dataclass(frozen=True)
class LogicCandidate:
    operator: str
    values: tuple[ValueMatch, ...]
    connector_starts: tuple[int, ...]
    expression_start: int
    expression_end: int

    @property
    def start(self) -> int:
        return self.expression_start

    @property
    def end(self) -> int:
        return self.expression_end


@dataclass(frozen=True)
class Decision:
    status: str
    route: str
    reason: str
    source: str
    source_id: str
    source_segment_index: object
    taxon: str
    organ: str
    language: str
    expression_start: int
    expression_end: int
    expression_text: str
    source_context: str
    input_reasons: tuple[str, ...] = ()
    operator: str = ""
    family: str = ""
    attribute_pato_id: str = ""
    value_terms: tuple[str, ...] = ()
    value_labels: tuple[str, ...] = ()
    value_source_forms: tuple[str, ...] = ()
    bearer_po_id: str = ""
    bearer_method: str = ""
    bearer_surface: str = ""
    bearer_start: int = -1
    bearer_end: int = -1
    resolved_unresolved_spans: int = 0

    @property
    def arity(self) -> int:
        return len(self.value_terms)


DECISION_FIELDS = [
    "status",
    "route",
    "reason",
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "language",
    "expression_start",
    "expression_end",
    "expression_text",
    "source_context",
    "input_reasons",
    "operator",
    "family",
    "attribute_pato_id",
    "arity",
    "value_terms",
    "value_labels",
    "value_source_forms",
    "bearer_po_id",
    "bearer_method",
    "bearer_surface",
    "bearer_start",
    "bearer_end",
    "resolved_unresolved_spans",
]
SAMPLE_FIELDS = [
    *DECISION_FIELDS,
    "semantic_judgment",
    "bearer_judgment",
    "completeness_judgment",
    "review_note",
]


def load_locative_keys(path: Path | None) -> frozenset[tuple[str, str, int, int, int, str]]:
    """Load the independently audited locative rows that are out of this pass's scope."""

    if path is None or not Path(path).exists():
        return frozenset()
    keys: set[tuple[str, str, int, int, int, str]] = set()
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("proposed_reason") != "locative_context":
                continue
            keys.add(
                (
                    str(row.get("source", "")),
                    str(row.get("source_id", "")),
                    int(row.get("source_segment_index", 0) or 0),
                    int(row.get("span_start", -1) or -1),
                    int(row.get("span_end", -1) or -1),
                    str(row.get("proposed_pato_id", "")),
                )
            )
    return frozenset(keys)


def _span_key(record: dict, span: dict) -> tuple[str, str, int, int, int, str]:
    return (
        str(record.get("source", "")),
        str(record.get("source_id", "")),
        int(record.get("source_segment_index", 0) or 0),
        int(span.get("start", -1) or -1),
        int(span.get("end", -1) or -1),
        str(span.get("candidate_pato_id", "")),
    )


def _operator(source_form: str) -> str:
    return "one_of" if source_form.casefold() in {"or", "ou"} else "all_of"


def _logic_edges(
    text: str,
    clause_start: int,
    clause_end: int,
    values: list[ValueMatch],
) -> list[LogicEdge]:
    edges: list[LogicEdge] = []
    for connector in _LOGICAL_CONNECTOR.finditer(text, clause_start, clause_end):
        left_values = [value for value in values if value.end <= connector.start()]
        right_values = [value for value in values if connector.end() <= value.start]
        left = max(left_values, key=lambda value: value.end) if left_values else None
        right = min(right_values, key=lambda value: value.start) if right_values else None
        reason = ""
        if left is None or right is None:
            reason = "ungrounded_operand"
        elif left.value.family != right.value.family:
            reason = "mixed_attribute_families"
        elif left.value.pato_id == right.value.pato_id:
            reason = "non_distinct_operands"
        elif not _STRICT_FILLER.fullmatch(text[left.end : connector.start()]):
            reason = "modified_or_ungrounded_left_operand"
        elif not _STRICT_FILLER.fullmatch(text[connector.end() : right.start]):
            reason = "modified_or_ungrounded_right_operand"
        edges.append(
            LogicEdge(
                _operator(connector.group("connector")),
                connector.start(),
                connector.end(),
                left,
                right,
                reason,
            )
        )
    return edges


def _logic_candidates(
    text: str,
    values: list[ValueMatch],
    edges: list[LogicEdge],
) -> list[LogicCandidate]:
    value_index = {
        (value.start, value.end, value.value.pato_id): index for index, value in enumerate(values)
    }
    candidates: list[LogicCandidate] = []
    for operator in ("one_of", "all_of"):
        adjacency: dict[int, set[int]] = defaultdict(set)
        for edge in edges:
            if edge.operator != operator or edge.reason or edge.left is None or edge.right is None:
                continue
            left_index = value_index[(edge.left.start, edge.left.end, edge.left.value.pato_id)]
            right_index = value_index[(edge.right.start, edge.right.end, edge.right.value.pato_id)]
            adjacency[left_index].add(right_index)
            adjacency[right_index].add(left_index)

            # Preserve exact comma-list operands: ``red, white or blue``.
            cursor = left_index
            while cursor > 0:
                previous = cursor - 1
                if (
                    adjacency.get(previous)
                    or values[previous].value.family != values[cursor].value.family
                    or not _COMMA.fullmatch(text[values[previous].end : values[cursor].start])
                ):
                    break
                adjacency[previous].add(cursor)
                adjacency[cursor].add(previous)
                cursor = previous

        visited: set[int] = set()
        for root in sorted(adjacency):
            if root in visited:
                continue
            pending = [root]
            component: set[int] = set()
            while pending:
                index = pending.pop()
                if index in component:
                    continue
                component.add(index)
                pending.extend(adjacency[index])
            visited.update(component)
            ordered = tuple(values[index] for index in sorted(component))
            if len({value.value.pato_id for value in ordered}) < 2:
                continue
            start, end = _expression_bounds(text, ordered[0].start, ordered[-1].end)
            connectors = tuple(
                edge.connector_start
                for edge in edges
                if edge.operator == operator
                and not edge.reason
                and start <= edge.connector_start <= end
            )
            candidates.append(LogicCandidate(operator, ordered, connectors, start, end))
    return candidates


def _candidate_value_keys(candidate: LogicCandidate) -> set[tuple[int, int, str]]:
    return {(value.start, value.end, value.value.pato_id) for value in candidate.values}


def _target_indexes_in_values(record: dict, candidate: LogicCandidate) -> tuple[int, ...]:
    indexes: list[int] = []
    for index, span in enumerate(record.get("unresolved_spans", []) or []):
        if span.get("reason") not in TARGET_REASONS:
            continue
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        pato_id = str(span.get("candidate_pato_id", ""))
        if any(
            value.start <= start and end <= value.end and pato_id == value.value.pato_id
            for value in candidate.values
        ):
            indexes.append(index)
    return tuple(indexes)


def _target_indexes_in_expression(record: dict, candidate: LogicCandidate) -> tuple[int, ...]:
    return tuple(
        index
        for index, span in enumerate(record.get("unresolved_spans", []) or [])
        if span.get("reason") in TARGET_REASONS
        and candidate.start <= int(span.get("start", -1))
        and int(span.get("end", -1)) <= candidate.end
    )


def _mixed_or_incomplete_logic(
    candidate: LogicCandidate,
    edges: Iterable[LogicEdge],
) -> str:
    keys = _candidate_value_keys(candidate)
    for edge in edges:
        left_key = (edge.left.start, edge.left.end, edge.left.value.pato_id) if edge.left else None
        right_key = (
            (edge.right.start, edge.right.end, edge.right.value.pato_id) if edge.right else None
        )
        shares = left_key in keys or right_key in keys
        nearby = candidate.start - 24 <= edge.connector_start <= candidate.end + 40
        if edge.operator != candidate.operator and shares:
            return "mixed_logical_operators"
        if edge.reason and (shares or nearby):
            return "incomplete_logical_expression"
        if not edge.reason and edge.operator == candidate.operator and not shares and nearby:
            return "nearby_unincluded_logical_expression"
    return ""


def _nearby_same_family_value(
    text: str,
    candidate: LogicCandidate,
    clause_values: Iterable[ValueMatch],
) -> bool:
    keys = _candidate_value_keys(candidate)
    family = candidate.values[0].value.family
    for other in clause_values:
        key = other.start, other.end, other.value.pato_id
        if key in keys or other.value.family != family:
            continue
        before = candidate.start - other.end
        after = other.start - candidate.end
        if not (0 <= before <= 48 or 0 <= after <= 64):
            continue
        between = text[min(other.end, candidate.end) : max(other.start, candidate.start)]
        if not re.search(r"[;:.]", between):
            return True
    return False


def _candidate_base(record: dict, candidate: LogicCandidate) -> dict[str, object]:
    text = str(record.get("text", ""))
    clause, _ = baseline._clause_at(text, candidate.start)
    family = candidate.values[0].value.family
    input_reasons = tuple(
        dict.fromkeys(
            str((record.get("unresolved_spans", []) or [])[index].get("reason", ""))
            for index in _target_indexes_in_values(record, candidate)
        )
    )
    return {
        "source": str(record.get("source", "")),
        "source_id": str(record.get("source_id", "")),
        "source_segment_index": record.get("source_segment_index", ""),
        "taxon": str(record.get("taxon", "")),
        "organ": str(record.get("organ", "")),
        "language": str(record.get("language", "")),
        "expression_start": candidate.start,
        "expression_end": candidate.end,
        "expression_text": text[candidate.start : candidate.end],
        "source_context": clause,
        "input_reasons": input_reasons,
        "operator": candidate.operator,
        "family": family,
        "attribute_pato_id": ATTRIBUTE_BY_FAMILY.get(family, ""),
        "value_terms": tuple(dict.fromkeys(value.value.pato_id for value in candidate.values)),
        "value_labels": tuple(dict.fromkeys(value.value.label for value in candidate.values)),
        "value_source_forms": tuple(value.source_form for value in candidate.values),
    }


def evaluate_candidate(
    record: dict,
    candidate: LogicCandidate,
    edges: Iterable[LogicEdge],
    clause_values: Iterable[ValueMatch],
    locative_keys: frozenset[tuple[str, str, int, int, int, str]] = frozenset(),
) -> Decision:
    text = str(record.get("text", ""))
    base = _candidate_base(record, candidate)
    matching = _target_indexes_in_values(record, candidate)
    contained = _target_indexes_in_expression(record, candidate)
    if not matching:
        return Decision("routed", "review_queue", "not_seeded_by_target_span", **base)
    if set(contained) != set(matching):
        return Decision("routed", "review_queue", "ungrounded_operand_span", **base)
    if any(
        _span_key(record, (record.get("unresolved_spans", []) or [])[index]) in locative_keys
        for index in matching
    ):
        return Decision("routed", "locative_context", "independently_audited_locative", **base)
    structural = _mixed_or_incomplete_logic(candidate, edges)
    if structural:
        return Decision("routed", "logical_expression_review", structural, **base)
    if _nearby_same_family_value(text, candidate, clause_values):
        return Decision(
            "routed",
            "logical_expression_review",
            "nearby_unincluded_same_attribute_value",
            **base,
        )
    clause, _ = baseline._clause_at(text, candidate.start)
    if _TEMPORAL.search(clause):
        return Decision("routed", "temporal_or_developmental", "temporal_context", **base)
    if _RANGE_CONNECTOR.search(text[candidate.start : candidate.end]):
        return Decision("routed", "qualitative_range_or_transition", "range_connector", **base)
    for value in candidate.values:
        contextual = baseline._negated_or_hedged(text, value.start)
        if contextual:
            return Decision("routed", "modality_or_negation", contextual, **base)

    bearers = tuple(_resolve_explicit_bearer(record, value) for value in candidate.values)
    if any(not bearer.po_id for bearer in bearers):
        reason = next(
            (bearer.method for bearer in bearers if not bearer.po_id),
            "heading_only_or_missing",
        )
        return Decision("routed", "bearer_review", reason, **base)
    if len({bearer.occurrence_key for bearer in bearers}) != 1:
        return Decision("routed", "bearer_review", "different_explicit_bearers", **base)
    selected = bearers[0]
    if selected.method not in {"explicit_local", "contextual_local"}:
        return Decision("routed", "bearer_review", "heading_only_or_missing", **base)
    # Reuse the independently reviewed union safeguards for nested/subregion bearers and
    # degree-qualified/incomplete endpoints.
    proxy = _proxy_candidate(candidate)
    if _ambiguous_local_bearers(record, proxy, selected):
        return Decision("routed", "bearer_review", "multiple_local_bearers", **base)
    operand_reason = _operand_context_reason(text, proxy, selected, clause_values)
    if operand_reason:
        return Decision("routed", "logical_expression_review", operand_reason, **base)
    scope_reason = _bearer_scope_reason(text, proxy, selected)
    if scope_reason:
        route = "bearer_review" if scope_reason in _BEARER_FAILURES else "locative_context"
        return Decision("routed", route, scope_reason, **base)
    return Decision(
        "promoted",
        f"FAC_{candidate.operator}",
        "exact_complete_logical_expression",
        **base,
        bearer_po_id=selected.po_id,
        bearer_method=selected.method,
        bearer_surface=selected.surface_form,
        bearer_start=selected.start,
        bearer_end=selected.end,
        resolved_unresolved_spans=len(matching),
    )


def _proxy_candidate(candidate: LogicCandidate):
    """Create the union helper's structural protocol without coupling its public API."""

    from flopo2.verify.recover_explicit_unions import UnionCandidate

    return UnionCandidate(
        candidate.values,
        candidate.connector_starts,
        candidate.expression_start,
        candidate.expression_end,
    )


def _existing_assertion(assertions: Iterable[dict], decision: Decision) -> dict | None:
    expected = set(decision.value_terms)
    return next(
        (
            row
            for row in assertions
            if row.get("po_id") == decision.bearer_po_id
            and (row.get("value_operator", "atomic") or "atomic") == decision.operator
            and set(row.get("value_terms", []) or []) == expected
            and int(row.get("source_start", -1)) <= decision.expression_start
            and decision.expression_end <= int(row.get("source_end", -1))
        ),
        None,
    )


def _assertion(record: dict, candidate: LogicCandidate, decision: Decision) -> dict:
    text = str(record.get("text", ""))
    qualifiers, qualifier_start, qualifier_text = baseline._modality_context(text, candidate.start)
    seasons, season_operator, season_start, season_end = baseline._season_context(
        text, candidate.start, candidate.end
    )
    source_start = min(candidate.start, qualifier_start, season_start)
    source_end = max(candidate.end, season_end)
    return {
        "po_id": decision.bearer_po_id,
        "pato_id": decision.attribute_pato_id,
        "negated": False,
        "organ": record.get("organ", ""),
        "source_text": text[source_start:source_end],
        "source_start": source_start,
        "source_end": source_end,
        "value_text": text[candidate.start : candidate.end],
        "value_operator": candidate.operator,
        "value_terms": list(decision.value_terms),
        "modality_text": qualifier_text,
        "season_contexts": seasons,
        "season_operator": season_operator,
        "normalization_status": "compositional",
        "mapping_provenance": [
            "PATO preferred labels or EXACT synonyms; complete explicit source logic",
            (
                "same explicit PO bearer occurrence: "
                f"{decision.bearer_surface} [{decision.bearer_start},{decision.bearer_end})"
            ),
            "arbitrary OWL class description; identify only in the FAC namespace",
        ],
        "extractor": EXTRACTOR,
        **qualifiers,
    }


def _route_for_span(
    record: dict,
    span: dict,
    lexicon: ExactPatoValueLexicon,
    locative_keys: frozenset[tuple[str, str, int, int, int, str]],
    candidate_failures: Iterable[Decision] = (),
) -> Decision:
    text = str(record.get("text", ""))
    start = int(span.get("start", -1))
    end = int(span.get("end", -1))
    clause, clause_start = baseline._clause_at(text, start)
    clause_end = clause_start + len(clause)
    family = baseline.QUALITY_FAMILY.get(str(span.get("candidate_pato_id", "")), "")
    base: dict[str, object] = {
        "source": str(record.get("source", "")),
        "source_id": str(record.get("source_id", "")),
        "source_segment_index": record.get("source_segment_index", ""),
        "taxon": str(record.get("taxon", "")),
        "organ": str(record.get("organ", "")),
        "language": str(record.get("language", "")),
        "expression_start": start,
        "expression_end": end,
        "expression_text": text[start:end],
        "source_context": clause,
        "input_reasons": (str(span.get("reason", "")),),
        "family": family,
        "attribute_pato_id": ATTRIBUTE_BY_FAMILY.get(family, ""),
        "value_terms": (str(span.get("candidate_pato_id", "")),),
        "value_source_forms": (str(span.get("surface_form", "")),),
    }
    if _span_key(record, span) in locative_keys:
        return Decision("retained", "locative_context", "independently_audited_locative", **base)
    before = text[max(clause_start, start - 48) : start]
    after = text[end : min(clause_end, end + 64)]
    direct_temporal = bool(
        _TEMPORAL_TRANSITION_LEFT.search(before)
        or _TEMPORAL_TRANSITION_RIGHT.match(after)
        or _STAGE_ATTACHMENT_LEFT.search(before)
        or _STAGE_ATTACHMENT_RIGHT.match(after)
    )
    if direct_temporal:
        return Decision("retained", "temporal_or_developmental", "temporal_context", **base)
    attached_locative = _LOCATIVE.match(after) or re.search(
        _LOCATIVE.pattern + r"\s*$", before, _LOCATIVE.flags
    )
    if attached_locative:
        return Decision("retained", "locative_context", "locative_phrase", **base)
    left_range = _ADJACENT_RANGE_LEFT.search(before)
    right_range = _ADJACENT_RANGE_RIGHT.match(after)
    left_logic = _ADJACENT_LOGIC_LEFT.search(before)
    right_logic = _ADJACENT_LOGIC_RIGHT.match(after)
    left_other = before[: left_range.start()] if left_range else ""
    right_other = after[right_range.end() :] if right_range else ""
    if (left_range and re.search(_NUMERIC.pattern + r"\s*$", left_other)) or (
        right_range and re.match(r"^\s*" + _NUMERIC.pattern, right_other)
    ):
        return Decision(
            "retained",
            "numeric_or_cardinality_context",
            "adjacent_numeric_context",
            **base,
        )
    values = lexicon.matches(text, clause_start, clause_end)
    same_family = [value for value in values if value.value.family == family]
    neighbors = [
        value
        for value in same_family
        if value.end <= start
        and start - value.end <= 72
        or end <= value.start
        and value.start - end <= 72
    ]
    if (left_range or right_range) and neighbors:
        return Decision(
            "retained",
            "qualitative_range_or_transition",
            "exact_values_joined_by_range_connector",
            **base,
        )
    if left_range or right_range:
        return Decision(
            "retained",
            "qualitative_range_or_transition",
            "range_endpoint_not_fully_grounded",
            **base,
        )
    failures = list(candidate_failures)
    if failures:
        selected = min(
            failures,
            key=lambda row: abs(row.expression_start - start) + abs(row.expression_end - end),
        )
        route = selected.route
        if selected.reason in _BEARER_FAILURES:
            route = "bearer_review"
        return Decision("retained", route, selected.reason, **base)
    touching_before = text[max(0, start - 2) : start]
    touching_after = text[end : min(len(text), end + 2)]
    if _TOUCHING_COMPOUND.search(touching_before) or _TOUCHING_COMPOUND.search(touching_after):
        return Decision("retained", "hyphen_or_slash_expression", "touching_compound", **base)
    if left_logic or right_logic:
        return Decision(
            "retained",
            "logical_expression_review",
            "incomplete_or_ambiguous_logical_expression",
            **base,
        )
    reason = str(span.get("reason", ""))
    if reason == "same_attribute_composite_or_transition":
        route = "adjacent_or_composite_review"
    elif reason == "unsupported_same_attribute_neighbor":
        route = "unmodeled_same_attribute_neighbor"
    else:
        route = "alternative_or_transition_review"
    return Decision("retained", route, "no_safe_complete_class_description", **base)


def recover_record(
    record: dict,
    lexicon: ExactPatoValueLexicon,
    *,
    locative_keys: frozenset[tuple[str, str, int, int, int, str]] = frozenset(),
) -> tuple[dict, Counter[str], list[Decision]]:
    result = dict(record)
    text = str(record.get("text", ""))
    assertions = [dict(row) for row in record.get("assertions", []) or []]
    unresolved = [dict(row) for row in record.get("unresolved_spans", []) or []]
    target_indexes = {
        index for index, span in enumerate(unresolved) if span.get("reason") in TARGET_REASONS
    }
    if not target_indexes:
        return result, Counter(), []

    outcomes: Counter[str] = Counter()
    decisions: list[Decision] = []
    removed: set[int] = set()
    failures_by_span: dict[int, list[Decision]] = defaultdict(list)
    clause_ranges: set[tuple[int, int]] = set()
    for index in target_indexes:
        clause, clause_start = baseline._clause_at(text, int(unresolved[index].get("start", -1)))
        clause_ranges.add((clause_start, clause_start + len(clause)))

    seen: set[tuple[str, int, int, tuple[str, ...]]] = set()
    for clause_start, clause_end in sorted(clause_ranges):
        values = lexicon.matches(text, clause_start, clause_end)
        edges = _logic_edges(text, clause_start, clause_end, values)
        for candidate in _logic_candidates(text, values, edges):
            key = (
                candidate.operator,
                candidate.start,
                candidate.end,
                tuple(value.value.pato_id for value in candidate.values),
            )
            if key in seen:
                continue
            seen.add(key)
            matching = _target_indexes_in_values(record, candidate)
            if not matching:
                continue
            decision = evaluate_candidate(record, candidate, edges, values, locative_keys)
            if decision.status != "promoted":
                for index in matching:
                    failures_by_span[index].append(decision)
                outcomes[f"routed:{decision.route}:{decision.reason}"] += 1
                continue
            if any(index in removed for index in matching):
                outcomes["routed:overlapping_promoted_expression"] += 1
                continue
            existing = _existing_assertion(assertions, decision)
            if existing is None:
                assertions.append(_assertion(record, candidate, decision))
                decisions.append(decision)
                outcomes["promoted_assertions"] += 1
                outcomes[f"promoted_operator:{decision.operator}"] += 1
                outcomes[f"promoted_family:{decision.family}"] += 1
                outcomes[f"promoted_po:{decision.bearer_po_id}"] += 1
                outcomes[f"promoted_arity:{decision.arity}"] += 1
            else:
                decision = Decision(
                    **{
                        **decision.__dict__,
                        "status": "resolved_existing",
                        "route": f"FAC_{candidate.operator}",
                        "reason": "equivalent_assertion_already_present",
                    }
                )
                decisions.append(decision)
                outcomes["resolved_by_existing_assertion"] += 1
            removed.update(matching)
            outcomes["resolved_evidence_spans"] += len(matching)

    for index in sorted(target_indexes - removed):
        decision = _route_for_span(
            record,
            unresolved[index],
            lexicon,
            locative_keys,
            failures_by_span.get(index, ()),
        )
        decisions.append(decision)
        outcomes[f"retained:{decision.route}"] += 1

    result["assertions"] = assertions
    result["unresolved_spans"] = [
        span for index, span in enumerate(unresolved) if index not in removed
    ]
    return result, outcomes, decisions


def _decision_row(decision: Decision) -> dict[str, object]:
    row = {
        field: getattr(decision, field)
        for field in DECISION_FIELDS
        if field
        not in {
            "arity",
            "input_reasons",
            "value_terms",
            "value_labels",
            "value_source_forms",
        }
    }
    row.update(
        {
            "input_reasons": "|".join(decision.input_reasons),
            "arity": decision.arity,
            "value_terms": "|".join(decision.value_terms),
            "value_labels": "|".join(decision.value_labels),
            "value_source_forms": "|".join(decision.value_source_forms),
        }
    )
    return row


def write_decisions(path: Path, decisions: Iterable[Decision]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(_decision_row(decision) for decision in decisions)


def write_fixed_seed_sample(
    path: Path,
    decisions: Iterable[Decision],
    *,
    seed: int = 20260718,
    size: int = 50,
) -> dict[str, object]:
    promoted = [decision for decision in decisions if decision.status == "promoted"]
    strata: dict[tuple[str, str, str], list[Decision]] = defaultdict(list)
    for decision in promoted:
        strata[(decision.source, decision.bearer_po_id, decision.operator)].append(decision)
    rng = random.Random(seed)

    def key(decision: Decision) -> tuple[object, ...]:
        return (
            decision.source,
            decision.source_id,
            decision.source_segment_index,
            decision.expression_start,
            decision.expression_end,
            decision.operator,
            decision.value_terms,
        )

    ordered_strata = sorted(strata)
    for rows in strata.values():
        rows.sort(key=key)
        rng.shuffle(rows)
    selected: list[Decision] = []
    cursor = 0
    while len(selected) < min(size, len(promoted)):
        progressed = False
        for stratum in ordered_strata:
            rows = strata[stratum]
            if cursor < len(rows):
                selected.append(rows[cursor])
                progressed = True
                if len(selected) >= size:
                    break
        if not progressed:
            break
        cursor += 1
    selected.sort(key=key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS, delimiter="\t")
        writer.writeheader()
        for decision in selected:
            writer.writerow(
                {
                    **_decision_row(decision),
                    "semantic_judgment": "",
                    "bearer_judgment": "",
                    "completeness_judgment": "",
                    "review_note": "",
                }
            )
    return {
        "path": str(path),
        "seed": seed,
        "requested_size": size,
        "sample_size": len(selected),
        "strata": len(strata),
        "sources": dict(Counter(decision.source for decision in selected)),
        "operators": dict(Counter(decision.operator for decision in selected)),
        "bearers": dict(Counter(decision.bearer_po_id for decision in selected)),
    }


def write_reviewed_sample(
    input_path: Path,
    output_path: Path,
    *,
    semantic_judgment: str,
    bearer_judgment: str,
    completeness_judgment: str,
    review_note: str,
) -> int:
    """Record an independently supplied uniform judgment on a generated audit sample."""

    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("reviewed sample output must be distinct from its input")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with (
        Path(input_path).open(encoding="utf-8", newline="") as source,
        output_path.open("w", encoding="utf-8", newline="") as output,
    ):
        reader = csv.DictReader(source, delimiter="\t")
        if reader.fieldnames != SAMPLE_FIELDS:
            raise ValueError("input is not a residual-logic promoted sample")
        writer = csv.DictWriter(
            output, fieldnames=SAMPLE_FIELDS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in reader:
            row.update(
                {
                    "semantic_judgment": semantic_judgment,
                    "bearer_judgment": bearer_judgment,
                    "completeness_judgment": completeness_judgment,
                    "review_note": review_note,
                }
            )
            writer.writerow(row)
            rows += 1
    return rows


def _update_invariants(original: dict, recovered: dict, invariants: dict[str, bool]) -> None:
    metadata_keys = set(original) - {"assertions", "unresolved_spans"}
    invariants["record_text_and_metadata_preserved"] &= all(
        original.get(key) == recovered.get(key) for key in metadata_keys
    )
    old_assertions = original.get("assertions", []) or []
    new_assertions = recovered.get("assertions", []) or []
    invariants["preexisting_assertions_preserved"] &= (
        new_assertions[: len(old_assertions)] == old_assertions
    )
    added = new_assertions[len(old_assertions) :]
    text = str(original.get("text", ""))
    for assertion in added:
        operator = assertion.get("value_operator")
        values = assertion.get("value_terms", []) or []
        invariants["operators_are_one_of_or_all_of"] &= operator in {"one_of", "all_of"}
        invariants["arities_are_distinct_and_at_least_two"] &= len(values) >= 2 and len(
            set(values)
        ) == len(values)
        invariants["attributes_match_reviewed_family"] &= (
            assertion.get("pato_id") in ATTRIBUTE_BY_FAMILY.values()
        )
        start = int(assertion.get("source_start", -1))
        end = int(assertion.get("source_end", -1))
        invariants["source_texts_equal_retained_source_slice"] &= (
            0 <= start <= end <= len(text) and assertion.get("source_text") == text[start:end]
        )
        invariants["no_flopo_ids_minted"] &= not any(
            str(assertion.get(field, "")).startswith("http://purl.obolibrary.org/obo/FLOPO_")
            for field in ("flopo_id", "phenotype_class_iri")
        )
    retained = recovered.get("unresolved_spans", []) or []
    invariants["retained_unresolved_offsets_and_text_exact"] &= all(
        0 <= int(span.get("start", -1)) <= int(span.get("end", -1)) <= len(text)
        and span.get("surface_form") == text[int(span.get("start", -1)) : int(span.get("end", -1))]
        for span in retained
    )


def recover_file(
    input_path: Path,
    output_path: Path,
    *,
    decisions_tsv: Path,
    pato_obo: Path = Path("ont/quality.obo"),
    locative_audit: Path | None = None,
    sample_tsv: Path | None = None,
    sample_seed: int = 20260718,
    sample_size: int = 50,
) -> dict[str, object]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("recovery output must be distinct from its input")
    lexicon = ExactPatoValueLexicon.load(pato_obo)
    locative_keys = load_locative_keys(locative_audit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    outcomes: Counter[str] = Counter()
    decisions: list[Decision] = []
    promoted_by_source: Counter[str] = Counter()
    promoted_by_operator: Counter[str] = Counter()
    invariants = {
        "record_text_and_metadata_preserved": True,
        "preexisting_assertions_preserved": True,
        "operators_are_one_of_or_all_of": True,
        "arities_are_distinct_and_at_least_two": True,
        "attributes_match_reviewed_family": True,
        "source_texts_equal_retained_source_slice": True,
        "retained_unresolved_offsets_and_text_exact": True,
        "no_flopo_ids_minted": True,
    }
    with (
        Path(input_path).open(encoding="utf-8") as source,
        output_path.open("w", encoding="utf-8") as output,
    ):
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            recovered, record_outcomes, record_decisions = recover_record(
                record, lexicon, locative_keys=locative_keys
            )
            output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
            records += 1
            outcomes.update(record_outcomes)
            decisions.extend(record_decisions)
            _update_invariants(record, recovered, invariants)
            for decision in record_decisions:
                if decision.status == "promoted":
                    promoted_by_source[decision.source] += 1
                    promoted_by_operator[decision.operator] += 1
    write_decisions(decisions_tsv, decisions)
    sample = (
        write_fixed_seed_sample(sample_tsv, decisions, seed=sample_seed, size=sample_size)
        if sample_tsv is not None
        else None
    )
    return {
        "input": str(input_path),
        "output": str(output_path),
        "decisions_tsv": str(decisions_tsv),
        "records": records,
        "exact_pato_value_forms": len(lexicon.forms),
        "locative_keys_excluded": len(locative_keys),
        "decisions": len(decisions),
        "promoted_by_source": dict(sorted(promoted_by_source.items())),
        "promoted_by_operator": dict(sorted(promoted_by_operator.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "sample": sample,
        "invariants": invariants,
        "result": "pass" if all(invariants.values()) else "fail",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--locative-audit", type=Path)
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--sample-seed", type=int, default=20260718)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = recover_file(
        args.input,
        args.output,
        decisions_tsv=args.decisions,
        pato_obo=args.pato_obo,
        locative_audit=args.locative_audit,
        sample_tsv=args.sample,
        sample_seed=args.sample_seed,
        sample_size=args.sample_size,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
