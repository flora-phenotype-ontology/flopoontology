"""Recover source-explicit PATO value unions without minting FLOPO vocabulary terms.

The full-corpus baseline deliberately retains an ``explicit_disjunction`` evidence span when
one or more alternatives cannot be represented by its small closed cue list.  This second pass
uses the pinned PATO ontology directly, but remains deliberately strict:

* every value is a PATO preferred label or ``EXACT`` synonym (no fuzzy or scoped-synonym match);
* every value belongs to the same reviewed PATO attribute family;
* every value resolves to the same *occurrence* of an explicit PO bearer in the source clause;
* heading-only bearer priors, transitions, degree modifiers, substring decomposition, and
  anatomical subregion attachments are retained for review; and
* only complete expressions of arity two or greater become ``value_operator=one_of`` assertions.

The union is an arbitrary OWL class description.  The pass therefore emits no FLOPO identifier;
the annotation-extension builder assigns its non-FLOPO ``FAC_`` class IRI downstream.  Input
JSONL is never overwritten, and exact source offsets plus unresolved-span accounting are kept.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from flopo2.extract import baseline
from flopo2.verify.recover_exact_pato_compounds import load_pato_terms


TARGET_REASON = "explicit_disjunction"
EXTRACTOR = "deterministic_exact_pato_explicit_union_recovery"
ATTRIBUTE_BY_FAMILY = {
    "colour": "PATO_0000014",
    "shape": "PATO_0000052",
    "pilosity": "PATO_0000066",
}
FAMILY_BY_ATTRIBUTE = {value: key for key, value in ATTRIBUTE_BY_FAMILY.items()}
_UNSAFE_EXACT_BOTANICAL_FORMS = frozenset({"oval", "ovoid"})
_DASHES = "-\u2013\u2014"
_CONNECTOR = re.compile(r"\b(?:or|ou)\b", re.IGNORECASE)
_STRICT_FILLER = re.compile(r"[\s,()\[\]{}]*")
_COMMA = re.compile(r"\s*,\s*")
_TRANSITION_BEFORE = re.compile(
    r"\b(?:to|through|vers|à|au)\s*(?:\([^)]*\)\s*)?$", re.IGNORECASE
)
_TRANSITION_AFTER = re.compile(
    r"^\s*(?:\([^)]*\)\s*)?\b(?:to|through|vers|à|au)\b", re.IGNORECASE
)
_RESPECTIVELY = re.compile(r"^\s*,?\s*(?:respectively|respectivement)\b", re.IGNORECASE)
_UNCERTAINTY = re.compile(r"[?]|\b(?:possibly|perhaps|peut-être|peut etre)\b", re.IGNORECASE)
_COMPARATIVE_CONTEXT = re.compile(
    r"\b(?:resembl(?:e|es|ing)|similar\s+to|like|"
    r"(?:larger|smaller|longer|shorter|broader|narrower)\s+than|"
    r"ressembl(?:e|ant|ant\s+à)|comme|plus\s+[\wÀ-ÖØ-öø-ÿ'’-]+\s+que)\b",
    re.IGNORECASE,
)
_EXCLUDED_SCOPE_AFTER = re.compile(
    r"^\s*[,;]?\s*(?:not|except(?:ing)?|excluding)\s+(?:in|from|within)\b",
    re.IGNORECASE,
)
_TEMPORAL_CONTEXT = re.compile(
    r"\b(?:turning|becoming|maturing|later|eventually|devenant|puis|"
    r"at\s+maturity|when\s+(?:young|mature|dry)|à\s+maturit[ée])\b",
    re.IGNORECASE,
)
_LOCATIVE_SCOPE = re.compile(
    r"\b(?:at|towards?|near|along|on|sur|vers|au|aux|à)\s+"
    r"(?:the\s+|l['\u2019]|la\s+|le\s+|les\s+|leur\s+|sa\s+)?"
    r"(?:apex|apices|base|bases|tip|tips|surface|surfaces|face|faces|side|sides|"
    r"margin|margins|edge|edges|sommet|sommets|extrémité|extrémités|extremite|"
    r"extremites|intérieur|interieur|extérieur|exterieur|bord|bords|marge|marges)\b",
    re.IGNORECASE,
)
_BEARER_SUBREGION_MODIFIER = re.compile(
    r"(?:\b(?:inner|outer|upper|lower|adaxial|abaxial|internal|external|"
    r"intérieur|interieur|extérieur|exterieur|supérieur|superieur|inférieur|inferieur)"
    r"\s+|\w+-)$",
    re.IGNORECASE,
)
_BEARER_SUBSET_MODIFIER = re.compile(
    r"(?:\b(?:other|basal|apical|lateral|terminal|lowermost|uppermost|lower|upper|"
    r"inner|outer|male|female|staminate|pistillate|fertile|sterile|"
    r"long-staminate|short-staminate)\s+)$",
    re.IGNORECASE,
)
_RELATIONAL_OBJECT_BEFORE_BEARER = re.compile(
    r"\b(?:shoots?|branches?|branchlets?|stems?|axes?|leaves?|leaflets?|flowers?|fruits?)\b"
    r"[^,;:.]{0,80}\b(?:from|arising\s+from|borne\s+on|of)\s+"
    r"(?:(?:an?|the)\s+)?(?:[A-Za-zÀ-ÖØ-öø-ÿ'’\-]+[\s,]+){0,6}$",
    re.IGNORECASE,
)
_UNSUPPORTED_BEARER_NOUN = re.compile(
    r"\b(?:leaf\s+blades?|blades?|scales?|pinnae?|pinnules?|fronds?|"
    r"veins?|nerves?|nervures?|margins?|borders?|edges?|fringes?|"
    r"surfaces?|faces?|sides?|throats?|gorges?|cent(?:er|re)s?|"
    r"apices?|apex|bases?|tips?|lobes?|teeth|segments?|parts?|"
    r"glands?|spikes?|stolons?|appendages?|axes?|rachis|rhachis|rachises?|rhachises?|"
    r"tubes?|cocci|coccus|mericarps?|mericarpes?|"
    r"indumentum|tomentum|pubescence|spots?|patches?|blotches?|streaks?|bands?|"
    r"écailles?|ecailles?|pennes?|pinnules?|frondes?|limbes?|"
    r"sommets?|extrémités?|extremites?|bords?|marges?|faces?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExactValue:
    pato_id: str
    label: str
    family: str
    lexical_form: str


@dataclass(frozen=True)
class ValueMatch:
    start: int
    end: int
    value: ExactValue
    source_form: str


@dataclass(frozen=True)
class LocalBearer:
    po_id: str
    method: str
    surface_form: str
    start: int
    end: int

    @property
    def occurrence_key(self) -> tuple[str, int, int]:
        return self.po_id, self.start, self.end


@dataclass(frozen=True)
class EdgeAttempt:
    connector_start: int
    connector_end: int
    left: ValueMatch | None
    right: ValueMatch | None
    reason: str = ""


@dataclass(frozen=True)
class UnionCandidate:
    values: tuple[ValueMatch, ...]
    connector_starts: tuple[int, ...]
    expression_start: int = -1
    expression_end: int = -1

    @property
    def start(self) -> int:
        return self.expression_start if self.expression_start >= 0 else self.values[0].start

    @property
    def end(self) -> int:
        return self.expression_end if self.expression_end >= 0 else self.values[-1].end


@dataclass(frozen=True)
class CandidateDecision:
    status: str
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
    family: str
    attribute_pato_id: str
    value_terms: tuple[str, ...]
    value_labels: tuple[str, ...]
    value_source_forms: tuple[str, ...]
    bearer_po_id: str = ""
    bearer_method: str = ""
    bearer_surface: str = ""
    bearer_start: int = -1
    bearer_end: int = -1
    resolved_unresolved_spans: int = 0

    @property
    def arity(self) -> int:
        return len(self.value_terms)


CANDIDATE_FIELDS = [
    "status",
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
    *CANDIDATE_FIELDS,
    "semantic_judgment",
    "bearer_judgment",
    "completeness_judgment",
    "review_note",
]


def _normal_form(value: str) -> str:
    return re.sub(rf"[\s{re.escape(_DASHES)}]+", " ", value.casefold()).strip()


class ExactPatoValueLexicon:
    """PATO value labels with preferred/EXACT lexical provenance and family ancestry."""

    def __init__(self, forms: dict[str, ExactValue]) -> None:
        self.forms = forms
        alternatives: list[str] = []
        for form in sorted(forms, key=lambda item: (-len(item), item)):
            if "/" in form:
                continue
            pattern = re.escape(form)
            pattern = pattern.replace(r"\ ", rf"[\s{re.escape(_DASHES)}]+")
            pattern = pattern.replace(r"\-", rf"[\s{re.escape(_DASHES)}]+")
            alternatives.append(pattern)
        self.pattern = re.compile(
            r"(?<!\w)(?P<value>" + "|".join(alternatives) + r")(?!\w)",
            re.IGNORECASE,
        )

    @classmethod
    def load(cls, pato_obo: Path) -> "ExactPatoValueLexicon":
        terms = load_pato_terms(Path(pato_obo))
        by_id = {term.pato_id: term for term in terms.values()}
        parents = {
            term.pato_id: tuple(parent.replace(":", "_") for parent in term.parents)
            for term in terms.values()
        }

        @lru_cache(maxsize=None)
        def family(term_id: str) -> str:
            if term_id in FAMILY_BY_ATTRIBUTE:
                return FAMILY_BY_ATTRIBUTE[term_id]
            inherited = {family(parent) for parent in parents.get(term_id, ())}
            inherited.discard("")
            return next(iter(inherited)) if len(inherited) == 1 else ""

        candidates: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        value_slim_ids = _subset_members(Path(pato_obo), "value_slim")
        for term_id, term in by_id.items():
            value_family = family(term_id)
            if (
                not value_family
                or term_id in FAMILY_BY_ATTRIBUTE
                or term_id not in value_slim_ids
            ):
                continue
            for source_form in (term.label, *term.exact_synonyms):
                normalized = _normal_form(source_form)
                if (
                    normalized not in _UNSAFE_EXACT_BOTANICAL_FORMS
                    and len(normalized) >= 3
                    and re.search(r"\w", normalized)
                ):
                    candidates[normalized].add((term_id, term.label, value_family))
        forms = {
            lexical_form: ExactValue(*next(iter(values)), lexical_form)
            for lexical_form, values in candidates.items()
            if len(values) == 1
        }
        return cls(forms)

    def matches(self, text: str, start: int, end: int) -> list[ValueMatch]:
        found: list[ValueMatch] = []
        for match in self.pattern.finditer(text, start, end):
            source_form = match.group("value")
            value = self.forms.get(_normal_form(source_form))
            if value is None:
                continue
            candidate = ValueMatch(match.start(), match.end(), value, source_form)
            if self._whole_lexical_token(text, candidate):
                found.append(candidate)
        return found

    def _whole_lexical_token(self, text: str, match: ValueMatch) -> bool:
        """Reject ``red`` inside ``red-orange`` unless the whole compound is an exact term."""

        touching = ""
        if match.start > 0 and text[match.start - 1] in _DASHES + "/":
            touching = text[match.start - 1]
        if match.end < len(text) and text[match.end] in _DASHES + "/":
            touching = text[match.end]
        if not touching:
            return True
        if touching == "/":
            return False
        left, right = match.start, match.end
        while left > 0 and (text[left - 1].isalpha() or text[left - 1] in _DASHES):
            left -= 1
        while right < len(text) and (text[right].isalpha() or text[right] in _DASHES):
            right += 1
        whole = self.forms.get(_normal_form(text[left:right]))
        return bool(
            whole
            and whole.pato_id == match.value.pato_id
            and left == match.start
            and right == match.end
        )


def _subset_members(path: Path, subset: str) -> frozenset[str]:
    """Return normalized OBO ids explicitly declared in one subset."""

    members: set[str] = set()
    current_id = ""
    current_subsets: set[str] = set()

    def finish() -> None:
        nonlocal current_id, current_subsets
        if current_id and subset in current_subsets:
            members.add(current_id.replace(":", "_"))
        current_id = ""
        current_subsets = set()

    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line == "[Term]":
                finish()
            elif line.startswith("["):
                finish()
            elif line.startswith("id: PATO:"):
                current_id = line.removeprefix("id: ")
            elif line.startswith("subset: "):
                current_subsets.add(line.removeprefix("subset: "))
            elif not line:
                finish()
    finish()
    return frozenset(members)


def _explicit_bearer_candidates(
    record: dict,
    value: ValueMatch,
) -> list[LocalBearer]:
    text = str(record.get("text", ""))
    clause, clause_start = baseline._clause_at(text, value.start)
    local_start = value.start - clause_start
    local_end = value.end - clause_start
    ranked: list[tuple[int, int, int, int, LocalBearer]] = []
    for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause):
            gap, side, length = baseline._match_gap(match, local_start, local_end)
            ranked.append(
                (
                    gap,
                    1,
                    side,
                    length,
                    LocalBearer(
                        po_id,
                        "explicit_local",
                        match.group(0),
                        clause_start + match.start(),
                        clause_start + match.end(),
                    ),
                )
            )
    for po_id, pattern, allowed_pato_ids in baseline.CONTEXTUAL_BEARER_PATTERNS:
        for match in pattern.finditer(clause):
            gap, side, length = baseline._match_gap(match, local_start, local_end)
            if value.value.pato_id in allowed_pato_ids:
                ranked.append(
                    (
                        gap,
                        0,
                        side,
                        length,
                        LocalBearer(
                            po_id,
                            "contextual_local",
                            match.group(0),
                            clause_start + match.start(),
                            clause_start + match.end(),
                        ),
                    )
                )
            else:
                ranked.append(
                    (
                        gap,
                        0,
                        side,
                        length,
                        LocalBearer(
                            "",
                            "blocked_local",
                            match.group(0),
                            clause_start + match.start(),
                            clause_start + match.end(),
                        ),
                    )
                )
    for pattern in baseline.UNRESOLVED_BEARER_PATTERNS:
        for match in pattern.finditer(clause):
            gap, side, length = baseline._match_gap(match, local_start, local_end)
            ranked.append(
                (
                    gap,
                    0,
                    side,
                    length,
                    LocalBearer(
                        "",
                        "blocked_local",
                        match.group(0),
                        clause_start + match.start(),
                        clause_start + match.end(),
                    ),
                )
            )
    return [row[-1] for row in sorted(ranked, key=lambda row: row[:-1])]


def _resolve_explicit_bearer(record: dict, value: ValueMatch) -> LocalBearer:
    candidates = _explicit_bearer_candidates(record, value)
    if candidates:
        # A bearer-like noun in the next comma member belongs to the following predicate, not
        # to the value immediately before it.  Prefer an already stated, valid bearer in cases
        # such as ``Fruits brown, orange or yellow, with scales on the outside``; the otherwise
        # nearer unresolved ``scales`` cue must not steal the colour union from ``Fruits``.
        selected = candidates[0]
        text = str(record.get("text", ""))
        if (
            not selected.po_id
            and selected.start >= value.end
            and re.match(r"^\s*,\s*with\b", text[value.end:selected.start], re.I)
        ):
            preceding_valid = [
                candidate
                for candidate in candidates
                if candidate.po_id and candidate.end <= value.start
            ]
            if preceding_valid:
                return preceding_valid[0]
        return selected
    # The heading is evidence for routing, never for promotion in this pass.
    return LocalBearer("", "heading_only_or_missing", str(record.get("organ", "")), -1, -1)


def _edge_attempts(
    text: str,
    clause_start: int,
    clause_end: int,
    values: list[ValueMatch],
) -> list[EdgeAttempt]:
    attempts: list[EdgeAttempt] = []
    clause = text[clause_start:clause_end]
    for connector in _CONNECTOR.finditer(clause):
        connector_start = clause_start + connector.start()
        connector_end = clause_start + connector.end()
        left_values = [value for value in values if value.end <= connector_start]
        right_values = [value for value in values if connector_end <= value.start]
        left = max(left_values, key=lambda value: value.end) if left_values else None
        right = min(right_values, key=lambda value: value.start) if right_values else None
        reason = ""
        if left is None or right is None:
            reason = "ungrounded_operand"
        elif left.value.family != right.value.family:
            reason = "mixed_attribute_families"
        elif left.value.pato_id == right.value.pato_id:
            reason = "non_distinct_operands"
        elif not _STRICT_FILLER.fullmatch(text[left.end:connector_start]):
            reason = "modified_or_ungrounded_left_operand"
        elif not _STRICT_FILLER.fullmatch(text[connector_end:right.start]):
            reason = "modified_or_ungrounded_right_operand"
        attempts.append(EdgeAttempt(connector_start, connector_end, left, right, reason))
    return attempts


def _union_candidates(
    text: str,
    values: list[ValueMatch],
    attempts: list[EdgeAttempt],
) -> list[UnionCandidate]:
    value_index = {
        (value.start, value.end, value.value.pato_id): index
        for index, value in enumerate(values)
    }
    edges: dict[int, set[int]] = defaultdict(set)
    connector_by_edge: dict[frozenset[int], set[int]] = defaultdict(set)
    for attempt in attempts:
        if attempt.reason or attempt.left is None or attempt.right is None:
            continue
        left_index = value_index[
            (attempt.left.start, attempt.left.end, attempt.left.value.pato_id)
        ]
        right_index = value_index[
            (attempt.right.start, attempt.right.end, attempt.right.value.pato_id)
        ]
        edges[left_index].add(right_index)
        edges[right_index].add(left_index)
        connector_by_edge[frozenset((left_index, right_index))].add(attempt.connector_start)

        # Include exact preceding comma-list members: ``red, white or yellow``.
        cursor = left_index
        while cursor > 0:
            previous = cursor - 1
            if (
                edges.get(previous)
                or
                values[previous].value.family != values[cursor].value.family
                or not _COMMA.fullmatch(text[values[previous].end:values[cursor].start])
            ):
                break
            edges[previous].add(cursor)
            edges[cursor].add(previous)
            cursor = previous

    candidates: list[UnionCandidate] = []
    visited: set[int] = set()
    for root in sorted(edges):
        if root in visited:
            continue
        stack = [root]
        component: set[int] = set()
        while stack:
            index = stack.pop()
            if index in component:
                continue
            component.add(index)
            stack.extend(edges[index])
        visited.update(component)
        ordered = tuple(values[index] for index in sorted(component))
        distinct = tuple(dict.fromkeys(value.value.pato_id for value in ordered))
        if len(distinct) < 2:
            continue
        connector_starts = tuple(
            sorted(
                attempt.connector_start
                for attempt in attempts
                if not attempt.reason
                and ordered[0].start <= attempt.connector_start <= ordered[-1].end
            )
        )
        expression_start, expression_end = _expression_bounds(
            text, ordered[0].start, ordered[-1].end
        )
        candidates.append(
            UnionCandidate(ordered, connector_starts, expression_start, expression_end)
        )
    return candidates


def _expression_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Include immediately enclosing logical parentheses in retained source evidence."""

    expression_start = start
    before = start - 1
    while before >= 0 and text[before].isspace():
        before -= 1
    if before >= 0 and text[before] in "([{":
        expression_start = before
    expression_end = end
    cursor = end
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor < len(text) and text[cursor] in ")]}":
        expression_end = cursor + 1
    return expression_start, expression_end


