"""Lossless source-statement provenance for flora trait records.

The extraction wire format predates first-class source statements.  This module upgrades both
new and legacy records without changing their original assertion spans.  A statement identifier
is source scoped: repeated wording in separate documents or segment occurrences never collapses
to one provenance entity.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


FREQUENCY_ALIASES = {
    "always": "universal",
    "universally": "universal",
    "usually": "usually",
    "typically": "usually",
    "normally": "usually",
    "generally": "usually",
    "mostly": "usually",
    "often": "often",
    "frequently": "often",
    "commonly": "often",
    "sometimes": "sometimes",
    "occasionally": "occasionally",
    "rarely": "rarely",
    "seldom": "rarely",
    "never": "never",
    "toujours": "universal",
    "généralement": "usually",
    "generalement": "usually",
    "souvent": "often",
    "parfois": "sometimes",
    "rarement": "rarely",
}
EPISTEMIC_ALIASES = {
    "probably": "probable",
    "probable": "probable",
    "possibly": "possible",
    "possible": "possible",
    "may": "possible",
    "perhaps": "possible",
    "uncertain": "uncertain",
    "reportedly": "reported",
    "reported": "reported",
}
VALUE_ALIASES = {
    "approximately": "approximately",
    "approx.": "approximately",
    "about": "approximately",
    "circa": "approximately",
    "ca.": "approximately",
    "ca": "approximately",
    "c.": "approximately",
    "c": "approximately",
    "environ": "approximately",
    "nearly": "nearly",
    "almost": "almost",
    "presque": "almost",
}


DEGREE_ALIASES = {
    "slightly": "slightly",
    "moderately": "moderately",
    "very": "very",
    "extremely": "extremely",
    "completely": "completely",
    "entirely": "completely",
    "complètement": "completely",
    "completement": "completely",
}


def _integer(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def stable_statement_id(
    record: dict[str, Any],
    start: int,
    end: int,
    verbatim_text: str,
) -> str:
    """Return a stable, source-scoped identifier for one retained statement span."""

    payload = {
        "source": str(record.get("source", "") or ""),
        "source_id": str(record.get("source_id", "") or ""),
        "source_segment_index": _integer(record.get("source_segment_index")),
        "segment_document_start": _integer(record.get("char_start")),
        "segment_document_end": _integer(record.get("char_end")),
        "start": start,
        "end": end,
        "verbatim_text": verbatim_text,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"statement-{digest}"


def _valid_span(text: str, start: Any, end: Any, expected: str) -> bool:
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start <= end <= len(text)
        and text[start:end] == expected
    )


def _valid_interval(text: str, start: Any, end: Any) -> bool:
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start <= end <= len(text)
    )


def _phrase_matches(
    segment: str,
    phrase: str,
    window: tuple[int, int] | None = None,
    *,
    case_insensitive: bool = False,
) -> list[tuple[int, int]]:
    """Return complete-token occurrences of ``phrase`` inside ``window``.

    The returned offsets are segment-relative.  Token guards prevent a normalized bearer such as
    ``leaf`` from being spuriously anchored inside ``leaflet``.
    """

    if not phrase:
        return []
    low, high = window or (0, len(segment))
    if not (0 <= low <= high <= len(segment)):
        return []
    left_guard = r"(?<!\w)" if phrase[0].isalnum() or phrase[0] == "_" else ""
    right_guard = r"(?!\w)" if phrase[-1].isalnum() or phrase[-1] == "_" else ""
    flags = re.IGNORECASE if case_insensitive else 0
    pattern = left_guard + re.escape(phrase) + right_guard
    return [
        (low + match.start(), low + match.end())
        for match in re.finditer(pattern, segment[low:high], flags)
    ]


def _alias_matches(
    segment: str,
    normalized: str,
    aliases: dict[str, str],
    window: tuple[int, int],
) -> list[tuple[int, int]]:
    """Return exact source occurrences of every alias for one normalized qualifier."""

    candidates = sorted(
        {alias for alias, value in aliases.items() if value == normalized},
        key=len,
        reverse=True,
    )
    if not candidates:
        return []
    low, high = window
    pattern = rf"(?<!\w)(?:{'|'.join(re.escape(value) for value in candidates)})(?!\w)"
    return [
        (low + match.start(), low + match.end())
        for match in re.finditer(pattern, segment[low:high], re.IGNORECASE)
    ]


_SENTENCE_END = frozenset({".", "!", "?"})


def _boundary_positions(segment: str) -> list[int]:
    """Indices of statement separators: ``;`` and sentence-final ``.``/``!``/``?``.

    A sentence-final mark qualifies when it ends the segment or is followed by whitespace and a
    capital letter.  A ``.`` between two digits is treated as a decimal point, not a boundary.
    """

    positions: list[int] = []
    length = len(segment)
    for idx, char in enumerate(segment):
        if char == ";":
            positions.append(idx)
        elif char in _SENTENCE_END:
            if (
                char == "."
                and 0 < idx < length - 1
                and segment[idx - 1].isdigit()
                and segment[idx + 1].isdigit()
            ):
                continue
            following = idx + 1
            while following < length and segment[following].isspace():
                following += 1
            if following >= length or segment[following].isupper():
                positions.append(idx)
    return positions


def _statement_window(segment: str, start: int, end: int) -> tuple[int, int]:
    """Clause bounds around an anchor that never cross a ``;`` or sentence boundary."""

    boundaries = _boundary_positions(segment)
    left = max((position + 1 for position in boundaries if position < start), default=0)
    right = min((position for position in boundaries if position >= end), default=len(segment))
    return left, right


def _locate_evidence(
    segment: str,
    text: object,
    start: object,
    end: object,
    *,
    window: tuple[int, int] | None = None,
    case_insensitive: bool = False,
) -> tuple[int, int] | None:
    """Resolve one evidence phrase to an exact interval, occurrence-safely.

    Exact supplied offsets win.  Otherwise a single occurrence inside the anchored clause is used;
    a phrase that repeats there without offsets is omitted (``None``), never assigned to the first
    substring.  Case-insensitive bearer recovery returns the source's actual interval.
    """

    phrase = str(text or "")
    if not phrase:
        return None
    if _valid_span(segment, start, end, phrase):
        return int(start), int(end)
    if (
        case_insensitive
        and _valid_interval(segment, start, end)
        and segment[int(start) : int(end)].casefold() == phrase.casefold()
    ):
        return int(start), int(end)
    # Invalid or incomplete supplied offsets must remain visible to validation, not be silently
    # replaced by a different occurrence with the same wording.
    if start is not None or end is not None:
        return None
    matches = _phrase_matches(
        segment,
        phrase,
        window,
        case_insensitive=case_insensitive,
    )
    if len(matches) == 1:
        return matches[0]
    return None


def _exact_context_spans(segment: str, assertion: dict[str, Any]) -> list[tuple[int, int]]:
    """Return exact evidence intervals that can disambiguate a repeated source anchor."""

    spans: list[tuple[int, int]] = []
    bearer = str(assertion.get("raw_entity_text", "") or "")
    bearer_start = assertion.get("bearer_start")
    bearer_end = assertion.get("bearer_end")
    if _valid_span(segment, bearer_start, bearer_end, bearer) or (
        bearer
        and _valid_interval(segment, bearer_start, bearer_end)
        and segment[int(bearer_start) : int(bearer_end)].casefold() == bearer.casefold()
    ):
        spans.append((int(bearer_start), int(bearer_end)))
    modality = str(assertion.get("modality_text", "") or "")
    if _valid_span(
        segment,
        assertion.get("modality_start"),
        assertion.get("modality_end"),
        modality,
    ):
        spans.append((int(assertion["modality_start"]), int(assertion["modality_end"])))
    for contexts_key, text_key in (
        ("season_contexts", "season_text"),
        ("developmental_stage_contexts", "stage_text"),
    ):
        for context in assertion.get(contexts_key, []) or []:
            if not isinstance(context, dict):
                continue
            phrase = str(context.get(text_key, "") or "")
            if _valid_span(segment, context.get("start"), context.get("end"), phrase):
                spans.append((int(context["start"]), int(context["end"])))
    return spans


def _source_anchor(
    segment: str,
    assertion: dict[str, Any],
    linked_statement: dict[str, Any] | None = None,
) -> tuple[int, int] | None:
    """Resolve and persist the exact occurrence of an assertion's narrow source anchor."""

    phrase = str(assertion.get("source_text", "") or "")
    start = assertion.get("source_start")
    end = assertion.get("source_end")
    if not phrase:
        return None
    if _valid_span(segment, start, end, phrase):
        return int(start), int(end)

    search_windows: list[tuple[int, int] | None] = []
    if linked_statement is not None:
        statement_start = linked_statement.get("start")
        statement_end = linked_statement.get("end")
        if _valid_interval(segment, statement_start, statement_end):
            search_windows.append((int(statement_start), int(statement_end)))
    # Exact context offsets can identify which clause owns otherwise repeated predicate wording.
    search_windows.extend(
        _statement_window(segment, evidence_start, evidence_end)
        for evidence_start, evidence_end in _exact_context_spans(segment, assertion)
    )
    search_windows.append(None)
    for window in search_windows:
        matches = _phrase_matches(segment, phrase, window)
        if len(matches) == 1:
            anchor_start, anchor_end = matches[0]
            assertion["source_start"] = anchor_start
            assertion["source_end"] = anchor_end
            return anchor_start, anchor_end
    return None


