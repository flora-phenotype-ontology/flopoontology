"""Per-operand and per-endpoint qualifiers (schema extension E2, curator approval 2026-09-18).

A categorical value expression such as ``glabrous or sparsely pubescent`` has one qualifier per
operand.  ``value_operands`` keeps each operand's verbatim text, grounded value and its own
degree, approximation and frequency qualifier.  Qualitative relations carry the same record on
their endpoints (``from_operand``/``to_operand``: ``narrowly elliptic to broadly elliptic``).

Semantics
    * Degree qualifiers other than ``completely`` are *entailing*: ``sparsely pubescent`` is
      pubescent, so the operand's head value enters the FAC union and the cue is provenance only.
    * Approximation (``approximately``, ``nearly``, ``almost``, ``sub``) is *non-entailing*:
      ``suborbicular`` is not orbicular.  An assertion with such an operand is not
      FAC-representable and carries no ``phenotype_class_iri``.
    * Operands never participate in the FAC signature, so FAC identity is unchanged for every
      assertion whose operands are all entailing.

This module is the single source of the cue lexicon and of the fail-closed validator shared by
the gate, the data-model validator and the OWL serializers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


VALUE_ID = re.compile(r"^(?:PATO|FLOPO)(?::|_)\d+$")

# Axis of every DegreeQualifier value (mirrors the ``axis`` annotation in flopo_trait.yaml).
DEGREE_AXIS: dict[str, str] = {
    "slightly": "intensity",
    "moderately": "intensity",
    "very": "intensity",
    "extremely": "intensity",
    "completely": "intensity",
    "narrowly": "width",
    "broadly": "width",
    "densely": "density",
    "sparsely": "density",
    "shortly": "extent",
    "finely": "texture",
    "deeply": "depth",
    "shallowly": "depth",
}
DEGREE_VALUES = frozenset({"unmodified", *DEGREE_AXIS})
VALUE_QUALIFIER_VALUES = frozenset({"exact", "approximately", "nearly", "almost", "sub"})
FREQUENCY_VALUES = frozenset(
    {"universal", "usually", "often", "sometimes", "occasionally", "rarely", "never", "unspecified"}
)
NON_ENTAILING_DEGREES = frozenset({"completely"})
NON_ENTAILING_VALUE_QUALIFIERS = frozenset({"approximately", "nearly", "almost", "sub"})

# English and French degree cues.  Multi-word cues are matched before their parts, so
# ``peu profondément`` is shallowly while ``peu ramifié`` is sparsely.
DEGREE_CUES: dict[str, str] = {
    # width
    "narrowly": "narrowly",
    "étroitement": "narrowly",
    "etroitement": "narrowly",
    "broadly": "broadly",
    "widely": "broadly",
    "largement": "broadly",
    # density
    "densely": "densely",
    "closely": "densely",
    "richly": "densely",
    "abundantly": "densely",
    "much": "densely",
    "densément": "densely",
    "densement": "densely",
    "abondamment": "densely",
    "richement": "densely",
    "sparsely": "sparsely",
    "sparingly": "sparsely",
    "thinly": "sparsely",
    "laxly": "sparsely",
    "loosely": "sparsely",
    "éparsement": "sparsely",
    "eparsement": "sparsely",
    "peu": "sparsely",
    # extent
    "shortly": "shortly",
    "brièvement": "shortly",
    "brievement": "shortly",
    "courtement": "shortly",
    # texture
    "finely": "finely",
    "minutely": "finely",
    "finement": "finely",
    # depth
    "deeply": "deeply",
    "profondément": "deeply",
    "profondement": "deeply",
    "shallowly": "shallowly",
    "peu profondément": "shallowly",
    "peu profondement": "shallowly",
    # intensity
    "slightly": "slightly",
    "weakly": "slightly",
    "faintly": "slightly",
    "légèrement": "slightly",
    "legerement": "slightly",
    "faiblement": "slightly",
    "un peu": "slightly",
    "moderately": "moderately",
    "very": "very",
    "strongly": "very",
    "highly": "very",
    "très": "very",
    "tres": "very",
    "fortement": "very",
    "extremely": "extremely",
    "completely": "completely",
    "entirely": "completely",
}
APPROXIMATION_CUES: dict[str, str] = {
    "±": "approximately",
    "+/-": "approximately",
    "+-": "approximately",
    "more or less": "approximately",
    "plus ou moins": "approximately",
    "approximately": "approximately",
    "nearly": "nearly",
    "almost": "almost",
    "presque": "almost",
    "sub": "sub",
    "semi": "sub",
}
_CUE_TOKEN = re.compile(
    "|".join(
        sorted(
            (
                re.escape(cue) if not cue[0].isalpha() else rf"\b{re.escape(cue)}\b"
                for cue in (*DEGREE_CUES, *APPROXIMATION_CUES)
            ),
            key=len,
            reverse=True,
        )
    ),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OperandIssue:
    code: str
    message: str


def degree_axis(degree: object) -> str:
    return DEGREE_AXIS.get(str(degree or ""), "")


def parse_qualifier_cue(cue: str) -> dict[str, str]:
    """Map a verbatim operand cue (``± densely``, ``very sparsely``) to qualifier values.

    The degree is the cue word nearest the value (``very sparsely`` is sparsely; the intensity
    word stays in the verbatim cue).  Frequency words are resolved with the shared provenance
    aliases.  Unknown words are ignored; callers decide whether an unmapped cue blocks.
    """

    from flopo2.annotation.provenance import FREQUENCY_ALIASES

    result = {
        "degree_qualifier": "unmodified",
        "value_qualifier": "exact",
        "frequency_qualifier": "unspecified",
    }
    for match in _CUE_TOKEN.finditer(cue):
        token = match.group(0).lower()
        if token in DEGREE_CUES:
            result["degree_qualifier"] = DEGREE_CUES[token]
        elif token in APPROXIMATION_CUES:
            result["value_qualifier"] = APPROXIMATION_CUES[token]
    for word in re.findall(r"[^\W\d_]+", cue.lower()):
        if word in FREQUENCY_ALIASES:
            result["frequency_qualifier"] = FREQUENCY_ALIASES[word]
    return result


def make_operand(
    index: int,
    value: str,
    segment: str,
    start: int,
    end: int,
    *,
    qualifier_start: int | None = None,
    qualifier_end: int | None = None,
    degree_qualifier: str = "unmodified",
    value_qualifier: str = "exact",
    frequency_qualifier: str = "unspecified",
) -> dict[str, Any]:
    """Build one wire-format operand; offsets are validated by :func:`validate_value_operands`."""

    operand: dict[str, Any] = {
        "operand_index": index,
        "value": str(value).replace(":", "_"),
        "text": segment[start:end],
        "start": start,
        "end": end,
        "degree_qualifier": degree_qualifier,
        "value_qualifier": value_qualifier,
        "frequency_qualifier": frequency_qualifier,
    }
    if qualifier_start is not None and qualifier_end is not None and qualifier_end > qualifier_start:
        operand["qualifier_text"] = segment[qualifier_start:qualifier_end]
        operand["qualifier_start"] = qualifier_start
        operand["qualifier_end"] = qualifier_end
    return operand


def operand_is_qualified(operand: dict[str, Any]) -> bool:
    return (
        (operand.get("degree_qualifier") or "unmodified") != "unmodified"
        or (operand.get("value_qualifier") or "exact") != "exact"
        or (operand.get("frequency_qualifier") or "unspecified") not in {"unspecified", "universal"}
    )


def operand_is_entailing(operand: dict[str, Any]) -> bool:
    """Whether the operand's head value is entailed by the operand (FAC-safe)."""

    return (operand.get("value_qualifier") or "exact") not in NON_ENTAILING_VALUE_QUALIFIERS and (
        operand.get("degree_qualifier") or "unmodified"
    ) not in NON_ENTAILING_DEGREES