def _overlapping_target_indexes(record: dict, candidate: UnionCandidate) -> tuple[int, ...]:
    values = candidate.values
    indexes: list[int] = []
    for index, span in enumerate(record.get("unresolved_spans", []) or []):
        if span.get("reason") != TARGET_REASON:
            continue
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        if any(value.start <= start and end <= value.end for value in values):
            indexes.append(index)
    return tuple(indexes)


def _target_spans_within_expression(record: dict, candidate: UnionCandidate) -> tuple[int, ...]:
    return tuple(
        index
        for index, span in enumerate(record.get("unresolved_spans", []) or [])
        if span.get("reason") == TARGET_REASON
        and candidate.start <= int(span.get("start", -1))
        and int(span.get("end", -1)) <= candidate.end
    )


def _ambiguous_local_bearers(
    record: dict,
    candidate: UnionCandidate,
    selected: LocalBearer,
) -> bool:
    """Reject a nearby nested PO phrase such as ``tepals of ... flowers``."""

    text = str(record.get("text", ""))
    _clause, clause_start = baseline._clause_at(text, candidate.start)
    window_start = max(0, min(selected.start, candidate.start) - 96)
    # A semicolon opens a new coordinated flora member.  Allow its immediately leading explicit
    # bearer (``... midnerve channelled; stipules triangular or ovate``) without allowing a
    # general sentence-wide relaxation of the nested-bearer safeguard.
    if (
        clause_start > 0
        and text[clause_start - 1] == ";"
        and selected.start - clause_start <= 32
        and selected.po_id == "PO_0020041"
        and re.match(r"^\s*stipules?\s+interpetiolar\b", _clause, re.I)
    ):
        window_start = max(window_start, clause_start)
    window_end = max(candidate.end, selected.end)
    occurrences: set[tuple[str, int, int]] = set()
    for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(text, window_start, window_end):
            occurrences.add((po_id, match.start(), match.end()))
    # Ignore overlapping shorter aliases (for example ``flower`` inside ``flower buds``).
    non_nested = {
        row
        for row in occurrences
        if not any(
            other != row
            and other[1] <= row[1]
            and row[2] <= other[2]
            and (other[2] - other[1]) > (row[2] - row[1])
            for other in occurrences
        )
    }
    return len({row[0] for row in non_nested}) > 1