def _evidence_window(
    segment: str,
    anchor: tuple[int, int] | None,
    linked_statement: dict[str, Any] | None = None,
) -> tuple[int, int] | None:
    """Return the clause-bounded search window for legacy evidence recovery."""

    if anchor is not None:
        clause_start, clause_end = _statement_window(segment, *anchor)
        if linked_statement is not None:
            statement_start = linked_statement.get("start")
            statement_end = linked_statement.get("end")
            if (
                _valid_interval(segment, statement_start, statement_end)
                and int(statement_start) <= anchor[0]
                and anchor[1] <= int(statement_end)
            ):
                # An already-retained statement is stronger occurrence evidence than the wider
                # clause.  Intersect it with clause bounds so a repeated cue elsewhere in the same
                # sentence cannot make an explicitly linked narrow statement look ambiguous.
                return (
                    max(int(statement_start), clause_start),
                    min(int(statement_end), clause_end),
                )
        return clause_start, clause_end
    if linked_statement is not None:
        start = linked_statement.get("start")
        end = linked_statement.get("end")
        if _valid_interval(segment, start, end) and int(start) < int(end):
            clause = _statement_window(segment, int(start), int(end))
            return max(int(start), clause[0]), min(int(end), clause[1])
    return None


def _fallback_clause_span(
    segment: str,
    assertion: dict[str, Any],
) -> tuple[int, int, str]:
    """Honest clause-bounded fallback when ``source_text`` has no resolvable occurrence.

    An exact auxiliary-evidence offset may still identify the relevant clause.  With no exact
    occurrence evidence, an empty statement is retained so strict validation exposes the defect;
    choosing the first repeated substring would create false provenance.
    """

    context_spans = _exact_context_spans(segment, assertion)
    if context_spans:
        start, end = context_spans[0]
        left, right = _statement_window(segment, start, end)
        return left, right, segment[left:right]
    return 0, 0, ""


