"""Materialize two-family negation consensus as immutable Stage-15 proposals.

Each ``negated_context`` review item carries a runner-owned :class:`NegationCandidate`.  A reviewer
may copy its admitted expression exactly or hold; only an admissible classification with a resolved
bearer can ever be admitted, and the admission is re-derived here from the frozen candidate
inventory, never from model text.  This bridge:

* validates every campaign hash (manifest, occurrences, clusters, evidence, candidate inventory,
  and the runner candidate report);
* requires two independent reviewer families and exact signature agreement;
* rebinds each accepted expression to its exact Stage-15 span and reruns the deterministic
  assertion gate with the runner-frozen negation scope;
* appends accepted assertions to a *separate* artifact, clears each accepted span exactly once,
  retains held spans byte-for-byte, and emits a terminal conservation ledger for all occurrences.

It never overwrites Stage 15 and never represents machine review as human review.
"""

from __future__ import annotations

import argparse
import hashlib
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
    canonical_json,
)
from flopo2.review.negation_inventory import (
    ADMISSIBLE,
    CANDIDATE_SCHEMA_VERSION,
    NEGATION_PROTOCOL,
    PAYLOAD_MARKER,
    REPORT_SCHEMA_VERSION,
    NegationCandidate,
    annotation_signature,
    negation_review_payload,
)
from flopo2.review.report import campaign_report
from flopo2.review.validation import load_validation_context
from flopo2.verify.gates import (
    Combination,
    check_assertion,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)


EXTRACTOR = "llm_consensus_negation_v1"
MATERIALIZATION_SCHEMA_VERSION = "flopo-negation-materialization-v1"
SegmentKey = tuple[str, str, int, str]


def _segment_key(row: dict[str, Any] | Occurrence | NegationCandidate) -> SegmentKey:
    if isinstance(row, (Occurrence, NegationCandidate)):
        return row.source, row.source_id, row.source_segment_index, row.taxon
    return (
        str(row.get("source", "") or ""),
        str(row.get("source_id", "") or ""),
        int(row.get("source_segment_index", 0) or 0),
        str(row.get("taxon", "") or ""),
    )


def _write_immutable_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
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


def _artifact_matches(record: dict[str, Any], path: Path, label: str) -> None:
    actual = sha256_file(path)
    if (actual.sha256, actual.bytes) != (record.get("sha256"), record.get("bytes")):
        raise ValueError(f"{label} hash does not match the negation candidate report")


def _load_candidates(
    candidate_path: Path, manifest: CampaignManifest
) -> dict[str, NegationCandidate]:
    if not manifest.sources or len(manifest.sources) != 1:
        raise ValueError("negation campaign must bind exactly one candidate inventory source")
    expected = manifest.sources[0]
    actual = sha256_file(candidate_path)
    if (actual.sha256, actual.bytes) != (expected.sha256, expected.bytes):
        raise ValueError("candidate inventory hash does not match the campaign manifest")
    candidates: dict[str, NegationCandidate] = {}
    for row in read_jsonl(candidate_path, NegationCandidate):
        if row.schema_version != CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported negation candidate schema")
        if row.occurrence_id in candidates:
            raise ValueError(f"duplicate negation candidate: {row.occurrence_id}")
        candidates[row.occurrence_id] = row
    return candidates