def _local_value_context_reason(
    text: str,
    candidate: UnionCandidate,
    value: ValueMatch,
) -> str:
    """Return only syntactically local negation/comparison context for one operand.

    ``baseline._negated_or_hedged`` deliberately scans an entire long flora clause.  That is
    appropriate for the baseline router but over-scopes an already delimited union: an unrelated
    later phrase such as ``shaped like a fig`` or ``sheath-like petiole`` must not make the
    preceding colour/shape alternatives comparative.
    """

    contextual = baseline._negated_or_hedged(text, value.start)
    if contextual != "comparative_context":
        return contextual

    # Preserve the baseline's conservative comparison guard except when every comparison cue is
    # in a later comma member.  Those cues characterize a subsequent predicate/part rather than
    # the already complete union: ``Fruit yellow or orange, shaped like a fig`` and
    # ``Leaves obovate ... or oblong, ... sheath-like petiole``.
    clause, clause_start = baseline._clause_at(text, value.start)
    matches = list(_COMPARATIVE_CONTEXT.finditer(clause))
    if matches and all(
        clause_start + match.start() >= candidate.end
        and "," in text[candidate.end : clause_start + match.start()]
        for match in matches
    ):
        return ""
    return contextual


def _bearer_scope_reason(
    text: str,
    candidate: UnionCandidate,
    bearer: LocalBearer,
) -> str:
    distance = max(bearer.start - candidate.end, candidate.start - bearer.end, 0)
    if distance > 96:
        return "distant_local_bearer"
    relation_start = min(candidate.start, bearer.start)
    relation_end = max(candidate.end, bearer.end)
    relation = text[relation_start:relation_end]
    if _UNSUPPORTED_BEARER_NOUN.search(relation):
        return "unsupported_subregion_or_bearer"
    clause, clause_start = baseline._clause_at(text, candidate.start)
    preceding_scope = text[clause_start:candidate.start]
    if _UNSUPPORTED_BEARER_NOUN.search(preceding_scope):
        return "unsupported_preceding_subregion_or_bearer"
    bearer_prefix = text[max(clause_start, bearer.start - 32):bearer.start]
    relational_prefix = text[max(clause_start, bearer.start - 128):bearer.start]
    if _RELATIONAL_OBJECT_BEFORE_BEARER.search(relational_prefix):
        return "intervening_relational_object_bearer"
    if _BEARER_SUBREGION_MODIFIER.search(bearer_prefix):
        return "qualified_bearer_subregion"
    if _BEARER_SUBSET_MODIFIER.search(bearer_prefix):
        return "qualified_bearer_subset"
    if bearer.start >= candidate.end and re.search(
        r"[,;:.]", text[candidate.values[-1].end:bearer.start]
    ):
        return "postposed_bearer_after_delimiter"
    after = text[candidate.end: min(len(text), candidate.end + 72)]
    before = text[max(0, candidate.start - 56):candidate.start]
    if _LOCATIVE_SCOPE.search(before) or _LOCATIVE_SCOPE.search(after):
        return "locative_subregion_scope"
    if _RESPECTIVELY.match(after):
        return "respectively_scoped_values"
    return ""


