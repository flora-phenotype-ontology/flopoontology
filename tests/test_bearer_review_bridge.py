from __future__ import annotations

import csv
import hashlib
import json

import pytest

from flopo2.verify.bearer_review_bridge import build_reviewer_b_packets


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _group(
    rank: int,
    group_key: str,
    candidate_po_id: str,
    evidence_count: int,
    decision: str,
) -> dict:
    return {
        "src_rank": str(rank),
        "src_group_key": group_key,
        "src_candidate_po_id": candidate_po_id,
        "src_evidence_count": str(evidence_count),
        "decision": decision,
        "confidence": "high",
        "recommended_po_id": candidate_po_id,
        "proposal_key": "",
        "preferred_label": group_key,
        "synonyms": "",
        "definition": "A machine proposal retained only for independent review.",
        "direct_superclass_ids": "PO_0009011",
        "superclass_justification": "Reviewer A proposal.",
        "parthood_relation": "none",
        "part_of_target_ids": "",
        "parthood_justification": "No universal relation proposed.",
        "senses_inspected": "fixture senses",
        "scope_note": "fixture scope",
        "evidence_note": "fixture evidence",
        "curation_notes": "unadjudicated",
        "source_register_ids": "TEST",
        "model_id": "reviewer-a-model",
        "tranche_id": f"T{rank}",
        "agent_id": f"agent-{rank}",
        # These human-facing source fields must not cross the bridge.
        "reviewer": "Human Name",
        "src_review_status": "accepted_existing_po",
    }


def _occurrence(
    occurrence_id: str,
    group_key: str,
    candidate_po_id: str,
    *,
    index: int,
    family: str,
    risk: str,
    reconciliation: str,
    language: str = "en",
    audit_method: str = "",
) -> dict:
    text = f"segment {index} white"
    start = text.index("white")
    candidates = [candidate_po_id] if candidate_po_id else []
    return {
        "occurrence_id": occurrence_id,
        "source_statement_id": f"statement-{index}",
        "source": "flora",
        "source_id": "volume.xml",
        "source_segment_index": index,
        "segment_document_start": index * 100,
        "segment_document_end": index * 100 + len(text),
        "taxon": "Planta exemplar",
        "organ": "description",
        "language": language,
        "text": text,
        "segment_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "previous_segment": None,
        "next_segment": None,
        "quality": {
            "start": start,
            "end": start + len("white"),
            "surface_form": "white",
            "candidate_pato_id": "PATO_0000323",
            "candidate_pato_label": "white",
            "extractor": "test",
            "reason": "missing_or_unsupported_bearer",
        },
        "clause": {"start": 0, "end": len(text), "text": text},
        "routing": {
            "group_key": group_key,
            "bearer_label": group_key,
            "disposition": "attachment_or_region_review",
            "family": "attachment_review",
            "candidate_po_id": candidate_po_id,
            "note": "inventory fixture",
        },
        "context_audit": {
            "candidate_po_id": candidate_po_id,
            "bearer_surface": group_key,
            "vocabulary_status": "",
            "attachment_status": "syntax_hold",
            "disposition": "retained",
            "method": audit_method,
        },
        "review": {
            "family": family,
            "risk_tier": risk,
            "reconciliation_status": reconciliation,
            "authoritative_po_id": candidate_po_id,
            "candidate_po_ids": candidates,
            "candidate_po_terms": [],
            "terminal_state": "pending_review",
            "decision": None,
        },
    }