def _statement_span(
    record: dict[str, Any],
    assertion: dict[str, Any],
    anchor: tuple[int, int] | None = None,
) -> tuple[int, int, str]:
    """Resolve a complete, occurrence-safe supporting statement span for an assertion.

    ``source_text`` may be a narrow predicate anchor.  A retained ``SourceStatement`` also includes
    any verbatim bearer, modality, season, and developmental-stage evidence that sits in the same
    clause, resolved by exact offsets first and by a single unambiguous occurrence otherwise.  The
    span never widens across a ``;`` or a sentence boundary relative to the anchor, and an
    unanchorable assertion falls back to a single clause rather than the whole segment.
    """

    segment = str(record.get("text", "") or "")
    anchor = anchor or _source_anchor(segment, assertion)
    if anchor is None:
        return _fallback_clause_span(segment, assertion)
    anchor_start, anchor_end = anchor

    window = _statement_window(segment, anchor_start, anchor_end)
    left_bound, right_bound = window
    evidence_spans: list[tuple[int, int]] = [(anchor_start, anchor_end)]

    def include(span: tuple[int, int] | None) -> None:
        # Evidence on the far side of a ``;`` or sentence boundary is never pulled in.
        if span is not None and left_bound <= span[0] and span[1] <= right_bound:
            evidence_spans.append(span)

    # An exact bearer mention when the extractor retained one; a case-normalized bearer is
    # recovered from the anchored clause.  Translated/non-verbatim labels are ignored, leaving the
    # record's organ_hint as their provenance context.
    include(
        _locate_evidence(
            segment,
            assertion.get("raw_entity_text"),
            assertion.get("bearer_start"),
            assertion.get("bearer_end"),
            window=window,
            case_insensitive=True,
        )
    )
    include(
        _locate_evidence(
            segment,
            assertion.get("modality_text"),
            assertion.get("modality_start"),
            assertion.get("modality_end"),
            window=window,
        )
    )
    for contexts_key, text_key in (
        ("season_contexts", "season_text"),
        ("developmental_stage_contexts", "stage_text"),
    ):
        for context in assertion.get(contexts_key, []) or []:
            if not isinstance(context, dict):
                continue
            include(
                _locate_evidence(
                    segment,
                    context.get(text_key),
                    context.get("start"),
                    context.get("end"),
                    window=window,
                )
            )

    statement_start = min(left for left, _right in evidence_spans)
    statement_end = max(right for _left, right in evidence_spans)
    return statement_start, statement_end, segment[statement_start:statement_end]