def _nearby_unresolved_same_family(
    record: dict,
    candidate: UnionCandidate,
) -> bool:
    family = candidate.values[0].value.family
    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") == TARGET_REASON:
            continue
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        if not (
            0 <= candidate.start - end <= 64
            or 0 <= start - candidate.end <= 64
        ):
            continue
        pato_id = str(span.get("candidate_pato_id", ""))
        if baseline.QUALITY_FAMILY.get(pato_id) == family:
            return True
    return False


def _operand_context_reason(
    text: str,
    candidate: UnionCandidate,
    bearer: LocalBearer,
    clause_values: Iterable[ValueMatch] = (),
) -> str:
    """Reject degree-qualified or syntactically continued value endpoints."""

    uncertainty_end = max(candidate.end, bearer.end if bearer.end >= 0 else candidate.end)
    if _UNCERTAINTY.search(text[candidate.start:min(len(text), uncertainty_end + 2)]):
        return "uncertain_alternative"

    # Text after the nearest comma/semicolon/colon, or after a preceding bearer, must not add a
    # degree modifier to the first exact value (``dark red``, ``narrowly elliptic``).
    previous_delimiter = max(
        (text.rfind(mark, 0, candidate.values[0].start) for mark in ",;:."),
        default=-1,
    )
    prefix_start = previous_delimiter + 1
    if bearer.end <= candidate.values[0].start:
        prefix_start = max(prefix_start, bearer.end)
    prefix = text[prefix_start:candidate.values[0].start]
    if not _STRICT_FILLER.fullmatch(prefix):
        return "modified_first_operand"

    family_pattern = baseline.UNSUPPORTED_FAMILY_TERMS.get(
        candidate.values[0].value.family
    )
    if family_pattern is not None:
        hard_start = max(
            (text.rfind(mark, 0, candidate.values[0].start) for mark in ";:."),
            default=-1,
        ) + 1
        if bearer.end <= candidate.values[0].start:
            hard_start = max(hard_start, bearer.end)
        leading_context = text[hard_start:candidate.values[0].start]
        if family_pattern.search(leading_context):
            return "unsupported_same_attribute_preceding_value"

    candidate_keys = {
        (value.start, value.end, value.value.pato_id) for value in candidate.values
    }
    for other in clause_values:
        other_key = (other.start, other.end, other.value.pato_id)
        if other_key in candidate_keys or other.value.family != candidate.values[0].value.family:
            continue
        before_distance = candidate.start - other.end
        after_distance = other.start - candidate.end
        if 0 <= before_distance <= 40 or 0 <= after_distance <= 56:
            between = text[min(other.end, candidate.end):max(other.start, candidate.start)]
            if "," in between and not re.search(r"[;:.]", between):
                return "nearby_unincluded_same_attribute_value"

    # A final value followed by free text before punctuation is incomplete unless that text ends
    # in the selected explicit bearer itself (``red or green petals``).  This catches composite
    # alternatives such as ``white with purple tube`` and ``white or creamy white``.
    final_end = candidate.values[-1].end
    delimiter_match = re.search(r"[,;:.]", text[final_end:])
    boundary = (
        final_end + delimiter_match.start() if delimiter_match else len(text)
    )
    suffix = text[final_end:boundary]
    if bearer.start >= final_end and bearer.end <= boundary:
        relative_start = bearer.start - final_end
        relative_end = bearer.end - final_end
        suffix = suffix[:relative_start] + suffix[relative_end:]
    if not _STRICT_FILLER.fullmatch(suffix):
        return "qualified_or_incomplete_final_operand"
    return ""