def _write_jsonl(path, rows) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _fixtures(tmp_path, *, tsv: bool = False):
    groups = [
        _group(1, "unresolved_attachment", "", 3, "syntax_or_coreference_hold"),
        _group(2, "trichome", "PO_0000282", 1, "reuse_existing_po"),
    ]
    occurrences = [
        _occurrence(
            "occ-3",
            "unresolved_attachment",
            "",
            index=3,
            family="unresolved_contextual_bearer",
            risk="high_coreference",
            reconciliation="agree_review",
            audit_method="",
        ),
        _occurrence(
            "occ-1",
            "unresolved_attachment",
            "",
            index=1,
            family="attachment_review",
            risk="high_attachment_or_region",
            reconciliation="agree_review",
            language="fr",
            audit_method="heading_only",
        ),
        _occurrence(
            "occ-2",
            "unresolved_attachment",
            "",
            index=2,
            family="unresolved_contextual_bearer",
            risk="high_coreference",
            reconciliation="agree_review",
            audit_method="",
        ),
        _occurrence(
            "occ-4",
            "trichome",
            "PO_0000282",
            index=4,
            family="accepted_existing_po",
            risk="medium_atomic_safety_hold",
            reconciliation="agree_existing_same_po",
            audit_method="explicit_local",
        ),
    ]
    curation = tmp_path / ("curation.tsv" if tsv else "curation.jsonl")
    if tsv:
        with curation.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(groups[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(groups)
    else:
        _write_jsonl(curation, groups)
    occurrence_path = tmp_path / "occurrences.jsonl"
    _write_jsonl(occurrence_path, occurrences)
    return curation, occurrence_path, groups, occurrences


def _build(tmp_path, *, tsv: bool = False, suffix: str = ""):
    curation, occurrences, _groups, _rows = _fixtures(tmp_path, tsv=tsv)
    output = tmp_path / f"packets{suffix}.jsonl"
    report = tmp_path / f"report{suffix}.json"
    result = build_reviewer_b_packets(
        curation,
        occurrences,
        output,
        report,
        expected_curation_sha256=_sha256(curation),
        expected_occurrences_sha256=_sha256(occurrences),
        expected_groups=2,
        expected_occurrences=4,
        high_volume_threshold=3,
        max_packet_occurrences=1,
    )
    return output, report, result


@pytest.mark.parametrize("tsv", [False, True])
def test_bridge_is_occurrence_preserving_inventory_only_and_supports_tsv(tmp_path, tsv):
    output, report_path, report = _build(tmp_path, tsv=tsv)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 4
    assert {row["occurrence"]["occurrence_id"] for row in rows} == {
        "occ-1",
        "occ-2",
        "occ-3",
        "occ-4",
    }
    assert all(row["inventory_only"] is True for row in rows)
    assert all(row["reviewer_b_response"] is None for row in rows)
    assert all(row["occurrence"]["review"]["decision"] is None for row in rows)
    assert all(row["reviewer_a"]["status"] == "unadjudicated_reviewer_a_proposal" for row in rows)
    assert all("reviewer" not in row["reviewer_a"] for row in rows)
    assert all("review_status" not in output.read_text(encoding="utf-8") for _ in [0])
    held = [row for row in rows if row["routing_key"]["group_key"] == "unresolved_attachment"]
    assert all(row["flags"]["mixed_senses"] for row in held)
    assert all(row["flags"]["high_volume_hold"] for row in held)
    assert all(row["flags"]["split_recommended"] for row in held)
    assert all(row["packet_member_count"] == 1 for row in rows)
    assert report["coverage"]["one_row_per_occurrence"] is True
    assert report["splitting"]["mixed_sense_groups"] == 1
    assert report["splitting"]["high_volume_hold_groups"] == 1
    assert report["invariants"]["human_review_status_written"] is False
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_bridge_output_is_deterministic(tmp_path):
    output, _report, _result = _build(tmp_path, suffix="-one")
    curation = tmp_path / "curation.jsonl"
    occurrences = tmp_path / "occurrences.jsonl"
    second = tmp_path / "packets-two.jsonl"
    build_reviewer_b_packets(
        curation,
        occurrences,
        second,
        tmp_path / "report-two.json",
        expected_curation_sha256=_sha256(curation),
        expected_occurrences_sha256=_sha256(occurrences),
        expected_groups=2,
        expected_occurrences=4,
        high_volume_threshold=3,
        max_packet_occurrences=1,
    )
    assert output.read_bytes() == second.read_bytes()


def test_bridge_fails_closed_on_hash_drift_without_outputs(tmp_path):
    curation, occurrences, _groups, _rows = _fixtures(tmp_path)
    output = tmp_path / "packets.jsonl"
    report = tmp_path / "report.json"
    with pytest.raises(ValueError, match="SHA-256 drift"):
        build_reviewer_b_packets(
            curation,
            occurrences,
            output,
            report,
            expected_curation_sha256="0" * 64,
            expected_occurrences_sha256=_sha256(occurrences),
            expected_groups=2,
            expected_occurrences=4,
        )
    assert not output.exists()
    assert not report.exists()


def test_bridge_fails_closed_on_routing_key_and_evidence_drift(tmp_path):
    curation, occurrences, groups, rows = _fixtures(tmp_path)
    groups[0]["src_evidence_count"] = "2"
    _write_jsonl(curation, groups)
    with pytest.raises(ValueError, match="group evidence-count drift"):
        build_reviewer_b_packets(
            curation,
            occurrences,
            tmp_path / "packets-count.jsonl",
            tmp_path / "report-count.json",
            expected_curation_sha256=_sha256(curation),
            expected_occurrences_sha256=_sha256(occurrences),
            expected_groups=2,
            expected_occurrences=4,
        )

    groups[0]["src_evidence_count"] = "3"
    rows[0]["routing"]["group_key"] = "not-a-curated-group"
    _write_jsonl(curation, groups)
    _write_jsonl(occurrences, rows)
    with pytest.raises(ValueError, match="no Reviewer-A group"):
        build_reviewer_b_packets(
            curation,
            occurrences,
            tmp_path / "packets-key.jsonl",
            tmp_path / "report-key.json",
            expected_curation_sha256=_sha256(curation),
            expected_occurrences_sha256=_sha256(occurrences),
            expected_groups=2,
            expected_occurrences=4,
        )


def test_bridge_rejects_a_decided_occurrence_inventory(tmp_path):
    curation, occurrences, _groups, rows = _fixtures(tmp_path)
    rows[0]["review"]["decision"] = "accept"
    _write_jsonl(occurrences, rows)
    with pytest.raises(ValueError, match="inventory must be unadjudicated"):
        build_reviewer_b_packets(
            curation,
            occurrences,
            tmp_path / "packets.jsonl",
            tmp_path / "report.json",
            expected_curation_sha256=_sha256(curation),
            expected_occurrences_sha256=_sha256(occurrences),
            expected_groups=2,
            expected_occurrences=4,
        )
