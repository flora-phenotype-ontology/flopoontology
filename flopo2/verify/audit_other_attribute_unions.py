"""Audit exact disjunctions outside the three reviewed PATO value families.

``recover_explicit_unions`` intentionally recognizes only colour, shape, and pilosity.  A
tempting generalization is to take the most-specific common ``attribute_slim`` ancestor of any
two exact PATO values.  That is not automatically sound: unrelated qualities can meet at a very
broad ancestor such as ``morphology``.  This module therefore *measures* that residual without
changing annotation data.

Rows reach ``review_queue`` only when they pass the same conservative source, logical, and
explicit-bearer checks as the reviewed-family recovery.  They still require semantic review of
the proposed attribute; no FAC class and no FLOPO identifier is minted here.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from flopo2.extract import baseline
from flopo2.verify.recover_exact_pato_compounds import PatoTerm, load_pato_terms
from flopo2.verify.recover_explicit_unions import (
    ATTRIBUTE_BY_FAMILY,
    TARGET_REASON,
    ExactPatoValueLexicon,
    ExactValue,
    LocalBearer,
    UnionCandidate,
    ValueMatch,
    _ambiguous_local_bearers,
    _bearer_scope_reason,
    _expression_bounds,
    _normal_form,
    _operand_context_reason,
    _resolve_explicit_bearer,
    _subset_members,
    _TEMPORAL_CONTEXT,
    _TRANSITION_AFTER,
    _TRANSITION_BEFORE,
    _UNSAFE_EXACT_BOTANICAL_FORMS,
)


_CONNECTOR = re.compile(r"\b(?:or|ou)\b", re.IGNORECASE)
_STRICT_FILLER = re.compile(r"[\s,()\[\]{}]*")
_COMMA = re.compile(r"\s*,\s*")
REVIEWED_ATTRIBUTES = frozenset(ATTRIBUTE_BY_FAMILY.values())
STATUS_REVIEW = "review_queue"
REVIEW_REASON = "structurally_safe_nonreviewed_attribute"
PATO_MORPHOLOGY = "PATO_0000051"
PATO_POSITION = "PATO_0000140"
_UNMODELLED_POSITION_VALUE_BEFORE = re.compile(
    r"\b(?:climbing|scandent|scrambling|twining|creeping|spreading|ascending)\s*,\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AttributeResolution:
    pato_id: str
    label: str
    distances: tuple[int, ...]

    @property
    def maximum_distance(self) -> int:
        return max(self.distances, default=0)


class PatoAttributeGraph:
    """The asserted PATO ``is_a`` graph plus its two slim memberships."""

    def __init__(
        self,
        terms: dict[str, PatoTerm],
        attributes: frozenset[str],
        values: frozenset[str],
    ) -> None:
        self.terms = terms
        self.attributes = attributes
        self.values = values
        self.parents = {
            pato_id: tuple(parent.replace(":", "_") for parent in term.parents)
            for pato_id, term in terms.items()
        }
        self._ancestor_cache: dict[str, frozenset[str]] = {}
        self._distance_cache: dict[tuple[str, str], int | None] = {}

    @classmethod
    def load(cls, pato_obo: Path) -> "PatoAttributeGraph":
        loaded = load_pato_terms(Path(pato_obo))
        terms = {term.pato_id: term for term in loaded.values()}
        return cls(
            terms,
            _subset_members(Path(pato_obo), "attribute_slim"),
            _subset_members(Path(pato_obo), "value_slim"),
        )

    def ancestors(self, pato_id: str) -> frozenset[str]:
        cached = self._ancestor_cache.get(pato_id)
        if cached is not None:
            return cached
        # PATO is expected to be acyclic, but the explicit stack also makes a malformed local
        # fixture terminate safely.
        found: set[str] = set()
        pending = [pato_id]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(self.parents.get(current, ()))
        result = frozenset(found)
        self._ancestor_cache[pato_id] = result
        return result

    def distance(self, pato_id: str, ancestor_id: str) -> int | None:
        key = pato_id, ancestor_id
        if key in self._distance_cache:
            return self._distance_cache[key]
        pending: deque[tuple[str, int]] = deque([(pato_id, 0)])
        visited: set[str] = set()
        result: int | None = None
        while pending:
            current, distance = pending.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current == ancestor_id:
                result = distance
                break
            pending.extend((parent, distance + 1) for parent in self.parents.get(current, ()))
        self._distance_cache[key] = result
        return result

    def unique_common_attribute(
        self, pato_ids: Iterable[str]
    ) -> AttributeResolution | None:
        ids = tuple(dict.fromkeys(pato_ids))
        if len(ids) < 2:
            return None
        common = set(self.attributes)
        for pato_id in ids:
            common.intersection_update(self.ancestors(pato_id))
        # Retain only common attributes that do not have a more-specific common attribute.
        most_specific = {
            candidate
            for candidate in common
            if not any(
                candidate != other and candidate in self.ancestors(other)
                for other in common
            )
        }
        if len(most_specific) != 1:
            return None
        pato_id = next(iter(most_specific))
        distances = tuple(self.distance(value_id, pato_id) for value_id in ids)
        if any(distance is None for distance in distances):
            return None
        term = self.terms.get(pato_id)
        return AttributeResolution(
            pato_id,
            term.label if term else "",
            tuple(int(distance) for distance in distances if distance is not None),
        )

    def shares_reviewed_attribute(self, pato_ids: Iterable[str]) -> bool:
        ids = tuple(pato_ids)
        return any(
            all(attribute in self.ancestors(pato_id) for pato_id in ids)
            for attribute in REVIEWED_ATTRIBUTES
        )


@dataclass(frozen=True)
class AuditEdge:
    left_index: int
    right_index: int
    connector_start: int
    connector_end: int
    attribute: AttributeResolution


AUDIT_FIELDS = [
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
    "attribute_pato_id",
    "attribute_label",
    "maximum_ancestry_distance",
    "arity",
    "value_terms",
    "value_labels",
    "value_source_forms",
    "bearer_po_id",
    "bearer_method",
    "bearer_surface",
    "bearer_start",
    "bearer_end",
]


def _all_exact_value_lexicon(graph: PatoAttributeGraph) -> ExactPatoValueLexicon:
    candidates: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for pato_id, term in graph.terms.items():
        if pato_id not in graph.values or pato_id in graph.attributes:
            continue
        for source_form in (term.label, *term.exact_synonyms):
            normalized = _normal_form(source_form)
            if (
                normalized not in _UNSAFE_EXACT_BOTANICAL_FORMS
                and len(normalized) >= 3
                and re.search(r"\w", normalized)
            ):
                candidates[normalized].add((pato_id, term.label))
    forms = {
        lexical_form: ExactValue(
            pato_id=next(iter(values))[0],
            label=next(iter(values))[1],
            family="",
            lexical_form=lexical_form,
        )
        for lexical_form, values in candidates.items()
        if len(values) == 1
    }
    return ExactPatoValueLexicon(forms)


def _direct_edges(
    text: str,
    clause_start: int,
    clause_end: int,
    values: list[ValueMatch],
    graph: PatoAttributeGraph,
    outcomes: Counter[str],
) -> list[AuditEdge]:
    edges: list[AuditEdge] = []
    for connector in _CONNECTOR.finditer(text, clause_start, clause_end):
        left_candidates = [
            (index, value)
            for index, value in enumerate(values)
            if value.end <= connector.start()
        ]
        right_candidates = [
            (index, value)
            for index, value in enumerate(values)
            if connector.end() <= value.start
        ]
        if not left_candidates or not right_candidates:
            outcomes["edge_routed:ungrounded_operand"] += 1
            continue
        left_index, left = max(left_candidates, key=lambda row: row[1].end)
        right_index, right = min(right_candidates, key=lambda row: row[1].start)
        if not _STRICT_FILLER.fullmatch(text[left.end:connector.start()]):
            outcomes["edge_routed:modified_left_operand"] += 1
            continue
        if not _STRICT_FILLER.fullmatch(text[connector.end():right.start]):
            outcomes["edge_routed:modified_right_operand"] += 1
            continue
        if left.value.pato_id == right.value.pato_id:
            outcomes["edge_routed:non_distinct_operands"] += 1
            continue
        value_ids = left.value.pato_id, right.value.pato_id
        if graph.shares_reviewed_attribute(value_ids):
            outcomes["edge_excluded:already_in_reviewed_family"] += 1
            continue
        attribute = graph.unique_common_attribute(value_ids)
        if attribute is None:
            outcomes["edge_routed:no_unique_common_attribute"] += 1
            continue
        edges.append(
            AuditEdge(
                left_index,
                right_index,
                connector.start(),
                connector.end(),
                attribute,
            )
        )
        outcomes[f"edge_other_attribute:{attribute.pato_id}"] += 1
    return edges


def _components(
    text: str,
    values: list[ValueMatch],
    edges: list[AuditEdge],
    graph: PatoAttributeGraph,
) -> list[tuple[UnionCandidate, AttributeResolution]]:
    by_attribute: dict[str, list[AuditEdge]] = defaultdict(list)
    for edge in edges:
        by_attribute[edge.attribute.pato_id].append(edge)
    candidates: list[tuple[UnionCandidate, AttributeResolution]] = []
    for attribute_id, attribute_edges in by_attribute.items():
        adjacency: dict[int, set[int]] = defaultdict(set)
        for edge in attribute_edges:
            adjacency[edge.left_index].add(edge.right_index)
            adjacency[edge.right_index].add(edge.left_index)
            # Preserve exact comma-list members in ``smooth, rough or wrinkled`` only for a
            # specific attribute.  A unique *broad* morphology ancestor does not make
            # ``long, simple or branched`` or ``terete, simple or branched`` a three-way union.
            cursor = edge.left_index
            while cursor > 0 and attribute_id != PATO_MORPHOLOGY:
                previous = cursor - 1
                value_ids = (
                    values[previous].value.pato_id,
                    values[cursor].value.pato_id,
                )
                previous_resolution = graph.unique_common_attribute(value_ids)
                if (
                    adjacency.get(previous)
                    or not _COMMA.fullmatch(text[values[previous].end:values[cursor].start])
                    or graph.shares_reviewed_attribute(value_ids)
                    or previous_resolution is None
                    or previous_resolution.pato_id != attribute_id
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
            ordered_indexes = sorted(component)
            ordered = tuple(
                ValueMatch(
                    values[index].start,
                    values[index].end,
                    ExactValue(
                        values[index].value.pato_id,
                        values[index].value.label,
                        attribute_id,
                        values[index].value.lexical_form,
                    ),
                    values[index].source_form,
                )
                for index in ordered_indexes
            )
            if len({value.value.pato_id for value in ordered}) < 2:
                continue
            connector_starts = tuple(
                sorted(
                    edge.connector_start
                    for edge in attribute_edges
                    if edge.left_index in component and edge.right_index in component
                )
            )
            start, end = _expression_bounds(text, ordered[0].start, ordered[-1].end)
            full_resolution = graph.unique_common_attribute(
                value.value.pato_id for value in ordered
            )
            if full_resolution is None or full_resolution.pato_id != attribute_id:
                continue
            candidates.append(
                (
                    UnionCandidate(ordered, connector_starts, start, end),
                    full_resolution,
                )
            )
    return candidates


def _target_scope_reason(record: dict, candidate: UnionCandidate) -> str:
    spans = [
        span
        for span in record.get("unresolved_spans", []) or []
        if span.get("reason") == TARGET_REASON
    ]
    overlapping = [
        span
        for span in spans
        if any(
            value.start <= int(span.get("start", -1))
            and int(span.get("end", -1)) <= value.end
            for value in candidate.values
        )
    ]
    if not overlapping:
        return "not_seeded_by_target_span"
    contained = [
        span
        for span in spans
        if candidate.start <= int(span.get("start", -1))
        and int(span.get("end", -1)) <= candidate.end
    ]
    if len(contained) != len(overlapping):
        return "ungrounded_operand_span"
    return ""


def _nearby_unresolved_attribute(
    record: dict,
    candidate: UnionCandidate,
    attribute_id: str,
    graph: PatoAttributeGraph,
) -> bool:
    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") == TARGET_REASON:
            continue
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        if not (0 <= candidate.start - end <= 64 or 0 <= start - candidate.end <= 64):
            continue
        pato_id = str(span.get("candidate_pato_id", ""))
        if attribute_id in graph.ancestors(pato_id):
            return True
    return False


def _base_row(
    record: dict,
    candidate: UnionCandidate,
    attribute: AttributeResolution,
) -> dict[str, object]:
    text = str(record.get("text", ""))
    clause, _ = baseline._clause_at(text, candidate.start)
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
        "attribute_pato_id": attribute.pato_id,
        "attribute_label": attribute.label,
        "maximum_ancestry_distance": attribute.maximum_distance,
        "arity": len(tuple(dict.fromkeys(v.value.pato_id for v in candidate.values))),
        "value_terms": "|".join(
            dict.fromkeys(value.value.pato_id for value in candidate.values)
        ),
        "value_labels": "|".join(
            dict.fromkeys(value.value.label for value in candidate.values)
        ),
        "value_source_forms": "|".join(value.source_form for value in candidate.values),
        "bearer_po_id": "",
        "bearer_method": "",
        "bearer_surface": "",
        "bearer_start": -1,
        "bearer_end": -1,
    }


def _decision(
    record: dict,
    candidate: UnionCandidate,
    attribute: AttributeResolution,
    graph: PatoAttributeGraph,
    clause_values: Iterable[ValueMatch],
) -> dict[str, object]:
    text = str(record.get("text", ""))
    base = _base_row(record, candidate, attribute)

    def routed(reason: str) -> dict[str, object]:
        return {"status": "routed", "reason": reason, **base}

    scope_reason = _target_scope_reason(record, candidate)
    if scope_reason:
        return routed(scope_reason)
    clause, clause_start = baseline._clause_at(text, candidate.start)
    clause_end = clause_start + len(clause)
    other_connectors = [
        connector.start()
        for connector in _CONNECTOR.finditer(text, clause_start, clause_end)
        if connector.start() not in set(candidate.connector_starts)
        and candidate.start - 24 <= connector.start() <= candidate.end + 40
    ]
    if other_connectors:
        return routed("incomplete_adjacent_alternative")
    connector_gaps = [
        text[value.end:connector_start]
        for value, connector_start in zip(
            candidate.values[:-1], candidate.connector_starts, strict=False
        )
    ]
    prefix = text[clause_start:candidate.start]
    # A serial comma signals a list whose earlier member may be outside the PATO exact-value
    # lexicon, as in ``membranous, chartaceous, or coriaceous``.  Do not silently emit the
    # incomplete two-way tail.
    if any("," in gap for gap in connector_gaps) and re.search(
        r"\b[A-Za-zÀ-ÖØ-öø-ÿ'’\-]+\s*,\s*$", prefix
    ):
        return routed("unmodelled_preceding_alternative")
    if attribute.pato_id == PATO_POSITION and _UNMODELLED_POSITION_VALUE_BEFORE.search(
        prefix
    ):
        return routed("unmodelled_preceding_alternative")
    if _nearby_unresolved_attribute(record, candidate, attribute.pato_id, graph):
        return routed("nearby_unresolved_same_attribute_value")
    before = text[max(0, candidate.start - 36):candidate.start]
    after = text[candidate.end:min(len(text), candidate.end + 36)]
    if _TRANSITION_BEFORE.search(before) or _TRANSITION_AFTER.search(after):
        return routed("transition_context")
    for value in candidate.values:
        contextual = baseline._negated_or_hedged(text, value.start)
        if contextual:
            return routed(contextual)
    if _TEMPORAL_CONTEXT.search(clause):
        return routed("developmental_stage_context")
    bearers = tuple(_resolve_explicit_bearer(record, value) for value in candidate.values)
    if any(not bearer.po_id for bearer in bearers):
        method = next(
            (bearer.method for bearer in bearers if not bearer.po_id),
            "heading_only_or_missing",
        )
        return routed(method)
    if len({bearer.occurrence_key for bearer in bearers}) != 1:
        return routed("different_explicit_bearers")
    selected: LocalBearer = bearers[0]
    if selected.method not in {"explicit_local", "contextual_local"}:
        return routed("heading_only_or_missing")
    if _ambiguous_local_bearers(record, candidate, selected):
        return routed("multiple_local_bearers")
    candidate_value_keys = {
        (value.start, value.end, value.value.pato_id) for value in candidate.values
    }
    mapped_clause_values = [
        ValueMatch(
            value.start,
            value.end,
            ExactValue(
                value.value.pato_id,
                value.value.label,
                attribute.pato_id
                if attribute.pato_id in graph.ancestors(value.value.pato_id)
                and (
                    attribute.pato_id != PATO_MORPHOLOGY
                    or (value.start, value.end, value.value.pato_id)
                    in candidate_value_keys
                )
                else "other",
                value.value.lexical_form,
            ),
            value.source_form,
        )
        for value in clause_values
    ]
    operand_reason = _operand_context_reason(
        text, candidate, selected, mapped_clause_values
    )
    if operand_reason:
        return routed(operand_reason)
    bearer_reason = _bearer_scope_reason(text, candidate, selected)
    if bearer_reason:
        return routed(bearer_reason)
    return {
        "status": STATUS_REVIEW,
        "reason": REVIEW_REASON,
        **base,
        "bearer_po_id": selected.po_id,
        "bearer_method": selected.method,
        "bearer_surface": selected.surface_form,
        "bearer_start": selected.start,
        "bearer_end": selected.end,
    }


def audit_record(
    record: dict,
    graph: PatoAttributeGraph,
    lexicon: ExactPatoValueLexicon,
) -> tuple[list[dict[str, object]], Counter[str]]:
    outcomes: Counter[str] = Counter()
    targets = [
        span
        for span in record.get("unresolved_spans", []) or []
        if span.get("reason") == TARGET_REASON
    ]
    if not targets:
        return [], outcomes
    text = str(record.get("text", ""))
    clause_ranges: set[tuple[int, int]] = set()
    for span in targets:
        clause, clause_start = baseline._clause_at(text, int(span.get("start", -1)))
        clause_ranges.add((clause_start, clause_start + len(clause)))
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, int, str, str]] = set()
    for clause_start, clause_end in sorted(clause_ranges):
        values = lexicon.matches(text, clause_start, clause_end)
        edges = _direct_edges(text, clause_start, clause_end, values, graph, outcomes)
        for candidate, attribute in _components(text, values, edges, graph):
            key = (
                candidate.start,
                candidate.end,
                attribute.pato_id,
                "|".join(value.value.pato_id for value in candidate.values),
            )
            if key in seen:
                continue
            seen.add(key)
            row = _decision(record, candidate, attribute, graph, values)
            rows.append(row)
            outcomes[f"candidate_{row['status']}:{row['reason']}"] += 1
    return rows, outcomes


def run_audit(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    pato_obo: Path,
) -> dict[str, object]:
    graph = PatoAttributeGraph.load(pato_obo)
    lexicon = _all_exact_value_lexicon(graph)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    records = 0
    with Path(input_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            records += 1
            record_rows, record_outcomes = audit_record(
                json.loads(line), graph, lexicon
            )
            rows.extend(record_rows)
            outcomes.update(record_outcomes)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    review_rows = [row for row in rows if row["status"] == STATUS_REVIEW]
    by_source = Counter(str(row["source"]) for row in review_rows)
    by_attribute = Counter(
        f"{row['attribute_pato_id']}|{row['attribute_label']}" for row in review_rows
    )
    by_arity = Counter(str(row["arity"]) for row in review_rows)
    unique_value_patterns = {
        (
            str(row["attribute_pato_id"]),
            tuple(sorted(str(row["value_terms"]).split("|"))),
        )
        for row in review_rows
    }
    unique_phenotype_patterns = {
        (
            str(row["bearer_po_id"]),
            str(row["attribute_pato_id"]),
            tuple(sorted(str(row["value_terms"]).split("|"))),
        )
        for row in review_rows
    }
    report: dict[str, object] = {
        "input": str(input_path),
        "output": str(output_path),
        "pato_obo": str(pato_obo),
        "records": records,
        "exact_value_forms": len(lexicon.forms),
        "candidate_rows": len(rows),
        "structurally_safe_review_occurrences": len(review_rows),
        "unique_attribute_value_patterns": len(unique_value_patterns),
        "unique_bearer_attribute_value_patterns": len(unique_phenotype_patterns),
        "review_by_source": dict(sorted(by_source.items())),
        "review_by_arity": dict(sorted(by_arity.items())),
        "review_by_attribute": dict(
            sorted(by_attribute.items(), key=lambda item: (-item[1], item[0]))
        ),
        "outcomes": dict(sorted(outcomes.items())),
        "disposition": (
            "next_wave_semantic_review; no annotations or ontology identifiers minted"
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    return parser


def main() -> None:
    args = _parser().parse_args()
    print(
        json.dumps(
            run_audit(args.input, args.output, args.report, args.pato_obo),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