def _normalise_statement(record: dict[str, Any], statement: dict[str, Any]) -> dict[str, Any]:
    segment = str(record.get("text", "") or "")
    out = dict(statement)
    verbatim = str(out.get("verbatim_text", out.get("source_text", "")) or "")
    start = out.get("start")
    end = out.get("end")
    if not _valid_span(segment, start, end, verbatim):
        matches = _phrase_matches(segment, verbatim) if verbatim else []
        if len(matches) == 1:
            start, end = matches[0]
        elif not verbatim and _valid_interval(segment, start, end) and start == end:
            # Preserve an explicitly empty / generated unanchorable statement.  Expanding it to
            # the whole segment would invent provenance and could cross several clauses.
            start, end = int(start), int(end)
        else:
            raise ValueError(
                "explicit source statement offsets do not select its verbatim_text"
            )
    out["start"] = int(start)
    out["end"] = int(end)
    out["verbatim_text"] = verbatim
    out.pop("source_text", None)
    out.setdefault("statement_id", stable_statement_id(record, int(start), int(end), verbatim))
    out.setdefault("language", str(record.get("language", "") or ""))
    document_start = record.get("char_start")
    if isinstance(document_start, int) and not isinstance(document_start, bool):
        out.setdefault("document_start", document_start + int(start))
        out.setdefault("document_end", document_start + int(end))
    return out


def _normalise_bearer(
    assertion: dict[str, Any],
    segment: str,
    window: tuple[int, int] | None,
    anchor: tuple[int, int] | None = None,
) -> None:
    """Attach exact, case-preserving offsets to one unambiguous local bearer mention."""

    bearer = str(assertion.get("raw_entity_text", "") or "")
    if not bearer:
        return
    span = None
    candidate_windows = [candidate for candidate in (anchor, window) if candidate is not None]
    for candidate_window in dict.fromkeys(candidate_windows):
        span = _locate_evidence(
            segment,
            bearer,
            assertion.get("bearer_start"),
            assertion.get("bearer_end"),
            window=candidate_window,
            case_insensitive=True,
        )
        if span is not None:
            break
    if span is None:
        return
    start, end = span
    assertion["bearer_start"] = start
    assertion["bearer_end"] = end
    # raw_entity_text is allowed to be minimally normalized, but an attached exact occurrence
    # should preserve the source's spelling and capitalization.
    assertion["raw_entity_text"] = segment[start:end]


def _quality_anchored_cue(
    segment: str,
    assertion: dict[str, Any],
    cue: str,
    window: tuple[int, int],
) -> tuple[int, int] | None:
    """Resolve a repeated cue only when one occurrence directly modifies a unique quality.

    Botanical clauses can contain several approximation signs (for example ``± obovale`` and
    ``± acuminé``).  The assertion's retained ``raw_quality_text`` supplies independent occurrence
    evidence: if that quality occurs once, select the nearest preceding cue only when the text
    between cue and quality contains no clause/list punctuation.  Otherwise remain unresolved.
    """

    if assertion.get("modality_start") is not None or assertion.get("modality_end") is not None:
        return None
    quality = str(assertion.get("raw_quality_text", "") or "")
    if not quality or not cue:
        return None
    quality_matches = _phrase_matches(segment, quality, window, case_insensitive=True)
    cue_matches = _phrase_matches(segment, cue, window, case_insensitive=True)
    if len(quality_matches) != 1 or len(cue_matches) < 2:
        return None
    quality_start, _quality_end = quality_matches[0]
    preceding = [match for match in cue_matches if match[1] <= quality_start]
    if not preceding:
        return None
    cue_start, cue_end = max(preceding, key=lambda match: match[1])
    intervening = segment[cue_end:quality_start]
    if re.search(r"[;,.!?]", intervening):
        return None
    return cue_start, cue_end


