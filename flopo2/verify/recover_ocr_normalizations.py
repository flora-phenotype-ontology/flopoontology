"""Recover reviewed OCR-split descriptors that exactly denote existing PATO terms.

The hyphen/slash inventory distinguishes ordinary botanical compounds from tokens whose
typesetting inserted a hyphen inside a word (for example ``coriace- ous``).  This pass is
deliberately occurrence-safe:

* only forms assigned to the reviewed ``F3_ocr_rejoin`` family are considered;
* removing whitespace and dash characters from the complete source token must match an
  unambiguous PATO preferred label or EXACT synonym;
* alternatives, ranges, temporal expressions, comparatives, and negation stay unresolved;
* a PO bearer must be explicit locally or supplied by a structured organ heading that is
  visible at the start of the source segment; and
* source text and offsets always refer to the unmodified flora text.

The source JSONL and flora text are never overwritten.  An optional audit TSV records a
disposition for every reviewed OCR occurrence, including those that remain unresolved.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.extract import baseline
from flopo2.verify.classify_unresolved import (
    compound_bounds,
    load_hyphen_forms,
    normalise_compound,
)
from flopo2.verify.recover_exact_pato_compounds import (
    BearerResolver,
    _reported_quote_context,
    load_pato_terms,
)


TARGET_REASON = "hyphenated_or_slash_compound"
TARGET_FAMILY = "F3_ocr_rejoin"
DASH_OR_SPACE = re.compile(r"[\s\-\u2013\u2014]+")
LOGICAL_CONNECTOR = re.compile(r"\b(?:or|ou|to|through)\b|\band\s*/\s*or\b", re.I)
TEMPORAL_CONNECTOR = re.compile(
    r"\b(?:turning|becoming|maturing|ripen(?:s|ed|ing)?|ripe|unripe|later|"
    r"eventually|then|afterwards?|initially|with\s+age|before|after|devenant|"
    r"puis|ensuite|matur(?:ation|it[ée])|m[ûu]r(?:e|es|s|it|issant\w*)?)\b",
    re.I,
)
COMPARATIVE = re.compile(
    r"\b(?:more|less|paler|darker|lighter|brighter|deeper|plus|moins)\b", re.I
)
AUDIT_FIELDS = (
    "source",
    "source_id",
    "source_segment_index",
    "organ",
    "token_start",
    "token_end",
    "source_token",
    "inventory_form",
    "pato_id",
    "pato_label",
    "matched_lexical_form",
    "covered_span_count",
    "disposition",
    "reason",
    "po_id",
    "bearer_method",
    "context",
)


@dataclass(frozen=True)
class ExactPatoMatch:
    pato_id: str
    pato_label: str
    lexical_form: str


@dataclass(frozen=True)
class OcrOccurrence:
    start: int
    end: int
    source_token: str
    inventory_form: str
    unresolved_indexes: tuple[int, ...]


def _compact(value: str) -> str:
    return DASH_OR_SPACE.sub("", value.casefold()).strip()


def exact_pato_compact_lexicon(path: Path) -> dict[str, ExactPatoMatch]:
    """Return unambiguous compact forms from PATO labels and EXACT synonyms."""

    candidates: dict[str, set[ExactPatoMatch]] = defaultdict(set)
    for term in load_pato_terms(path).values():
        for lexical_form in (term.label, *term.exact_synonyms):
            compact = _compact(lexical_form)
            if compact:
                candidates[compact].add(
                    ExactPatoMatch(term.pato_id, term.label, lexical_form)
                )
    return {
        compact: min(
            matches,
            key=lambda match: (
                match.lexical_form.casefold() != match.pato_label.casefold(),
                match.lexical_form.casefold(),
                match.pato_id,
            ),
        )
        for compact, matches in candidates.items()
        if len({match.pato_id for match in matches}) == 1
    }


def find_ocr_occurrences(record: dict, reviewed_forms: dict) -> list[OcrOccurrence]:
    """Group component spans into reviewed, complete OCR-split source tokens."""

    text = str(record.get("text", "") or "")
    unresolved = list(record.get("unresolved_spans", []) or [])
    grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
    inventory_forms: dict[tuple[int, int], str] = {}
    for index, span in enumerate(unresolved):
        if span.get("reason") != TARGET_REASON:
            continue
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        if not 0 <= start < end <= len(text):
            continue
        token_start, token_end = compound_bounds(text, start, end)
        token = text[token_start:token_end]
        inventory_form = normalise_compound(token)
        reviewed = reviewed_forms.get(inventory_form)
        if reviewed is None or reviewed.family != TARGET_FAMILY:
            continue
        key = (token_start, token_end)
        grouped[key].append(index)
        inventory_forms[key] = inventory_form
    return [
        OcrOccurrence(
            start,
            end,
            text[start:end],
            inventory_forms[(start, end)],
            tuple(sorted(indexes)),
        )
        for (start, end), indexes in sorted(grouped.items())
    ]


def _phrase(text: str, start: int, end: int) -> tuple[str, int, int]:
    """Return the comma-delimited phrase containing a token.

    OCR repairs need narrower logical scope than the general colour-compound guard: a later
    ``lanceolate or ovate`` phrase after a comma must not block an independent preceding
    ``coriace- ous`` texture assertion.
    """

    left = max((text.rfind(char, 0, start) for char in ",;:."), default=-1) + 1
    rights = [position for char in ",;:." if (position := text.find(char, end)) >= 0]
    right = min(rights, default=len(text))
    return text[left:right], left, right


def _context_reason(text: str, start: int, end: int) -> str:
    contextual = baseline._negated_or_hedged(text, start)
    if contextual:
        return contextual
    phrase, _left, _right = _phrase(text, start, end)
    if TEMPORAL_CONNECTOR.search(phrase):
        return "developmental_stage_context"
    if LOGICAL_CONNECTOR.search(phrase):
        return "logical_compound_context"
    if COMPARATIVE.search(phrase):
        return "comparative_context"
    return ""


def _structured_heading_is_visible(record: dict, po_id: str) -> bool:
    organ = str(record.get("organ", "") or "").strip()
    text = str(record.get("text", "") or "")
    if not organ or not po_id:
        return False
    return bool(re.match(rf"\s*{re.escape(organ)}\b", text, re.IGNORECASE))


def _bearer_offsets(text: str, surface_form: str, quality_start: int) -> tuple[int, int]:
    if not surface_form:
        return -1, -1
    matches = list(re.finditer(re.escape(surface_form), text, re.IGNORECASE))
    if not matches:
        return -1, -1
    match = min(matches, key=lambda item: abs(item.start() - quality_start))
    return match.start(), match.end()


def recover_record(
    record: dict,
    reviewed_forms: dict,
    pato_lexicon: dict[str, ExactPatoMatch],
    bearers: BearerResolver,
) -> tuple[dict, list[dict], Counter[str]]:
    """Return a copied record, occurrence audit rows, and accounting counts."""

    result = dict(record)
    assertions = [dict(assertion) for assertion in record.get("assertions", []) or []]
    unresolved = [dict(span) for span in record.get("unresolved_spans", []) or []]
    text = str(record.get("text", "") or "")
    removed_indexes: set[int] = set()
    outcomes: Counter[str] = Counter()
    audit: list[dict] = []
    seen = {
        (
            assertion.get("po_id", ""),
            assertion.get("pato_id", ""),
            assertion.get("source_start"),
            assertion.get("source_end"),
        )
        for assertion in assertions
    }

    for occurrence in find_ocr_occurrences(record, reviewed_forms):
        match = pato_lexicon.get(_compact(occurrence.source_token))
        disposition = "retained"
        reason = "no_exact_pato_whole_token"
        po_id = ""
        bearer_method = ""
        if match is not None:
            reason = _context_reason(text, occurrence.start, occurrence.end)
            if not reason:
                bearer = bearers.resolve(
                    record, occurrence.start, occurrence.end, match.pato_id
                )
                po_id = bearer.po_id
                bearer_method = bearer.method
                if not po_id:
                    reason = "missing_or_unsupported_bearer"
                elif bearer.method == "organ_heading" and not _structured_heading_is_visible(
                    record, po_id
                ):
                    reason = "heading_only_bearer_review"
                else:
                    reason = ""
                    key = (po_id, match.pato_id, occurrence.start, occurrence.end)
                    if key in seen:
                        disposition = "already_asserted"
                        reason = "duplicate_assertion"
                        outcomes["already_asserted"] += 1
                    else:
                        qualifier_fields, qualifier_start, qualifier_text = (
                            baseline._modality_context(text, occurrence.start)
                        )
                        seasons, season_operator, season_start, season_end = (
                            baseline._season_context(
                                text, occurrence.start, occurrence.end
                            )
                        )
                        reported_quote = _reported_quote_context(
                            text, occurrence.start, occurrence.end
                        )
                        if reported_quote:
                            qualifier_fields["epistemic_modality"] = "reported"
                            qualifier_start = min(qualifier_start, reported_quote[0])
                            qualifier_text = reported_quote[2]
                        source_start = min(
                            occurrence.start, qualifier_start, season_start
                        )
                        source_end = max(
                            occurrence.end,
                            season_end,
                            reported_quote[1]
                            if reported_quote
                            else occurrence.end,
                        )
                        bearer_start, bearer_end = _bearer_offsets(
                            text, bearer.surface_form, occurrence.start
                        )
                        assertion = {
                            "po_id": po_id,
                            "pato_id": match.pato_id,
                            "negated": False,
                            "organ": record.get("organ", ""),
                            "source_text": text[source_start:source_end],
                            "source_start": source_start,
                            "source_end": source_end,
                            "raw_quality_text": occurrence.source_token,
                            "raw_entity_text": (
                                text[bearer_start:bearer_end]
                                if bearer_start >= 0
                                else bearer.surface_form
                            ),
                            "bearer_start": (
                                bearer_start if bearer_start >= 0 else None
                            ),
                            "bearer_end": bearer_end if bearer_end >= 0 else None,
                            "modality_text": qualifier_text,
                            "season_contexts": seasons,
                            "season_operator": season_operator,
                            "normalization_status": "auto",
                            "mapping_provenance": [
                                "reviewed OCR/tokenization reconstruction; complete source "
                                "token maps to a PATO preferred label or EXACT synonym after "
                                "removing only whitespace and dash characters",
                                *(
                                    [
                                        "explicitly quoted source phrase; epistemic modality "
                                        "reported"
                                    ]
                                    if reported_quote
                                    else []
                                ),
                            ],
                            "extractor": "deterministic_ocr_pato_recovery",
                            **qualifier_fields,
                        }
                        assertions.append(assertion)
                        seen.add(key)
                        disposition = "promoted"
                        outcomes[f"promoted:{match.pato_id}"] += 1
                    removed_indexes.update(occurrence.unresolved_indexes)
                    outcomes["resolved_evidence_spans"] += len(
                        occurrence.unresolved_indexes
                    )
        if disposition == "retained":
            outcomes[f"retained:{reason}"] += 1
        phrase, _phrase_start, _phrase_end = _phrase(
            text, occurrence.start, occurrence.end
        )
        audit.append(
            {
                "source": record.get("source", ""),
                "source_id": record.get("source_id", ""),
                "source_segment_index": record.get("source_segment_index", 0),
                "organ": record.get("organ", ""),
                "token_start": occurrence.start,
                "token_end": occurrence.end,
                "source_token": occurrence.source_token,
                "inventory_form": occurrence.inventory_form,
                "pato_id": match.pato_id if match else "",
                "pato_label": match.pato_label if match else "",
                "matched_lexical_form": match.lexical_form if match else "",
                "covered_span_count": len(occurrence.unresolved_indexes),
                "disposition": disposition,
                "reason": reason,
                "po_id": po_id,
                "bearer_method": bearer_method,
                "context": phrase.strip(),
            }
        )

    result["assertions"] = assertions
    result["unresolved_spans"] = [
        span for index, span in enumerate(unresolved) if index not in removed_indexes
    ]
    result.pop("annotation_extension_iri", None)
    if removed_indexes:
        result = ensure_source_statements(result)
    return result, audit, outcomes


def recover_file(
    input_path: Path,
    output_path: Path,
    *,
    classified_forms: Path,
    pato_obo: Path = Path("ont/quality.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    audit_tsv: Path | None = None,
) -> dict[str, object]:
    """Recover one JSONL non-destructively and optionally write a full audit."""

    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("recovery output must be distinct from its input")
    reviewed_forms = load_hyphen_forms(classified_forms)
    pato_lexicon = exact_pato_compact_lexicon(pato_obo)
    bearers = BearerResolver(po_lexicon)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if audit_tsv is not None:
        audit_tsv.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    audit_rows = 0
    promoted_by_source: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    audit_context = (
        audit_tsv.open("w", encoding="utf-8", newline="")
        if audit_tsv is not None
        else None
    )
    try:
        writer = (
            csv.DictWriter(
                audit_context,
                fieldnames=AUDIT_FIELDS,
                delimiter="\t",
                lineterminator="\n",
            )
            if audit_context is not None
            else None
        )
        if writer is not None:
            writer.writeheader()
        with Path(input_path).open(encoding="utf-8") as source, output_path.open(
            "w", encoding="utf-8"
        ) as output:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                recovered, audit, outcomes = recover_record(
                    record, reviewed_forms, pato_lexicon, bearers
                )
                output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
                if writer is not None:
                    writer.writerows(audit)
                records += 1
                audit_rows += len(audit)
                outcome_counts.update(outcomes)
                promoted = sum(
                    count
                    for outcome, count in outcomes.items()
                    if outcome.startswith("promoted:")
                )
                if promoted:
                    promoted_by_source[str(record.get("source", ""))] += promoted
    finally:
        if audit_context is not None:
            audit_context.close()
    return {
        "input": str(input_path),
        "output": str(output_path),
        "records": records,
        "reviewed_ocr_forms": sum(
            form.family == TARGET_FAMILY for form in reviewed_forms.values()
        ),
        "audited_occurrences": audit_rows,
        "promoted_by_source": dict(sorted(promoted_by_source.items())),
        "outcomes": dict(sorted(outcome_counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--classified-forms", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = recover_file(
        args.input,
        args.output,
        classified_forms=args.classified_forms,
        pato_obo=args.pato_obo,
        po_lexicon=args.po_lexicon,
        audit_tsv=args.audit,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
