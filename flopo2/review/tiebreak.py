"""Third-reviewer tie-break admission for items a two-family campaign left held.

Curator decision 2026-09-18: a held machine-review item may be admitted under the
``two_of_three`` rule when

* a third, family-independent tie-break reviewer returns a non-hold decision that passes the
  campaign's own local validation, and
* at least one of the campaign's manifest reviewers returned the *identical* normalized
  signature, and that review also passes local validation.

An adversarial verdict is not required, but an existing adversarial ``block`` for the item still
holds it.  Every deterministic gate of the calling materializer runs unchanged afterwards.  The
synthesized :class:`ConsensusDecision` names all three machine reviewers and the rule; it never
records a curator or human review.

Curator decision 2026-09-18 (extension): a caller may pass ``curator_overrides``, an explicit
mapping of ``item_id -> curator note`` (e.g. ``"curator 2026-09-18"``), naming items for which a
human curator has reviewed and overridden an existing adversarial block. Only items already named
in this mapping are affected; every other deterministic gate (local validation, exact partner
agreement) still applies unchanged, and an item outside the mapping with an adversarial block is
still held. The synthesized :class:`ConsensusDecision` for an overridden item records the reason
``curator_override_adversarial_block:<note>`` so the override is traceable to this decision.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from flopo2.review.consensus import _validate_provenance
from flopo2.review.io import read_jsonl
from flopo2.review.models import (
    AdversarialVerdict,
    CampaignManifest,
    ConsensusDecision,
    ReviewDecision,
)
from flopo2.review.validation import ValidationContext, validate_review_decision


TIEBREAK_RULES = {"two_of_three": "two_of_three_exact_agreement"}
DEFAULT_TIEBREAK_REVIEWER: dict[str, Any] = {
    "reviewer_id": "reviewer_claude_opus_5",
    "provider": "anthropic",
    "model": "claude-opus-5",
    "model_family": "claude",
    "reasoning_effort": "high",
}


@dataclass(frozen=True)
class TiebreakResolution:
    rule: str
    admitted: dict[str, ConsensusDecision]
    held: dict[str, tuple[str, ...]]
    agreeing_reviewers: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        reasons: dict[str, int] = defaultdict(int)
        for values in self.held.values():
            for reason in values[:1]:
                reasons[reason] += 1
        return {
            "rule": self.rule,
            "admission_reason": TIEBREAK_RULES[self.rule],
            "tiebreak_items": len(self.admitted) + len(self.held),
            "admitted": len(self.admitted),
            "held": len(self.held),
            "held_first_reasons": dict(sorted(reasons.items())),
        }


def tiebreak_review(row: dict[str, Any], manifest: CampaignManifest) -> ReviewDecision:
    """Rebuild the tie-break reviewer's ``ReviewDecision`` from one tie-break row."""

    decision = row.get("decision")
    if not isinstance(decision, dict):
        raise ValueError(f"{row.get('item_id')}: tie-break row lacks a decision")
    reviewer = {**DEFAULT_TIEBREAK_REVIEWER, **(row.get("reviewer") or {})}
    prompt = next((p for p in manifest.prompts if p.prompt_id == "reviewer"), None)
    if prompt is None:
        raise ValueError("campaign manifest has no reviewer prompt")
    return ReviewDecision.model_validate(
        {
            **reviewer,
            "prompt_id": "reviewer",
            "prompt_sha256": prompt.sha256,
            "campaign_id": row.get("campaign_id"),
            "item_id": row.get("item_id"),
            "disposition": decision.get("disposition"),
            "proposed_signature": decision.get("proposed_signature"),
            "rationale": row.get("rationale") or "tie-break decision",
            "confidence": float(row.get("confidence", 0.9)),
            "evidence_ids": decision.get("evidence_ids"),
            "validation_passed": bool(decision.get("validation_passed")),
        }
    )


def _read_rows(path: Path, campaign_id: str) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: tie-break row is not an object")
            if row.get("campaign_id") == campaign_id:
                rows.append(row)
    return rows