def _adjacent_structural_failure(
    candidate: UnionCandidate,
    attempts: Iterable[EdgeAttempt],
) -> bool:
    """True when another attached ``or`` has an ungrounded or modified endpoint."""

    value_keys = {
        (value.start, value.end, value.value.pato_id) for value in candidate.values
    }
    for attempt in attempts:
        left_key = (
            (attempt.left.start, attempt.left.end, attempt.left.value.pato_id)
            if attempt.left
            else None
        )
        right_key = (
            (attempt.right.start, attempt.right.end, attempt.right.value.pato_id)
            if attempt.right
            else None
        )
        shares_operand = left_key in value_keys or right_key in value_keys
        nearby = candidate.start - 24 <= attempt.connector_start <= candidate.end + 40
        if attempt.reason and (shares_operand or nearby):
            return True
        if (
            not attempt.reason
            and not shares_operand
            and nearby
            and attempt.left is not None
            and attempt.right is not None
            and attempt.left.value.family == candidate.values[0].value.family
        ):
            return True
    return False


def _decision_base(record: dict, candidate: UnionCandidate) -> dict[str, object]:
    family = candidate.values[0].value.family if candidate.values else ""
    text = str(record.get("text", ""))
    clause, _clause_start = baseline._clause_at(text, candidate.start)
    return {
        "source": str(record.get("source", "")),
        "source_id": str(record.get("source_id", "")),
        "source_segment_index": record.get("source_segment_index", ""),
        "taxon": str(record.get("taxon", "")),
        "organ": str(record.get("organ", "")),
        "language": str(record.get("language", "")),
        "expression_start": candidate.start,
        "expression_end": candidate.end,
        "expression_text": text[candidate.start:candidate.end],
        "source_context": clause,
        "family": family,
        "attribute_pato_id": ATTRIBUTE_BY_FAMILY.get(family, ""),
        "value_terms": tuple(
            dict.fromkeys(value.value.pato_id for value in candidate.values)
        ),
        "value_labels": tuple(
            dict.fromkeys(value.value.label for value in candidate.values)
        ),
        "value_source_forms": tuple(value.source_form for value in candidate.values),
    }