def normalise_modalities(
    assertion: dict[str, Any],
    segment: str = "",
    window: tuple[int, int] | None = None,
    anchor: tuple[int, int] | None = None,
) -> None:
    """Populate orthogonal qualifiers and retain only an exact source modality cue.

    Legacy ``modifier=usually`` may correspond to source ``typically``.  Recovery searches the
    clause holding the assertion anchor, not merely its narrow predicate ``source_text``.  A cue
    that repeats in that clause is left without offsets rather than assigned to the first match.
    """

    modifier = str(assertion.get("modifier", "") or "").strip().lower()
    frequency = FREQUENCY_ALIASES.get(modifier)
    epistemic = EPISTEMIC_ALIASES.get(modifier)
    value = VALUE_ALIASES.get(modifier)
    degree = DEGREE_ALIASES.get(modifier)
    if frequency and assertion.get("frequency_qualifier") in {None, "", "unspecified"}:
        assertion["frequency_qualifier"] = frequency
    elif not assertion.get("frequency_qualifier"):
        assertion["frequency_qualifier"] = "unspecified"
    if epistemic and assertion.get("epistemic_modality") in {None, "", "asserted"}:
        assertion["epistemic_modality"] = epistemic
    elif not assertion.get("epistemic_modality"):
        assertion["epistemic_modality"] = "asserted"
    if value and assertion.get("value_qualifier") in {None, "", "exact"}:
        assertion["value_qualifier"] = value
    elif not assertion.get("value_qualifier"):
        assertion["value_qualifier"] = "exact"
    if degree and assertion.get("degree_qualifier") in {None, "", "unmodified"}:
        assertion["degree_qualifier"] = degree
    elif not assertion.get("degree_qualifier"):
        assertion["degree_qualifier"] = "unmodified"
    search_window = window or ((0, len(segment)) if segment else None)
    candidate_windows = [candidate for candidate in (anchor, search_window) if candidate is not None]
    candidate_windows = list(dict.fromkeys(candidate_windows))
    current_cue = str(assertion.get("modality_text", "") or "")
    resolved: tuple[int, int] | None = None
    if current_cue and segment:
        for candidate_window in candidate_windows:
            resolved = _locate_evidence(
                segment,
                current_cue,
                assertion.get("modality_start"),
                assertion.get("modality_end"),
                window=candidate_window,
                case_insensitive=True,
            )
            if resolved is None:
                resolved = _quality_anchored_cue(
                    segment, assertion, current_cue, candidate_window
                )
            if resolved is not None:
                break

    normalized_groups = (
        (str(assertion.get("frequency_qualifier", "") or ""), FREQUENCY_ALIASES),
        (str(assertion.get("epistemic_modality", "") or ""), EPISTEMIC_ALIASES),
        (str(assertion.get("value_qualifier", "") or ""), VALUE_ALIASES),
        (str(assertion.get("degree_qualifier", "") or ""), DEGREE_ALIASES),
    )
    if resolved is None and segment and search_window is not None:
        for candidate_window in candidate_windows:
            alias_matches: list[tuple[int, int]] = []
            for normalized, aliases in normalized_groups:
                if normalized in {"", "unspecified", "asserted", "exact", "unmodified"}:
                    continue
                alias_matches.extend(
                    _alias_matches(segment, normalized, aliases, candidate_window)
                )
            # Orthogonal qualifier categories should not select overlapping aliases twice.
            alias_matches = sorted(set(alias_matches))
            if len(alias_matches) == 1:
                resolved = alias_matches[0]
                break

    if resolved is not None:
        cue_start, cue_end = resolved
        assertion["modality_text"] = segment[cue_start:cue_end]
        assertion["modality_start"] = cue_start
        assertion["modality_end"] = cue_end
    elif current_cue and segment:
        # Preserve a genuinely verbatim but ambiguous cue without guessing an occurrence; strict
        # validation will require offsets.  Drop normalized spellings that do not occur in the
        # anchored clause, because retaining them would invent source text.
        current_matches = _phrase_matches(
            segment,
            current_cue,
            search_window,
            case_insensitive=True,
        )
        if current_matches:
            assertion["modality_text"] = segment[current_matches[0][0] : current_matches[0][1]]
        else:
            assertion["modality_text"] = ""
            assertion.pop("modality_start", None)
            assertion.pop("modality_end", None)
    assertion.setdefault("season_contexts", [])
    assertion.setdefault("season_operator", "atomic")
    assertion.setdefault("bearer_context_qualities", [])
    assertion.setdefault("developmental_stage_contexts", [])
    assertion.setdefault("developmental_stage_operator", "atomic")