def _verify_candidate_report(
    path: Path,
    *,
    manifest: CampaignManifest,
    stage15_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    candidate_path: Path,
) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid negation candidate report {path}: {error}") from error
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported negation candidate report")
    if report.get("protocol") != NEGATION_PROTOCOL:
        raise ValueError("negation candidate report protocol drift")
    if report.get("campaign_id") != manifest.campaign_id:
        raise ValueError("negation candidate report belongs to another campaign")
    conservation = report.get("conservation", {})
    if not all(
        conservation.get(key)
        for key in (
            "one_cluster_per_occurrence",
            "all_spans_classified",
            "stage15_exact_span_rebinding",
            "admission_requires_admissible_classification",
        )
    ):
        raise ValueError("negation candidate extraction is not conserved")
    actual_stage = sha256_file(stage15_path)
    if (actual_stage.sha256, actual_stage.bytes) != (manifest.input.sha256, manifest.input.bytes):
        raise ValueError("Stage 15 does not match the negation campaign baseline")
    if (report["stage15"]["sha256"], report["stage15"]["bytes"]) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("candidate report Stage 15 binding drift")
    for expected, actual_path, key in (
        (manifest.occurrences, occurrence_path, "occurrences"),
        (manifest.clusters, cluster_path, "clusters"),
        (manifest.evidence_registry, evidence_path, "evidence_registry"),
        (manifest.sources[0], candidate_path, "candidate_inventory"),
    ):
        if (report[key]["sha256"], report[key]["bytes"]) != (expected.sha256, expected.bytes):
            raise ValueError(f"candidate report {key} binding drift")
        _artifact_matches(report[key], actual_path, key)
    if int(report.get("negated_context_spans", -1)) != manifest.starting_occurrences:
        raise ValueError("candidate report occurrence count drift")
    if manifest.starting_occurrences != manifest.starting_clusters:
        raise ValueError("negation campaign is not one item per occurrence")
    return report


def _held_row(
    occurrence: Occurrence,
    candidate: NegationCandidate,
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
        "span_start": occurrence.span_start,
        "span_end": occurrence.span_end,
        "surface_form": occurrence.surface_form,
        "classification": candidate.classification,
        "negation_scope": candidate.negation_scope,
        "candidate_admission": candidate.admission,
        "candidate_hold_reason": candidate.hold_reason,
        "reason": reason,
        "details": list(details),
        "consensus": decision.model_dump(mode="json", exclude_none=True),
    }


def _verify_context_binding(occurrence: Occurrence, candidate: NegationCandidate) -> None:
    """The runner payload embedded in the reviewed context must match the frozen candidate."""

    expected_payload = negation_review_payload(candidate)
    expected_block = f"{PAYLOAD_MARKER}\n{canonical_json(expected_payload)}"
    if not occurrence.context.endswith(expected_block):
        raise ValueError(f"{occurrence.occurrence_id}: negation payload not bound into context")
    digest = hashlib.sha256(canonical_json(expected_payload).encode()).hexdigest()
    if digest != candidate.payload_sha256:
        raise ValueError(f"{occurrence.occurrence_id}: candidate payload hash drift")


def _accepted_expression(
    occurrence: Occurrence,
    candidate: NegationCandidate,
    decision: ConsensusDecision,
) -> None:
    """Fail closed unless the consensus is the exact admissible runner candidate."""

    if candidate.admission != "admit" or candidate.admitted_expression is None:
        raise ValueError(f"{occurrence.occurrence_id}: accepted a non-admissible candidate")
    if candidate.classification not in ADMISSIBLE:
        raise ValueError(f"{occurrence.occurrence_id}: accepted candidate is not admissible")
    proposed = ProposedSignature.model_validate_json(decision.normalized_signature or "")
    if proposed.kind != "annotation_expression" or proposed.expression is None:
        raise ValueError(f"{occurrence.occurrence_id}: consensus is not an annotation expression")
    if proposed.expression != candidate.admitted_expression:
        raise ValueError(f"{occurrence.occurrence_id}: consensus expression differs from candidate")
    _, digest = annotation_signature(candidate.admitted_expression)
    if decision.signature_sha256 != digest or candidate.admitted_signature_sha256 != digest:
        raise ValueError(f"{occurrence.occurrence_id}: accepted signature hash drift")


