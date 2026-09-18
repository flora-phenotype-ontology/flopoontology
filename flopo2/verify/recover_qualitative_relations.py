"""Prepare source-bound qualitative-continuum candidates for independent LLM review.

This pass consumes the corrected logical-operand decision table but trusts none of its rows by
itself.  Every proposed continuum is rebound to the frozen Stage 13 text, live ontology catalogs,
an allowed bearer/attribute combination, exact endpoint and connector offsets, an exact unresolved
span allow-list, and a segment with no overlapping existing assertion.  The output is a derived
review input; it does not mutate Stage 13 or admit an assertion.
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

from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import (
    QualitativeRelationCandidate,
    QualitativeRelationSignature,
)


EXTRACTOR = "qualitative_relation_candidate_v1"
TARGET_DECISION = "recover_qualitative_range"
TARGET_INTERPRETATION = "continuum"
TARGET_RULE = "R6_grounded_same_family_endpoints"
CONNECTORS = frozenset({"to", "à", "a", "-", "–", "—"})
SegmentKey = tuple[str, str, int]


def _segment_key(row: dict[str, Any]) -> SegmentKey:
    return (
        str(row.get("source", "")),
        str(row.get("source_id", "")),
        int(row.get("source_segment_index", 0) or 0),
    )


def _pipe(value: object) -> list[str]:
    return [item for item in str(value or "").split("|") if item]


def _load_ids(path: Path) -> tuple[set[str], set[str]]:
    identifiers: set[str] = set()
    attributes: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            identifier = str(row.get("id", "") or "")
            if not identifier:
                continue
            identifiers.add(identifier)
            if "attribute_slim" in (row.get("slim") or "").split("|"):
                attributes.add(identifier)
    return identifiers, attributes


def _load_flopo_ids(path: Path) -> set[str]:
    identifiers: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            iri = str(row.get("flopo_iri", "") or "")
            if "/FLOPO_" in iri:
                identifiers.add(iri.rsplit("/", 1)[-1])
    return identifiers


def _load_combinations(path: Path) -> dict[tuple[str, str], str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (str(row.get("po_id", "")), str(row.get("pato_id", ""))): str(
                row.get("status", "")
            )
            for row in csv.DictReader(handle, delimiter="\t")
        }


def _eligible_decisions(path: Path) -> tuple[dict[SegmentKey, list[dict]], Counter[str]]:
    grouped: defaultdict[SegmentKey, list[dict]] = defaultdict(list)
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            counts["decision_rows"] += 1
            if row.get("decision") != TARGET_DECISION:
                counts["not_qualitative_range"] += 1
                continue
            if row.get("operator_interpretation") != TARGET_INTERPRETATION:
                counts["non_continuum_interpretation"] += 1
                continue
            if row.get("range_rule") != TARGET_RULE:
                counts["non_high_confidence_rule"] += 1
                continue
            if row.get("modifiers") or row.get("negation_guard"):
                counts["modified_or_negated"] += 1
                continue
            if not row.get("bearer_po_id") or not row.get("attribute_pato_id") or not row.get("family"):
                counts["missing_bearer_or_attribute"] += 1
                continue
            if len(_pipe(row.get("operand_term_ids"))) != 2:
                counts["not_exactly_two_grounded_endpoints"] += 1
                continue
            uid = str(row.get("expression_uid", ""))
            if not uid or uid in seen:
                raise ValueError(f"duplicate or missing expression identity: {uid!r}")
            seen.add(uid)
            grouped[_segment_key(row)].append(row)
            counts["structurally_eligible"] += 1
    return dict(grouped), counts


def _expression_digest(row: dict, text: str) -> str:
    uid = "|".join(
        (
            str(row.get("source", "")),
            str(row.get("source_id", "")),
            str(int(row.get("source_segment_index", 0) or 0)),
            str(int(row.get("expression_start", -1))),
            str(int(row.get("expression_end", -1))),
        )
    )
    return hashlib.sha256(f"{uid}|{text}".encode()).hexdigest()[:16]


def _find_surface(expression: str, surface: str, start: int) -> tuple[int, int] | None:
    offset = expression.find(surface, start)
    if offset >= 0:
        return offset, offset + len(surface)
    lowered = expression.casefold()
    needle = surface.casefold()
    offset = lowered.find(needle, start)
    if offset >= 0 and len(needle) == len(surface):
        return offset, offset + len(surface)
    return None


def _core_within_surface(surface: str, normalized: str) -> tuple[int, int] | None:
    normalized = re.sub(r"\s+", " ", normalized.strip()).strip(".,;:")
    if not normalized:
        return None
    pattern = re.compile(
        re.escape(normalized).replace(r"\ ", r"\s+") + r"(?=[\s.,;:]*$)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(surface))
    if not matches:
        return None
    match = matches[-1]
    return match.start(), match.end()


def _locate_relation(record: dict, row: dict) -> tuple[dict[str, Any] | None, str]:
    text = str(record.get("text", "") or "")
    try:
        start = int(row["expression_start"])
        end = int(row["expression_end"])
    except (KeyError, TypeError, ValueError):
        return None, "invalid_expression_offsets"
    expression = str(row.get("expression_text", "") or "")
    if start < 0 or end <= start or end > len(text) or text[start:end] != expression:
        return None, "expression_not_verbatim_in_stage13"
    if row.get("expression_digest") != _expression_digest(row, expression):
        return None, "expression_digest_mismatch"

    surfaces = _pipe(row.get("operand_surfaces"))
    normalized = _pipe(row.get("operand_normalized"))
    term_ids = _pipe(row.get("operand_term_ids"))
    if not (len(surfaces) == len(normalized) == len(term_ids) == 2):
        return None, "operand_accounting_mismatch"
    located: list[tuple[int, int, str]] = []
    cursor = 0
    for surface, core in zip(surfaces, normalized, strict=True):
        match = _find_surface(expression, surface, cursor)
        if match is None:
            return None, "operand_surface_not_verbatim"
        local_start, local_end = match
        core_span = _core_within_surface(expression[local_start:local_end], core)
        if core_span is None:
            return None, "operand_core_not_verbatim"
        core_start = start + local_start + core_span[0]
        core_end = start + local_start + core_span[1]
        located.append((core_start, core_end, text[core_start:core_end]))
        cursor = local_end
    if located[0][1] > located[1][0]:
        return None, "overlapping_endpoints"

    bridge = text[located[0][1]:located[1][0]]
    connector_match = re.search(r"\S(?:.*\S)?", bridge, re.DOTALL)
    if connector_match is None:
        return None, "missing_connector"
    connector_text = connector_match.group(0)
    connector_start = located[0][1] + connector_match.start()
    connector_end = located[0][1] + connector_match.end()
    if re.sub(r"\s+", " ", connector_text.casefold()).strip() not in CONNECTORS:
        return None, "unsupported_connector"

    bearer_text = str(row.get("bearer_surface", "") or "")
    bearer_start = bearer_end = None
    if bearer_text:
        prefix = text[start:located[0][0]]
        bearer_match = _find_surface(prefix, bearer_text, 0)
        if bearer_match is not None:
            bearer_start = start + bearer_match[0]
            bearer_end = start + bearer_match[1]
            bearer_text = text[bearer_start:bearer_end]
        else:
            bearer_text = ""

    return {
        "signature": {
            "bearer_id": row["bearer_po_id"],
            "attribute_id": row["attribute_pato_id"],
            "interpretation": TARGET_INTERPRETATION,
            "from_value": term_ids[0],
            "to_value": term_ids[1],
        },
        "bearer_method": str(row.get("bearer_method", "") or "unspecified"),
        "bearer_text": bearer_text,
        "bearer_start": bearer_start,
        "bearer_end": bearer_end,
        "expression_start": start,
        "expression_end": end,
        "expression_text": expression,
        "from_text": located[0][2],
        "from_start": located[0][0],
        "from_end": located[0][1],
        "connector_text": connector_text,
        "connector_start": connector_start,
        "connector_end": connector_end,
        "to_text": located[1][2],
        "to_start": located[1][0],
        "to_end": located[1][1],
    }, ""


def _overlaps(assertion: dict, start: int, end: int) -> bool:
    try:
        other_start = int(assertion.get("source_start", -1))
        other_end = int(assertion.get("source_end", -1))
    except (TypeError, ValueError):
        return False
    return other_start < end and start < other_end


def _clear_targets(record: dict, candidate: dict) -> tuple[tuple[tuple[int, int], ...], str]:
    endpoint_ids = {
        candidate["signature"]["from_value"],
        candidate["signature"]["to_value"],
    }
    endpoint_ranges = (
        (candidate["from_start"], candidate["from_end"]),
        (candidate["to_start"], candidate["to_end"]),
    )
    counts: Counter[tuple[int, int]] = Counter()
    contained: list[dict] = []
    for span in record.get("unresolved_spans", []) or []:
        span_start = int(span.get("start", -1))
        span_end = int(span.get("end", -1))
        if candidate["expression_start"] <= span_start and span_end <= candidate["expression_end"]:
            contained.append(span)
        if (
            str(span.get("candidate_pato_id", "")) in endpoint_ids
            and any(left <= span_start and span_end <= right for left, right in endpoint_ranges)
        ):
            counts[(span_start, span_end)] += 1
    if any(count != 1 for count in counts.values()):
        return (), "ambiguous_clear_target"
    targets = tuple(sorted(counts))
    if not targets:
        return (), "no_exact_endpoint_clear_target"
    target_set = set(targets)
    unrelated = [
        span
        for span in contained
        if (int(span.get("start", -1)), int(span.get("end", -1))) not in target_set
    ]
    if unrelated:
        return (), "unreviewed_contained_unresolved_span"
    return targets, ""


def prepare_review_input(
    *,
    stage13_path: Path,
    decisions_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    exclusions_path: Path,
    report_path: Path,
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Prepare immutable candidate records while preserving a disposition for every input row."""

    inputs = {Path(stage13_path).resolve(), Path(decisions_path).resolve()}
    outputs = {
        Path(review_input_path).resolve(),
        Path(candidate_ledger_path).resolve(),
        Path(exclusions_path).resolve(),
        Path(report_path).resolve(),
    }
    if len(outputs) != 4 or inputs & outputs:
        raise ValueError("all qualitative recovery inputs and outputs must be distinct paths")

    grouped, counts = _eligible_decisions(Path(decisions_path))
    po_ids, _ = _load_ids(Path(po_lexicon))
    pato_ids, attribute_ids = _load_ids(Path(pato_lexicon))
    flopo_ids = _load_flopo_ids(Path(flopo_registry))
    combinations = _load_combinations(Path(combinations_path))
    wanted = set(grouped)
    found: set[SegmentKey] = set()
    review_records: list[dict] = []
    ledger: list[dict] = []
    exclusions: list[dict] = []

    with Path(stage13_path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _segment_key(record)
            if key not in wanted:
                continue
            if key in found:
                raise ValueError(f"duplicate Stage 13 segment identity: {key}")
            found.add(key)
            synthetic_spans: list[dict] = []
            for row in grouped[key]:
                candidate_data, reason = _locate_relation(record, row)
                if not reason and candidate_data is not None:
                    raw_signature = candidate_data["signature"]
                    if raw_signature["from_value"] == raw_signature["to_value"]:
                        reason = "identical_endpoints"
                    else:
                        try:
                            signature = QualitativeRelationSignature.model_validate(raw_signature)
                        except ValueError:
                            reason = "invalid_candidate_signature"
                if not reason and candidate_data is not None:
                    identifiers = (signature.bearer_id, signature.attribute_id)
                    if signature.bearer_id.startswith("PO_") and signature.bearer_id not in po_ids:
                        reason = "unknown_bearer_id"
                    elif (
                        signature.bearer_id.startswith("FLOPO_")
                        and signature.bearer_id not in flopo_ids
                    ):
                        reason = "unknown_bearer_id"
                    elif signature.attribute_id not in pato_ids:
                        reason = "unknown_attribute_id"
                    elif signature.attribute_id not in attribute_ids:
                        reason = "top_level_not_pato_attribute"
                    elif any(
                        value.startswith("PATO_") and value not in pato_ids
                        or value.startswith("FLOPO_") and value not in flopo_ids
                        for value in (signature.from_value, signature.to_value)
                    ):
                        reason = "unknown_endpoint_id"
                    elif combinations.get(identifiers, "novel") != "allowed":
                        reason = "bearer_attribute_combination_not_allowed"
                if not reason and candidate_data is not None:
                    clear_targets, reason = _clear_targets(record, candidate_data)
                    candidate_data["clear_unresolved_spans"] = clear_targets
                if not reason and candidate_data is not None:
                    if any(
                        _overlaps(
                            assertion,
                            candidate_data["expression_start"],
                            candidate_data["expression_end"],
                        )
                        for assertion in record.get("assertions", []) or []
                    ):
                        reason = "overlapping_existing_assertion"
                if reason or candidate_data is None:
                    exclusions.append(
                        {
                            "expression_uid": row.get("expression_uid", ""),
                            "source": key[0],
                            "source_id": key[1],
                            "source_segment_index": key[2],
                            "expression_start": row.get("expression_start", ""),
                            "expression_end": row.get("expression_end", ""),
                            "expression_text": row.get("expression_text", ""),
                            "reason": reason or "candidate_construction_failed",
                        }
                    )
                    counts[f"excluded:{reason or 'candidate_construction_failed'}"] += 1
                    continue
                candidate = QualitativeRelationCandidate.model_validate(candidate_data)
                candidate_id = stable_id(
                    "qualrel",
                    (
                        *key,
                        candidate.expression_start,
                        candidate.expression_end,
                        candidate.signature.model_dump(mode="json"),
                    ),
                )
                synthetic_spans.append(
                    {
                        "start": candidate.expression_start,
                        "end": candidate.expression_end,
                        "surface_form": candidate.expression_text,
                        "reason": "qualitative_value_relation_candidate",
                        "candidate_pato_id": candidate.signature.attribute_id,
                        "pending_bearer": candidate.signature.bearer_id,
                        "extractor": EXTRACTOR,
                        "candidate_id": candidate_id,
                        "qualitative_relation_candidate": candidate.model_dump(mode="json"),
                    }
                )
                ledger.append(
                    {
                        "candidate_id": candidate_id,
                        "expression_uid": row.get("expression_uid", ""),
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "family": row.get("family", ""),
                        "range_rule": row.get("range_rule", ""),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                counts["candidates"] += 1
                counts[f"candidate_family:{row.get('family', '')}"] += 1
                counts["clear_targets"] += len(candidate.clear_unresolved_spans)
            if synthetic_spans:
                synthetic_spans.sort(key=lambda span: (span["start"], span["end"], span["candidate_id"]))
                review_records.append(
                    {
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "language": record.get("language", ""),
                        "char_start": record.get("char_start", 0),
                        "char_end": record.get("char_end", len(record.get("text", ""))),
                        "text": record.get("text", ""),
                        "unresolved_spans": synthetic_spans,
                    }
                )
    for missing in sorted(wanted - found):
        for row in grouped[missing]:
            exclusions.append(
                {
                    "expression_uid": row.get("expression_uid", ""),
                    "source": missing[0],
                    "source_id": missing[1],
                    "source_segment_index": missing[2],
                    "expression_start": row.get("expression_start", ""),
                    "expression_end": row.get("expression_end", ""),
                    "expression_text": row.get("expression_text", ""),
                    "reason": "segment_absent_from_stage13",
                }
            )
            counts["excluded:segment_absent_from_stage13"] += 1

    if counts["candidates"] + len(exclusions) != counts["structurally_eligible"]:
        raise ValueError("qualitative candidate conservation failed")
    for path in (review_input_path, candidate_ledger_path, exclusions_path, report_path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        Path(review_input_path),
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in review_records),
    )
    atomic_write_text(
        Path(candidate_ledger_path),
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ledger),
    )
    atomic_write_text(
        Path(exclusions_path),
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in exclusions),
    )
    report = {
        "schema_version": "flopo-qualitative-candidate-report-v1",
        "input": str(stage13_path),
        "decisions": str(decisions_path),
        "review_records": len(review_records),
        "candidates": len(ledger),
        "exclusions": len(exclusions),
        "conserved": len(ledger) + len(exclusions) == counts["structurally_eligible"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage13": sha256_file(Path(stage13_path)).model_dump(mode="json"),
            "decisions": sha256_file(Path(decisions_path)).model_dump(mode="json"),
            "review_input": sha256_file(Path(review_input_path)).model_dump(mode="json"),
            "candidate_ledger": sha256_file(Path(candidate_ledger_path)).model_dump(mode="json"),
            "exclusions": sha256_file(Path(exclusions_path)).model_dump(mode="json"),
        },
    }
    atomic_write_text(Path(report_path), json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage13", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--review-input", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = prepare_review_input(
        stage13_path=args.stage13,
        decisions_path=args.decisions,
        review_input_path=args.review_input,
        candidate_ledger_path=args.ledger,
        exclusions_path=args.exclusions,
        report_path=args.report,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
        flopo_registry=args.flopo_registry,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
