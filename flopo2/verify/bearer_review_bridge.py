"""Build inventory-only Reviewer-B packets from bearer group proposals and occurrences.

The bridge never admits a Reviewer-A proposal. Matching uses only the original routing key
(``group_key``, ``candidate_po_id``), and every output row remains one source occurrence. Shared
packet identifiers merely let a later, independent reviewer process semantically homogeneous
occurrences together.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

CANONICAL_GROUP_COUNT = 388
CANONICAL_OCCURRENCE_COUNT = 42_725
PO_ID = re.compile(r"^PO_\d{7}$")
REVIEWER_A_DECISIONS = frozenset(
    {
        "reuse_existing_po",
        "reuse_existing_po_with_attachment",
        "propose_flopo_local_bearer",
        "not_an_anatomical_bearer",
        "syntax_or_coreference_hold",
        "semantic_ambiguity_hold",
    }
)
HOLD_DECISIONS = frozenset({"syntax_or_coreference_hold", "semantic_ambiguity_hold"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, not boolean")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an integer: {value!r}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


@dataclass(frozen=True, order=True)
class RoutingKey:
    """The only permitted join key between group proposals and occurrences."""

    group_key: str
    candidate_po_id: str

    @classmethod
    def from_group(cls, row: dict[str, Any]) -> RoutingKey:
        return cls(_text(row.get("src_group_key")), _text(row.get("src_candidate_po_id")))

    @classmethod
    def from_occurrence(cls, row: dict[str, Any]) -> RoutingKey:
        routing = row.get("routing")
        if not isinstance(routing, dict):
            raise ValueError("occurrence routing must be an object")
        return cls(_text(routing.get("group_key")), _text(routing.get("candidate_po_id")))

    def validate(self, *, where: str) -> None:
        if not self.group_key:
            raise ValueError(f"{where} has an empty routing group_key")
        if self.candidate_po_id and not PO_ID.fullmatch(self.candidate_po_id):
            raise ValueError(f"{where} has an invalid candidate PO id: {self.candidate_po_id!r}")

    def json(self) -> dict[str, str]:
        return {"group_key": self.group_key, "candidate_po_id": self.candidate_po_id}


@dataclass(frozen=True)
class ReviewerAGroup:
    rank: int
    key: RoutingKey
    evidence_count: int
    proposal: dict[str, Any]

    @classmethod
    def parse(cls, row: dict[str, Any], *, line_number: int) -> ReviewerAGroup:
        rank = _integer(row.get("src_rank"), f"curation row {line_number} src_rank")
        if rank < 1:
            raise ValueError(f"curation row {line_number} has invalid rank: {rank}")
        key = RoutingKey.from_group(row)
        key.validate(where=f"curation row {line_number}")
        evidence_count = _integer(
            row.get("src_evidence_count"), f"curation row {line_number} src_evidence_count"
        )
        if evidence_count < 1:
            raise ValueError(f"curation row {line_number} has no evidence")
        proposed_decision = _text(row.get("decision"))
        if proposed_decision not in REVIEWER_A_DECISIONS:
            raise ValueError(
                f"curation row {line_number} has invalid Reviewer-A proposal: "
                f"{proposed_decision!r}"
            )
        model_id = _text(row.get("model_id"))
        if not model_id:
            raise ValueError(f"curation row {line_number} lacks machine model provenance")
        proposal = {
            "status": "unadjudicated_reviewer_a_proposal",
            "source_rank": rank,
            "proposed_decision": proposed_decision,
            "confidence": _text(row.get("confidence")),
            "recommended_po_id": _text(row.get("recommended_po_id")),
            "proposal_key": _text(row.get("proposal_key")),
            "preferred_label": _text(row.get("preferred_label")),
            "synonyms": _text(row.get("synonyms")),
            "definition": _text(row.get("definition")),
            "direct_superclass_ids": _text(row.get("direct_superclass_ids")),
            "superclass_justification": _text(row.get("superclass_justification")),
            "parthood_relation": _text(row.get("parthood_relation")),
            "part_of_target_ids": _text(row.get("part_of_target_ids")),
            "parthood_justification": _text(row.get("parthood_justification")),
            "senses_inspected": _text(row.get("senses_inspected")),
            "scope_note": _text(row.get("scope_note")),
            "evidence_note": _text(row.get("evidence_note")),
            "curation_notes": _text(row.get("curation_notes")),
            "source_register_ids": _text(row.get("source_register_ids")),
            "machine_provenance": {
                "model_id": model_id,
                "tranche_id": _text(row.get("tranche_id")),
                "agent_id": _text(row.get("agent_id")),
            },
        }
        return cls(rank=rank, key=key, evidence_count=evidence_count, proposal=proposal)


@dataclass(frozen=True, order=True)
class SenseKey:
    """Occurrence-level semantics that must not be collapsed into one review packet."""

    review_family: str
    risk_tier: str
    reconciliation_status: str
    authoritative_po_id: str
    candidate_po_ids: tuple[str, ...]
    audit_candidate_po_id: str
    audit_method: str
    attachment_status: str
    vocabulary_status: str
    language: str

    @classmethod
    def from_occurrence(cls, row: dict[str, Any]) -> SenseKey:
        review = row.get("review")
        audit = row.get("context_audit")
        if not isinstance(review, dict) or not isinstance(audit, dict):
            raise ValueError("occurrence review and context_audit must be objects")
        candidates = review.get("candidate_po_ids", []) or []
        if not isinstance(candidates, list) or any(not isinstance(value, str) for value in candidates):
            raise ValueError("occurrence review.candidate_po_ids must be a string list")
        return cls(
            review_family=_text(review.get("family")),
            risk_tier=_text(review.get("risk_tier")),
            reconciliation_status=_text(review.get("reconciliation_status")),
            authoritative_po_id=_text(review.get("authoritative_po_id")),
            candidate_po_ids=tuple(candidates),
            audit_candidate_po_id=_text(audit.get("candidate_po_id")),
            audit_method=_text(audit.get("method")),
            attachment_status=_text(audit.get("attachment_status")),
            vocabulary_status=_text(audit.get("vocabulary_status")),
            language=_text(row.get("language")),
        )

    def json(self) -> dict[str, Any]:
        return {
            "review_family": self.review_family,
            "risk_tier": self.risk_tier,
            "reconciliation_status": self.reconciliation_status,
            "authoritative_po_id": self.authoritative_po_id,
            "candidate_po_ids": list(self.candidate_po_ids),
            "audit_candidate_po_id": self.audit_candidate_po_id,
            "audit_method": self.audit_method,
            "attachment_status": self.attachment_status,
            "vocabulary_status": self.vocabulary_status,
            "language": self.language,
        }


@dataclass(frozen=True)
class OccurrenceMeta:
    occurrence_id: str
    key: RoutingKey
    sense: SenseKey
    coordinate: tuple[str, str, int, int, int]
    quality_id: str
    organ: str


@dataclass
class GroupStats:
    occurrences: int = 0
    senses: set[SenseKey] | None = None
    risks: Counter[str] | None = None
    qualities: set[str] | None = None
    organs: set[str] | None = None

    def __post_init__(self) -> None:
        self.senses = set()
        self.risks = Counter()
        self.qualities = set()
        self.organs = set()

    def add(self, meta: OccurrenceMeta) -> None:
        assert self.senses is not None
        assert self.risks is not None
        assert self.qualities is not None
        assert self.organs is not None
        self.occurrences += 1
        self.senses.add(meta.sense)
        self.risks[meta.sense.risk_tier] += 1
        self.qualities.add(meta.quality_id)
        self.organs.add(meta.organ)


def _read_curation(path: Path) -> Iterator[dict[str, Any]]:
    if Path(path).suffix.casefold() == ".tsv":
        with Path(path).open(encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle, delimiter="\t")
        return
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid curation JSON at {path}:{line_number}: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"curation row {line_number} is not an object")
            yield row


def _read_occurrences(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid occurrence JSON at {path}:{line_number}: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"occurrence row {line_number} is not an object")
            yield line_number, row


def _occurrence_meta(row: dict[str, Any], *, line_number: int) -> OccurrenceMeta:
    occurrence_id = _text(row.get("occurrence_id"))
    if not occurrence_id:
        raise ValueError(f"occurrence row {line_number} lacks occurrence_id")
    key = RoutingKey.from_occurrence(row)
    key.validate(where=f"occurrence row {line_number}")
    review = row.get("review")
    quality = row.get("quality")
    if not isinstance(review, dict) or not isinstance(quality, dict):
        raise ValueError(f"occurrence row {line_number} lacks review or quality object")
    if review.get("decision") is not None:
        raise ValueError(
            f"occurrence row {line_number} contains a decision; inventory must be unadjudicated"
        )
    start = _integer(quality.get("start"), f"occurrence row {line_number} quality.start")
    end = _integer(quality.get("end"), f"occurrence row {line_number} quality.end")
    if start < 0 or end <= start:
        raise ValueError(f"occurrence row {line_number} has invalid quality offsets")
    coordinate = (
        _text(row.get("source")),
        _text(row.get("source_id")),
        _integer(row.get("source_segment_index"), f"occurrence row {line_number} segment index"),
        start,
        end,
    )
    if not coordinate[0] or not coordinate[1]:
        raise ValueError(f"occurrence row {line_number} lacks source identity")
    return OccurrenceMeta(
        occurrence_id=occurrence_id,
        key=key,
        sense=SenseKey.from_occurrence(row),
        coordinate=coordinate,
        quality_id=_text(quality.get("candidate_pato_id")),
        organ=_text(row.get("organ")),
    )


def _validate_hash(path: Path, expected: str, label: str) -> str:
    expected = expected.casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"expected {label} SHA-256 must be 64 lowercase hexadecimal characters")
    observed = _sha256(path)
    if observed != expected:
        raise ValueError(f"{label} SHA-256 drift: expected {expected}, observed {observed}")
    return observed


def _load_groups(path: Path, expected_count: int) -> dict[RoutingKey, ReviewerAGroup]:
    groups: dict[RoutingKey, ReviewerAGroup] = {}
    ranks: set[int] = set()
    for line_number, row in enumerate(_read_curation(path), start=1):
        group = ReviewerAGroup.parse(row, line_number=line_number)
        if group.rank in ranks:
            raise ValueError(f"duplicate Reviewer-A rank: {group.rank}")
        if group.key in groups:
            raise ValueError(f"duplicate Reviewer-A routing key: {group.key}")
        ranks.add(group.rank)
        groups[group.key] = group
    if len(groups) != expected_count:
        raise ValueError(f"Reviewer-A group count drift: expected {expected_count}, observed {len(groups)}")
    return groups


def _scan_occurrences(
    path: Path,
    groups: dict[RoutingKey, ReviewerAGroup],
    expected_count: int,
) -> tuple[
    dict[RoutingKey, GroupStats],
    dict[tuple[RoutingKey, SenseKey], list[str]],
    Counter[str],
]:
    stats: dict[RoutingKey, GroupStats] = defaultdict(GroupStats)
    members: dict[tuple[RoutingKey, SenseKey], list[str]] = defaultdict(list)
    risks: Counter[str] = Counter()
    occurrence_ids: set[str] = set()
    coordinates: set[tuple[str, str, int, int, int]] = set()
    count = 0
    for line_number, row in _read_occurrences(path):
        meta = _occurrence_meta(row, line_number=line_number)
        if meta.occurrence_id in occurrence_ids:
            raise ValueError(f"duplicate occurrence_id: {meta.occurrence_id}")
        if meta.coordinate in coordinates:
            raise ValueError(f"duplicate occurrence coordinate: {meta.coordinate!r}")
        if meta.key not in groups:
            raise ValueError(f"occurrence routing key has no Reviewer-A group: {meta.key}")
        occurrence_ids.add(meta.occurrence_id)
        coordinates.add(meta.coordinate)
        stats[meta.key].add(meta)
        members[(meta.key, meta.sense)].append(meta.occurrence_id)
        risks[meta.sense.risk_tier] += 1
        count += 1
    if count != expected_count:
        raise ValueError(f"occurrence count drift: expected {expected_count}, observed {count}")
    missing = sorted(set(groups) - set(stats))
    if missing:
        raise ValueError(f"Reviewer-A groups without occurrences: {missing[:5]!r}")
    mismatches = [
        (key, groups[key].evidence_count, stats[key].occurrences)
        for key in sorted(groups)
        if groups[key].evidence_count != stats[key].occurrences
    ]
    if mismatches:
        raise ValueError(f"group evidence-count drift: {mismatches[:5]!r}")
    return dict(stats), dict(members), risks


def _atomic_paths(paths: list[Path]) -> list[Path]:
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError("curation, occurrence, packet, and report paths must all be distinct")
    return resolved


def build_reviewer_b_packets(
    curation_path: Path,
    occurrences_path: Path,
    output_path: Path,
    report_path: Path,
    *,
    expected_curation_sha256: str,
    expected_occurrences_sha256: str,
    expected_groups: int = CANONICAL_GROUP_COUNT,
    expected_occurrences: int = CANONICAL_OCCURRENCE_COUNT,
    high_volume_threshold: int = 500,
    max_packet_occurrences: int = 200,
) -> dict[str, Any]:
    """Build occurrence-preserving packets after strict hash, key, and count validation."""

    if expected_groups < 1 or expected_occurrences < 1:
        raise ValueError("expected counts must be positive")
    if high_volume_threshold < 1 or max_packet_occurrences < 1:
        raise ValueError("volume and packet thresholds must be positive")
    curation_path = Path(curation_path)
    occurrences_path = Path(occurrences_path)
    output_path = Path(output_path)
    report_path = Path(report_path)
    _atomic_paths([curation_path, occurrences_path, output_path, report_path])
    curation_hash = _validate_hash(
        curation_path, expected_curation_sha256, "Reviewer-A curation"
    )
    occurrences_hash = _validate_hash(
        occurrences_path, expected_occurrences_sha256, "bearer occurrences"
    )
    groups = _load_groups(curation_path, expected_groups)
    group_stats, members, risks = _scan_occurrences(
        occurrences_path, groups, expected_occurrences
    )

    # Assign a stable shard and member index independently of input row order.
    membership: dict[str, tuple[SenseKey, int, int, int]] = {}
    packet_sizes: Counter[str] = Counter()
    for (key, sense), ids in sorted(members.items()):
        ordered = sorted(ids)
        for position, occurrence_id in enumerate(ordered):
            shard = position // max_packet_occurrences
            shard_start = shard * max_packet_occurrences
            shard_size = min(max_packet_occurrences, len(ordered) - shard_start)
            membership[occurrence_id] = (sense, shard, position - shard_start, shard_size)
            packet_id = _stable_id("reviewer-b-packet", [key.json(), sense.json(), shard])
            packet_sizes[packet_id] += 1

    mixed_groups = {
        key for key, value in group_stats.items() if value.senses is not None and len(value.senses) > 1
    }
    high_volume_holds = {
        key
        for key, value in group_stats.items()
        if value.occurrences >= high_volume_threshold
        and groups[key].proposal["proposed_decision"] in HOLD_DECISIONS
    }
    split_groups = mixed_groups | high_volume_holds

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_fd, output_tmp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    report_fd, report_tmp_name = tempfile.mkstemp(
        prefix=f".{report_path.name}.", suffix=".tmp", dir=report_path.parent
    )
    output_tmp = Path(output_tmp_name)
    report_tmp = Path(report_tmp_name)
    os.close(output_fd)
    os.close(report_fd)
    try:
        written = 0
        with output_tmp.open("w", encoding="utf-8") as output:
            for line_number, occurrence in _read_occurrences(occurrences_path):
                meta = _occurrence_meta(occurrence, line_number=line_number)
                sense, shard, member_index, member_count = membership[meta.occurrence_id]
                packet_id = _stable_id(
                    "reviewer-b-packet", [meta.key.json(), sense.json(), shard]
                )
                stats = group_stats[meta.key]
                flags = {
                    "mixed_senses": meta.key in mixed_groups,
                    "high_volume_hold": meta.key in high_volume_holds,
                    "split_recommended": meta.key in split_groups,
                    "split_reasons": [
                        reason
                        for condition, reason in (
                            (meta.key in mixed_groups, "mixed_occurrence_senses"),
                            (meta.key in high_volume_holds, "high_volume_reviewer_a_hold"),
                        )
                        if condition
                    ],
                }
                row = {
                    "schema_version": 1,
                    "inventory_only": True,
                    "packet_id": packet_id,
                    "packet_shard": shard,
                    "packet_member_index": member_index,
                    "packet_member_count": member_count,
                    "routing_key": meta.key.json(),
                    "occurrence_safe_grouping": sense.json(),
                    "group_inventory": {
                        "occurrences": stats.occurrences,
                        "sense_count": len(stats.senses or ()),
                        "quality_count": len(stats.qualities or ()),
                        "organ_count": len(stats.organs or ()),
                    },
                    "flags": flags,
                    "reviewer_a": groups[meta.key].proposal,
                    "reviewer_b_response": None,
                    "occurrence": occurrence,
                }
                output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                written += 1
        if written != expected_occurrences:
            raise ValueError(
                f"packet conservation failed: expected {expected_occurrences}, wrote {written}"
            )
        output_hash = _sha256(output_tmp)
        proposal_counts = Counter(
            str(group.proposal["proposed_decision"]) for group in groups.values()
        )
        report: dict[str, Any] = {
            "schema_version": 1,
            "inventory_only": True,
            "inputs": {
                "reviewer_a_curation": {
                    "path": str(curation_path.resolve()),
                    "sha256": curation_hash,
                    "groups": len(groups),
                },
                "bearer_occurrences": {
                    "path": str(occurrences_path.resolve()),
                    "sha256": occurrences_hash,
                    "occurrences": expected_occurrences,
                },
            },
            "output": {
                "path": str(output_path.resolve()),
                "sha256": output_hash,
                "occurrence_rows": written,
                "packets": len(packet_sizes),
                "maximum_packet_size": max(packet_sizes.values(), default=0),
            },
            "coverage": {
                "matched_groups": len(group_stats),
                "matched_occurrences": written,
                "unmatched_groups": 0,
                "unmatched_occurrences": 0,
                "group_evidence_counts_exact": True,
                "one_row_per_occurrence": True,
            },
            "reviewer_a_proposals_not_admitted": dict(sorted(proposal_counts.items())),
            "risk_tiers": dict(sorted(risks.items())),
            "splitting": {
                "high_volume_threshold": high_volume_threshold,
                "max_packet_occurrences": max_packet_occurrences,
                "mixed_sense_groups": len(mixed_groups),
                "mixed_sense_occurrences": sum(group_stats[key].occurrences for key in mixed_groups),
                "high_volume_hold_groups": len(high_volume_holds),
                "high_volume_hold_occurrences": sum(
                    group_stats[key].occurrences for key in high_volume_holds
                ),
                "split_recommended_groups": len(split_groups),
                "split_recommended_occurrences": sum(
                    group_stats[key].occurrences for key in split_groups
                ),
            },
            "invariants": {
                "hashes_pinned": True,
                "routing_key_only_join": True,
                "occurrence_inventory_unadjudicated": True,
                "reviewer_b_responses_blank": True,
                "ontology_or_config_written": False,
                "human_review_status_written": False,
            },
        }
        report_tmp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(output_tmp, output_path)
        os.replace(report_tmp, report_path)
        return report
    except BaseException:
        output_tmp.unlink(missing_ok=True)
        report_tmp.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("curation", type=Path, help="validated Reviewer-A bearer curation JSONL/TSV")
    parser.add_argument("occurrences", type=Path, help="inventory-only bearer occurrence JSONL")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-curation-sha256", required=True)
    parser.add_argument("--expected-occurrences-sha256", required=True)
    parser.add_argument("--expect-groups", type=int, default=CANONICAL_GROUP_COUNT)
    parser.add_argument("--expect-occurrences", type=int, default=CANONICAL_OCCURRENCE_COUNT)
    parser.add_argument("--high-volume-threshold", type=int, default=500)
    parser.add_argument("--max-packet-occurrences", type=int, default=200)
    args = parser.parse_args()
    result = build_reviewer_b_packets(
        args.curation,
        args.occurrences,
        args.output,
        args.report,
        expected_curation_sha256=args.expected_curation_sha256,
        expected_occurrences_sha256=args.expected_occurrences_sha256,
        expected_groups=args.expect_groups,
        expected_occurrences=args.expect_occurrences,
        high_volume_threshold=args.high_volume_threshold,
        max_packet_occurrences=args.max_packet_occurrences,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