def _assertion_for(occurrence: Occurrence, candidate: NegationCandidate) -> dict[str, Any]:
    expression = candidate.admitted_expression
    assert expression is not None
    negated = candidate.classification != "numeric_upper_bound"
    scope = candidate.negation_scope if negated else ""
    assertion: dict[str, Any] = {
        "po_id": expression.bearer_id,
        "pato_id": expression.quality_id,
        "negated": negated,
        "negation_scope": scope,
        "organ": occurrence.organ,
        "source_text": candidate.source_text,
        "source_start": candidate.source_start,
        "source_end": candidate.source_end,
        "value_low": expression.value_low,
        "value_high": expression.value_high,
        "value_low_inclusive": expression.value_low_inclusive,
        "value_high_inclusive": expression.value_high_inclusive,
        "unit": expression.unit,
        "value_text": "",
        "value_operator": expression.value_operator,
        "value_terms": list(expression.value_terms),
        "part_restrictions": [row.model_dump(mode="json") for row in expression.part_restrictions],
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
            f"llm_consensus:{candidate.occurrence_id}",
            f"negation_classification:{candidate.classification}",
            f"negation_scope:{candidate.negation_scope}",
            f"negation_cue:{candidate.cue_start}-{candidate.cue_end}",
            f"bearer_method:{candidate.bearer_method or 'unrecorded'}",
            f"llm_signature:{candidate.admitted_signature_sha256}",
        ],
        "raw_entity_text": candidate.bearer_text,
        "raw_quality_text": candidate.surface_form,
        "extractor": EXTRACTOR,
        "composition": {
            "status": "accept",
            "confidence": 1.0,
            "reasons": ["two_family_llm_exact_negation_consensus"],
        },
    }
    if candidate.bearer_start is not None:
        assertion["bearer_start"] = candidate.bearer_start
        assertion["bearer_end"] = candidate.bearer_end
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
        for row in (upgraded.get("source_statements", []) or [])
        if row.get("statement_id") == statement_id
    ]
    if len(matches) != 1:
        raise ValueError(f"source statement {statement_id!r} was not materialized exactly once")
    return materialized, matches[0]


