"""Independent-review consensus, adversarial checks, and conservation ledger."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from flopo2.review.io import read_jsonl, write_jsonl
from flopo2.review.models import (
    AdversarialVerdict,
    CampaignManifest,
    ConsensusDecision,
    LedgerEntry,
    ReviewDecision,
)
from flopo2.review.validation import (
    LocalValidation,
    ValidationContext,
    load_validation_context,
    validate_adversarial_verdict,
    validate_review_decision,
)


def _load_unique(paths: Iterable[Path], model: type, identity) -> list:
    rows: list = []
    seen: set[tuple] = set()
    for path in paths:
        for row in read_jsonl(path, model):
            key = identity(row)
            if key in seen:
                raise ValueError(f"duplicate {model.__name__} for {key}")
            seen.add(key)
            rows.append(row)
    return rows


def _validate_provenance(decision, manifest: CampaignManifest, *, expected_role: str) -> None:
    if decision.campaign_id != manifest.campaign_id:
        raise ValueError(f"{decision.item_id}: decision belongs to another campaign")
    specifications = {row.reviewer_id: row for row in manifest.models}
    specification = specifications.get(decision.reviewer_id)
    if specification is None or specification.role != expected_role:
        raise ValueError(f"{decision.item_id}: reviewer is absent from the {expected_role} manifest")
    for field in ("provider", "model", "model_family"):
        if getattr(decision, field) != getattr(specification, field):
            raise ValueError(f"{decision.item_id}: {field} does not match manifest")
    expected_prompt_id = "reviewer" if expected_role == "reviewer" else "adversarial"
    if decision.prompt_id != expected_prompt_id:
        raise ValueError(
            f"{decision.item_id}: {expected_role} must use the {expected_prompt_id} prompt"
        )
    prompts = {row.prompt_id: row for row in manifest.prompts}
    prompt = prompts.get(decision.prompt_id)
    if prompt is None or prompt.sha256 != decision.prompt_sha256:
        raise ValueError(f"{decision.item_id}: prompt provenance does not match manifest")


def _resolve_item(
    campaign_id: str,
    item_id: str,
    reviewers: list[ReviewDecision],
    verdicts: list[AdversarialVerdict],
    review_validations: dict[tuple[str, str], LocalValidation],
    context: ValidationContext,
) -> ConsensusDecision:
    reviewer_ids = tuple(sorted(row.reviewer_id for row in reviewers))
    if len(reviewers) < 2:
        return ConsensusDecision(
            campaign_id=campaign_id,
            item_id=item_id,
            status="held",
            reviewer_ids=reviewer_ids,
            reasons=("missing_independent_review",),
            validation_passed=False,
        )
    if len(reviewers) > 2:
        return ConsensusDecision(
            campaign_id=campaign_id,
            item_id=item_id,
            status="llm_disputed",
            reviewer_ids=reviewer_ids,
            reasons=("expected_exactly_two_reviewers",),
            validation_passed=False,
        )
    first, second = reviewers
    if first.reviewer_id == second.reviewer_id or (
        first.model_family.casefold() == second.model_family.casefold()
    ):
        return ConsensusDecision(
            campaign_id=campaign_id,
            item_id=item_id,
            status="llm_disputed",
            reviewer_ids=reviewer_ids,
            reasons=("reviewers_not_independent",),
            validation_passed=False,
        )
    local_reviews = [
        review_validations[(row.item_id, row.reviewer_id)] for row in (first, second)
    ]
    if first.disposition == second.disposition == "hold":
        exact_signature = first.normalized_signature == second.normalized_signature
        local_reasons = tuple(
            dict.fromkeys(reason for row in local_reviews for reason in row.reasons)
        )
        return ConsensusDecision(
            campaign_id=campaign_id,
            item_id=item_id,
            status="held",
            disposition="hold",
            normalized_signature=(first.normalized_signature if exact_signature else None),
            signature_sha256=(first.signature_sha256 if exact_signature else None),
            reviewer_ids=reviewer_ids,
            reasons=(
                "reviewers_requested_hold",
                *(("hold_reason_disagreement",) if not exact_signature else ()),
                *local_reasons,
            ),
            validation_passed=all(row.passed for row in local_reviews),
        )
    if any(not row.passed for row in local_reviews):
        local_reasons = tuple(
            dict.fromkeys(reason for row in local_reviews for reason in row.reasons)
        )
        return ConsensusDecision(
            campaign_id=campaign_id,
            item_id=item_id,
            status="held",
            reviewer_ids=reviewer_ids,
            reasons=("local_review_validation_failed", *local_reasons),
            validation_passed=False,
        )
    if first.disposition != second.disposition:
        return ConsensusDecision(
            campaign_id=campaign_id,
            item_id=item_id,
            status="llm_disputed",
            reviewer_ids=reviewer_ids,
            reasons=("disposition_disagreement",),
            validation_passed=False,
        )
    if first.normalized_signature != second.normalized_signature:
        return ConsensusDecision(
            campaign_id=campaign_id,
            item_id=item_id,
            status="llm_disputed",
            reviewer_ids=reviewer_ids,
            reasons=("normalized_signature_disagreement",),
            validation_passed=False,
        )
    signature = first.normalized_signature
    signature_hash = first.signature_sha256
    common = {
        "campaign_id": campaign_id,
        "item_id": item_id,
        "disposition": first.disposition,
        "normalized_signature": signature,
        "signature_sha256": signature_hash,
        "reviewer_ids": reviewer_ids,
    }
    if first.disposition in {
        "reusable_flopo_class",
        "reusable_flopo_support_class",
    }:
        matching = [
            row for row in verdicts if row.candidate_signature_sha256 == signature_hash
        ]
        if len(matching) != 1:
            return ConsensusDecision(
                **common,
                status="held",
                reasons=("missing_adversarial_verdict",),
                validation_passed=False,
            )
        adjudicator = matching[0]
        if adjudicator.model_family.casefold() in {
            first.model_family.casefold(),
            second.model_family.casefold(),
        }:
            return ConsensusDecision(
                **common,
                status="llm_disputed",
                adjudicator_id=adjudicator.reviewer_id,
                reasons=("adjudicator_not_independent",),
                validation_passed=False,
            )
        adversarial_validation = validate_adversarial_verdict(
            adjudicator,
            context,
            candidate_signature_sha256=signature_hash,
        )
        if not adversarial_validation.passed or adjudicator.verdict == "block":
            reason = (
                "local_adversarial_validation_failed"
                if not adversarial_validation.passed
                else "adversarial_blocker"
            )
            return ConsensusDecision(
                **common,
                status="held",
                adjudicator_id=adjudicator.reviewer_id,
                reasons=(reason, *adversarial_validation.reasons),
                validation_passed=False,
            )
        return ConsensusDecision(
            **common,
            status="llm_consensus",
            adjudicator_id=adjudicator.reviewer_id,
            reasons=("independent_agreement", "adversarial_no_blocker"),
            validation_passed=True,
        )
    return ConsensusDecision(
        **common,
        status="llm_consensus",
        reasons=("independent_agreement",),
        validation_passed=True,
    )


def build_consensus(
    *,
    manifest: CampaignManifest,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    review_paths: Iterable[Path],
    adjudication_paths: Iterable[Path] = (),
    consensus_path: Path,
    exception_path: Path,
    ledger_path: Path,
) -> dict[str, int]:
    """Combine machine decisions and prove one terminal ledger row per input occurrence."""

    validation_context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    occurrences = list(validation_context.occurrences.values())
    occurrence_ids = [row.occurrence_id for row in occurrences]
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise ValueError("duplicate occurrence in campaign inventory")
    cluster_ids = {row.cluster_id for row in occurrences}
    if len(cluster_ids) != manifest.starting_clusters:
        raise ValueError("cluster count does not match immutable campaign manifest")
    reviews = _load_unique(
        review_paths, ReviewDecision, lambda row: (row.item_id, row.reviewer_id)
    )
    verdicts = _load_unique(
        adjudication_paths, AdversarialVerdict, lambda row: (row.item_id, row.reviewer_id)
    )
    for decision in reviews:
        _validate_provenance(decision, manifest, expected_role="reviewer")
        if decision.item_id not in cluster_ids:
            raise ValueError(f"review decision targets unknown item: {decision.item_id}")
    for verdict in verdicts:
        _validate_provenance(verdict, manifest, expected_role="adjudicator")
        if verdict.item_id not in cluster_ids:
            raise ValueError(f"adversarial verdict targets unknown item: {verdict.item_id}")
    review_validations = {
        (decision.item_id, decision.reviewer_id): validate_review_decision(
            decision, validation_context
        )
        for decision in reviews
    }
    reviews_by_item: defaultdict[str, list[ReviewDecision]] = defaultdict(list)
    verdicts_by_item: defaultdict[str, list[AdversarialVerdict]] = defaultdict(list)
    for review in reviews:
        reviews_by_item[review.item_id].append(review)
    for verdict in verdicts:
        verdicts_by_item[verdict.item_id].append(verdict)
    decisions = [
        _resolve_item(
            manifest.campaign_id,
            item_id,
            reviews_by_item[item_id],
            verdicts_by_item[item_id],
            review_validations,
            validation_context,
        )
        for item_id in sorted(cluster_ids)
    ]
    decision_index = {row.item_id: row for row in decisions}
    ledger = [
        LedgerEntry(
            campaign_id=manifest.campaign_id,
            occurrence_id=occurrence.occurrence_id,
            item_id=occurrence.cluster_id,
            status=decision_index[occurrence.cluster_id].status,
            disposition=decision_index[occurrence.cluster_id].disposition,
            signature_sha256=decision_index[occurrence.cluster_id].signature_sha256,
            reasons=decision_index[occurrence.cluster_id].reasons,
        )
        for occurrence in occurrences
    ]
    if len(ledger) != manifest.starting_occurrences or {
        row.occurrence_id for row in ledger
    } != set(occurrence_ids):
        raise ValueError("conservation failure: ledger does not cover every starting occurrence")
    write_jsonl(consensus_path, decisions)
    write_jsonl(exception_path, (row for row in decisions if row.status != "llm_consensus"))
    write_jsonl(ledger_path, ledger)
    return dict(sorted(Counter(row.status for row in ledger).items()))
