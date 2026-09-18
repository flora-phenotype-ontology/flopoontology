"""Materialize exact two-family consensus for typed phenotype-expression candidates.

With ``--tiebreak FILE --tiebreak-rule two_of_three`` only occurrences the campaign held are
reconsidered (see :mod:`flopo2.review.tiebreak`); occurrences already admitted by the campaign's
own consensus are counted as prior and not re-emitted.  Every admitted tie-break proposal still
passes the unchanged post-consensus ``check_assertion`` gate.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file
from flopo2.review.models import CampaignManifest, ConsensusDecision, Occurrence, ProposedSignature
from flopo2.review.report import campaign_report
from flopo2.review.tiebreak import TIEBREAK_RULES, TiebreakResolution, resolve_tiebreak
from flopo2.review.validation import load_validation_context
from flopo2.verify.gates import (
    check_assertion,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)


EXTRACTOR = "llm_consensus_phenotype_expression_v1"
SegmentKey = tuple[str, str, int, str]


def _segment_key(row: dict[str, Any] | Occurrence) -> SegmentKey:
    if isinstance(row, Occurrence):
        return row.source, row.source_id, row.source_segment_index, row.taxon
    return (
        str(row.get("source", "") or ""),
        str(row.get("source_id", "") or ""),
        int(row.get("source_segment_index", 0) or 0),
        str(row.get("taxon", "") or ""),
    )


def _write_immutable_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed materialization artifact: {path}")
    atomic_write_text(path, payload)


def _verify_candidate_report(
    path: Path,
    *,
    manifest: CampaignManifest,
    stage_path: Path,
) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema_version") not in {
        "flopo-one-of-candidate-report-v1",
        "flopo-expression-candidate-report-v1",
    }:
        raise ValueError("unsupported expression candidate report")
    if not report.get("conserved"):
        raise ValueError("expression candidate extraction is not conserved")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("expression candidate report lacks artifact bindings")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict) or not artifact.get("path"):
            raise ValueError(f"malformed candidate artifact binding: {name}")
        actual = sha256_file(Path(artifact["path"]))
        if (actual.sha256, actual.bytes) != (artifact.get("sha256"), artifact.get("bytes")):
            raise ValueError(f"expression candidate artifact hash mismatch: {name}")
    actual_stage = sha256_file(stage_path)
    stage = artifacts.get("stage", {})
    if (actual_stage.sha256, actual_stage.bytes) != (
        stage.get("sha256"),
        stage.get("bytes"),
    ):
        raise ValueError("materialization baseline does not match candidate extraction")
    review_input = artifacts.get("review_input", {})
    if (review_input.get("sha256"), review_input.get("bytes")) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("campaign input does not match candidate extraction")
    if int(report.get("candidates", -1)) != manifest.starting_occurrences:
        raise ValueError("candidate count does not match campaign occurrences")
    return report


def _held_row(
    occurrence: Occurrence,
    decision: ConsensusDecision,
    *,
    reason: str,
    details: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "campaign_id": decision.campaign_id,
        "item_id": decision.item_id,
        "occurrence_id": occurrence.occurrence_id,
        "source": occurrence.source,
        "source_id": occurrence.source_id,
        "source_segment_index": occurrence.source_segment_index,
        "taxon": occurrence.taxon,
        "expression_start": occurrence.span_start,
        "expression_end": occurrence.span_end,
        "expression_text": occurrence.surface_form,
        "reason": reason,
        "details": list(details),
        "consensus": decision.model_dump(mode="json", exclude_none=True),
        "candidate": (
            occurrence.phenotype_expression_candidate.model_dump(mode="json")
            if occurrence.phenotype_expression_candidate is not None
            else None
        ),
    }


def _assertion_for(occurrence: Occurrence, decision: ConsensusDecision) -> dict[str, Any]:
    candidate = occurrence.phenotype_expression_candidate
    if candidate is None:
        raise ValueError(f"{occurrence.occurrence_id}: missing phenotype expression candidate")
    proposed = ProposedSignature.model_validate_json(decision.normalized_signature or "")
    if proposed.kind != "annotation_expression" or proposed.expression != candidate.signature:
        raise ValueError(f"{occurrence.occurrence_id}: consensus expression signature drift")
    expression = candidate.signature
    admission_rule = next(
        (reason for reason in decision.reasons if reason in TIEBREAK_RULES.values()), None
    )
    logical = expression.value_operator in {"one_of", "all_of"}
    atomic = expression.value_operator == "atomic"
    if (
        not (logical or atomic)
        or (logical and len(expression.value_terms) < 2)
        or (atomic and len(expression.value_terms) > 1)
        or expression.negated
        or expression.developmental_stage_ids
        or expression.part_restrictions
        or expression.value_low is not None
        or expression.value_high is not None
        or expression.unit
    ):
        raise ValueError(f"{occurrence.occurrence_id}: unsupported expression materialization")
    assertion: dict[str, Any] = {
        "po_id": expression.bearer_id,
        "pato_id": expression.quality_id,
        "negated": False,
        "negation_scope": "",
        "organ": occurrence.organ,
        "source_text": candidate.expression_text,
        "source_start": candidate.expression_start,
        "source_end": candidate.expression_end,
        "value_text": candidate.expression_text,
        "value_operator": expression.value_operator,
        "value_terms": list(expression.value_terms),
        "part_restrictions": [],
        "bearer_context_qualities": [],
        "developmental_stage_contexts": [],
        "developmental_stage_operator": "atomic",
        "frequency_qualifier": "unspecified",
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": "",
        "season_contexts": [],
        "season_operator": "atomic",
        "normalization_status": "compositional",
        "mapping_provenance": [
            f"llm_consensus:{decision.campaign_id}",
            f"llm_review_item:{decision.item_id}",
            f"llm_signature:{decision.signature_sha256}",
            f"bearer_method:{candidate.bearer_method}",
            *((f"llm_review_rule:{admission_rule}",) if admission_rule else ()),
            *(
                (f"llm_reviewer:{reviewer}" for reviewer in decision.reviewer_ids)
                if admission_rule
                else ()
            ),
        ],
        "raw_quality_text": candidate.expression_text,
        "extractor": EXTRACTOR,
        "composition": {
            "status": "accept",
            "confidence": 1.0,
            "reasons": [admission_rule or "two_family_llm_exact_expression_consensus"],
        },
    }
    if candidate.bearer_start is not None:
        assertion.update(
            {
                "raw_entity_text": candidate.bearer_text,
                "bearer_start": candidate.bearer_start,
                "bearer_end": candidate.bearer_end,
            }
        )
    # Bind the canonical annotation-class IRI before the proposal can leave this module. Existing
    # atomic EQ combinations still retain their FLOPO mapping in the gate; the FAC is the stable
    # target for the complete source expression and never consumes a FLOPO identifier.
    ensure_annotation_class_iri(assertion)
    return assertion


def _statement_for(record: dict[str, Any], assertion: dict[str, Any]) -> tuple[dict, dict]:
    probe = dict(record)
    probe["assertions"] = [*(record.get("assertions", []) or []), assertion]
    upgraded = ensure_source_statements(probe)
    materialized = upgraded["assertions"][-1]
    statement_id = materialized.get("source_statement_id")
    matches = [
        row
        for row in upgraded.get("source_statements", []) or []
        if row.get("statement_id") == statement_id
    ]
    if len(matches) != 1:
        raise ValueError(f"source statement {statement_id!r} was not materialized exactly once")
    return materialized, matches[0]


def materialize_expression_consensus(
    *,
    manifest_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    candidate_report_path: Path,
    stage_path: Path,
    proposals_path: Path,
    held_path: Path,
    report_path: Path,
    combinations_path: Path = Path("config/valid_combinations.tsv"),
    registry_path: Path = Path("config/flopo_id_registry.tsv"),
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
    tiebreak_path: Path | None = None,
    tiebreak_rule: str | None = None,
    review_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Revalidate a complete campaign and emit one terminal outcome per occurrence."""

    if (tiebreak_path is None) != (tiebreak_rule is None):
        raise ValueError("--tiebreak and --tiebreak-rule must be supplied together")
    paths = (
        manifest_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
        candidate_report_path,
        stage_path,
        proposals_path,
        held_path,
        report_path,
        *((tiebreak_path,) if tiebreak_path is not None else ()),
        *review_paths,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("expression materialization inputs and outputs must be distinct")
    manifest = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    candidate_report = _verify_candidate_report(
        candidate_report_path, manifest=manifest, stage_path=stage_path
    )
    review_report = campaign_report(
        manifest,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
    )
    if not review_report["ok"]:
        raise ValueError("expression review campaign is incomplete or unconserved")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    decisions = {row.item_id: row for row in read_jsonl(consensus_path, ConsensusDecision)}
    tiebreak: TiebreakResolution | None = None
    if tiebreak_path is not None and tiebreak_rule is not None:
        tiebreak = resolve_tiebreak(
            tiebreak_path=tiebreak_path,
            rule=tiebreak_rule,
            manifest=manifest,
            context=context,
            base_decisions=decisions,
            review_paths=review_paths,
            admissible_dispositions=frozenset({"annotation_expression"}),
        )
    occurrences = sorted(context.occurrences.values(), key=lambda row: row.occurrence_id)
    actionable: defaultdict[SegmentKey, list[tuple[Occurrence, ConsensusDecision]]] = (
        defaultdict(list)
    )
    held: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for occurrence in occurrences:
        decision = decisions[occurrence.cluster_id]
        base_actionable = (
            decision.status == "llm_consensus"
            and decision.disposition == "annotation_expression"
            and decision.validation_passed
        )
        if tiebreak is not None:
            if base_actionable:
                counts["prior_consensus"] += 1
                continue
            if occurrence.cluster_id in tiebreak.admitted:
                decision = tiebreak.admitted[occurrence.cluster_id]
                base_actionable = True
        if base_actionable:
            _assertion_for(occurrence, decision)
            actionable[_segment_key(occurrence)].append((occurrence, decision))
            counts["consensus_candidates"] += 1
        else:
            held.append(
                _held_row(
                    occurrence,
                    decision,
                    reason="campaign_exception",
                    details=decision.reasons,
                )
            )
            counts["campaign_exception_held"] += 1

    combinations = load_combinations(combinations_path)
    registry = load_eq_registry(registry_path)
    signature_registry = load_signature_registry(registry_path)
    attribute_ids = load_pato_attribute_terms(pato_lexicon_path)
    pato_ids = load_catalog_ids(pato_lexicon_path)
    po_ids = load_catalog_ids(po_lexicon_path)
    flopo_ids = load_flopo_ids(registry_path)
    proposals: list[dict[str, Any]] = []
    matched: Counter[SegmentKey] = Counter()
    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _segment_key(record)
            rows = actionable.get(key, [])
            if not rows:
                continue
            matched[key] += 1
            if matched[key] != 1:
                raise ValueError(f"duplicate Stage segment identity at line {line_number}: {key}")
            text = str(record.get("text", "") or "")
            unresolved_ranges = Counter(
                (int(span.get("start", -1)), int(span.get("end", -1)))
                for span in record.get("unresolved_spans", []) or []
                if isinstance(span, dict)
            )
            used_clear_ranges: set[tuple[int, int]] = set()
            for occurrence, decision in sorted(rows, key=lambda row: row[0].span_start):
                candidate = occurrence.phenotype_expression_candidate
                assert candidate is not None
                if text[candidate.expression_start : candidate.expression_end] != candidate.expression_text:
                    raise ValueError(f"{occurrence.occurrence_id}: Stage expression drift")
                clear_ranges = set(candidate.clear_unresolved_spans)
                if not clear_ranges or any(unresolved_ranges[item] != 1 for item in clear_ranges):
                    raise ValueError(
                        f"{occurrence.occurrence_id}: unresolved clear allow-list drift"
                    )
                if overlap := used_clear_ranges.intersection(clear_ranges):
                    raise ValueError(
                        f"{occurrence.occurrence_id}: duplicate clear ranges {sorted(overlap)}"
                    )
                used_clear_ranges.update(clear_ranges)
                assertion = _assertion_for(occurrence, decision)
                gate = check_assertion(
                    text,
                    assertion,
                    combinations,
                    registry,
                    signature_registry,
                    attribute_ids,
                    taxon_provenance=record.get("taxon") if "taxon" in record else None,
                    pato_catalog_ids=pato_ids,
                    flopo_catalog_ids=flopo_ids,
                    po_catalog_ids=po_ids,
                )
                if gate.status != "accepted" or gate.po_pato_status != "allowed":
                    held.append(
                        _held_row(
                            occurrence,
                            decision,
                            reason="post_consensus_gate_held",
                            details=gate.reasons,
                        )
                    )
                    counts["post_consensus_gate_held"] += 1
                    continue
                assertion["gate"] = asdict(gate)
                assertion, source_statement = _statement_for(record, assertion)
                proposals.append(
                    {
                        "source": occurrence.source,
                        "source_id": occurrence.source_id,
                        "source_segment_index": occurrence.source_segment_index,
                        "taxon": occurrence.taxon,
                        "assertion": assertion,
                        "source_statement": source_statement,
                        "apply": {
                            "clear_unresolved_spans": [
                                {"start": start, "end": end}
                                for start, end in sorted(clear_ranges)
                            ]
                        },
                        "machine_review": {
                            "campaign_id": decision.campaign_id,
                            "item_id": decision.item_id,
                            "occurrence_id": occurrence.occurrence_id,
                            "status": decision.status,
                            "disposition": decision.disposition,
                            "signature_sha256": decision.signature_sha256,
                            "reviewer_ids": list(decision.reviewer_ids),
                            "validation_passed": decision.validation_passed,
                            **(
                                {"admission_rule": decision.reasons[0]}
                                if tiebreak is not None
                                else {}
                            ),
                        },
                    }
                )
                counts["proposals"] += 1
                counts["clear_targets"] += len(clear_ranges)
    unmatched = sorted(set(actionable) - set(matched))
    if unmatched:
        raise ValueError(f"reviewed expressions miss Stage segments: {unmatched[:3]}")
    proposals.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["assertion"]["source_start"],
        )
    )
    held.sort(key=lambda row: row["occurrence_id"])
    conserved_total = len(proposals) + len(held) + counts["prior_consensus"]
    if conserved_total != manifest.starting_occurrences:
        raise ValueError("expression materialization conservation failure")
    _write_immutable_rows(proposals_path, proposals)
    _write_immutable_rows(held_path, held)
    result = {
        "schema_version": "flopo-expression-consensus-materialization-v1",
        "campaign_id": manifest.campaign_id,
        "starting_occurrences": manifest.starting_occurrences,
        "proposals": len(proposals),
        "held": len(held),
        "conserved": conserved_total == manifest.starting_occurrences,
        "counts": dict(sorted(counts.items())),
        "candidate_report_sha256": sha256_file(candidate_report_path).sha256,
        "campaign_report": review_report,
        "candidate_extraction": {
            "candidates": candidate_report["candidates"],
            "exclusions": candidate_report["exclusions"],
        },
        "artifacts": {
            "stage": sha256_file(stage_path).model_dump(mode="json"),
            "proposals": sha256_file(proposals_path).model_dump(mode="json"),
            "held": sha256_file(held_path).model_dump(mode="json"),
        },
    }
    if tiebreak is not None:
        result["tiebreak"] = {
            **tiebreak.summary(),
            "tiebreak_file": sha256_file(tiebreak_path).model_dump(mode="json"),
            "reviews": [sha256_file(path).model_dump(mode="json") for path in review_paths],
            "held_items": {item: list(reasons) for item, reasons in sorted(tiebreak.held.items())},
        }
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if report_path.exists() and report_path.read_text(encoding="utf-8") != payload:
        raise FileExistsError(f"refusing to replace changed materialization report: {report_path}")
    if not report_path.exists():
        atomic_write_text(report_path, payload)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--consensus", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument("--tiebreak", type=Path, default=None)
    parser.add_argument("--tiebreak-rule", choices=sorted(TIEBREAK_RULES), default=None)
    parser.add_argument("--review", type=Path, action="append", default=[])
    args = parser.parse_args()
    result = materialize_expression_consensus(
        manifest_path=args.manifest,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        consensus_path=args.consensus,
        ledger_path=args.ledger,
        candidate_report_path=args.candidate_report,
        stage_path=args.stage,
        proposals_path=args.proposals,
        held_path=args.held,
        report_path=args.report,
        combinations_path=args.combinations,
        registry_path=args.registry,
        po_lexicon_path=args.po_lexicon,
        pato_lexicon_path=args.pato_lexicon,
        tiebreak_path=args.tiebreak,
        tiebreak_rule=args.tiebreak_rule,
        review_paths=tuple(args.review),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