def materialize_negation_consensus(
    *,
    manifest_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    candidate_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    candidate_report_path: Path,
    stage15_path: Path,
    proposals_path: Path,
    held_path: Path,
    conservation_path: Path,
    report_path: Path,
    combinations_path: Path = Path("config/valid_combinations.tsv"),
    registry_path: Path = Path("config/flopo_id_registry.tsv"),
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
) -> dict[str, Any]:
    """Revalidate the full negation campaign and emit one terminal outcome per span."""

    paths = (
        manifest_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        candidate_path,
        consensus_path,
        ledger_path,
        candidate_report_path,
        stage15_path,
        proposals_path,
        held_path,
        conservation_path,
        report_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("negation materialization paths must be distinct")
    manifest = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    candidate_report = _verify_candidate_report(
        candidate_report_path,
        manifest=manifest,
        stage15_path=stage15_path,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
        candidate_path=candidate_path,
    )
    review_report = campaign_report(
        manifest, occurrence_path, cluster_path, evidence_path, consensus_path, ledger_path
    )
    if not review_report["ok"]:
        raise ValueError("negation review campaign is incomplete or unconserved")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    candidates = _load_candidates(candidate_path, manifest)
    if set(candidates) != set(context.occurrences):
        raise ValueError("candidate inventory does not cover the campaign occurrences exactly")
    decisions = {row.item_id: row for row in read_jsonl(consensus_path, ConsensusDecision)}

    combos = load_combinations(combinations_path)
    registry = load_eq_registry(registry_path)
    signature_registry = load_signature_registry(registry_path)
    attribute_ids = load_pato_attribute_terms(pato_lexicon_path)
    pato_ids = load_catalog_ids(pato_lexicon_path)
    po_ids = load_catalog_ids(po_lexicon_path)
    flopo_ids = load_flopo_ids(registry_path)
    flopo_ids.update(
        candidate.admitted_expression.bearer_id
        for candidate in candidates.values()
        if candidate.admitted_expression is not None
        and candidate.admitted_expression.bearer_id.startswith("FLOPO_")
    )

    occurrences = sorted(context.occurrences.values(), key=lambda row: row.occurrence_id)
    actionable: defaultdict[SegmentKey, list[tuple[Occurrence, NegationCandidate]]] = defaultdict(
        list
    )
    held: list[dict[str, Any]] = []
    ledger: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for occurrence in occurrences:
        candidate = candidates[occurrence.occurrence_id]
        if candidate.cluster_id != occurrence.cluster_id or (
            candidate.span_start,
            candidate.span_end,
            candidate.surface_form,
            candidate.quality_pato_id,
        ) != (
            occurrence.span_start,
            occurrence.span_end,
            occurrence.surface_form,
            occurrence.candidate_pato_id,
        ):
            raise ValueError(f"{occurrence.occurrence_id}: candidate does not match occurrence")
        _verify_context_binding(occurrence, candidate)
        decision = decisions[occurrence.cluster_id]
        accepted = (
            decision.status == "llm_consensus"
            and decision.disposition == "annotation_expression"
            and decision.validation_passed
        )
        if accepted and candidate.admission == "admit":
            _accepted_expression(occurrence, candidate, decision)
            actionable[_segment_key(occurrence)].append((occurrence, candidate))
            counts["consensus_candidates"] += 1
        elif accepted and candidate.admission != "admit":
            # A reviewer accepted an expression the runner never admitted: fail closed to held.
            held.append(
                _held_row(
                    occurrence, candidate, decision, reason="accepted_non_admissible_candidate"
                )
            )
            ledger[occurrence.occurrence_id] = _ledger_entry(occurrence, candidate, "held")
            counts["accepted_non_admissible_held"] += 1
        else:
            held.append(
                _held_row(
                    occurrence,
                    candidate,
                    decision,
                    reason="campaign_exception",
                    details=decision.reasons,
                )
            )
            ledger[occurrence.occurrence_id] = _ledger_entry(occurrence, candidate, "held")
            counts["campaign_exception_held"] += 1

    proposals: list[dict[str, Any]] = []
    matched: Counter[SegmentKey] = Counter()
    with stage15_path.open(encoding="utf-8") as handle:
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
                raise ValueError(
                    f"duplicate Stage 15 segment identity at line {line_number}: {key}"
                )
            text = str(record.get("text", "") or "")
            unresolved_ranges = Counter(
                (int(span.get("start", -1)), int(span.get("end", -1)))
                for span in (record.get("unresolved_spans", []) or [])
                if isinstance(span, dict) and str(span.get("reason", "")) == "negated_context"
            )
            used_clear_ranges: set[tuple[int, int]] = set()
            for occurrence, candidate in sorted(rows, key=lambda row: row[0].span_start):
                if text[candidate.span_start : candidate.span_end] != candidate.surface_form:
                    raise ValueError(f"{occurrence.occurrence_id}: Stage 15 span drift")
                if text[candidate.source_start : candidate.source_end] != candidate.source_text:
                    raise ValueError(f"{occurrence.occurrence_id}: Stage 15 source-text drift")
                if candidate.bearer_start is not None:
                    assert candidate.bearer_end is not None
                    if text[candidate.bearer_start : candidate.bearer_end] != candidate.bearer_text:
                        raise ValueError(f"{occurrence.occurrence_id}: Stage 15 bearer-text drift")
                clear = candidate.clear_span
                if unresolved_ranges[clear] != 1:
                    raise ValueError(f"{occurrence.occurrence_id}: unresolved clear-range drift")
                if clear in used_clear_ranges:
                    raise ValueError(f"{occurrence.occurrence_id}: duplicate clear range {clear}")
                used_clear_ranges.add(clear)
                assertion = _assertion_for(occurrence, candidate)
                expression = candidate.admitted_expression
                assert expression is not None
                local_combos = dict(combos)
                local_combos[(expression.bearer_id, expression.quality_id)] = Combination(
                    status="allowed", source=f"llm_consensus:{manifest.campaign_id}"
                )
                gate = check_assertion(
                    text,
                    assertion,
                    local_combos,
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
                            candidate,
                            decisions[occurrence.cluster_id],
                            reason="post_consensus_gate_held",
                            details=gate.reasons,
                        )
                    )
                    ledger[occurrence.occurrence_id] = _ledger_entry(occurrence, candidate, "held")
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
                        "classification": candidate.classification,
                        "negation_scope": candidate.negation_scope,
                        "assertion": assertion,
                        "source_statement": source_statement,
                        "apply": {"clear_unresolved_spans": [{"start": clear[0], "end": clear[1]}]},
                    }
                )
                ledger[occurrence.occurrence_id] = _ledger_entry(occurrence, candidate, "accepted")
                counts["proposals"] += 1

    unmatched = sorted(set(actionable) - set(matched))
    if unmatched:
        raise ValueError(f"reviewed occurrences miss Stage 15 segments: {unmatched[:3]}")
    proposals.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["taxon"],
            row["assertion"]["source_start"],
        )
    )
    held.sort(key=lambda row: row["occurrence_id"])
    ledger_rows = [ledger[occurrence.occurrence_id] for occurrence in occurrences]
    if len(ledger_rows) != manifest.starting_occurrences:
        raise ValueError("negation ledger does not cover every starting occurrence")
    accepted_ids = {row["occurrence_id"] for row in ledger_rows if row["outcome"] == "accepted"}
    held_ids = {row["occurrence_id"] for row in ledger_rows if row["outcome"] == "held"}
    if accepted_ids & held_ids or accepted_ids | held_ids != set(context.occurrences):
        raise ValueError(
            "negation conservation failure: an occurrence is not resolved exactly once"
        )
    terminal = len(proposals) + len(held)
    if terminal != manifest.starting_occurrences:
        raise ValueError(
            f"negation conservation failure: {terminal} != {manifest.starting_occurrences}"
        )
    if len(accepted_ids) != len(proposals):
        raise ValueError("accepted ledger rows disagree with emitted proposals")

    _write_immutable_rows(proposals_path, proposals)
    _write_immutable_rows(held_path, held)
    _write_immutable_rows(conservation_path, ledger_rows)
    result = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "protocol": NEGATION_PROTOCOL,
        "campaign_id": manifest.campaign_id,
        "starting_occurrences": manifest.starting_occurrences,
        "proposals": len(proposals),
        "held": len(held),
        "conserved": terminal == manifest.starting_occurrences,
        "counts": dict(sorted(counts.items())),
        "classifications": candidate_report["classifications"],
        "admissions": candidate_report["admissions"],
        "review_report": review_report,
        "candidate_report_sha256": sha256_file(candidate_report_path).sha256,
        "artifacts": {
            "stage15": sha256_file(stage15_path).model_dump(mode="json"),
            "candidate_inventory": sha256_file(candidate_path).model_dump(mode="json"),
            "proposals": sha256_file(proposals_path).model_dump(mode="json"),
            "held": sha256_file(held_path).model_dump(mode="json"),
            "conservation_ledger": sha256_file(conservation_path).model_dump(mode="json"),
        },
        "provenance": {
            "review_kind": "two_family_llm_exact_negation_consensus",
            "human_reviewed": False,
            "stage15_modified": False,
            "configuration_allow_list_modified": False,
        },
    }
    _write_immutable_report(report_path, result)
    return result


