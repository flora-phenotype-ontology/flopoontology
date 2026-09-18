"""Inventory exact compound-colour occurrences lacking an active FLOPO EQ class.

The exact-colour recovery pass can only materialize an occurrence after the corresponding
PO--PATO pair has an active FLOPO class.  This module freezes the complementary class-extension
scope: lexically exact standardized colour compounds with a resolved bearer for which that EQ
class is absent.  It emits one source-bound occurrence row and one aggregate class-candidate row
per distinct pair, but it neither approves a combination nor allocates a FLOPO identifier.

The output is intended for independent machine review and adversarial class review.  Contextual
risks remain explicit, and every target compound has exactly one terminal outcome so the inventory
cannot silently drop difficult examples.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import canonical_json
from flopo2.verify.recover_contextual_exact_colour_compounds import (
    TARGET_REASON,
    _HARD_CONTEXT_EXCLUSIONS,
    _bearer_offsets,
)
from flopo2.verify.recover_exact_pato_compounds import (
    BearerResolver,
    _colour_modifier_start,
    _nearby_context_reason,
    _unsafe_bearer_scope,
    exact_compound_colour_lexicon,
    find_exact_compounds,
)
from flopo2.verify.recover_leaf_apex_expressions import _active_eq_pairs
from flopo2.verify.recover_qualitative_relations import _load_combinations, _overlaps


SCHEMA_VERSION = "flopo-exact-colour-eq-gap-inventory-v1"
EXTRACTOR = "exact_colour_eq_gap_inventory_v1"
BLOCKED_COMBINATION_STATUSES = frozenset({"blocked", "blocklisted", "invalid"})


def _catalog(path: Path) -> tuple[set[str], dict[str, str]]:
    identifiers: set[str] = set()
    labels: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            identifier = str(row.get("id", "") or "")
            if not identifier:
                continue
            identifiers.add(identifier)
            labels[identifier] = str(row.get("label", "") or "")
    return identifiers, labels


def _immutable_text(path: Path, payload: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed exact-colour EQ-gap artifact: {path}")
    atomic_write_text(path, payload)


def _clear_ranges(record: dict[str, Any], compound: Any) -> tuple[tuple[int, int], ...]:
    """Return the exact current unresolved components, or raise a diagnostic error."""

    text = str(record.get("text", "") or "")
    unresolved = record.get("unresolved_spans", []) or []
    ranges: list[tuple[int, int]] = []
    for index in compound.unresolved_indexes:
        if index < 0 or index >= len(unresolved):
            raise ValueError("invalid_clear_target_index")
        span = unresolved[index]
        try:
            start, end = int(span["start"]), int(span["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid_clear_target_offsets") from exc
        if (
            span.get("reason") != TARGET_REASON
            or not (compound.start <= start < end <= compound.end)
            or text[start:end] != str(span.get("surface_form", "") or "")
        ):
            raise ValueError("clear_target_not_exact_current_compound_span")
        ranges.append((start, end))
    if not ranges:
        raise ValueError("no_exact_current_clear_target")
    if len(ranges) != len(set(ranges)):
        raise ValueError("duplicate_clear_target")
    return tuple(sorted(ranges))


def _context(text: str, start: int, end: int, radius: int = 180) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return f"{text[left:start]}[[{text[start:end]}]]{text[end:right]}".strip()


def inventory_exact_colour_eq_gaps(
    *,
    stage_path: Path,
    occurrences_path: Path,
    classes_path: Path,
    exclusions_path: Path,
    report_path: Path,
    pato_obo: Path = Path("ont/quality.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Freeze missing exact-colour EQ pairs without approving or minting any class."""

    inputs = {
        stage_path.resolve(),
        pato_obo.resolve(),
        po_lexicon.resolve(),
        pato_lexicon.resolve(),
        flopo_registry.resolve(),
        combinations_path.resolve(),
    }
    outputs = {
        occurrences_path.resolve(),
        classes_path.resolve(),
        exclusions_path.resolve(),
        report_path.resolve(),
    }
    if len(outputs) != 4 or inputs & outputs:
        raise ValueError("all exact-colour EQ-gap inputs and outputs must be distinct")

    po_ids, po_labels = _catalog(po_lexicon)
    pato_ids, pato_labels = _catalog(pato_lexicon)
    combinations = _load_combinations(combinations_path)
    active_pairs = _active_eq_pairs(flopo_registry)
    bearers = BearerResolver(po_lexicon)
    lexicon = exact_compound_colour_lexicon(pato_obo)
    counts: Counter[str] = Counter()
    occurrences: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{stage_path}:{line_number}: record is not an object")
            text = str(record.get("text", "") or "")
            source = str(record.get("source", "") or "")
            source_id = str(record.get("source_id", "") or "")
            segment_index = int(record.get("source_segment_index", 0) or 0)
            for compound in find_exact_compounds(record, lexicon):
                counts["target_compounds"] += 1
                identity = (
                    source,
                    source_id,
                    segment_index,
                    compound.start,
                    compound.end,
                    compound.pato_id,
                )
                if identity in seen:
                    raise ValueError(f"duplicate exact compound at line {line_number}: {identity}")
                seen.add(identity)
                reason = ""
                details: dict[str, Any] = {}
                if compound.pato_id not in pato_ids:
                    reason = "unknown_live_pato_id"
                try:
                    clear_ranges = _clear_ranges(record, compound)
                except ValueError as exc:
                    clear_ranges = ()
                    reason = reason or str(exc)
                contextual = _nearby_context_reason(text, compound.start, compound.end)
                if not reason and contextual in _HARD_CONTEXT_EXCLUSIONS:
                    reason = contextual
                if not reason and _colour_modifier_start(text, compound.start) < compound.start:
                    reason = "unmodeled_colour_modifier"
                bearer = None
                if not reason:
                    bearer = bearers.resolve(
                        record, compound.start, compound.end, compound.pato_id
                    )
                    if not bearer.po_id:
                        reason = f"bearer_{bearer.method or 'missing'}"
                    elif bearer.po_id not in po_ids:
                        reason = "unknown_live_po_id"
                if not reason and bearer is not None:
                    pair = (bearer.po_id, compound.pato_id)
                    details = {
                        "po_id": pair[0],
                        "pato_id": pair[1],
                        "combination_status": combinations.get(pair, "novel"),
                    }
                    if pair in active_pairs:
                        reason = "active_existing_flopo_eq"
                    elif details["combination_status"] in BLOCKED_COMBINATION_STATUSES:
                        reason = "blocked_po_pato_combination"
                if not reason and any(
                    _overlaps(assertion, compound.start, compound.end)
                    for assertion in record.get("assertions", []) or []
                ):
                    reason = "overlapping_existing_assertion"

                if reason:
                    exclusions.append(
                        {
                            "source": source,
                            "source_id": source_id,
                            "source_segment_index": segment_index,
                            "taxon": str(record.get("taxon", "") or ""),
                            "start": compound.start,
                            "end": compound.end,
                            "surface_form": text[compound.start : compound.end],
                            "candidate_pato_id": compound.pato_id,
                            "reason": reason,
                            **details,
                        }
                    )
                    counts[f"excluded:{reason}"] += 1
                    continue

                assert bearer is not None and bearer.po_id
                pair = (bearer.po_id, compound.pato_id)
                risk_flags = ["missing_active_flopo_eq"]
                if contextual:
                    risk_flags.append(f"context_guard:{contextual}")
                unsafe_scope = _unsafe_bearer_scope(
                    text, compound.start, compound.end, bearer
                )
                if unsafe_scope:
                    risk_flags.append(f"bearer_scope:{unsafe_scope[0]}")
                if bearer.method == "organ_heading":
                    risk_flags.append("organ_heading_bearer")
                combination_status = combinations.get(pair, "novel")
                if combination_status != "allowed":
                    risk_flags.append(f"combination_status:{combination_status}")
                bearer_text, bearer_start, bearer_end = _bearer_offsets(
                    text, bearer.surface_form, compound.start
                )
                occurrence_id = stable_id("eqgapocc", (*identity, *pair))
                context = _context(text, compound.start, compound.end)
                occurrences.append(
                    {
                        "occurrence_id": occurrence_id,
                        "source": source,
                        "source_id": source_id,
                        "source_segment_index": segment_index,
                        "taxon": str(record.get("taxon", "") or ""),
                        "organ": str(record.get("organ", "") or ""),
                        "language": str(record.get("language", "") or ""),
                        "start": compound.start,
                        "end": compound.end,
                        "surface_form": text[compound.start : compound.end],
                        "lexical_form": compound.lexical_form,
                        "po_id": pair[0],
                        "po_label": po_labels.get(pair[0], ""),
                        "pato_id": pair[1],
                        "pato_label": pato_labels.get(pair[1], compound.pato_label),
                        "bearer_method": bearer.method,
                        "bearer_text": bearer_text,
                        "bearer_start": bearer_start,
                        "bearer_end": bearer_end,
                        "clear_unresolved_spans": [list(row) for row in clear_ranges],
                        "combination_status": combination_status,
                        "risk_flags": risk_flags,
                        "context": context,
                        "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
                        "extractor": EXTRACTOR,
                    }
                )
                counts["gap_occurrences"] += 1
                counts[f"gap_combination_status:{combination_status}"] += 1

    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for occurrence in occurrences:
        grouped[(occurrence["po_id"], occurrence["pato_id"])].append(occurrence)
    classes: list[dict[str, Any]] = []
    for pair, rows in sorted(grouped.items()):
        membership = sorted(row["occurrence_id"] for row in rows)
        examples = [
            {
                "occurrence_id": row["occurrence_id"],
                "source": row["source"],
                "source_id": row["source_id"],
                "taxon": row["taxon"],
                "context": row["context"],
                "risk_flags": row["risk_flags"],
            }
            for row in sorted(rows, key=lambda item: item["occurrence_id"])[:8]
        ]
        class_id = stable_id("eqgap", pair)
        statuses = sorted({row["combination_status"] for row in rows})
        classes.append(
            {
                "class_candidate_id": class_id,
                "po_id": pair[0],
                "po_label": po_labels.get(pair[0], ""),
                "pato_id": pair[1],
                "pato_label": pato_labels.get(pair[1], ""),
                "proposed_label": " ".join(
                    value
                    for value in (po_labels.get(pair[0], ""), pato_labels.get(pair[1], ""))
                    if value
                ),
                "proposed_signature": f"EQ|{pair[0]}|{pair[1]}",
                "combination_statuses": statuses,
                "occurrence_count": len(rows),
                "source_collection_count": len({row["source"] for row in rows}),
                "source_document_count": len(
                    {(row["source"], row["source_id"]) for row in rows}
                ),
                "taxon_count": len({row["taxon"] for row in rows if row["taxon"]}),
                "occurrence_membership_sha256": hashlib.sha256(
                    canonical_json(membership).encode()
                ).hexdigest(),
                "examples": examples,
                "review_status": "pending_machine_review",
            }
        )

    occurrences.sort(key=lambda row: row["occurrence_id"])
    exclusions.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["start"],
            row["end"],
        )
    )
    if len(occurrences) + len(exclusions) != counts["target_compounds"]:
        raise ValueError("exact-colour EQ-gap conservation failed")
    _immutable_text(
        occurrences_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in occurrences),
    )
    _immutable_text(
        classes_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in classes),
    )
    _immutable_text(
        exclusions_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in exclusions),
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "target_compounds": counts["target_compounds"],
        "gap_occurrences": len(occurrences),
        "gap_classes": len(classes),
        "exclusions": len(exclusions),
        "conserved": len(occurrences) + len(exclusions) == counts["target_compounds"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage": sha256_file(stage_path).model_dump(mode="json"),
            "pato_obo": sha256_file(pato_obo).model_dump(mode="json"),
            "po_lexicon": sha256_file(po_lexicon).model_dump(mode="json"),
            "pato_lexicon": sha256_file(pato_lexicon).model_dump(mode="json"),
            "flopo_registry": sha256_file(flopo_registry).model_dump(mode="json"),
            "combinations": sha256_file(combinations_path).model_dump(mode="json"),
            "occurrences": sha256_file(occurrences_path).model_dump(mode="json"),
            "classes": sha256_file(classes_path).model_dump(mode="json"),
            "exclusions": sha256_file(exclusions_path).model_dump(mode="json"),
        },
    }
    _immutable_text(report_path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = inventory_exact_colour_eq_gaps(
        stage_path=args.stage,
        occurrences_path=args.occurrences,
        classes_path=args.classes,
        exclusions_path=args.exclusions,
        report_path=args.report,
        pato_obo=args.pato_obo,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
        flopo_registry=args.flopo_registry,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
