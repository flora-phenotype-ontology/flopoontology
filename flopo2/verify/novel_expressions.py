"""Build non-minting curator queues for reusable FLOPO expression candidates.

``novel_combinations`` is intentionally a PO--PATO compatibility review.  This module
instead starts from Phase 7's ``gate.flopo_signature`` and therefore keeps reusable
categorical conjunctions and disjunctions distinct from their component pairs.

Quantitative source phenotypes need an additional distinction.  FLOPO should contain the
reusable PO + PATO attribute trait (for example, ``pedicel length``), while an exact flora
range such as 5--10 mm belongs to the FAC annotation expression.  Consequently the main
queue groups numeric evidence under the gate's reusable ``EQ|PO|PATO`` signature.  The
optional FAC evidence sheet uses the canonical annotation-expression signature to retain
each distinct bound/unit expression without proposing it as a FLOPO class.

Neither output allocates or writes a FLOPO identifier.  Every candidate remains pending
until a curator explicitly reviews its ontology scope and definition.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flopo2.owl.annotation_class import OBO, canonical_signature_json, canonical_unit_iri


REVIEW_FIELDS = (
    "review_rank",
    "flopo_signature",
    "gate_signature_role",
    "expression_kind",
    "review_scope",
    "po_id",
    "po_label",
    "pato_id",
    "pato_label",
    "value_operator",
    "value_term_ids",
    "value_term_labels",
    "proposed_label",
    "numeric_handling",
    "numeric_evidence_count",
    "numeric_range_count",
    "numeric_ranges",
    "fac_expression_count",
    "fac_linked_evidence_count",
    "fac_iri_count",
    "phenotype_class_iris",
    "evidence_count",
    "gate_accepted_count",
    "gate_review_count",
    "gate_blocked_count",
    "composition_accepted_count",
    "composition_review_count",
    "source_collection_count",
    "accepted_source_collection_count",
    "source_collections",
    "evidence_by_source",
    "taxon_count",
    "source_document_count",
    "qualified_count",
    "reusability_evidence",
    "reusability_review_status",
    "example_1_source",
    "example_1",
    "example_2_source",
    "example_2",
    "example_3_source",
    "example_3",
    "ontology_action",
    "review_status",
    "reviewer",
    "review_date",
    "review_notes",
)

FAC_FIELDS = (
    "candidate_review_rank",
    "flopo_signature",
    "fac_expression_sha256",
    "fac_signature_status",
    "canonical_expression_json",
    "curation_scope",
    "po_id",
    "pato_id",
    "value_operator",
    "value_term_ids",
    "value_low",
    "value_high",
    "value_low_inclusive",
    "value_high_inclusive",
    "unit",
    "fac_iri_count",
    "phenotype_class_iris",
    "evidence_count",
    "source_collection_count",
    "source_collections",
    "taxon_count",
    "source_document_count",
    "example_1_source",
    "example_1",
    "example_2_source",
    "example_2",
    "ontology_action",
)


def _catalog(path: Path) -> tuple[dict[str, str], set[str]]:
    labels: dict[str, str] = {}
    attributes: set[str] = set()
    if not path.exists():
        return labels, attributes
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            identifier = str(row.get("id", "") or "").strip()
            if not identifier:
                continue
            labels[identifier] = str(row.get("label", "") or "")
            if "attribute_slim" in str(row.get("slim", "") or "").split("|"):
                attributes.add(identifier)
    return labels, attributes


def _qualified(assertion: dict[str, Any]) -> bool:
    return bool(
        (assertion.get("frequency_qualifier", "unspecified") or "unspecified")
        != "unspecified"
        or (assertion.get("epistemic_modality", "asserted") or "asserted") != "asserted"
        or (assertion.get("value_qualifier", "exact") or "exact") != "exact"
        or (assertion.get("degree_qualifier", "unmodified") or "unmodified")
        != "unmodified"
    )


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _composition_accepted(assertion: dict[str, Any]) -> bool:
    composition = assertion.get("composition")
    return not isinstance(composition, dict) or composition.get("status") == "accept"


def _representative_examples(
    examples: list[tuple[str, str]], limit: int
) -> list[tuple[str, str]]:
    """Prefer independent flora collections, then fill from remaining examples."""

    chosen: list[tuple[str, str]] = []
    used_sources: set[str] = set()
    for source, example in examples:
        if source not in used_sources:
            chosen.append((source, example))
            used_sources.add(source)
        if len(chosen) == limit:
            return chosen
    for item in examples:
        if item not in chosen:
            chosen.append(item)
        if len(chosen) == limit:
            break
    return chosen


def _decimal_display(value: object | None) -> str:
    if value is None:
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _numeric_range(assertion: dict[str, Any]) -> str:
    low = _decimal_display(assertion.get("value_low"))
    high = _decimal_display(assertion.get("value_high"))
    if not low and not high:
        return ""
    if low and high:
        if low == high:
            bounds = low
        else:
            left = "[" if assertion.get("value_low_inclusive", True) else "("
            right = "]" if assertion.get("value_high_inclusive", True) else ")"
            bounds = f"{left}{low}--{high}{right}"
    elif low:
        operator = ">=" if assertion.get("value_low_inclusive", True) else ">"
        bounds = f"{operator}{low}"
    else:
        operator = "<=" if assertion.get("value_high_inclusive", True) else "<"
        bounds = f"{operator}{high}"
    raw_unit = assertion.get("unit")
    try:
        unit = canonical_unit_iri(raw_unit).replace(OBO, "")
    except ValueError:
        unit = _clean(raw_unit)
    return " ".join(part for part in (bounds, unit) if part)


def _fallback_expression(assertion: dict[str, Any]) -> str:
    """Return a deterministic diagnostic key even for a gate-blocked invalid expression."""

    payload = {
        "signature_version": "fallback-1",
        "po_id": str(assertion.get("po_id", "") or ""),
        "pato_id": str(assertion.get("pato_id", "") or ""),
        "value_operator": str(assertion.get("value_operator", "atomic") or "atomic"),
        "value_terms": sorted(
            {
                str(value)
                for value in (
                    assertion.get("value_terms", [])
                    or assertion.get("value_term_ids", [])
                    or []
                )
            }
        ),
        "value_low": _decimal_display(assertion.get("value_low")) or None,
        "value_high": _decimal_display(assertion.get("value_high")) or None,
        "value_low_inclusive": assertion.get("value_low_inclusive", True),
        "value_high_inclusive": assertion.get("value_high_inclusive", True),
        "unit": _clean(assertion.get("unit")) or None,
        "bearer_context_qualities": sorted(
            {str(value) for value in assertion.get("bearer_context_qualities", []) or []}
        ),
        "season_operator": str(assertion.get("season_operator", "atomic") or "atomic"),
        "season_contexts": assertion.get("season_contexts", []) or [],
        "negated": bool(assertion.get("negated", False)),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fac_expression(assertion: dict[str, Any]) -> tuple[str, str, str]:
    """Return canonical/fallback JSON, its digest, and a diagnostic status."""

    try:
        signature = canonical_signature_json(assertion)
        status = "canonical"
    except (InvalidOperation, TypeError, ValueError):
        signature = _fallback_expression(assertion)
        status = "fallback_invalid_expression"
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return signature, digest, status


def _new_aggregate() -> dict[str, Any]:
    return {
        "po_ids": set(),
        "pato_ids": set(),
        "operators": set(),
        "value_terms": set(),
        "numeric_evidence_count": 0,
        "numeric_ranges": set(),
        "fac_expressions": set(),
        "fac_linked_evidence_count": 0,
        "fac_iris": set(),
        "evidence_count": 0,
        "gate_statuses": Counter(),
        "composition_accepted_count": 0,
        "composition_review_count": 0,
        "sources": Counter(),
        "accepted_sources": set(),
        "taxa": set(),
        "documents": set(),
        "qualified_count": 0,
        "examples": [],
    }


def _new_fac_aggregate(signature_json: str, status: str) -> dict[str, Any]:
    return {
        "canonical_expression_json": signature_json,
        "statuses": {status},
        "po_ids": set(),
        "pato_ids": set(),
        "operators": set(),
        "value_terms": set(),
        "value_lows": set(),
        "value_highs": set(),
        "value_low_inclusivities": set(),
        "value_high_inclusivities": set(),
        "units": set(),
        "numeric": False,
        "fac_iris": set(),
        "evidence_count": 0,
        "sources": Counter(),
        "taxa": set(),
        "documents": set(),
        "examples": [],
    }


def _join(values: set[str]) -> str:
    return "|".join(sorted(value for value in values if value))


def _expression_kind(operators: set[str], numeric_count: int) -> str:
    if numeric_count:
        return "numeric_trait"
    if operators == {"one_of"}:
        return "disjunctive_phenotype"
    if operators == {"all_of"}:
        return "conjunctive_phenotype"
    if operators in (set(), {"atomic"}):
        return "atomic_phenotype"
    return "mixed_expression_evidence"


def _review_scope(
    expression_kind: str, pato_ids: set[str], pato_attributes: set[str]
) -> str:
    if expression_kind == "numeric_trait" or (
        expression_kind == "atomic_phenotype"
        and pato_ids
        and pato_ids.issubset(pato_attributes)
    ):
        return "reusable_trait"
    if expression_kind in {"disjunctive_phenotype", "conjunctive_phenotype"}:
        return "reusable_composite_phenotype"
    return "reusable_phenotype"


def _reuse_evidence(aggregate: dict[str, Any]) -> str:
    evidence: list[str] = []
    if aggregate["evidence_count"] > 1:
        evidence.append("repeated_occurrence")
    if len(aggregate["sources"]) > 1:
        evidence.append("multiple_source_collections")
    if len(aggregate["documents"]) > 1:
        evidence.append("multiple_source_documents")
    if len(aggregate["taxa"]) > 1:
        evidence.append("multiple_taxa")
    # A single occurrence is only a statement about this corpus.  It is deliberately not
    # called "not reusable": ontological reusability is a curator judgment.
    return "|".join(evidence) if evidence else "single_corpus_occurrence_only"


def _proposed_label(
    expression_kind: str,
    po_ids: set[str],
    pato_ids: set[str],
    value_terms: set[str],
    po_labels: dict[str, str],
    pato_labels: dict[str, str],
) -> str:
    bearer = "/".join(po_labels.get(value, value) for value in sorted(po_ids))
    values = [pato_labels.get(value, value) for value in sorted(value_terms)]
    if values:
        connector = " or " if expression_kind == "disjunctive_phenotype" else " and "
        quality = connector.join(values)
    else:
        quality = "/".join(pato_labels.get(value, value) for value in sorted(pato_ids))
    return " ".join(part for part in (bearer, quality) if part)


def _write_tsv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_review_queues(
    input_path: Path,
    output_path: Path,
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    fac_output_path: Path | None = None,
) -> dict[str, Any]:
    """Aggregate all ``new_class_candidate`` assertions without minting FLOPO IDs."""

    po_labels, _ = _catalog(po_lexicon)
    pato_labels, pato_attributes = _catalog(pato_lexicon)
    aggregates: dict[str, dict[str, Any]] = {}
    fac_aggregates: dict[tuple[str, str], dict[str, Any]] = {}

    with Path(input_path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            source = str(record.get("source", "") or "")
            source_id = str(record.get("source_id", "") or "")
            taxon = str(record.get("taxon", "") or "")
            document = "|".join((source, source_id))
            for assertion_index, assertion in enumerate(record.get("assertions", []) or []):
                gate = assertion.get("gate") or {}
                if gate.get("flopo_status") != "new_class_candidate":
                    continue
                flopo_signature = str(gate.get("flopo_signature", "") or "").strip()
                if not flopo_signature:
                    raise ValueError(
                        "new_class_candidate has no gate.flopo_signature at "
                        f"line {line_number}, assertion {assertion_index}"
                    )

                aggregate = aggregates.setdefault(flopo_signature, _new_aggregate())
                po_id = str(assertion.get("po_id", "") or "")
                pato_id = str(assertion.get("pato_id", "") or "")
                operator = str(assertion.get("value_operator", "atomic") or "atomic")
                value_terms = {
                    str(value)
                    for value in (
                        assertion.get("value_terms", [])
                        or assertion.get("value_term_ids", [])
                        or []
                    )
                }
                numeric = (
                    assertion.get("value_low") is not None
                    or assertion.get("value_high") is not None
                )
                expression_json, expression_digest, expression_status = _fac_expression(assertion)
                fac_iri = str(assertion.get("phenotype_class_iri", "") or "").strip()
                gate_status = str(gate.get("status", "unknown") or "unknown")
                example = _clean(assertion.get("source_text"))
                example_key = (source, example)

                aggregate["po_ids"].add(po_id)
                aggregate["pato_ids"].add(pato_id)
                aggregate["operators"].add(operator)
                aggregate["value_terms"].update(value_terms)
                aggregate["evidence_count"] += 1
                aggregate["gate_statuses"][gate_status] += 1
                aggregate["fac_expressions"].add(expression_digest)
                if numeric:
                    aggregate["numeric_evidence_count"] += 1
                    aggregate["numeric_ranges"].add(_numeric_range(assertion))
                if fac_iri:
                    aggregate["fac_linked_evidence_count"] += 1
                    aggregate["fac_iris"].add(fac_iri)
                if _composition_accepted(assertion):
                    aggregate["composition_accepted_count"] += 1
                else:
                    aggregate["composition_review_count"] += 1
                if source:
                    aggregate["sources"][source] += 1
                    if gate_status == "accepted":
                        aggregate["accepted_sources"].add(source)
                if taxon:
                    aggregate["taxa"].add(taxon)
                if document.strip("|"):
                    aggregate["documents"].add(document)
                if _qualified(assertion):
                    aggregate["qualified_count"] += 1
                if example and example_key not in aggregate["examples"]:
                    aggregate["examples"].append(example_key)

                fac_key = (flopo_signature, expression_digest)
                fac = fac_aggregates.setdefault(
                    fac_key,
                    _new_fac_aggregate(expression_json, expression_status),
                )
                fac["statuses"].add(expression_status)
                fac["po_ids"].add(po_id)
                fac["pato_ids"].add(pato_id)
                fac["operators"].add(operator)
                fac["value_terms"].update(value_terms)
                fac["value_lows"].add(_decimal_display(assertion.get("value_low")))
                fac["value_highs"].add(_decimal_display(assertion.get("value_high")))
                fac["value_low_inclusivities"].add(
                    str(bool(assertion.get("value_low_inclusive", True))).lower()
                )
                fac["value_high_inclusivities"].add(
                    str(bool(assertion.get("value_high_inclusive", True))).lower()
                )
                fac["units"].add(_clean(assertion.get("unit")))
                fac["numeric"] = fac["numeric"] or numeric
                fac["evidence_count"] += 1
                if fac_iri:
                    fac["fac_iris"].add(fac_iri)
                if source:
                    fac["sources"][source] += 1
                if taxon:
                    fac["taxa"].add(taxon)
                if document.strip("|"):
                    fac["documents"].add(document)
                if example and example_key not in fac["examples"]:
                    fac["examples"].append(example_key)

    rows: list[dict[str, object]] = []
    for flopo_signature, aggregate in aggregates.items():
        expression_kind = _expression_kind(
            aggregate["operators"], aggregate["numeric_evidence_count"]
        )
        review_scope = _review_scope(expression_kind, aggregate["pato_ids"], pato_attributes)
        examples = _representative_examples(aggregate["examples"], 3)
        examples += [("", "")] * (3 - len(examples))
        sources = aggregate["sources"]
        source_names = sorted(sources)
        value_terms = aggregate["value_terms"]
        numeric_ranges = {value for value in aggregate["numeric_ranges"] if value}
        rows.append(
            {
                "review_rank": 0,
                "flopo_signature": flopo_signature,
                "gate_signature_role": (
                    "reusable_po_pato_trait"
                    if aggregate["numeric_evidence_count"]
                    else "full_reusable_expression"
                ),
                "expression_kind": expression_kind,
                "review_scope": review_scope,
                "po_id": _join(aggregate["po_ids"]),
                "po_label": _join(
                    {po_labels.get(value, "") for value in aggregate["po_ids"]}
                ),
                "pato_id": _join(aggregate["pato_ids"]),
                "pato_label": _join(
                    {pato_labels.get(value, "") for value in aggregate["pato_ids"]}
                ),
                "value_operator": _join(aggregate["operators"]),
                "value_term_ids": _join(value_terms),
                "value_term_labels": _join(
                    {pato_labels.get(value, "") for value in value_terms}
                ),
                "proposed_label": _proposed_label(
                    expression_kind,
                    aggregate["po_ids"],
                    aggregate["pato_ids"],
                    value_terms,
                    po_labels,
                    pato_labels,
                ),
                "numeric_handling": (
                    "review_reusable_trait;exact_bounds_and_units_fac_only"
                    if aggregate["numeric_evidence_count"]
                    else ""
                ),
                "numeric_evidence_count": aggregate["numeric_evidence_count"],
                "numeric_range_count": len(numeric_ranges),
                "numeric_ranges": "|".join(sorted(numeric_ranges)),
                "fac_expression_count": len(aggregate["fac_expressions"]),
                "fac_linked_evidence_count": aggregate["fac_linked_evidence_count"],
                "fac_iri_count": len(aggregate["fac_iris"]),
                "phenotype_class_iris": _join(aggregate["fac_iris"]),
                "evidence_count": aggregate["evidence_count"],
                "gate_accepted_count": aggregate["gate_statuses"]["accepted"],
                "gate_review_count": aggregate["gate_statuses"]["review"],
                "gate_blocked_count": aggregate["gate_statuses"]["blocked"],
                "composition_accepted_count": aggregate["composition_accepted_count"],
                "composition_review_count": aggregate["composition_review_count"],
                "source_collection_count": len(sources),
                "accepted_source_collection_count": len(aggregate["accepted_sources"]),
                "source_collections": "|".join(source_names),
                "evidence_by_source": "|".join(
                    f"{source}:{sources[source]}" for source in source_names
                ),
                "taxon_count": len(aggregate["taxa"]),
                "source_document_count": len(aggregate["documents"]),
                "qualified_count": aggregate["qualified_count"],
                "reusability_evidence": _reuse_evidence(aggregate),
                "reusability_review_status": "pending_curator_review",
                "example_1_source": examples[0][0],
                "example_1": examples[0][1],
                "example_2_source": examples[1][0],
                "example_2": examples[1][1],
                "example_3_source": examples[2][0],
                "example_3": examples[2][1],
                "ontology_action": "review_only_no_flopo_id_minted",
                "review_status": "pending",
                "reviewer": "",
                "review_date": "",
                "review_notes": "",
            }
        )

    rows.sort(
        key=lambda row: (
            -int(row["accepted_source_collection_count"]),
            -int(row["gate_accepted_count"]),
            -int(row["source_collection_count"]),
            -int(row["evidence_count"]),
            -int(row["taxon_count"]),
            -int(row["source_document_count"]),
            str(row["flopo_signature"]),
        )
    )
    ranks: dict[str, int] = {}
    for rank, row in enumerate(rows, start=1):
        row["review_rank"] = rank
        ranks[str(row["flopo_signature"])] = rank
    _write_tsv(output_path, REVIEW_FIELDS, rows)

    fac_rows: list[dict[str, object]] = []
    if fac_output_path is not None:
        for (flopo_signature, digest), aggregate in fac_aggregates.items():
            examples = _representative_examples(aggregate["examples"], 2)
            examples += [("", "")] * (2 - len(examples))
            source_names = sorted(aggregate["sources"])
            fac_rows.append(
                {
                    "candidate_review_rank": ranks[flopo_signature],
                    "flopo_signature": flopo_signature,
                    "fac_expression_sha256": digest,
                    "fac_signature_status": _join(aggregate["statuses"]),
                    "canonical_expression_json": aggregate["canonical_expression_json"],
                    "curation_scope": (
                        "fac_only_numeric_value"
                        if aggregate["numeric"]
                        else "supports_flopo_expression_review"
                    ),
                    "po_id": _join(aggregate["po_ids"]),
                    "pato_id": _join(aggregate["pato_ids"]),
                    "value_operator": _join(aggregate["operators"]),
                    "value_term_ids": _join(aggregate["value_terms"]),
                    "value_low": _join(aggregate["value_lows"]),
                    "value_high": _join(aggregate["value_highs"]),
                    "value_low_inclusive": _join(
                        aggregate["value_low_inclusivities"]
                    ),
                    "value_high_inclusive": _join(
                        aggregate["value_high_inclusivities"]
                    ),
                    "unit": _join(aggregate["units"]),
                    "fac_iri_count": len(aggregate["fac_iris"]),
                    "phenotype_class_iris": _join(aggregate["fac_iris"]),
                    "evidence_count": aggregate["evidence_count"],
                    "source_collection_count": len(aggregate["sources"]),
                    "source_collections": "|".join(source_names),
                    "taxon_count": len(aggregate["taxa"]),
                    "source_document_count": len(aggregate["documents"]),
                    "example_1_source": examples[0][0],
                    "example_1": examples[0][1],
                    "example_2_source": examples[1][0],
                    "example_2": examples[1][1],
                    "ontology_action": "fac_evidence_only_no_flopo_id_minted",
                }
            )
        fac_rows.sort(
            key=lambda row: (
                int(row["candidate_review_rank"]),
                str(row["fac_expression_sha256"]),
            )
        )
        _write_tsv(fac_output_path, FAC_FIELDS, fac_rows)

    return {
        "candidates": len(rows),
        "evidence": sum(int(row["evidence_count"]) for row in rows),
        "atomic_candidates": sum(row["expression_kind"] == "atomic_phenotype" for row in rows),
        "disjunctive_candidates": sum(
            row["expression_kind"] == "disjunctive_phenotype" for row in rows
        ),
        "conjunctive_candidates": sum(
            row["expression_kind"] == "conjunctive_phenotype" for row in rows
        ),
        "numeric_trait_candidates": sum(
            row["expression_kind"] == "numeric_trait" for row in rows
        ),
        "numeric_evidence": sum(int(row["numeric_evidence_count"]) for row in rows),
        "fac_expressions": len(fac_aggregates),
        "fac_linked_evidence": sum(
            int(row["fac_linked_evidence_count"]) for row in rows
        ),
        "out": str(output_path),
        "fac_out": str(fac_output_path) if fac_output_path is not None else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate full FLOPO expression candidates for curator review without minting IDs."
        )
    )
    parser.add_argument("input", type=Path, help="complete gated JSONL (annotated or unannotated)")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--fac-output",
        type=Path,
        help="optional expression-level FAC evidence TSV; numeric bounds are FAC-only",
    )
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    args = parser.parse_args()
    print(
        json.dumps(
            build_review_queues(
                args.input,
                args.output,
                args.po_lexicon,
                args.pato_lexicon,
                args.fac_output,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
