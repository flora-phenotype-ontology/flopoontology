"""Validation and canonicalization for non-FAC qualitative value relations.

Qualitative continua, taxon-level ranges of alternatives, and temporal transitions are not
finite OWL unions.  This module keeps their source-ordered endpoints explicit while providing one
fail-closed validator shared by the gate, data-model validator, database, and RDF serializers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


OBO = "http://purl.obolibrary.org/obo/"
INTERPRETATIONS = frozenset(
    {"continuum", "taxon_level_alternatives", "temporal_transition"}
)
VALUE_ID = re.compile(r"^(?:PATO|FLOPO)(?::|_)\d+$")


@dataclass(frozen=True)
class QualitativeRelationIssue:
    code: str
    message: str


def canonical_value_id(value: object) -> str:
    normalized = str(value or "").strip().replace(":", "_")
    if not VALUE_ID.fullmatch(normalized):
        raise ValueError(f"qualitative endpoint must be a PATO or FLOPO class: {value!r}")
    return normalized


def canonical_value_iri(value: object) -> str:
    return OBO + canonical_value_id(value)


def canonical_qualitative_relation(assertion: dict[str, Any]) -> dict[str, Any]:
    """Return the source-ordered semantic and evidence record, or fail closed."""

    relation = assertion.get("qualitative_value_relation")
    if not isinstance(relation, dict):
        raise ValueError("qualitative_value_relation must be an object")
    interpretation = str(relation.get("interpretation", "") or "").strip()
    if interpretation not in INTERPRETATIONS:
        raise ValueError(f"unsupported qualitative relation interpretation: {interpretation!r}")
    from_value = canonical_value_id(relation.get("from_value"))
    to_value = canonical_value_id(relation.get("to_value"))
    if from_value == to_value:
        raise ValueError("qualitative relation endpoints must be distinct")

    result: dict[str, Any] = {
        "interpretation": interpretation,
        "from_value": from_value,
        "to_value": to_value,
    }
    for prefix in ("from", "connector", "to"):
        text = relation.get(f"{prefix}_text")
        start = relation.get(f"{prefix}_start")
        end = relation.get(f"{prefix}_end")
        if not isinstance(text, str) or not text:
            raise ValueError(f"qualitative relation {prefix}_text must be non-empty")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
        ):
            raise ValueError(f"qualitative relation {prefix} offsets must be integers")
        result[f"{prefix}_text"] = text
        result[f"{prefix}_start"] = start
        result[f"{prefix}_end"] = end
    return result


def qualitative_relation_semantics(assertion: dict[str, Any]) -> dict[str, str]:
    """Canonical provenance-free semantics for stable assertion identity."""

    relation = canonical_qualitative_relation(assertion)
    return {
        "interpretation": relation["interpretation"],
        "from_value": canonical_value_iri(relation["from_value"]),
        "to_value": canonical_value_iri(relation["to_value"]),
    }


def is_fac_representable(assertion: dict[str, Any]) -> bool:
    """Whether the assertion has a complete expression in the current FAC grammar."""

    from flopo2.annotation.operands import operands_fac_representable

    return not (
        str(assertion.get("cardinality", "") or "").strip()
        or assertion.get("qualitative_value_relation")
        or not operands_fac_representable(assertion)
    )


def validate_qualitative_value_relation(
    assertion: dict[str, Any],
    segment_text: str,
    *,
    pato_catalog_ids: set[str] | None = None,
    flopo_catalog_ids: set[str] | None = None,
    attribute_pato_ids: set[str] | None = None,
) -> tuple[QualitativeRelationIssue, ...]:
    """Validate endpoint identity, source evidence, and mutual-exclusion invariants."""

    if not assertion.get("qualitative_value_relation"):
        return ()
    issues: list[QualitativeRelationIssue] = []
    try:
        relation = canonical_qualitative_relation(assertion)
    except ValueError as exc:
        return (QualitativeRelationIssue("invalid_qualitative_value_relation", str(exc)),)

    for endpoint in (relation["from_value"], relation["to_value"]):
        if endpoint.startswith("PATO_") and pato_catalog_ids and endpoint not in pato_catalog_ids:
            issues.append(
                QualitativeRelationIssue("unknown_qualitative_endpoint_pato_id", endpoint)
            )
        elif endpoint.startswith("FLOPO_") and flopo_catalog_ids and endpoint not in flopo_catalog_ids:
            issues.append(
                QualitativeRelationIssue("unknown_qualitative_endpoint_flopo_id", endpoint)
            )

    pato_id = str(assertion.get("pato_id", "") or "").replace(":", "_")
    if attribute_pato_ids and pato_id not in attribute_pato_ids:
        issues.append(
            QualitativeRelationIssue(
                "qualitative_relation_top_level_not_attribute",
                f"top-level quality is not a PATO attribute: {pato_id!r}",
            )
        )

    spans: list[tuple[int, int, str, str]] = []
    for prefix in ("from", "connector", "to"):
        start = relation[f"{prefix}_start"]
        end = relation[f"{prefix}_end"]
        expected = relation[f"{prefix}_text"]
        spans.append((start, end, expected, prefix))
        if start < 0 or end <= start or end > len(segment_text):
            issues.append(
                QualitativeRelationIssue(
                    f"invalid_qualitative_{prefix}_offsets",
                    f"[{start}, {end}) outside source length {len(segment_text)}",
                )
            )
        elif segment_text[start:end] != expected:
            issues.append(
                QualitativeRelationIssue(
                    f"qualitative_{prefix}_not_verbatim",
                    f"offsets do not select {expected!r}",
                )
            )
    if not (spans[0][1] <= spans[1][0] and spans[1][1] <= spans[2][0]):
        issues.append(
            QualitativeRelationIssue(
                "qualitative_relation_source_order",
                "expected from endpoint, connector, and to endpoint in non-overlapping source order",
            )
        )

    source_start = assertion.get("source_start")
    source_end = assertion.get("source_end")
    if (
        isinstance(source_start, int)
        and not isinstance(source_start, bool)
        and isinstance(source_end, int)
        and not isinstance(source_end, bool)
        and not (source_start <= spans[0][0] and spans[2][1] <= source_end)
    ):
        issues.append(
            QualitativeRelationIssue(
                "qualitative_relation_outside_assertion_span",
                "endpoint evidence is not wholly contained in source_start/source_end",
            )
        )

    operator = str(assertion.get("value_operator", "atomic") or "atomic")
    values = assertion.get("value_terms", []) or assertion.get("value_term_ids", []) or []
    conflicts = {
        "qualitative_relation_with_logical_operator": operator != "atomic",
        "qualitative_relation_with_value_terms": bool(values),
        "qualitative_relation_with_numeric_value": (
            assertion.get("value_low") is not None or assertion.get("value_high") is not None
        ),
        "qualitative_relation_with_unit": bool(str(assertion.get("unit", "") or "").strip()),
        "qualitative_relation_with_cardinality": bool(
            str(assertion.get("cardinality", "") or "").strip()
        ),
        "qualitative_relation_with_negation": bool(assertion.get("negated", False)),
        "qualitative_relation_with_fac_iri": bool(assertion.get("phenotype_class_iri")),
        "qualitative_relation_with_part_restrictions": bool(
            assertion.get("part_restrictions", []) or []
        ),
        "qualitative_relation_with_bearer_context": bool(
            assertion.get("bearer_context_qualities", []) or []
        ),
        "qualitative_relation_with_developmental_stage": bool(
            assertion.get("developmental_stage_contexts", []) or []
        ),
    }
    for code, present in conflicts.items():
        if present:
            issues.append(QualitativeRelationIssue(code, code.replace("_", " ")))
    return tuple(issues)