def evaluate_candidate(
    record: dict,
    candidate: UnionCandidate,
    attempts: Iterable[EdgeAttempt] = (),
    clause_values: Iterable[ValueMatch] = (),
) -> CandidateDecision:
    text = str(record.get("text", ""))
    base = _decision_base(record, candidate)
    overlapping = _overlapping_target_indexes(record, candidate)
    contained = _target_spans_within_expression(record, candidate)
    if not overlapping:
        return CandidateDecision("routed", "not_seeded_by_target_span", **base)
    if set(contained) != set(overlapping):
        return CandidateDecision("routed", "ungrounded_operand_span", **base)
    if _adjacent_structural_failure(candidate, attempts):
        return CandidateDecision("routed", "incomplete_adjacent_alternative", **base)
    if _nearby_unresolved_same_family(record, candidate):
        return CandidateDecision(
            "routed", "nearby_unresolved_same_attribute_value", **base
        )
    before = text[max(0, candidate.start - 36):candidate.start]
    after = text[candidate.end:min(len(text), candidate.end + 36)]
    if _TRANSITION_BEFORE.search(before) or _TRANSITION_AFTER.search(after):
        return CandidateDecision("routed", "transition_context", **base)
    for value in candidate.values:
        contextual = _local_value_context_reason(text, candidate, value)
        if contextual:
            return CandidateDecision("routed", contextual, **base)
    if _EXCLUDED_SCOPE_AFTER.match(after):
        return CandidateDecision("routed", "excluded_geographic_scope", **base)
    clause, _clause_start = baseline._clause_at(text, candidate.start)
    if _TEMPORAL_CONTEXT.search(clause):
        return CandidateDecision("routed", "developmental_stage_context", **base)
    bearers = tuple(_resolve_explicit_bearer(record, value) for value in candidate.values)
    if any(not bearer.po_id for bearer in bearers):
        method = next(
            (bearer.method for bearer in bearers if not bearer.po_id),
            "heading_only_or_missing",
        )
        return CandidateDecision("routed", method, **base)
    occurrence_keys = {bearer.occurrence_key for bearer in bearers}
    if len(occurrence_keys) != 1:
        return CandidateDecision("routed", "different_explicit_bearers", **base)
    selected = bearers[0]
    if selected.method not in {"explicit_local", "contextual_local"}:
        return CandidateDecision("routed", "heading_only_or_missing", **base)
    if _ambiguous_local_bearers(record, candidate, selected):
        return CandidateDecision("routed", "multiple_local_bearers", **base)
    operand_context_reason = _operand_context_reason(
        text, candidate, selected, clause_values
    )
    if operand_context_reason:
        return CandidateDecision("routed", operand_context_reason, **base)
    scope_reason = _bearer_scope_reason(text, candidate, selected)
    if scope_reason:
        return CandidateDecision("routed", scope_reason, **base)
    return CandidateDecision(
        "promoted",
        "exact_complete_union",
        **base,
        bearer_po_id=selected.po_id,
        bearer_method=selected.method,
        bearer_surface=selected.surface_form,
        bearer_start=selected.start,
        bearer_end=selected.end,
        resolved_unresolved_spans=len(overlapping),
    )


