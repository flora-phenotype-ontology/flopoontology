"""Rebind prior Opus logical analysis into exact one-of expression review candidates.

The archived logical-operand table is machine-generated evidence, not an admission decision.  This
module accepts only its narrow ``recover_one_of`` rows, then independently rebinds every source
offset, operand surface, live ontology identifier, bearer/attribute combination, overlapping
assertion, and unresolved-span clear target against a frozen corpus.  The result is a typed
occurrence-level candidate for fresh two-family review; the input corpus is never changed here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from flopo2.extract import baseline
from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import PhenotypeExpression, PhenotypeExpressionCandidate


TARGET_REASONS = frozenset(
    {
        "explicit_disjunction",
        "same_attribute_composite_or_transition",
        "unsupported_alternative_or_transition",
        "unsupported_same_attribute_neighbor",
        "hyphenated_or_slash_compound",
    }
)
TARGET_DECISION = "recover_one_of"
TARGET_INTERPRETATION = "explicit_finite_disjunction"
REVIEW_REASON = "machine_analyzed_one_of_candidate"
EXTRACTOR = "machine_analyzed_one_of_candidate_v1"
SegmentKey = tuple[str, str, int]


def _segment_key(row: dict[str, Any]) -> SegmentKey:
    return (
        str(row.get("source", "") or ""),
        str(row.get("source_id", "") or ""),
        int(row.get("source_segment_index", 0) or 0),
    )


def _pipe(value: object) -> list[str]:
    return [item for item in str(value or "").split("|") if item]


def _expression_digest(row: dict[str, Any], expression: str) -> str:
    uid = "|".join(
        (
            str(row.get("source", "")),
            str(row.get("source_id", "")),
            str(int(row.get("source_segment_index", 0) or 0)),
            str(int(row.get("expression_start", -1))),
            str(int(row.get("expression_end", -1))),
        )
    )
    return hashlib.sha256(f"{uid}|{expression}".encode()).hexdigest()[:16]


def _load_catalog_ids(path: Path) -> tuple[set[str], set[str]]:
    identifiers: set[str] = set()
    attributes: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            identifier = str(row.get("id", "") or "")
            if identifier:
                identifiers.add(identifier)
                if "attribute_slim" in str(row.get("slim", "") or "").split("|"):
                    attributes.add(identifier)
    return identifiers, attributes


def _load_flopo_ids(path: Path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            iri.rsplit("/", 1)[-1]
            for row in csv.DictReader(handle, delimiter="\t")
            if (iri := str(row.get("flopo_iri", "") or "")) and "/FLOPO_" in iri
        }


def _load_combinations(path: Path) -> dict[tuple[str, str], str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (str(row.get("po_id", "") or ""), str(row.get("pato_id", "") or "")): str(
                row.get("status", "") or ""
            )
            for row in csv.DictReader(handle, delimiter="\t")
        }


def _eligible_rows(path: Path) -> tuple[dict[SegmentKey, list[dict[str, str]]], Counter[str]]:
    grouped: defaultdict[SegmentKey, list[dict[str, str]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    identities: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            counts["decision_rows"] += 1
            if row.get("decision") != TARGET_DECISION:
                counts["not_recover_one_of"] += 1
                continue
            if row.get("operator") != "one_of" or row.get(
                "operator_interpretation"
            ) != TARGET_INTERPRETATION:
                counts["not_explicit_one_of"] += 1
                continue
            if any(
                row.get(field)
                for field in (
                    "modifiers",
                    "modality_text",
                    "frequency_qualifier",
                    "epistemic_modality",
                    "negation_guard",
                )
            ):
                counts["modified_or_contextual"] += 1
                continue
            terms = _pipe(row.get("operand_term_ids"))
            surfaces = _pipe(row.get("operand_surfaces"))
            if len(terms) < 2 or len(terms) != len(surfaces) or len(terms) != len(set(terms)):
                counts["invalid_operand_accounting"] += 1
                continue
            if not row.get("bearer_po_id") or not row.get("attribute_pato_id"):
                counts["missing_bearer_or_attribute"] += 1
                continue
            identity = str(row.get("expression_uid", "") or "")
            if not identity or identity in identities:
                raise ValueError(f"duplicate or missing expression identity: {identity!r}")
            identities.add(identity)
            grouped[_segment_key(row)].append(row)
            counts["structurally_eligible"] += 1
    return dict(grouped), counts


def _find_operands(
    expression: str, surfaces: list[str]
) -> tuple[tuple[tuple[int, int], ...], str]:
    located: list[tuple[int, int]] = []
    cursor = 0
    folded = expression.casefold()
    for surface in surfaces:
        offset = expression.find(surface, cursor)
        if offset < 0:
            offset = folded.find(surface.casefold(), cursor)
        if offset < 0:
            return (), "operand_surface_not_verbatim"
        located.append((offset, offset + len(surface)))
        cursor = offset + len(surface)
    for left, right in zip(located, located[1:], strict=False):
        bridge = expression[left[1] : right[0]]
        if not re.search(r"\b(?:or|ou)\b|,", bridge, re.IGNORECASE):
            return (), "operand_bridge_has_no_one_of_syntax"
    if not re.search(r"\b(?:or|ou)\b", expression, re.IGNORECASE):
        return (), "expression_has_no_explicit_disjunction"
    return tuple(located), ""


def _overlaps(assertion: dict[str, Any], start: int, end: int) -> bool:
    try:
        other_start, other_end = int(assertion.get("source_start", -1)), int(
            assertion.get("source_end", -1)
        )
    except (TypeError, ValueError):
        return False
    return other_start < end and start < other_end


def _candidate_for(
    record: dict[str, Any],
    decision: dict[str, str],
    *,
    po_ids: set[str],
    pato_ids: set[str],
    pato_attributes: set[str],
    flopo_ids: set[str],
    combinations: dict[tuple[str, str], str],
) -> tuple[PhenotypeExpressionCandidate | None, str]:
    text = str(record.get("text", "") or "")
    try:
        start, end = int(decision["expression_start"]), int(decision["expression_end"])
    except (KeyError, TypeError, ValueError):
        return None, "invalid_expression_offsets"
    expression = str(decision.get("expression_text", "") or "")
    if start < 0 or end <= start or end > len(text) or text[start:end] != expression:
        return None, "expression_not_verbatim_in_stage"
    if decision.get("expression_digest") != _expression_digest(decision, expression):
        return None, "expression_digest_mismatch"
    terms = _pipe(decision.get("operand_term_ids"))
    surfaces = _pipe(decision.get("operand_surfaces"))
    located, reason = _find_operands(expression, surfaces)
    if reason:
        return None, reason
    absolute_operands = tuple((start + left, start + right) for left, right in located)
    bearer_id = str(decision.get("bearer_po_id", "") or "")
    attribute_id = str(decision.get("attribute_pato_id", "") or "")
    if bearer_id.startswith("PO_") and bearer_id not in po_ids:
        return None, "unknown_bearer_id"
    if bearer_id.startswith("FLOPO_") and bearer_id not in flopo_ids:
        return None, "unknown_bearer_id"
    if not bearer_id.startswith(("PO_", "FLOPO_")):
        return None, "invalid_bearer_namespace"
    if attribute_id not in pato_ids or attribute_id not in pato_attributes:
        return None, "invalid_pato_attribute"
    if any(
        term.startswith("PATO_") and term not in pato_ids
        or term.startswith("FLOPO_") and term not in flopo_ids
        or not term.startswith(("PATO_", "FLOPO_"))
        for term in terms
    ):
        return None, "unknown_value_term"
    if combinations.get((bearer_id, attribute_id), "novel") != "allowed":
        return None, "bearer_attribute_combination_not_allowed"
    if any(
        _overlaps(assertion, start, end) for assertion in record.get("assertions", []) or []
    ):
        return None, "overlapping_existing_assertion"
    for operand_start, _operand_end in absolute_operands:
        contextual = baseline._negated_or_hedged(text, operand_start)
        if contextual:
            return None, contextual
    modalities, _modality_start, modality_text = baseline._modality_context(text, start)
    if modalities or modality_text:
        return None, "modal_or_frequency_context"
    seasons, _season_operator, _season_start, _season_end = baseline._season_context(
        text, start, end
    )
    if seasons:
        return None, "season_context"

    contained = [
        span
        for span in record.get("unresolved_spans", []) or []
        if start <= int(span.get("start", -1)) and int(span.get("end", -1)) <= end
    ]
    clear: list[tuple[int, int]] = []
    for span in contained:
        span_start, span_end = int(span.get("start", -1)), int(span.get("end", -1))
        span_term = str(span.get("candidate_pato_id", "") or "")
        if span.get("reason") not in TARGET_REASONS or not any(
            operand_start <= span_start
            and span_end <= operand_end
            and span_term == term
            for (operand_start, operand_end), term in zip(
                absolute_operands, terms, strict=True
            )
        ):
            return None, "unreviewed_contained_unresolved_span"
        clear.append((span_start, span_end))
    if not clear:
        return None, "no_exact_current_clear_target"
    if len(clear) != len(set(clear)):
        return None, "duplicate_clear_target"

    bearer_surface = str(decision.get("bearer_surface", "") or "")
    bearer_text = ""
    bearer_start = bearer_end = None
    if bearer_surface:
        matches = list(re.finditer(re.escape(bearer_surface), text, re.IGNORECASE))
        if matches:
            selected = min(matches, key=lambda match: abs(match.start() - start))
            bearer_text = text[selected.start() : selected.end()]
            bearer_start, bearer_end = selected.start(), selected.end()
    signature = PhenotypeExpression(
        bearer_id=bearer_id,
        quality_id=attribute_id,
        value_operator="one_of",
        value_terms=tuple(terms),
    )
    return (
        PhenotypeExpressionCandidate(
            signature=signature,
            bearer_method=str(decision.get("bearer_method", "") or "machine_analysis"),
            bearer_text=bearer_text,
            bearer_start=bearer_start,
            bearer_end=bearer_end,
            expression_start=start,
            expression_end=end,
            expression_text=expression,
            clear_unresolved_spans=tuple(sorted(clear)),
        ),
        "",
    )


def _write_immutable_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed derived artifact: {path}")
    atomic_write_text(path, payload)


def prepare_one_of_review(
    *,
    stage_path: Path,
    decisions_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    exclusions_path: Path,
    report_path: Path,
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry_path: Path = Path("config/flopo_id_registry.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Build immutable source-bound one-of candidates and exclusion accounting."""

    paths = (
        stage_path,
        decisions_path,
        review_input_path,
        candidate_ledger_path,
        exclusions_path,
        report_path,
        po_lexicon_path,
        pato_lexicon_path,
        flopo_registry_path,
        combinations_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("one-of candidate inputs and outputs must be distinct")
    grouped, counts = _eligible_rows(decisions_path)
    po_ids, _po_attributes = _load_catalog_ids(po_lexicon_path)
    pato_ids, pato_attributes = _load_catalog_ids(pato_lexicon_path)
    flopo_ids = _load_flopo_ids(flopo_registry_path)
    combinations = _load_combinations(combinations_path)
    wanted = set(grouped)
    found: set[SegmentKey] = set()
    review_records: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _segment_key(record)
            if key not in wanted:
                continue
            if key in found:
                raise ValueError(f"duplicate Stage segment identity at line {line_number}: {key}")
            found.add(key)
            synthetic: list[dict[str, Any]] = []
            used_clear_ranges: set[tuple[int, int]] = set()
            for decision in grouped[key]:
                candidate, reason = _candidate_for(
                    record,
                    decision,
                    po_ids=po_ids,
                    pato_ids=pato_ids,
                    pato_attributes=pato_attributes,
                    flopo_ids=flopo_ids,
                    combinations=combinations,
                )
                if candidate is None:
                    exclusions.append(
                        {
                            "expression_uid": decision.get("expression_uid", ""),
                            "source": key[0],
                            "source_id": key[1],
                            "source_segment_index": key[2],
                            "expression_start": decision.get("expression_start", ""),
                            "expression_end": decision.get("expression_end", ""),
                            "expression_text": decision.get("expression_text", ""),
                            "reason": reason or "candidate_construction_failed",
                        }
                    )
                    counts[f"excluded:{reason or 'candidate_construction_failed'}"] += 1
                    continue
                clear_ranges = set(candidate.clear_unresolved_spans)
                if overlap := used_clear_ranges.intersection(clear_ranges):
                    exclusions.append(
                        {
                            "expression_uid": decision.get("expression_uid", ""),
                            "source": key[0],
                            "source_id": key[1],
                            "source_segment_index": key[2],
                            "expression_start": candidate.expression_start,
                            "expression_end": candidate.expression_end,
                            "expression_text": candidate.expression_text,
                            "reason": "overlapping_candidate_clear_targets",
                            "overlap": sorted(overlap),
                        }
                    )
                    counts["excluded:overlapping_candidate_clear_targets"] += 1
                    continue
                used_clear_ranges.update(clear_ranges)
                candidate_id = stable_id(
                    "oneof",
                    (
                        *key,
                        candidate.expression_start,
                        candidate.expression_end,
                        candidate.signature.model_dump(mode="json"),
                    ),
                )
                synthetic.append(
                    {
                        "start": candidate.expression_start,
                        "end": candidate.expression_end,
                        "surface_form": candidate.expression_text,
                        "reason": REVIEW_REASON,
                        "candidate_pato_id": candidate.signature.quality_id,
                        "pending_bearer": candidate.signature.bearer_id,
                        "extractor": EXTRACTOR,
                        "candidate_id": candidate_id,
                        "phenotype_expression_candidate": candidate.model_dump(mode="json"),
                    }
                )
                ledger.append(
                    {
                        "candidate_id": candidate_id,
                        "expression_uid": decision.get("expression_uid", ""),
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "family": decision.get("family", ""),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                counts["candidates"] += 1
                counts["clear_targets"] += len(candidate.clear_unresolved_spans)
                counts[f"candidate_family:{decision.get('family', '')}"] += 1
            if synthetic:
                synthetic.sort(key=lambda row: (row["start"], row["end"], row["candidate_id"]))
                text = str(record.get("text", "") or "")
                review_records.append(
                    {
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "language": record.get("language", ""),
                        "char_start": int(record.get("char_start", 0) or 0),
                        "char_end": int(record.get("char_end", len(text)) or len(text)),
                        "text": text,
                        "assertions": record.get("assertions", []) or [],
                        "term_mentions": record.get("term_mentions", []) or [],
                        "unresolved_spans": synthetic,
                    }
                )
    for key in sorted(wanted - found):
        for decision in grouped[key]:
            exclusions.append(
                {
                    "expression_uid": decision.get("expression_uid", ""),
                    "source": key[0],
                    "source_id": key[1],
                    "source_segment_index": key[2],
                    "expression_start": decision.get("expression_start", ""),
                    "expression_end": decision.get("expression_end", ""),
                    "expression_text": decision.get("expression_text", ""),
                    "reason": "segment_absent_from_stage",
                }
            )
            counts["excluded:segment_absent_from_stage"] += 1

    if counts["candidates"] + len(exclusions) != counts["structurally_eligible"]:
        raise ValueError("one-of candidate extraction does not conserve eligible decisions")
    review_records.sort(
        key=lambda row: (row["source"], row["source_id"], row["source_segment_index"])
    )
    ledger.sort(key=lambda row: row["candidate_id"])
    exclusions.sort(key=lambda row: str(row.get("expression_uid", "")))
    _write_immutable_rows(review_input_path, review_records)
    _write_immutable_rows(candidate_ledger_path, ledger)
    _write_immutable_rows(exclusions_path, exclusions)
    report = {
        "schema_version": "flopo-one-of-candidate-report-v1",
        "candidates": counts["candidates"],
        "exclusions": len(exclusions),
        "eligible_decisions": counts["structurally_eligible"],
        "conserved": counts["candidates"] + len(exclusions)
        == counts["structurally_eligible"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage": sha256_file(stage_path).model_dump(mode="json"),
            "decisions": sha256_file(decisions_path).model_dump(mode="json"),
            "review_input": sha256_file(review_input_path).model_dump(mode="json"),
            "candidate_ledger": sha256_file(candidate_ledger_path).model_dump(mode="json"),
            "exclusions": sha256_file(exclusions_path).model_dump(mode="json"),
            "po_lexicon": sha256_file(po_lexicon_path).model_dump(mode="json"),
            "pato_lexicon": sha256_file(pato_lexicon_path).model_dump(mode="json"),
            "flopo_registry": sha256_file(flopo_registry_path).model_dump(mode="json"),
            "combinations": sha256_file(combinations_path).model_dump(mode="json"),
        },
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if report_path.exists() and report_path.read_text(encoding="utf-8") != payload:
        raise FileExistsError(f"refusing to replace changed candidate report: {report_path}")
    if not report_path.exists():
        atomic_write_text(report_path, payload)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--review-input", type=Path, required=True)
    parser.add_argument("--candidate-ledger", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument(
        "--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv")
    )
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = prepare_one_of_review(
        stage_path=args.stage,
        decisions_path=args.decisions,
        review_input_path=args.review_input,
        candidate_ledger_path=args.candidate_ledger,
        exclusions_path=args.exclusions,
        report_path=args.report,
        po_lexicon_path=args.po_lexicon,
        pato_lexicon_path=args.pato_lexicon,
        flopo_registry_path=args.flopo_registry,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