def operands_fac_representable(assertion: dict[str, Any]) -> bool:
    return all(
        operand_is_entailing(operand)
        for operand in assertion.get("value_operands", []) or []
        if isinstance(operand, dict)
    )


def operands_make_qualified(assertion: dict[str, Any]) -> bool:
    """Operand-level frequency or approximation makes an assertion non-strict.

    Entailing degree operands keep strict eligibility (``sparsely pubescent`` is pubescent).
    """

    for operand in assertion.get("value_operands", []) or []:
        if not isinstance(operand, dict):
            continue
        if (operand.get("value_qualifier") or "exact") != "exact":
            return True
        if (operand.get("frequency_qualifier") or "unspecified") not in {"unspecified", "universal"}:
            return True
    return False


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_operand(
    operand: Any, segment: str, label: str
) -> tuple[list[OperandIssue], tuple[int, int] | None]:
    issues: list[OperandIssue] = []
    if not isinstance(operand, dict):
        return [OperandIssue("value_operand_not_object", label)], None
    value = str(operand.get("value", "") or "")
    if not VALUE_ID.fullmatch(value):
        issues.append(OperandIssue("invalid_value_operand_value", f"{label}: {value!r}"))
    text = operand.get("text")
    start, end = operand.get("start"), operand.get("end")
    span: tuple[int, int] | None = None
    if not isinstance(text, str) or not text or not _int(start) or not _int(end):
        issues.append(OperandIssue("value_operand_not_verbatim", f"{label}: missing text/offsets"))
    elif not (0 <= start < end <= len(segment)) or segment[start:end] != text:
        issues.append(OperandIssue("value_operand_not_verbatim", f"{label}: {text!r}"))
    else:
        span = (start, end)
    degree = operand.get("degree_qualifier") or "unmodified"
    value_qualifier = operand.get("value_qualifier") or "exact"
    frequency = operand.get("frequency_qualifier") or "unspecified"
    if degree not in DEGREE_VALUES:
        issues.append(OperandIssue("invalid_operand_degree_qualifier", f"{label}: {degree!r}"))
    if value_qualifier not in VALUE_QUALIFIER_VALUES:
        issues.append(
            OperandIssue("invalid_operand_value_qualifier", f"{label}: {value_qualifier!r}")
        )
    if frequency not in FREQUENCY_VALUES:
        issues.append(
            OperandIssue("invalid_operand_frequency_qualifier", f"{label}: {frequency!r}")
        )
    cue = operand.get("qualifier_text")
    cue_start, cue_end = operand.get("qualifier_start"), operand.get("qualifier_end")
    if operand_is_qualified(operand) and not cue:
        issues.append(
            OperandIssue(
                "operand_qualifier_missing_cue",
                f"{label}: a non-default operand qualifier must retain its exact cue",
            )
        )
    if cue or cue_start is not None or cue_end is not None:
        if (
            not isinstance(cue, str)
            or not cue
            or not _int(cue_start)
            or not _int(cue_end)
            or not (0 <= cue_start < cue_end <= len(segment))
            or segment[cue_start:cue_end] != cue
        ):
            issues.append(OperandIssue("operand_qualifier_not_verbatim", f"{label}: {cue!r}"))
        elif span is not None and not (span[0] <= cue_start and cue_end <= span[1]):
            issues.append(OperandIssue("operand_qualifier_outside_operand", f"{label}: {cue!r}"))
    return issues, span


