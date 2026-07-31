"""Negated-context recovery: materialize reviewed universal phenotype negation and upper bounds.

This is a precision-first recovery pass for the ``negated_context`` residual spans that the baseline
extractor parked because a negation cue governs the candidate quality, or a negated comparator
governs a measurement.  It supersedes two earlier attempts whose emitted evidence dropped the cue
(``source_text="ramifiées"`` for *non ramifiées*), used ``record.organ`` + candidate offsets as the
bearer provenance, located modality with a global search, prefilled composition, and mis-scoped
compound / coordinated / bearer-absence negation as atomic quality negation.

Every promotion is driven by an **audited row ledger** (``final_semantic_corrections.tsv``) that an
independent exhaustive semantic + provenance audit produced and this module re-verifies byte-for-byte
against the pinned record text.  For each promoted row the ledger supplies the reviewed bearer PO id,
the exact bearer surface and offsets (or an explicit record-organ-field basis when the bearer is only
the segment heading), the exact negation / comparator cue offsets, the exact modality cue and offsets,
any bearer-context quality and developmental-stage context with exact offsets, bound inclusivity, and
the exact complete supporting source statement span.  Nothing is heuristically re-derived; a row whose
offsets do not select their verbatim text is *held*, never guessed.

Assertion semantics (open-world, universal taxon reading), matching :mod:`flopo2.owl.assertions`:

* ``quality`` negation -> ``has_part some (B and ObjectComplementOf(has_quality some Q))`` (bearer
  present, lacks the quality); ``negated=True``, ``negation_scope="quality"``.
* ``numeric`` upper bound -> ``value_low=None``, ``value_high=N``; a strict *atteindre* form renders
  ``xsd:maxExclusive`` (``value_high_inclusive=False``), an *exceed* / *no more than* / *pas plus de*
  form renders ``xsd:maxInclusive``; ``negated=False`` (an upper bound is never a complement).

Compound/coating scope (``not white waxy``), coordinated/hedged scope, meaning-inverting frequency,
exception, taxon comparison, bearer-absence, relational lower-part bearers, and OCR-ambiguous scope
are held as residual with a precise reason rather than flattened.  Minted assertions carry **no**
composition/gate/FAC block: those are recomputed by the real downstream pipeline.  The source
statement is left for :mod:`flopo2.annotation.provenance` to retain from the exact ``source_text``
span this module writes.  False promotion is worse than a documented residual.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from flopo2.annotation.provenance import stable_statement_id

NEG_REASON = "negated_context"

EXTRACTOR = "deterministic_negated_context_recovery"


def _int_or_none(value: str) -> int | None:
    value = (value or "").strip()
    if value == "":
        return None
    return int(value)


def _float_or_none(value: str) -> float | None:
    value = (value or "").strip()
    if value == "":
        return None
    return float(value)


def _bool_or_none(value: str) -> bool | None:
    value = (value or "").strip().lower()
    if value == "":
        return None
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    raise ValueError(f"unparseable boolean in ledger: {value!r}")


@dataclass(frozen=True)
class LedgerRow:
    source: str
    source_id: str
    source_segment_index: int
    span_start: int
    span_end: int
    span_surface: str
    assertion_index: int
    kind: str  # "quality" | "numeric"
    promote: bool
    po_id: str
    pato_id: str
    negated: bool
    value_high: float | None
    value_high_inclusive: bool | None
    unit: str
    cue_text: str
    cue_start: int | None
    cue_end: int | None
    frequency_qualifier: str
    epistemic_modality: str
    modality_text: str
    modality_start: int | None
    modality_end: int | None
    bearer_context_ids: tuple[str, ...]
    bearer_context_text: str
    bearer_context_start: int | None
    bearer_context_end: int | None
    stage_term: str
    stage_text: str
    stage_start: int | None
    stage_end: int | None
    bearer_surface: str
    bearer_start: int | None
    bearer_end: int | None
    bearer_basis: str
    raw_quality_text: str
    evidence_text: str
    evidence_start: int | None
    evidence_end: int | None
    statement_text: str
    statement_start: int | None
    statement_end: int | None
    hold_reason: str
    residual_reason: str
    pending_bearer: str
    retain_partial_residual: bool
    notes: str
    origin: str = "ledger"

    @property
    def span_key(self) -> tuple[str, str, int, int, int]:
        return (
            self.source,
            self.source_id,
            self.source_segment_index,
            self.span_start,
            self.span_end,
        )


def load_ledger(path: Path) -> dict[tuple[str, str, int, int, int], list[LedgerRow]]:
    """Group the reviewed ledger rows by their span identity."""

    grouped: dict[tuple[str, str, int, int, int], list[LedgerRow]] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle, delimiter="\t"):
            row = LedgerRow(
                source=raw["source"],
                source_id=raw["source_id"],
                source_segment_index=int(raw["source_segment_index"]),
                span_start=int(raw["span_start"]),
                span_end=int(raw["span_end"]),
                span_surface=raw.get("span_surface", ""),
                assertion_index=int(raw.get("assertion_index_within_span", "0") or 0),
                kind=raw["kind"],
                promote=(raw["recommended_promote"].strip().lower() == "true"),
                po_id=raw["recommended_po_id"].strip(),
                pato_id=raw["pato_id"].strip(),
                negated=(raw["negated"].strip().lower() == "true"),
                value_high=_float_or_none(raw.get("value_high", "")),
                value_high_inclusive=_bool_or_none(raw.get("value_high_inclusive", "")),
                unit=raw.get("unit", "").strip(),
                cue_text=raw.get("logical_cue_text", ""),
                cue_start=_int_or_none(raw.get("logical_cue_start", "")),
                cue_end=_int_or_none(raw.get("logical_cue_end", "")),
                frequency_qualifier=(raw.get("recommended_frequency_qualifier", "").strip() or "unspecified"),
                epistemic_modality=(raw.get("recommended_epistemic_modality", "").strip() or "asserted"),
                modality_text=raw.get("recommended_modality_text", ""),
                modality_start=_int_or_none(raw.get("modality_start", "")),
                modality_end=_int_or_none(raw.get("modality_end", "")),
                bearer_context_ids=tuple(
                    v for v in raw.get("bearer_context_quality_ids", "").split("|") if v.strip()
                ),
                bearer_context_text=raw.get("bearer_context_text", ""),
                bearer_context_start=_int_or_none(raw.get("bearer_context_start", "")),
                bearer_context_end=_int_or_none(raw.get("bearer_context_end", "")),
                stage_term=raw.get("developmental_stage_term", "").strip(),
                stage_text=raw.get("developmental_stage_text", ""),
                stage_start=_int_or_none(raw.get("developmental_stage_start", "")),
                stage_end=_int_or_none(raw.get("developmental_stage_end", "")),
                bearer_surface=raw.get("bearer_surface", ""),
                bearer_start=_int_or_none(raw.get("bearer_start", "")),
                bearer_end=_int_or_none(raw.get("bearer_end", "")),
                bearer_basis=raw.get("bearer_evidence_basis", "").strip(),
                raw_quality_text=(
                    raw.get("current_raw_quality_text", "") or raw.get("span_surface", "")
                ),
                evidence_text=raw.get("assertion_evidence_text", ""),
                evidence_start=_int_or_none(raw.get("assertion_evidence_start", "")),
                evidence_end=_int_or_none(raw.get("assertion_evidence_end", "")),
                statement_text=raw.get("source_statement_text", ""),
                statement_start=_int_or_none(raw.get("source_statement_start", "")),
                statement_end=_int_or_none(raw.get("source_statement_end", "")),
                hold_reason=raw.get("hold_reason", "").strip(),
                residual_reason=(
                    "negation_scope_held_for_curation"
                    if raw.get("recommended_promote", "").strip().lower() != "true"
                    else ""
                ),
                pending_bearer="",
                retain_partial_residual=False,
                notes=raw.get("notes", "").strip(),
                origin="ledger",
            )
            grouped.setdefault(row.span_key, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: r.assertion_index)
    return grouped


_TRANCHE_PROMOTE = {"promote_standard_po_next", "split_promote_standard_po_and_hold_local_bearer"}


_COORDINATOR_RE = re.compile(r"\s+(?:and|et|or|ou|&)\s+", re.IGNORECASE)


def _coordinated_bearers(
    surface: str,
    start: int | None,
    po_ids: list[str],
) -> list[tuple[str, int | None, int | None, str]]:
    """Pair reviewed coordinated bearer components with their PO identifiers.

    The tranche ledger deliberately records ``lobes and pinnae`` once while listing the two
    reviewed PO identifiers in source order.  Each phenotype assertion nevertheless needs its own
    exact bearer occurrence.  A multi-ID row is therefore accepted only when the verbatim bearer
    surface splits into the same number of coordinated components; ambiguity is a ledger error, not
    an invitation to copy the whole phrase onto both assertions.
    """

    if len(po_ids) == 1:
        end = None if start is None else start + len(surface)
        return [(surface, start, end, po_ids[0])]

    pieces: list[tuple[str, int | None, int | None, str]] = []
    cursor = 0
    for match in _COORDINATOR_RE.finditer(surface):
        left, right = cursor, match.start()
        while left < right and surface[left].isspace():
            left += 1
        while right > left and surface[right - 1].isspace():
            right -= 1
        if left < right:
            pieces.append(
                (
                    surface[left:right],
                    None if start is None else start + left,
                    None if start is None else start + right,
                    "",
                )
            )
        cursor = match.end()
    left, right = cursor, len(surface)
    while left < right and surface[left].isspace():
        left += 1
    while right > left and surface[right - 1].isspace():
        right -= 1
    if left < right:
        pieces.append(
            (
                surface[left:right],
                None if start is None else start + left,
                None if start is None else start + right,
                "",
            )
        )

    if len(pieces) != len(po_ids):
        raise ValueError(
            "coordinated tranche bearer/PO mismatch: "
            f"surface={surface!r}, components={len(pieces)}, po_ids={po_ids!r}"
        )
    return [(piece, begin, end, po_id) for (piece, begin, end, _), po_id in zip(pieces, po_ids)]


def load_tranche(path: Path) -> dict[tuple[str, str, int, int, int], list[LedgerRow]]:
    """Load the numeric second tranche as LedgerRow objects (numeric upper bounds).

    Rows with a standard reviewed PO bearer are promoted; rows whose only bearer needs a
    FLOPO-local class are held with a precise ``required_residual_reason``. The single
    coordinated split promotes its standard-PO part and records the held local sub-part.
    """

    grouped: dict[tuple[str, str, int, int, int], list[LedgerRow]] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle, delimiter="\t"):
            disposition = raw.get("disposition", "").strip()
            promote = disposition in _TRANCHE_PROMOTE
            po_ids = [
                value.strip()
                for value in raw.get("standard_po_bearer_ids", "").split("|")
                if value.strip()
            ]
            required_reason = raw.get("required_residual_reason", "").strip()
            bearer_surface = raw.get("bearer_surface", "")
            bearer_start = _int_or_none(raw.get("bearer_start", ""))
            components = (
                _coordinated_bearers(bearer_surface, bearer_start, po_ids)
                if po_ids
                else [(bearer_surface, bearer_start, _int_or_none(raw.get("bearer_end", "")), "")]
            )
            for assertion_index, (component, component_start, component_end, po_id) in enumerate(
                components
            ):
                row = LedgerRow(
                    source=raw["source"],
                    source_id=raw["source_id"],
                    source_segment_index=int(raw["source_segment_index"]),
                    span_start=int(raw["span_start"]),
                    span_end=int(raw["span_end"]),
                    span_surface=raw.get("span_surface", ""),
                    assertion_index=assertion_index,
                    kind="numeric",
                    promote=promote and bool(po_id),
                    po_id=po_id,
                    pato_id=raw["pato_id"].strip(),
                    negated=False,
                    value_high=_float_or_none(raw.get("value_high", "")),
                    value_high_inclusive=_bool_or_none(
                        raw.get("value_high_inclusive", "")
                    ),
                    unit=raw.get("unit", "").strip(),
                    cue_text=raw.get("comparator_cue", ""),
                    cue_start=_int_or_none(raw.get("cue_start", "")),
                    cue_end=_int_or_none(raw.get("cue_end", "")),
                    frequency_qualifier="unspecified",
                    epistemic_modality="asserted",
                    modality_text="",
                    modality_start=None,
                    modality_end=None,
                    bearer_context_ids=(),
                    bearer_context_text="",
                    bearer_context_start=None,
                    bearer_context_end=None,
                    stage_term="",
                    stage_text="",
                    stage_start=None,
                    stage_end=None,
                    bearer_surface=component,
                    bearer_start=component_start,
                    bearer_end=component_end,
                    bearer_basis="verbatim_local_bearer",
                    raw_quality_text=raw.get("span_surface", ""),
                    evidence_text=raw.get("assertion_evidence_text", ""),
                    evidence_start=_int_or_none(raw.get("assertion_evidence_start", "")),
                    evidence_end=_int_or_none(raw.get("assertion_evidence_end", "")),
                    statement_text=raw.get("source_statement_text", ""),
                    statement_start=_int_or_none(raw.get("source_statement_start", "")),
                    statement_end=_int_or_none(raw.get("source_statement_end", "")),
                    hold_reason=("" if promote and po_id else required_reason),
                    residual_reason=required_reason,
                    pending_bearer=raw.get("flopo_local_bearer_needed", "").strip(),
                    retain_partial_residual=(
                        disposition == "split_promote_standard_po_and_hold_local_bearer"
                        and assertion_index == 0
                    ),
                    notes=raw.get("notes", "").strip(),
                    origin="numeric_tranche",
                )
                grouped.setdefault(row.span_key, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: r.assertion_index)
    return grouped


def merge_ledgers(
    primary: dict[tuple[str, str, int, int, int], list[LedgerRow]],
    secondary: dict[tuple[str, str, int, int, int], list[LedgerRow]],
) -> tuple[dict[tuple[str, str, int, int, int], list[LedgerRow]], int]:
    """Merge ``secondary`` rows into ``primary``; the primary ledger wins any span-key overlap."""

    merged = {k: list(v) for k, v in primary.items()}
    overlaps = 0
    for key, rows in secondary.items():
        if key in merged:
            overlaps += 1
            continue
        merged[key] = list(rows)
    return merged, overlaps


class LedgerOffsetError(ValueError):
    """A ledger row whose offsets do not select their verbatim text against the record."""


def _require(text: str, start: int | None, end: int | None, expected: str, what: str) -> None:
    if start is None or end is None:
        raise LedgerOffsetError(f"{what}: missing offsets")
    if not (0 <= start <= end <= len(text)) or text[start:end] != expected:
        raise LedgerOffsetError(
            f"{what}: text[{start}:{end}]={text[start:end]!r} != {expected!r}"
        )


def materialize_assertion(record: dict, row: LedgerRow) -> dict:
    """Build one fully provenance-exact assertion dict from a promoted ledger row.

    Raises :class:`LedgerOffsetError` when any reviewed offset fails to select its verbatim text,
    so a corrupt row is held rather than emitted with fabricated provenance.
    """

    text = record.get("text", "")
    # Re-verify every reviewed offset against the pinned record text.
    _require(text, row.statement_start, row.statement_end, row.statement_text, "source_statement")
    _require(text, row.evidence_start, row.evidence_end, row.evidence_text, "assertion_evidence")
    _require(text, row.cue_start, row.cue_end, row.cue_text, "logical_cue")
    if row.bearer_basis == "verbatim_local_bearer":
        _require(text, row.bearer_start, row.bearer_end, row.bearer_surface, "bearer")
    if row.modality_text:
        _require(text, row.modality_start, row.modality_end, row.modality_text, "modality")
    if row.stage_term:
        _require(text, row.stage_start, row.stage_end, row.stage_text, "developmental_stage")
    if row.bearer_context_ids:
        _require(
            text, row.bearer_context_start, row.bearer_context_end, row.bearer_context_text,
            "bearer_context",
        )
    # The reviewed cue and the tight assertion evidence must sit inside the retained statement
    # interval; the tight evidence (not the whole statement) becomes the assertion source_text so an
    # unrelated sibling disjunction in the statement cannot trip the atomic-disjunction gate.
    if not (row.statement_start <= row.cue_start and row.cue_end <= row.statement_end):
        raise LedgerOffsetError("logical_cue outside source_statement interval")
    if not (row.statement_start <= row.evidence_start and row.evidence_end <= row.statement_end):
        raise LedgerOffsetError("assertion_evidence outside source_statement interval")
    if not (row.evidence_start <= row.cue_start and row.cue_end <= row.evidence_end):
        raise LedgerOffsetError("logical_cue outside assertion_evidence interval")

    assertion: dict = {
        "po_id": row.po_id,
        "pato_id": row.pato_id,
        "negated": bool(row.negated),
        "organ": record.get("organ", ""),
        "source_text": row.evidence_text,
        "source_start": row.evidence_start,
        "source_end": row.evidence_end,
        "value_text": "",
        "trait": "",
        "modifier": "",
        "cardinality": "",
        "confidence": None,
        "raw_entity_text": row.bearer_surface,
        "raw_quality_text": row.raw_quality_text,
        "entity_mention_id": "",
        "quality_mention_ids": [],
        "value_operator": "atomic",
        "value_terms": [],
        "bearer_context_qualities": list(row.bearer_context_ids),
        "normalization_status": "reviewed",
        "mapping_provenance": [
            f"negated_context_recovery:{row.kind}:{row.cue_text}",
            f"bearer_basis:{row.bearer_basis}",
            f"reviewed_bearer:{row.po_id}",
        ],
        "extractor": EXTRACTOR,
        "frequency_qualifier": row.frequency_qualifier,
        "epistemic_modality": row.epistemic_modality,
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": row.modality_text,
        "season_contexts": [],
        "season_operator": "atomic",
        "developmental_stage_operator": "atomic",
    }

    # Exact provenance offsets consumed by the interval-aware provenance/validation layer.
    if row.bearer_basis == "verbatim_local_bearer":
        assertion["bearer_start"] = row.bearer_start
        assertion["bearer_end"] = row.bearer_end
    if row.modality_text:
        assertion["modality_start"] = row.modality_start
        assertion["modality_end"] = row.modality_end

    if row.negated:
        assertion["negation_scope"] = "quality"

    if row.kind == "numeric":
        assertion["value_low"] = None
        assertion["value_high"] = row.value_high
        assertion["unit"] = row.unit
        assertion["value_low_inclusive"] = True
        assertion["value_high_inclusive"] = (
            True if row.value_high_inclusive is None else bool(row.value_high_inclusive)
        )
    else:
        assertion["value_low"] = None
        assertion["value_high"] = None
        assertion["unit"] = ""

    if row.stage_term:
        assertion["developmental_stage_contexts"] = [
            {
                "stage_term": row.stage_term,
                "stage_text": row.stage_text,
                "start": row.stage_start,
                "end": row.stage_end,
                "temporal_relation": "present_during",
            }
        ]
    else:
        assertion["developmental_stage_contexts"] = []

    return assertion


def _build_statement(record: dict, row: LedgerRow) -> dict:
    """Return the retained ``SourceStatement`` for a promoted row's complete supporting statement.

    The assertion ``source_text`` is the tight evidence; the complete audited semicolon/sentence
    statement is retained here as first-class provenance and linked by ``source_statement_id`` so
    the interval-aware validator can confirm every evidence interval sits inside it.
    """

    text = record.get("text", "")
    start, end = int(row.statement_start), int(row.statement_end)
    verbatim = text[start:end]
    statement = {
        "statement_id": stable_statement_id(record, start, end, verbatim),
        "verbatim_text": verbatim,
        "start": start,
        "end": end,
        "language": str(record.get("language", "") or ""),
    }
    char_start = record.get("char_start")
    if isinstance(char_start, int) and not isinstance(char_start, bool):
        statement["document_start"] = char_start + start
        statement["document_end"] = char_start + end
    return statement


def _assertion_identity(assertion: dict) -> tuple:
    return (
        assertion.get("po_id", ""),
        assertion.get("pato_id", ""),
        assertion.get("negated", False),
        assertion.get("value_high"),
        assertion.get("value_high_inclusive", True),
        assertion.get("source_start"),
        assertion.get("source_end"),
    )


AUDIT_FIELDS = (
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "record_organ",
    "language",
    "span_start",
    "span_end",
    "span_surface",
    "kind",
    "disposition",
    "po_id",
    "pato_id",
    "negated",
    "value_high",
    "value_high_inclusive",
    "cue_text",
    "bearer_surface",
    "bearer_basis",
    "frequency_qualifier",
    "modality_text",
    "stage_term",
    "assertion_evidence",
    "source_statement",
    "origin",
    "pending_bearer",
    "reason",
)


def recover_negation_record(
    record: dict,
    ledger: dict[tuple[str, str, int, int, int], list[LedgerRow]],
) -> tuple[dict, list[dict], list[dict]]:
    """Return (out_record, audit_rows, proposal_rows).

    Non-destructive: copies the record, appends minted assertions, removes each recovered span
    exactly once, and preserves every other field and unrelated span byte-for-byte.
    """

    out = dict(record)
    assertions = [dict(a) for a in record.get("assertions", []) or []]
    statements = [dict(s) for s in record.get("source_statements", []) or []]
    statement_ids = {s.get("statement_id") for s in statements}
    seen = {_assertion_identity(a) for a in assertions}
    retained: list[dict] = []
    audit: list[dict] = []
    proposals: list[dict] = []
    source = record.get("source", "")
    source_id = record.get("source_id", "")
    seg = int(record.get("source_segment_index", 0) or 0)

    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") != NEG_REASON:
            retained.append(span)
            continue
        key = (source, source_id, seg, int(span["start"]), int(span["end"]))
        rows = ledger.get(key)
        if not rows:
            # Span not in the reviewed promotable set: keep it byte-for-byte and record the precise
            # disposition in the audit rather than mutating an unreviewed residual.
            retained.append(span)
            audit.append(_audit_row(record, span, rows=None, disposition="residual_not_in_reviewed_ledger"))
            continue

        promote_rows = [r for r in rows if r.promote]
        if not promote_rows:
            reason = rows[0].hold_reason or rows[0].residual_reason or "held_by_ledger"
            retained.append(_span_with_residual(span, rows[0].residual_reason or "negation_scope_held_for_curation", reason))
            audit.append(_audit_row(record, span, rows=rows, disposition="held", reason=reason))
            continue

        minted: list[tuple[LedgerRow, dict]] = []
        held_reason = ""
        for row in promote_rows:
            try:
                assertion = materialize_assertion(record, row)
            except LedgerOffsetError as exc:
                held_reason = f"ledger_offset_mismatch:{exc}"
                minted = []
                break
            identity = _assertion_identity(assertion)
            if identity in seen:
                continue
            seen.add(identity)
            minted.append((row, assertion))

        if not minted:
            retained.append(
                _span_with_residual(span, "negation_offset_defect", held_reason or "no_new_assertion")
            )
            audit.append(
                _audit_row(
                    record, span, rows=promote_rows, disposition="held_offset_defect",
                    reason=held_reason or "no_new_assertion",
                )
            )
            continue

        for row, assertion in minted:
            statement = _build_statement(record, row)
            if statement["statement_id"] not in statement_ids:
                statements.append(statement)
                statement_ids.add(statement["statement_id"])
            assertion["source_statement_id"] = statement["statement_id"]
            assertions.append(assertion)
            proposals.append(
                {
                    "source": source,
                    "source_id": source_id,
                    "source_segment_index": seg,
                    "taxon": record.get("taxon", ""),
                    "span_start": int(span["start"]),
                    "span_end": int(span["end"]),
                    "span_surface": span.get("surface_form", ""),
                    "candidate_quality_start": int(span["start"]),
                    "candidate_quality_end": int(span["end"]),
                    "kind": row.kind,
                    "origin": row.origin,
                    "assertion_evidence_text": row.evidence_text,
                    "assertion_evidence_start": row.evidence_start,
                    "assertion_evidence_end": row.evidence_end,
                    "source_statement_id": statement["statement_id"],
                    "source_statement_text": row.statement_text,
                    "candidate_quality_text": row.raw_quality_text,
                    "assertion": assertion,
                }
            )
            audit.append(_audit_row(record, span, rows=[row], disposition="recovered"))

        partial_row = next((row for row in rows if row.retain_partial_residual), None)
        if partial_row is not None:
            # The source measurement governs two bearers, but only the standard-PO half can be
            # materialized today.  Replace the consumed negated-context candidate with an explicit
            # missing-bearer residual for the local FLOPO extension half.  This prevents both
            # double-counting the original span and silently losing the rachis-wing phenotype.
            retained.append(_partial_bearer_residual(span, partial_row, promote_rows))
            audit.append(
                _audit_row(
                    record,
                    span,
                    rows=[partial_row],
                    disposition="retained_partial_bearer",
                    reason=partial_row.residual_reason,
                )
            )

    out["assertions"] = assertions
    out["source_statements"] = statements
    out["unresolved_spans"] = retained
    out.pop("annotation_extension_iri", None)
    return out, audit, proposals


def _slice(record: dict, start: int | None, end: int | None) -> str:
    if start is None or end is None:
        return ""
    return record.get("text", "")[start:end]


def _span_with_residual(span: dict, reason_code: str, detail: str) -> dict:
    """Return a copy of a held span annotated with a precise residual reason.

    The original ``reason`` (``negated_context``) and every other field are preserved verbatim; the
    additive ``negation_residual_reason`` records why the reviewed span was not promoted so no
    retained numeric or categorical row is silently left at the generic cue reason.
    """

    out = dict(span)
    out["negation_residual_reason"] = reason_code
    if detail and detail != reason_code:
        out["negation_residual_detail"] = detail
    return out


def _partial_bearer_residual(
    span: dict,
    row: LedgerRow,
    promoted_rows: list[LedgerRow],
) -> dict:
    """Represent the unmaterialized half of a reviewed coordinated-bearer assertion."""

    out = dict(span)
    out["original_reason"] = out.get("reason", NEG_REASON)
    out["reason"] = "missing_or_unsupported_bearer"
    out["negation_residual_reason"] = row.residual_reason
    out["partial_promotion"] = True
    out["pending_bearer"] = row.pending_bearer
    out["promoted_po_ids"] = sorted({item.po_id for item in promoted_rows if item.po_id})
    return out


def _audit_row(record, span, *, rows, disposition, reason="") -> dict:
    row = rows[0] if rows else None
    return {
        "source": record.get("source", ""),
        "source_id": record.get("source_id", ""),
        "source_segment_index": record.get("source_segment_index", 0),
        "taxon": record.get("taxon", ""),
        "record_organ": record.get("organ", ""),
        "language": record.get("language", ""),
        "span_start": int(span["start"]),
        "span_end": int(span["end"]),
        "span_surface": span.get("surface_form", ""),
        "kind": row.kind if row else "",
        "disposition": disposition,
        "po_id": row.po_id if row else "",
        "pato_id": row.pato_id if row else "",
        "negated": row.negated if row else "",
        "value_high": row.value_high if row else "",
        "value_high_inclusive": row.value_high_inclusive if row else "",
        "cue_text": row.cue_text if row else "",
        "bearer_surface": row.bearer_surface if row else "",
        "bearer_basis": row.bearer_basis if row else "",
        "frequency_qualifier": row.frequency_qualifier if row else "",
        "modality_text": row.modality_text if row else "",
        "stage_term": row.stage_term if row else "",
        "assertion_evidence": row.evidence_text if row else "",
        "source_statement": row.statement_text if row else "",
        "origin": row.origin if row else "",
        "pending_bearer": row.pending_bearer if row else "",
        "reason": reason,
    }


def recover_file(
    input_path: Path,
    ledger_path: Path,
    recovered_path: Path,
    audit_path: Path,
    proposals_path: Path,
    accounting_path: Path,
    tranche_path: Path | None = None,
) -> dict:
    paths = [Path(p).resolve() for p in (input_path, recovered_path, audit_path, proposals_path)]
    if len(set(paths)) != len(paths):
        raise ValueError("input, recovered, audit, and proposal paths must all be distinct")
    ledger = load_ledger(ledger_path)
    tranche_overlaps = 0
    if tranche_path is not None:
        ledger, tranche_overlaps = merge_ledgers(ledger, load_tranche(tranche_path))
    for p in (recovered_path, audit_path, proposals_path, accounting_path):
        p.parent.mkdir(parents=True, exist_ok=True)

    disp: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    by_origin: Counter[str] = Counter()
    records_in = 0
    records_out = 0
    neg_spans = 0
    retained_neg = 0
    assertions_minted = 0
    assertions_in = 0
    assertions_out = 0

    with (
        Path(input_path).open(encoding="utf-8") as src,
        Path(recovered_path).open("w", encoding="utf-8") as rec_out,
        Path(audit_path).open("w", encoding="utf-8", newline="") as aud_out,
        Path(proposals_path).open("w", encoding="utf-8") as prop_out,
    ):
        writer = csv.DictWriter(aud_out, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for line in src:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            records_in += 1
            assertions_in += len(record.get("assertions", []) or [])
            neg_here = sum(
                1 for s in record.get("unresolved_spans", []) or [] if s.get("reason") == NEG_REASON
            )
            neg_spans += neg_here
            if neg_here == 0:
                rec_out.write(line + "\n")
                records_out += 1
                assertions_out += len(record.get("assertions", []) or [])
                continue
            out, audit, proposals = recover_negation_record(record, ledger)
            rec_out.write(json.dumps(out, ensure_ascii=False) + "\n")
            records_out += 1
            assertions_out += len(out.get("assertions", []) or [])
            retained_neg += sum(
                1 for s in out.get("unresolved_spans", []) or [] if s.get("reason") == NEG_REASON
            )
            for arow in audit:
                writer.writerow(arow)
                disp[arow["disposition"]] += 1
                if arow["disposition"] == "recovered":
                    by_source[arow["source"]] += 1
                    by_kind[arow["kind"]] += 1
            for p in proposals:
                prop_out.write(json.dumps(p, ensure_ascii=False) + "\n")
                assertions_minted += 1
                by_origin[p.get("origin", "ledger")] += 1

    spans_removed = neg_spans - retained_neg

    accounting = {
        "input": str(input_path),
        "ledger": str(ledger_path),
        "tranche": str(tranche_path) if tranche_path is not None else "",
        "tranche_span_overlaps_with_ledger": tranche_overlaps,
        "records_input": records_in,
        "records_output": records_out,
        "records_identity_ok": records_in == records_out,
        "negated_context_spans_input": neg_spans,
        "negated_context_spans_removed": spans_removed,
        "negated_context_spans_retained": retained_neg,
        "assertions_input": assertions_in,
        "assertions_output": assertions_out,
        "assertions_minted": assertions_minted,
        "assertion_conservation_ok": assertions_out == assertions_in + assertions_minted,
        "span_conservation_ok": neg_spans == spans_removed + retained_neg,
        "promoted_spans": spans_removed,
        "promoted_assertions": assertions_minted,
        "promoted_by_source": dict(sorted(by_source.items())),
        "promoted_by_kind": dict(sorted(by_kind.items())),
        "promoted_by_origin": dict(sorted(by_origin.items())),
        "dispositions": dict(disp.most_common()),
        "recovered_jsonl": str(recovered_path),
        "audit_tsv": str(audit_path),
        "proposals_jsonl": str(proposals_path),
    }
    Path(accounting_path).write_text(
        json.dumps(accounting, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return accounting


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--tranche", type=Path, default=None)
    parser.add_argument("--recovered", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--accounting", type=Path, required=True)
    args = parser.parse_args()
    result = recover_file(
        args.input, args.ledger, args.recovered, args.audit, args.proposals, args.accounting,
        tranche_path=args.tranche,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