def resolve_tiebreak(
    *,
    tiebreak_path: Path,
    rule: str,
    manifest: CampaignManifest,
    context: ValidationContext,
    base_decisions: dict[str, ConsensusDecision],
    review_paths: Iterable[Path],
    adjudication_paths: Iterable[Path] = (),
    admissible_dispositions: frozenset[str],
    curator_overrides: Mapping[str, str] | None = None,
) -> TiebreakResolution:
    """Resolve tie-break rows for one campaign under ``rule``."""

    if rule not in TIEBREAK_RULES:
        raise ValueError(f"unsupported tie-break rule: {rule}")
    overrides: dict[str, str] = dict(curator_overrides or {})
    review_paths = list(review_paths)
    if not review_paths:
        raise ValueError("tie-break resolution requires the campaign review files")
    reviews: dict[str, list[ReviewDecision]] = defaultdict(list)
    for path in review_paths:
        for review in read_jsonl(path, ReviewDecision):
            if review.campaign_id != manifest.campaign_id:
                continue
            _validate_provenance(review, manifest, expected_role="reviewer")
            reviews[review.item_id].append(review)
    blocks: dict[str, list[str]] = defaultdict(list)
    for path in adjudication_paths:
        for verdict in read_jsonl(path, AdversarialVerdict):
            if verdict.campaign_id == manifest.campaign_id and verdict.verdict == "block":
                blocks[verdict.item_id].append(verdict.reviewer_id)
    manifest_families = {
        row.model_family.casefold() for row in manifest.models if row.role == "reviewer"
    }

    admitted: dict[str, ConsensusDecision] = {}
    held: dict[str, tuple[str, ...]] = {}
    agreeing: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()
    for row in _read_rows(tiebreak_path, manifest.campaign_id):
        tiebreak = tiebreak_review(row, manifest)
        item_id = tiebreak.item_id
        if item_id in seen:
            raise ValueError(f"{item_id}: duplicate tie-break row")
        seen.add(item_id)
        if item_id not in context.clusters:
            raise ValueError(f"{item_id}: tie-break item is not in the campaign")
        base = base_decisions.get(item_id)
        if base is None:
            raise ValueError(f"{item_id}: tie-break item has no campaign decision")
        if base.status == "llm_consensus":
            # Campaign consensus already exists; only a downstream gate can have held it, and a
            # third reviewer cannot override a deterministic gate.
            held[item_id] = ("campaign_consensus_already_reached",)
            continue
        if tiebreak.model_family.casefold() in manifest_families or tiebreak.reviewer_id in {
            row.reviewer_id for row in manifest.models
        }:
            raise ValueError(f"{item_id}: tie-break reviewer is not independent")
        item_reviews = reviews.get(item_id, [])
        if len(item_reviews) != 2:
            raise ValueError(f"{item_id}: expected two campaign reviews, got {len(item_reviews)}")
        reviewer_ids = tuple(
            sorted({tiebreak.reviewer_id, *(review.reviewer_id for review in item_reviews)})
        )
        if tiebreak.disposition == "hold":
            held[item_id] = ("tiebreak_reviewer_hold",)
            continue
        if tiebreak.disposition not in admissible_dispositions:
            held[item_id] = ("tiebreak_disposition_not_admissible",)
            continue
        local = validate_review_decision(tiebreak, context)
        if not local.passed:
            held[item_id] = ("tiebreak_local_validation_failed", *local.reasons)
            continue
        partners = tuple(
            sorted(
                review.reviewer_id
                for review in item_reviews
                if review.disposition == tiebreak.disposition
                and review.normalized_signature == tiebreak.normalized_signature
                and validate_review_decision(review, context).passed
            )
        )
        if not partners:
            held[item_id] = ("no_exact_validated_partner",)
            continue
        override_note = overrides.pop(item_id, None)
        blocked_by = blocks.get(item_id) or []
        if blocked_by and override_note is None:
            held[item_id] = (
                "adversarial_blocker",
                *(f"adjudicator:{identifier}" for identifier in sorted(blocked_by)),
            )
            continue
        overridden = bool(blocked_by) and override_note is not None
        admitted[item_id] = ConsensusDecision(
            campaign_id=manifest.campaign_id,
            item_id=item_id,
            status="llm_consensus",
            disposition=tiebreak.disposition,
            normalized_signature=tiebreak.normalized_signature,
            signature_sha256=tiebreak.signature_sha256,
            reviewer_ids=reviewer_ids,
            reasons=(
                TIEBREAK_RULES[rule],
                f"tiebreak_reviewer:{tiebreak.reviewer_id}",
                *(f"agreeing_reviewer:{identifier}" for identifier in partners),
                *(
                    (
                        f"curator_override_adversarial_block:{override_note}",
                        *(
                            f"overridden_adjudicator:{identifier}"
                            for identifier in sorted(blocked_by)
                        ),
                    )
                    if overridden
                    else ()
                ),
            ),
            validation_passed=True,
        )
        agreeing[item_id] = (tiebreak.reviewer_id, *partners)
    if overrides:
        raise ValueError(
            "curator_overrides names items that were not admitted: "
            f"{sorted(overrides)}"
        )
    return TiebreakResolution(
        rule=rule, admitted=admitted, held=held, agreeing_reviewers=agreeing
    )
