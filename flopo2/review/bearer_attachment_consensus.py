"""2-of-3 exact consensus for the bearer-attachment review campaign.

Admission rule (curator decision 2026-09-18, ``flopo2/ANNOTATION_MODEL.md`` section 3): an item is
admitted to materialization when at least two of the three reviewer families (Claude Opus, Claude
Sonnet, Qwen) return the *same* candidate ``bearer_id``; ``hold`` and invalid responses are never
votes for a bearer.  Materialization then re-applies every deterministic gate.  Everything else
is held, with the reason.  Pairwise agreement rates are reported over items answered validly by
both reviewers of the pair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

from flopo2.review.bearer_attachment_inventory import HOLD

CONSENSUS_SCHEMA_VERSION = "flopo-bearer-attachment-consensus-v1"
ADMISSION_RULE = "machine_review_2_of_3_exact_bearer_agreement"


def load_reviews(paths: list[Path]) -> dict[str, dict[str, dict[str, Any]]]:
    """``reviewer -> item_id -> review row`` (duplicates are an error)."""

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for path in paths:
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            per = out.setdefault(row["reviewer_id"], {})
            if row["item_id"] in per:
                raise ValueError(f"duplicate review {row['reviewer_id']} {row['item_id']}")
            per[row["item_id"]] = row
    return out


def decide(votes: dict[str, str]) -> dict[str, Any]:
    """Consensus for one item from ``reviewer -> bearer_id`` (``hold``/``invalid`` allowed)."""

    bearers = Counter(v for v in votes.values() if v not in {HOLD, "invalid", ""})
    if bearers:
        bearer, count = bearers.most_common(1)[0]
        if count >= 2 and list(bearers.values()).count(count) == 1:
            agreeing = sorted(r for r, v in votes.items() if v == bearer)
            dissent = sorted(r for r, v in votes.items() if v != bearer)
            return {
                "status": "admitted_for_gates",
                "bearer_id": bearer,
                "agreeing_reviewers": agreeing,
                "dissenting_reviewers": dissent,
                "reasons": [ADMISSION_RULE] + (
                    ["dissent_other_bearer"]
                    if any(votes[r] not in {HOLD, "invalid", ""} for r in dissent)
                    else []
                ),
            }
    reasons = []
    if not bearers:
        reasons.append("all_reviewers_hold_or_invalid")
    elif len(bearers) > 1 and max(bearers.values()) < 2:
        reasons.append("bearer_disagreement")
    else:
        reasons.append("fewer_than_two_agreeing_reviewers")
    if any(v == "invalid" for v in votes.values()):
        reasons.append("invalid_review_present")
    if len(votes) < 3:
        reasons.append("missing_review")
    return {"status": "held", "bearer_id": HOLD, "agreeing_reviewers": [], "dissenting_reviewers": [],
            "reasons": reasons}


def build_consensus(
    inventory: Path, review_paths: list[Path], out: Path, *, item_ids: set[str] | None = None
) -> dict[str, Any]:
    reviews = load_reviews(review_paths)
    reviewers = sorted(reviews)
    items = [json.loads(line) for line in inventory.open(encoding="utf-8") if line.strip()]
    if item_ids is not None:
        items = [item for item in items if item["item_id"] in item_ids]
    status_counts: Counter[str] = Counter()
    span_counts: Counter[str] = Counter()
    pair_stats: dict[str, Counter[str]] = {f"{a}~{b}": Counter() for a, b in combinations(reviewers, 2)}
    with out.open("w", encoding="utf-8") as handle:
        for item in items:
            votes = {
                reviewer: reviews[reviewer][item["item_id"]]["bearer_id"]
                for reviewer in reviewers
                if item["item_id"] in reviews[reviewer]
            }
            for a, b in combinations(reviewers, 2):
                if a in votes and b in votes and "invalid" not in (votes[a], votes[b]):
                    stats = pair_stats[f"{a}~{b}"]
                    stats["both_valid"] += 1
                    stats["exact"] += votes[a] == votes[b]
                    if votes[a] != HOLD and votes[b] != HOLD:
                        stats["both_bearer"] += 1
                        stats["both_bearer_same"] += votes[a] == votes[b]
                    if votes[a] != HOLD or votes[b] != HOLD:
                        stats["either_bearer"] += 1
                        stats["either_bearer_same"] += votes[a] == votes[b]
            decision = decide(votes)
            signature = json.dumps({"item_id": item["item_id"], "bearer_id": decision["bearer_id"]},
                                   sort_keys=True)
            row = {
                "schema_version": CONSENSUS_SCHEMA_VERSION,
                "item_id": item["item_id"],
                "target_kind": item["target_kind"],
                "votes": votes,
                "signature": signature,
                "signature_sha256": hashlib.sha256(signature.encode()).hexdigest(),
                **decision,
            }
            status_counts[decision["status"]] += 1
            span_counts[decision["status"]] += len(item["spans"])
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    agreement = {
        pair: {
            **dict(stats),
            "exact_rate": round(stats["exact"] / stats["both_valid"], 4) if stats["both_valid"] else None,
            "bearer_given_either_bearer_rate": (
                round(stats["either_bearer_same"] / stats["either_bearer"], 4)
                if stats["either_bearer"] else None
            ),
        }
        for pair, stats in pair_stats.items()
    }
    report = {
        "items": len(items),
        "reviewers": reviewers,
        "status_items": dict(status_counts),
        "status_spans": dict(span_counts),
        "pairwise_agreement": agreement,
        "vote_distribution": {
            reviewer: dict(Counter(
                "hold" if row["bearer_id"] == HOLD else "invalid" if row["bearer_id"] == "invalid"
                else "bearer" for row in reviews[reviewer].values()
                if item_ids is None or row["item_id"] in item_ids
            ))
            for reviewer in reviewers
        },
    }
    out.with_name(out.stem + "-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("inventory", type=Path)
    parser.add_argument("reviews", type=Path, nargs="+")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--item-ids", type=Path)
    args = parser.parse_args(argv)
    ids = None
    if args.item_ids:
        ids = {line.strip() for line in args.item_ids.open() if line.strip()}
    print(json.dumps(build_consensus(args.inventory, args.reviews, args.output, item_ids=ids), indent=2))


if __name__ == "__main__":
    main()