def ensure_source_statements(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with every assertion linked to a retained source statement.

    Explicit source statements are preserved in input order.  Legacy assertions create a shared
    statement when they use the same source-scoped span.  An assertion that already carries an
    external ``source_statement_id`` keeps it; a matching statement record is materialized if the
    input omitted one.
    """

    out = copy.deepcopy(record)
    statements: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    for raw in out.get("source_statements", []) or []:
        if not isinstance(raw, dict):
            raise ValueError("source_statements entries must be objects")
        statement = _normalise_statement(out, raw)
        statement_id = str(statement["statement_id"])
        previous = by_id.get(statement_id)
        if previous is not None and previous != statement:
            raise ValueError(f"conflicting source statement identifier: {statement_id}")
        if previous is None:
            by_id[statement_id] = statement
            statements.append(statement)

    for assertion in out.get("assertions", []) or []:
        if not isinstance(assertion, dict):
            continue
        requested_id = str(assertion.get("source_statement_id", "") or "")
        linked_statement = by_id.get(requested_id)
        segment = str(out.get("text", "") or "")
        anchor = _source_anchor(segment, assertion, linked_statement)
        window = _evidence_window(segment, anchor, linked_statement)
        normalise_modalities(assertion, segment, window, anchor)
        _normalise_bearer(assertion, segment, window, anchor)
        start, end, verbatim = _statement_span(out, assertion, anchor)
        statement_id = requested_id or stable_statement_id(out, start, end, verbatim)
        if statement_id not in by_id:
            statement = _normalise_statement(
                out,
                {
                    "statement_id": statement_id,
                    "verbatim_text": verbatim,
                    "start": start,
                    "end": end,
                },
            )
            by_id[statement_id] = statement
            statements.append(statement)
        assertion["source_statement_id"] = statement_id

    out["source_statements"] = statements
    return out


def upgrade_jsonl(input_path: Path, output_path: Path, limit: int | None = None) -> dict[str, Any]:
    """Stream a legacy extraction artifact into the lossless assertion wire model."""

    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("provenance upgrade requires a distinct output path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    source_positions: Counter[tuple[str, str]] = Counter()
    with Path(input_path).open(encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8"
    ) as target:
        for line in source:
            if not line.strip():
                continue
            if limit is not None and counts["segments"] >= limit:
                break
            record = json.loads(line)
            source_key = (str(record.get("source", "")), str(record.get("source_id", "")))
            record.setdefault("source_segment_index", source_positions[source_key])
            source_positions[source_key] += 1
            upgraded = ensure_source_statements(record)
            target.write(json.dumps(upgraded, ensure_ascii=False) + "\n")
            counts["segments"] += 1
            counts["assertions"] += len(upgraded.get("assertions", []) or [])
            counts["source_statements"] += len(upgraded.get("source_statements", []) or [])
            counts["qualified_assertions"] += sum(
                1
                for assertion in upgraded.get("assertions", []) or []
                if assertion.get("frequency_qualifier", "unspecified")
                not in {"unspecified", "universal"}
                or assertion.get("epistemic_modality", "asserted") != "asserted"
                or assertion.get("value_qualifier", "exact") != "exact"
                or assertion.get("degree_qualifier", "unmodified") != "unmodified"
            )
            counts["seasonal_assertions"] += sum(
                bool(assertion.get("season_contexts"))
                for assertion in upgraded.get("assertions", []) or []
            )
    return {**dict(counts), "input": str(input_path), "output": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upgrade legacy FLOPO extraction JSONL with first-class source provenance."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            upgrade_jsonl(args.input, args.output, args.limit),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
