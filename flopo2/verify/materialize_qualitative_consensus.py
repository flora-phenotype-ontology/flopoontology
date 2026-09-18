"""Turn exact two-family qualitative-relation consensus into Stage 14 proposals.

The LLM outputs remain proposals.  By default this bridge accepts only a complete, conserved
campaign whose two independent reviewers agreed on the runner's exact immutable signature.  An
explicit recovery mode may also accept a conserved campaign with missing reviews, provided every
incompletely reviewed item is terminally held and therefore cannot materialize.  It then rebinds
each accepted occurrence to the frozen Stage 13 source, reruns deterministic ontology gates, and
emits append-only proposals plus a terminal held row for every occurrence not eligible for
application.  No FAC or FLOPO class is minted by this module.

With ``--tiebreak FILE --tiebreak-rule two_of_three`` only occurrences the campaign held are
reconsidered (see :mod:`flopo2.review.tiebreak`); occurrences the campaign's own consensus already
admitted are counted as ``prior_consensus`` and not re-emitted.  Every tie-break admission still
passes the unchanged post-consensus gates, and its provenance names all three machine reviewers
and the admission rule.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file
from flopo2.review.models import (
    CampaignManifest,
    ConsensusDecision,
    Occurrence,
    ProposedSignature,
)
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


EXTRACTOR = "llm_consensus_qualitative_relation_v1"
SegmentKey = tuple[str, str, int, str]


def _segment_key(row: dict[str, Any] | Occurrence) -> SegmentKey:
    if isinstance(row, Occurrence):
        return (row.source, row.source_id, row.source_segment_index, row.taxon)
    return (
        str(row.get("source", "")),
        str(row.get("source_id", "")),
        int(row.get("source_segment_index", 0) or 0),
        str(row.get("taxon", "")),
    )


def _verify_candidate_report(
    path: Path,
    *,
    manifest: CampaignManifest,
    stage13_path: Path,
) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid qualitative candidate report {path}: {exc}") from exc
    if report.get("schema_version") != "flopo-qualitative-candidate-report-v1":
        raise ValueError("unsupported qualitative candidate report")
    if not report.get("conserved"):
        raise ValueError("qualitative candidate extraction is not conserved")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("qualitative candidate report predates artifact hash binding")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict) or not artifact.get("path"):
            raise ValueError(f"malformed candidate artifact binding: {name}")
        actual = sha256_file(Path(artifact["path"]))
        if (actual.sha256, actual.bytes) != (artifact.get("sha256"), artifact.get("bytes")):
            raise ValueError(f"qualitative candidate artifact hash mismatch: {name}")
    stage = artifacts.get("stage13", {})
    actual_stage = sha256_file(stage13_path)
    if (actual_stage.sha256, actual_stage.bytes) != (
        stage.get("sha256"),
        stage.get("bytes"),
    ):
        raise ValueError("Stage 13 does not match the candidate extraction baseline")
    review_input = artifacts.get("review_input", {})
    if (review_input.get("sha256"), review_input.get("bytes")) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("campaign input does not match the candidate extraction output")
    if int(report.get("candidates", -1)) != manifest.starting_occurrences:
        raise ValueError("candidate count does not match campaign occurrence count")
    return report


def _write_immutable_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed derived artifact: {path}")
    atomic_write_text(path, payload)


def _write_immutable_report(path: Path, report: dict[str, Any]) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed materialization report: {path}")
    atomic_write_text(path, payload)


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
            occurrence.qualitative_relation_candidate.model_dump(mode="json")
            if occurrence.qualitative_relation_candidate is not None
            else None
        ),
    }


def _assertion_for(
    occurrence: Occurrence,
    decision: ConsensusDecision,
) -> dict[str, Any]:
    candidate = occurrence.qualitative_relation_candidate
    if candidate is None:
        raise ValueError(f"{occurrence.occurrence_id}: missing qualitative candidate")
    signature = ProposedSignature.model_validate_json(decision.normalized_signature or "")
    if (
        signature.kind != "structured_qualitative_relation"
        or signature.qualitative_relation != candidate.signature
    ):
        raise ValueError(f"{occurrence.occurrence_id}: consensus signature drift")
    admission_rule = next(
        (reason for reason in decision.reasons if reason in TIEBREAK_RULES.values()), None
    )
    relation = {
        "interpretation": candidate.signature.interpretation,
        "from_value": candidate.signature.from_value,
        "to_value": candidate.signature.to_value,
        "from_text": candidate.from_text,
        "from_start": candidate.from_start,
        "from_end": candidate.from_end,
        "connector_text": candidate.connector_text,
        "connector_start": candidate.connector_start,
        "connector_end": candidate.connector_end,
        "to_text": candidate.to_text,
        "to_start": candidate.to_start,
        "to_end": candidate.to_end,
    }
    assertion: dict[str, Any] = {
        "po_id": candidate.signature.bearer_id,
        "pato_id": candidate.signature.attribute_id,
        "raw_quality_text": candidate.expression_text,
        "source_text": candidate.expression_text,
        "source_start": candidate.expression_start,
        "source_end": candidate.expression_end,
        "value_operator": "atomic",
        "value_terms": [],
        "qualitative_value_relation": relation,
        "negated": False,
        "extractor": EXTRACTOR,
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
        "composition": {
            "status": "accept",
            "confidence": 1.0,
            "reasons": [admission_rule or "two_family_llm_exact_signature_consensus"],
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
    return assertion


def _statement_for(record: dict[str, Any], assertion: dict[str, Any]) -> tuple[dict, dict]:
    probe = dict(record)
    existing = list(record.get("assertions", []) or [])
    probe["assertions"] = [*existing, assertion]
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


def materialize_qualitative_consensus(
    *,
    manifest_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    candidate_report_path: Path,
    stage13_path: Path,
    proposals_path: Path,
    held_path: Path,
    report_path: Path,
    combinations_path: Path = Path("config/valid_combinations.tsv"),
    registry_path: Path = Path("config/flopo_id_registry.tsv"),
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
    allow_incomplete_review: bool = False,
    tiebreak_path: Path | None = None,
    tiebreak_rule: str | None = None,
    review_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Revalidate a complete campaign and emit one terminal outcome per occurrence."""

    if (tiebreak_path is None) != (tiebreak_rule is None):
        raise ValueError("--tiebreak and --tiebreak-rule must be supplied together")
    paths = [
        manifest_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
        candidate_report_path,
        stage13_path,
        proposals_path,
        held_path,
        report_path,
        *((tiebreak_path,) if tiebreak_path is not None else ()),
        *review_paths,
    ]
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("materialization inputs and outputs must be distinct paths")
    manifest = CampaignManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    candidate_report = _verify_candidate_report(
        candidate_report_path,
        manifest=manifest,
        stage13_path=stage13_path,
    )
    review_report = campaign_report(
        manifest,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
    )
    decisions = list(read_jsonl(consensus_path, ConsensusDecision))
    safe_incomplete_review = (
        allow_incomplete_review
        and review_report["integrity_ok"]
        and review_report["conservation"]["complete"]
        and all(
            len(row.reviewer_ids) == 2
            or (
                len(row.reviewer_ids) < 2
                and row.status == "held"
                and "missing_independent_review" in row.reasons
                and not row.validation_passed
            )
            for row in decisions
        )
    )
    if not review_report["ok"] and not safe_incomplete_review:
        raise ValueError("machine-review campaign is incomplete or fails conservation")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    decision_index = {row.item_id: row for row in decisions}
    tiebreak: TiebreakResolution | None = None
    if tiebreak_path is not None and tiebreak_rule is not None:
        tiebreak = resolve_tiebreak(
            tiebreak_path=tiebreak_path,
            rule=tiebreak_rule,
            manifest=manifest,
            context=context,
            base_decisions=decision_index,
            review_paths=review_paths,
            admissible_dispositions=frozenset({"structured_qualitative_relation"}),
        )
    occurrences = sorted(context.occurrences.values(), key=lambda row: row.occurrence_id)
    actionable: defaultdict[SegmentKey, list[tuple[Occurrence, ConsensusDecision]]] = (
        defaultdict(list)
    )
    held: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for occurrence in occurrences:
        decision = decision_index[occurrence.cluster_id]
        base_actionable = (
            decision.status == "llm_consensus"
            and decision.disposition == "structured_qualitative_relation"
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
            # Parse and compare now, before touching the Stage 13 stream.
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

    combos = load_combinations(combinations_path)
    registry = load_eq_registry(registry_path)
    signature_registry = load_signature_registry(registry_path)
    attribute_ids = load_pato_attribute_terms(pato_lexicon_path)
    pato_ids = load_catalog_ids(pato_lexicon_path)
    po_ids = load_catalog_ids(po_lexicon_path)
    flopo_ids = load_flopo_ids(registry_path)
    proposals: list[dict[str, Any]] = []
    matched: Counter[SegmentKey] = Counter()

    with stage13_path.open(encoding="utf-8") as handle:
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
                raise ValueError(f"duplicate Stage 13 segment identity at line {line_number}: {key}")
            text = str(record.get("text", "") or "")
            used_clear_ranges: set[tuple[int, int]] = set()
            unresolved_ranges = Counter(
                (int(span.get("start", -1)), int(span.get("end", -1)))
                for span in record.get("unresolved_spans", []) or []
            )
            for occurrence, decision in sorted(rows, key=lambda row: row[0].span_start):
                candidate = occurrence.qualitative_relation_candidate
                assert candidate is not None
                if (
                    text[candidate.expression_start : candidate.expression_end]
                    != candidate.expression_text
                ):
                    raise ValueError(f"{occurrence.occurrence_id}: Stage 13 expression drift")
                clear_ranges = set(candidate.clear_unresolved_spans)
                if not clear_ranges or any(unresolved_ranges[item] != 1 for item in clear_ranges):
                    raise ValueError(
                        f"{occurrence.occurrence_id}: unresolved clear allow-list drift"
                    )
                overlap = used_clear_ranges.intersection(clear_ranges)
                if overlap:
                    raise ValueError(
                        f"{occurrence.occurrence_id}: duplicate clear ranges {sorted(overlap)}"
                    )
                used_clear_ranges.update(clear_ranges)
                assertion = _assertion_for(occurrence, decision)
                gate = check_assertion(
                    text,
                    assertion,
                    combos,
                    registry,
                    signature_registry,
                    attribute_ids,
                    taxon_provenance=record.get("taxon") if "taxon" in record else None,
                    pato_catalog_ids=pato_ids,
                    flopo_catalog_ids=flopo_ids,
                    po_catalog_ids=po_ids,
                )
                if gate.status != "accepted" or gate.flopo_status != "structured_annotation_only":
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

    missing_segments = [key for key in actionable if matched[key] != 1]
    if missing_segments:
        raise ValueError(
            f"{len(missing_segments)} actionable segment(s) were not matched exactly once: "
            f"{missing_segments[:3]}"
        )
    proposals.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["assertion"]["source_start"],
            row["machine_review"]["occurrence_id"],
        )
    )
    held.sort(key=lambda row: row["occurrence_id"])
    conserved_total = len(proposals) + len(held) + counts["prior_consensus"]
    if conserved_total != manifest.starting_occurrences:
        raise ValueError("post-consensus materialization conservation failed")
    _write_immutable_rows(proposals_path, proposals)
    _write_immutable_rows(held_path, held)
    result = {
        "schema_version": "flopo-qualitative-consensus-materialization-v1",
        "campaign_id": manifest.campaign_id,
        "starting_occurrences": manifest.starting_occurrences,
        "proposals": len(proposals),
        "held": len(held),
        "conserved": conserved_total == manifest.starting_occurrences,
        "review_mode": (
            "complete" if review_report["ok"] else "conserved_partial_with_terminal_holds"
        ),
        "counts": dict(sorted(counts.items())),
        "candidate_report_sha256": sha256_file(candidate_report_path).sha256,
        "campaign_report": review_report,
        "candidate_extraction": {
            "candidates": candidate_report["candidates"],
            "exclusions": candidate_report["exclusions"],
        },
        "artifacts": {
            "proposals": sha256_file(proposals_path).model_dump(mode="json"),
            "held": sha256_file(held_path).model_dump(mode="json"),
            "stage13": sha256_file(stage13_path).model_dump(mode="json"),
        },
    }
    if tiebreak is not None:
        assert tiebreak_path is not None
        result["tiebreak"] = {
            **tiebreak.summary(),
            "tiebreak_file": sha256_file(tiebreak_path).model_dump(mode="json"),
            "reviews": [sha256_file(path).model_dump(mode="json") for path in review_paths],
            "held_items": {item: list(reasons) for item, reasons in sorted(tiebreak.held.items())},
        }
    _write_immutable_report(report_path, result)
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
    parser.add_argument("--stage13", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--allow-incomplete-review",
        action="store_true",
        help="admit complete consensuses while terminally holding items with a missing review",
    )
    parser.add_argument("--tiebreak", type=Path, default=None)
    parser.add_argument("--tiebreak-rule", choices=sorted(TIEBREAK_RULES), default=None)
    parser.add_argument(
        "--review",
        type=Path,
        action="append",
        default=[],
        help="campaign reviewer decision file (repeat); required with --tiebreak",
    )
    args = parser.parse_args()
    result = materialize_qualitative_consensus(
        manifest_path=args.manifest,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        consensus_path=args.consensus,
        ledger_path=args.ledger,
        candidate_report_path=args.candidate_report,
        stage13_path=args.stage13,
        proposals_path=args.proposals,
        held_path=args.held,
        report_path=args.report,
        combinations_path=args.combinations,
        registry_path=args.registry,
        po_lexicon_path=args.po_lexicon,
        pato_lexicon_path=args.pato_lexicon,
        allow_incomplete_review=args.allow_incomplete_review,
        tiebreak_path=args.tiebreak,
        tiebreak_rule=args.tiebreak_rule,
        review_paths=tuple(args.review),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