def _conflicts(assertion: dict[str, Any], operand: dict[str, Any], label: str) -> list[OperandIssue]:
    """Same qualifier axis set at assertion and operand level with different values."""

    issues: list[OperandIssue] = []
    top_degree = assertion.get("degree_qualifier") or "unmodified"
    op_degree = operand.get("degree_qualifier") or "unmodified"
    if (
        top_degree != "unmodified"
        and op_degree != "unmodified"
        and degree_axis(top_degree) == degree_axis(op_degree)
        and top_degree != op_degree
    ):
        issues.append(
            OperandIssue(
                "assertion_and_operand_qualifier_conflict",
                f"{label}: degree {top_degree!r} vs {op_degree!r}",
            )
        )
    for key, default in (("value_qualifier", "exact"), ("frequency_qualifier", "unspecified")):
        top = assertion.get(key) or default
        own = operand.get(key) or default
        if top != default and own != default and top != own:
            issues.append(
                OperandIssue(
                    "assertion_and_operand_qualifier_conflict",
                    f"{label}: {key} {top!r} vs {own!r}",
                )
            )
    return issues


def value_operand_spans(assertion: dict[str, Any]) -> list[tuple[str, int | None, int | None]]:
    """Every operand and qualifier evidence span (text, start, end) for coverage checks."""

    spans: list[tuple[str, int | None, int | None]] = []
    operands = list(assertion.get("value_operands", []) or [])
    relation = assertion.get("qualitative_value_relation") or {}
    if isinstance(relation, dict):
        operands.extend(
            relation[key] for key in ("from_operand", "to_operand") if relation.get(key)
        )
    for operand in operands:
        if not isinstance(operand, dict):
            continue
        spans.append((str(operand.get("text") or ""), operand.get("start"), operand.get("end")))
        if operand.get("qualifier_text"):
            spans.append(
                (
                    str(operand.get("qualifier_text") or ""),
                    operand.get("qualifier_start"),
                    operand.get("qualifier_end"),
                )
            )
    return spans