def _rejected_edge_decision(record: dict, attempt: EdgeAttempt) -> CandidateDecision:
    values = tuple(value for value in (attempt.left, attempt.right) if value is not None)
    if not values:
        # Keep exact connector offsets even when neither endpoint was groundable.
        base: dict[str, object] = {
            "source": str(record.get("source", "")),
            "source_id": str(record.get("source_id", "")),
            "source_segment_index": record.get("source_segment_index", ""),
            "taxon": str(record.get("taxon", "")),
            "organ": str(record.get("organ", "")),
            "language": str(record.get("language", "")),
            "expression_start": attempt.connector_start,
            "expression_end": attempt.connector_end,
            "expression_text": str(record.get("text", ""))[
                attempt.connector_start:attempt.connector_end
            ],
            "source_context": baseline._clause_at(
                str(record.get("text", "")), attempt.connector_start
            )[0],
            "family": "",
            "attribute_pato_id": "",
            "value_terms": (),
            "value_labels": (),
            "value_source_forms": (),
        }
    else:
        candidate = UnionCandidate(values, (attempt.connector_start,))
        base = _decision_base(record, candidate)
    return CandidateDecision("routed", attempt.reason or "structural_parse_failure", **base)


def recover_record(
    record: dict,
    lexicon: ExactPatoValueLexicon,
) -> tuple[dict, Counter[str], list[CandidateDecision]]:
    result = dict(record)
    text = str(record.get("text", ""))
    assertions = [dict(row) for row in record.get("assertions", []) or []]
    unresolved = [dict(row) for row in record.get("unresolved_spans", []) or []]
    target_spans = [row for row in unresolved if row.get("reason") == TARGET_REASON]
    outcomes: Counter[str] = Counter()
    decisions: list[CandidateDecision] = []
    removed: set[int] = set()
    if not target_spans:
        return result, outcomes, decisions

    clause_ranges: set[tuple[int, int]] = set()
    for span in target_spans:
        clause, clause_start = baseline._clause_at(text, int(span.get("start", -1)))
        clause_ranges.add((clause_start, clause_start + len(clause)))

    seen_candidates: set[tuple[int, int, tuple[str, ...]]] = set()
    rejected_attempts: list[EdgeAttempt] = []
    for clause_start, clause_end in sorted(clause_ranges):
        values = lexicon.matches(text, clause_start, clause_end)
        attempts = _edge_attempts(text, clause_start, clause_end, values)
        rejected_attempts.extend(attempt for attempt in attempts if attempt.reason)
        for candidate in _union_candidates(text, values, attempts):
            value_terms = tuple(value.value.pato_id for value in candidate.values)
            key = candidate.start, candidate.end, value_terms
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            decision = evaluate_candidate(record, candidate, attempts, values)
            decisions.append(decision)
            outcomes[f"{decision.status}:{decision.reason}"] += 1
            if decision.status != "promoted":
                continue
            existing = next(
                (
                    row
                    for row in assertions
                    if row.get("po_id") == decision.bearer_po_id
                    and (row.get("value_operator", "atomic") or "atomic") == "one_of"
                    and set(row.get("value_terms", []) or []) == set(decision.value_terms)
                    and int(row.get("source_start", -1)) <= decision.expression_start
                    and decision.expression_end <= int(row.get("source_end", -1))
                ),
                None,
            )
            matching_indexes = _overlapping_target_indexes(record, candidate)
            if existing is not None:
                removed.update(matching_indexes)
                outcomes["already_asserted"] += 1
                continue
            qualifier_fields, qualifier_start, qualifier_text = baseline._modality_context(
                text, candidate.start
            )
            seasons, season_operator, season_start, season_end = baseline._season_context(
                text, candidate.start, candidate.end
            )
            source_start = min(candidate.start, qualifier_start, season_start)
            source_end = max(candidate.end, season_end)
            assertions.append(
                {
                    "po_id": decision.bearer_po_id,
                    "pato_id": decision.attribute_pato_id,
                    "negated": False,
                    "organ": record.get("organ", ""),
                    "source_text": text[source_start:source_end],
                    "source_start": source_start,
                    "source_end": source_end,
                    "value_text": text[candidate.start:candidate.end],
                    "value_operator": "one_of",
                    "value_terms": list(decision.value_terms),
                    "modality_text": qualifier_text,
                    "season_contexts": seasons,
                    "season_operator": season_operator,
                    "normalization_status": "compositional",
                    "mapping_provenance": [
                        "PATO preferred labels or EXACT synonyms; complete explicit source union",
                        (
                            "same explicit PO bearer occurrence: "
                            f"{decision.bearer_surface} [{decision.bearer_start},"
                            f"{decision.bearer_end})"
                        ),
                    ],
                    "extractor": EXTRACTOR,
                    **qualifier_fields,
                }
            )
            removed.update(matching_indexes)
            outcomes["promoted_assertions"] += 1
            outcomes[f"promoted_arity:{decision.arity}"] += 1
            outcomes[f"promoted_family:{decision.family}"] += 1
            outcomes[f"promoted_bearer_method:{decision.bearer_method}"] += 1
            outcomes[f"promoted_po:{decision.bearer_po_id}"] += 1
            outcomes[
                "promoted_pattern:" + "|".join(decision.value_terms)
            ] += 1
            outcomes["resolved_evidence_spans"] += len(matching_indexes)

    # Keep structural failures as routed evidence, but avoid duplicating a connector already
    # represented inside an evaluated multi-value component.
    candidate_connector_starts = {
        connector
        for decision in decisions
        for connector in _CONNECTOR_STARTS_IN_TEXT(
            text, decision.expression_start, decision.expression_end
        )
    }
    for attempt in rejected_attempts:
        if attempt.connector_start in candidate_connector_starts:
            continue
        decision = _rejected_edge_decision(record, attempt)
        decisions.append(decision)
        outcomes[f"{decision.status}:{decision.reason}"] += 1

    result["assertions"] = assertions
    result["unresolved_spans"] = [
        row for index, row in enumerate(unresolved) if index not in removed
    ]
    return result, outcomes, decisions


