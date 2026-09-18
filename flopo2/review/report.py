"""Machine-readable campaign completion report."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from flopo2.review.io import read_jsonl, sha256_file
from flopo2.review.models import CampaignManifest, ConsensusDecision, LedgerEntry
from flopo2.review.validation import load_validation_context


def campaign_report(
    manifest: CampaignManifest,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
) -> dict:
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    occurrences = list(context.occurrences.values())
    decisions = list(read_jsonl(consensus_path, ConsensusDecision))
    ledger = list(read_jsonl(ledger_path, LedgerEntry))
    starting_ids = set(context.occurrences)
    occurrence_ids = [row.occurrence_id for row in ledger]
    decision_ids = [row.item_id for row in decisions]
    decision_index = {row.item_id: row for row in decisions}
    ledger_index = {row.occurrence_id: row for row in ledger}
    exact_decision_cover = (
        len(decision_ids) == len(set(decision_ids))
        and set(decision_ids) == set(context.clusters)
    )
    exact_ledger_cover = (
        len(ledger) == manifest.starting_occurrences
        and len(occurrence_ids) == len(set(occurrence_ids))
        and set(occurrence_ids) == starting_ids
    )
    joined = exact_decision_cover and exact_ledger_cover
    if joined:
        for occurrence in occurrences:
            decision = decision_index[occurrence.cluster_id]
            entry = ledger_index[occurrence.occurrence_id]
            if (
                entry.campaign_id != manifest.campaign_id
                or entry.item_id != occurrence.cluster_id
                or entry.status != decision.status
                or entry.disposition != decision.disposition
                or entry.signature_sha256 != decision.signature_sha256
                or entry.reasons != decision.reasons
            ):
                joined = False
                break
    integrity_ok = (
        joined
        and all(row.campaign_id == manifest.campaign_id for row in ledger)
        and all(row.campaign_id == manifest.campaign_id for row in decisions)
    )
    review_complete = integrity_ok and all(len(row.reviewer_ids) == 2 for row in decisions)
    exception_clusters = sum(row.status != "llm_consensus" for row in decisions)
    return {
        "schema_version": "flopo-campaign-report-v2",
        "campaign_id": manifest.campaign_id,
        "starting_occurrences": manifest.starting_occurrences,
        "starting_clusters": manifest.starting_clusters,
        "decision_statuses": dict(sorted(Counter(row.status for row in decisions).items())),
        "occurrence_statuses": dict(sorted(Counter(row.status for row in ledger).items())),
        "dispositions": dict(
            sorted(Counter(row.disposition or "undisposed" for row in ledger).items())
        ),
        "conservation": {
            "ledger_rows": len(ledger),
            "unique_occurrences": len(set(occurrence_ids)),
            "complete": exact_ledger_cover,
        },
        "integrity_ok": integrity_ok,
        "review_complete": review_complete,
        "exception_clusters": exception_clusters,
        "artifacts": {
            "occurrences": sha256_file(occurrence_path).model_dump(),
            "clusters": sha256_file(cluster_path).model_dump(),
            "evidence_registry": sha256_file(evidence_path).model_dump(),
            "consensus": sha256_file(consensus_path).model_dump(),
            "ledger": sha256_file(ledger_path).model_dump(),
        },
        "ok": integrity_ok and review_complete,
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