def _ledger_entry(
    occurrence: Occurrence, candidate: NegationCandidate, outcome: str
) -> dict[str, Any]:
    return {
        "occurrence_id": occurrence.occurrence_id,
        "item_id": occurrence.cluster_id,
        "source": occurrence.source,
        "source_id": occurrence.source_id,
        "source_segment_index": occurrence.source_segment_index,
        "taxon": occurrence.taxon,
        "span_start": occurrence.span_start,
        "span_end": occurrence.span_end,
        "classification": candidate.classification,
        "negation_scope": candidate.negation_scope,
        "outcome": outcome,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--consensus", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--stage15", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--conservation", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--combinations", type=Path, default=Path("config/valid_combinations.tsv"))
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    args = parser.parse_args()
    result = materialize_negation_consensus(
        manifest_path=args.manifest,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        candidate_path=args.candidates,
        consensus_path=args.consensus,
        ledger_path=args.ledger,
        candidate_report_path=args.candidate_report,
        stage15_path=args.stage15,
        proposals_path=args.proposals,
        held_path=args.held,
        conservation_path=args.conservation,
        report_path=args.report,
        combinations_path=args.combinations,
        registry_path=args.registry,
        po_lexicon_path=args.po_lexicon,
        pato_lexicon_path=args.pato_lexicon,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