def _CONNECTOR_STARTS_IN_TEXT(text: str, start: int, end: int) -> tuple[int, ...]:
    return tuple(match.start() for match in _CONNECTOR.finditer(text, start, end))


def _decision_row(decision: CandidateDecision) -> dict[str, object]:
    row = {
        field: getattr(decision, field)
        for field in CANDIDATE_FIELDS
        if field not in {"arity", "value_terms", "value_labels", "value_source_forms"}
    }
    row.update(
        {
            "arity": decision.arity,
            "value_terms": "|".join(decision.value_terms),
            "value_labels": "|".join(decision.value_labels),
            "value_source_forms": "|".join(decision.value_source_forms),
        }
    )
    return row


def write_candidate_tsv(path: Path, decisions: Iterable[CandidateDecision]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(_decision_row(decision) for decision in decisions)


def write_fixed_seed_sample(
    path: Path,
    decisions: Iterable[CandidateDecision],
    *,
    seed: int = 20260718,
    size: int = 50,
) -> dict[str, object]:
    promoted = list(decision for decision in decisions if decision.status == "promoted")
    strata: dict[tuple[str, int], list[CandidateDecision]] = defaultdict(list)
    for decision in promoted:
        strata[(decision.source, decision.arity)].append(decision)
    rng = random.Random(seed)
    chosen: list[CandidateDecision] = []
    chosen_keys: set[tuple[object, ...]] = set()

    def key(decision: CandidateDecision) -> tuple[object, ...]:
        return (
            decision.source,
            decision.source_id,
            decision.source_segment_index,
            decision.expression_start,
            decision.expression_end,
            decision.value_terms,
        )

    # Guarantee one row from every flora/arity stratum, then fill the remainder globally.
    for stratum in sorted(strata):
        decision = rng.choice(sorted(strata[stratum], key=key))
        if key(decision) not in chosen_keys:
            chosen.append(decision)
            chosen_keys.add(key(decision))
    remaining = [decision for decision in promoted if key(decision) not in chosen_keys]
    rng.shuffle(remaining)
    chosen.extend(remaining[: max(0, size - len(chosen))])
    chosen = sorted(chosen[:size], key=lambda decision: (decision.source, decision.arity, key(decision)))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS, delimiter="\t")
        writer.writeheader()
        for decision in chosen:
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
        "sample_size": len(chosen),
        "strata": {
            f"{source}|arity_{arity}": sum(
                decision.source == source and decision.arity == arity
                for decision in chosen
            )
            for source, arity in sorted(strata)
        },
    }


def recover_file(
    input_path: Path,
    output_path: Path,
    *,
    candidate_tsv: Path,
    pato_obo: Path = Path("ont/quality.obo"),
    sample_tsv: Path | None = None,
    sample_seed: int = 20260718,
    sample_size: int = 50,
) -> dict[str, object]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("recovery output must be distinct from its input")
    lexicon = ExactPatoValueLexicon.load(pato_obo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    outcomes: Counter[str] = Counter()
    promoted_by_source: Counter[str] = Counter()
    promoted_by_arity: Counter[int] = Counter()
    all_decisions: list[CandidateDecision] = []
    with Path(input_path).open(encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            recovered, record_outcomes, decisions = recover_record(record, lexicon)
            output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
            records += 1
            outcomes.update(record_outcomes)
            all_decisions.extend(decisions)
            for decision in decisions:
                if decision.status == "promoted":
                    promoted_by_source[decision.source] += 1
                    promoted_by_arity[decision.arity] += 1
    write_candidate_tsv(candidate_tsv, all_decisions)
    sample_report = None
    if sample_tsv is not None:
        sample_report = write_fixed_seed_sample(
            sample_tsv,
            all_decisions,
            seed=sample_seed,
            size=sample_size,
        )
    return {
        "input": str(input_path),
        "output": str(output_path),
        "candidate_tsv": str(candidate_tsv),
        "records": records,
        "exact_pato_value_forms": len(lexicon.forms),
        "decisions": len(all_decisions),
        "promoted_by_source": dict(sorted(promoted_by_source.items())),
        "promoted_by_arity": {
            str(key): value for key, value in sorted(promoted_by_arity.items())
        },
        "outcomes": dict(sorted(outcomes.items())),
        "sample": sample_report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--sample-seed", type=int, default=20260718)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = recover_file(
        args.input,
        args.output,
        candidate_tsv=args.candidates,
        pato_obo=args.pato_obo,
        sample_tsv=args.sample,
        sample_seed=args.sample_seed,
        sample_size=args.sample_size,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