def validate_value_operands(
    assertion: dict[str, Any],
    segment: str,
    *,
    pato_catalog_ids: set[str] | None = None,
    flopo_catalog_ids: set[str] | None = None,
) -> tuple[OperandIssue, ...]:
    """Validate ``value_operands`` and qualitative-relation endpoint operands."""

    issues: list[OperandIssue] = []
    operands = assertion.get("value_operands", []) or []
    if operands and not isinstance(operands, list):
        return (OperandIssue("value_operands_not_list", repr(type(operands))),)

    def catalog(value: str, label: str) -> None:
        normalized = value.replace(":", "_")
        if normalized.startswith("PATO_") and pato_catalog_ids and normalized not in pato_catalog_ids:
            issues.append(OperandIssue("unknown_value_operand_pato_id", f"{label}: {value}"))
        elif (
            normalized.startswith("FLOPO_")
            and flopo_catalog_ids
            and normalized not in flopo_catalog_ids
        ):
            issues.append(OperandIssue("unknown_value_operand_flopo_id", f"{label}: {value}"))

    spans: list[tuple[int, int]] = []
    for position, operand in enumerate(operands):
        label = f"operand {position}"
        own, span = _validate_operand(operand, segment, label)
        issues.extend(own)
        if not isinstance(operand, dict):
            continue
        if operand.get("operand_index") != position:
            issues.append(
                OperandIssue(
                    "value_operand_index_mismatch",
                    f"{label}: operand_index={operand.get('operand_index')!r}",
                )
            )
        catalog(str(operand.get("value", "") or ""), label)
        issues.extend(_conflicts(assertion, operand, label))
        if span is not None:
            spans.append(span)

    if operands:
        if len(spans) == len(operands) and any(
            left[1] > right[0] for left, right in zip(spans, spans[1:])
        ):
            issues.append(
                OperandIssue(
                    "value_operand_source_order",
                    "operands must be in increasing, non-overlapping source order",
                )
            )
        source_start = assertion.get("source_start")
        source_end = assertion.get("source_end")
        if _int(source_start) and _int(source_end) and any(
            not (source_start <= start and end <= source_end) for start, end in spans
        ):
            issues.append(
                OperandIssue(
                    "value_operand_outside_assertion_span",
                    "operand evidence is not wholly contained in source_start/source_end",
                )
            )
        if assertion.get("qualitative_value_relation"):
            issues.append(
                OperandIssue(
                    "value_operands_with_qualitative_relation",
                    "a qualitative relation carries endpoint operands, not value_operands",
                )
            )
        operator = str(assertion.get("value_operator", "atomic") or "atomic")
        terms = [
            str(term).replace(":", "_")
            for term in (assertion.get("value_terms", []) or assertion.get("value_term_ids", []) or [])
        ]
        expected = set(terms) or {str(assertion.get("pato_id", "") or "").replace(":", "_")}
        values = {
            str(operand.get("value", "") or "").replace(":", "_")
            for operand in operands
            if isinstance(operand, dict)
        }
        if values != expected:
            issues.append(
                OperandIssue(
                    "value_operands_terms_mismatch",
                    f"operand values {sorted(values)} != value terms {sorted(expected)}",
                )
            )
        if operator == "atomic" and len(operands) != 1:
            issues.append(
                OperandIssue("atomic_value_has_multiple_operands", f"{len(operands)} operands")
            )
        if not operands_fac_representable(assertion) and assertion.get("phenotype_class_iri"):
            issues.append(
                OperandIssue(
                    "non_entailing_operand_in_fac",
                    "an approximated operand is not entailed by its head value; no FAC IRI",
                )
            )

    relation = assertion.get("qualitative_value_relation")
    if isinstance(relation, dict):
        for side in ("from", "to"):
            operand = relation.get(f"{side}_operand")
            if not operand:
                continue
            label = f"{side}_operand"
            own, _span = _validate_operand(operand, segment, label)
            issues.extend(own)
            if not isinstance(operand, dict):
                continue
            catalog(str(operand.get("value", "") or ""), label)
            if str(operand.get("value", "") or "").replace(":", "_") != str(
                relation.get(f"{side}_value", "") or ""
            ).replace(":", "_"):
                issues.append(
                    OperandIssue(
                        "qualitative_endpoint_operand_mismatch",
                        f"{label}: value differs from {side}_value",
                    )
                )
            if (
                operand.get("text") != relation.get(f"{side}_text")
                or operand.get("start") != relation.get(f"{side}_start")
                or operand.get("end") != relation.get(f"{side}_end")
            ):
                issues.append(
                    OperandIssue(
                        "qualitative_endpoint_operand_mismatch",
                        f"{label}: text/offsets differ from {side}_text/{side}_start/{side}_end",
                    )
                )
            expected_index = 0 if side == "from" else 1
            if operand.get("operand_index") != expected_index:
                issues.append(
                    OperandIssue(
                        "value_operand_index_mismatch",
                        f"{label}: operand_index must be {expected_index}",
                    )
                )
            issues.extend(_conflicts(assertion, operand, label))
    return tuple(issues)
