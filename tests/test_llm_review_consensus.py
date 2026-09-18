import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flopo2.review.adversarial import build_adversarial_batches
from flopo2.review.consensus import build_consensus
from flopo2.review.io import read_jsonl
from flopo2.review.models import (
    AdversarialVerdict,
    ConsensusDecision,
    LedgerEntry,
    EvidenceRecord,
    Occurrence,
    ReviewDecision,
    ReviewBatchResponse,
)
from flopo2.review.report import campaign_report
from flopo2.review.responses import ingest_response, write_response_schemas
from test_llm_review_inventory import campaign_fixture


def _prompt(manifest, prompt_id="reviewer"):
    return next(row for row in manifest.prompts if row.prompt_id == prompt_id)


def _review(
    manifest,
    occurrence,
    reviewer_id,
    *,
    disposition="existing_term_mapping",
    signature=None,
    authority_id=None,
):
    model = next(row for row in manifest.models if row.reviewer_id == reviewer_id)
    prompt = _prompt(manifest)
    return ReviewDecision(
        campaign_id=manifest.campaign_id,
        item_id=occurrence.cluster_id,
        reviewer_id=reviewer_id,
        provider=model.provider,
        model=model.model,
        model_family=model.model_family,
        reasoning_effort=model.reasoning_effort,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        disposition=disposition,
        proposed_signature=signature
        or {
            "kind": "existing_term_mapping",
            "target_id": "PATO_0000322",
            "target_scope": "quality",
        },
        rationale="Grounded in the supplied ontology snapshot.",
        confidence=0.95,
        evidence_ids=tuple(
            item for item in (occurrence.evidence_id, authority_id) if item is not None
        ),
        validation_passed=True,
    )


def _adversary(manifest, review, occurrence, *, verdict="no_blocker"):
    model = next(row for row in manifest.models if row.reviewer_id == "adversary")
    prompt = _prompt(manifest, "adversarial")
    return AdversarialVerdict(
        campaign_id=manifest.campaign_id,
        item_id=review.item_id,
        reviewer_id=model.reviewer_id,
        provider=model.provider,
        model=model.model,
        model_family=model.model_family,
        reasoning_effort=model.reasoning_effort,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        candidate_signature_sha256=review.signature_sha256,
        verdict=verdict,
        rationale="No scope, parentage, or evidence blocker found.",
        evidence_ids=(occurrence.evidence_id,),
        validation_passed=True,
    )


def _write(path: Path, rows) -> None:
    path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")


def _run(tmp_path, manifest, occurrences, clusters, evidence, reviews, adjudications=()):
    review_path = tmp_path / "reviews.jsonl"
    adjudication_path = tmp_path / "adjudications.jsonl"
    _write(review_path, reviews)
    _write(adjudication_path, adjudications)
    consensus = tmp_path / "consensus.jsonl"
    exceptions = tmp_path / "exceptions.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    counts = build_consensus(
        manifest=manifest,
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        review_paths=[review_path],
        adjudication_paths=[adjudication_path],
        consensus_path=consensus,
        exception_path=exceptions,
        ledger_path=ledger,
    )
    return counts, consensus, exceptions, ledger


def test_exact_normalized_signature_consensus_and_conservation(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    occurrence = next(read_jsonl(occurrences, Occurrence))
    item_id = occurrence.cluster_id
    reviews = [
        _review(manifest, occurrence, "claude"),
        _review(manifest, occurrence, "gpt"),
    ]
    counts, consensus_path, exceptions_path, ledger_path = _run(
        tmp_path, manifest, occurrences, clusters, evidence, reviews
    )
    decisions = list(read_jsonl(consensus_path, ConsensusDecision))
    agreed = next(row for row in decisions if row.item_id == item_id)
    assert agreed.status == "llm_consensus"
    assert agreed.normalized_signature == (
        '{"kind":"existing_term_mapping","target_id":"PATO_0000322",'
        '"target_scope":"quality"}'
    )
    assert counts == {"held": 2, "llm_consensus": 2}
    assert all(row.status != "llm_consensus" for row in read_jsonl(exceptions_path, ConsensusDecision))
    ledger = list(read_jsonl(ledger_path, LedgerEntry))
    assert len(ledger) == manifest.starting_occurrences
    assert len({row.occurrence_id for row in ledger}) == manifest.starting_occurrences


def test_malformed_and_duplicate_model_results_are_rejected(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    occurrence = next(read_jsonl(occurrences, Occurrence))
    review = _review(manifest, occurrence, "claude")
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text('{"item_id": "broken"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid ReviewDecision"):
        build_consensus(
            manifest=manifest,
            occurrence_path=occurrences,
            cluster_path=clusters,
            evidence_path=evidence,
            review_paths=[malformed],
            consensus_path=tmp_path / "c.jsonl",
            exception_path=tmp_path / "e.jsonl",
            ledger_path=tmp_path / "l.jsonl",
        )
    duplicate = tmp_path / "duplicate.jsonl"
    _write(duplicate, [review, review])
    with pytest.raises(ValueError, match="duplicate ReviewDecision"):
        build_consensus(
            manifest=manifest,
            occurrence_path=occurrences,
            cluster_path=clusters,
            evidence_path=evidence,
            review_paths=[duplicate],
            consensus_path=tmp_path / "c2.jsonl",
            exception_path=tmp_path / "e2.jsonl",
            ledger_path=tmp_path / "l2.jsonl",
        )


def test_same_model_family_is_not_independent_and_disagreement_is_disputed(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    occurrence = next(read_jsonl(occurrences, Occurrence))
    item_id = occurrence.cluster_id
    same_family = [
        _review(manifest, occurrence, "gpt"),
        _review(manifest, occurrence, "gpt-same-family"),
    ]
    _, consensus_path, _, _ = _run(
        tmp_path, manifest, occurrences, clusters, evidence, same_family
    )
    row = next(row for row in read_jsonl(consensus_path, ConsensusDecision) if row.item_id == item_id)
    assert row.status == "llm_disputed"
    assert row.reasons == ("reviewers_not_independent",)

    disagreement = [
        _review(manifest, occurrence, "claude"),
        _review(
            manifest,
            occurrence,
            "gpt",
            signature={
                "kind": "existing_term_mapping",
                "target_id": "PATO_0000318",
                "target_scope": "quality",
            },
        ),
    ]
    other = tmp_path / "other"
    other.mkdir()
    _, consensus_path, _, _ = _run(
        other, manifest, occurrences, clusters, evidence, disagreement
    )
    row = next(row for row in read_jsonl(consensus_path, ConsensusDecision) if row.item_id == item_id)
    assert row.status == "llm_disputed"
    assert row.reasons == ("normalized_signature_disagreement",)


def test_reusable_class_requires_independent_adversarial_no_blocker(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    occurrence = next(read_jsonl(occurrences, Occurrence))
    item_id = occurrence.cluster_id
    authority_id = next(
        row.evidence_id
        for row in read_jsonl(evidence, EvidenceRecord)
        if row.kind == "authority"
    )
    signature = {
        "kind": "reusable_flopo_class",
        "label": "red leaf phenotype",
        "definition": "A phenotype in which a leaf has a red colour quality.",
        "expression": {
            "bearer_id": "PO_0009025",
            "quality_id": "PATO_0000322",
        },
        "parent_ids": ["FLOPO_0000001"],
        "authoritative_evidence_ids": [authority_id],
    }
    reviews = [
        _review(
            manifest,
            occurrence,
            "claude",
            disposition="reusable_flopo_class",
            signature=signature,
            authority_id=authority_id,
        ),
        _review(
            manifest,
            occurrence,
            "gpt",
            disposition="reusable_flopo_class",
            signature=signature,
            authority_id=authority_id,
        ),
    ]
    review_artifact = tmp_path / "reusable-reviews.jsonl"
    _write(review_artifact, reviews)
    adversarial_index = build_adversarial_batches(
        manifest=manifest,
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        review_paths=[review_artifact],
        output_dir=tmp_path / "adversarial-packets",
    )
    assert adversarial_index["item_count"] == 1
    packet = json.loads(
        (tmp_path / "adversarial-packets" / "batch-00001.json").read_text()
    )
    candidate = packet["items"][0]
    assert candidate["candidate_signature"] == json.loads(reviews[0].normalized_signature)
    assert candidate["candidate_signature_sha256"] == reviews[0].signature_sha256
    assert {row["reviewer_id"] for row in candidate["reviewers"]} == {"claude", "gpt"}
    assert all(row["rationale"] and row["evidence_ids"] for row in candidate["reviewers"])
    _, consensus_path, _, _ = _run(
        tmp_path, manifest, occurrences, clusters, evidence, reviews
    )
    row = next(row for row in read_jsonl(consensus_path, ConsensusDecision) if row.item_id == item_id)
    assert row.status == "held"
    assert row.reasons == ("missing_adversarial_verdict",)

    accepted = tmp_path / "accepted"
    accepted.mkdir()
    _, consensus_path, _, _ = _run(
        accepted,
        manifest,
        occurrences,
        clusters,
        evidence,
        reviews,
        [_adversary(manifest, reviews[0], occurrence)],
    )
    row = next(row for row in read_jsonl(consensus_path, ConsensusDecision) if row.item_id == item_id)
    assert row.status == "llm_consensus"
    assert row.adjudicator_id == "adversary"

    blocked = tmp_path / "blocked"
    blocked.mkdir()
    _, consensus_path, _, _ = _run(
        blocked,
        manifest,
        occurrences,
        clusters,
        evidence,
        reviews,
        [_adversary(manifest, reviews[0], occurrence, verdict="block")],
    )
    row = next(row for row in read_jsonl(consensus_path, ConsensusDecision) if row.item_id == item_id)
    assert row.status == "held"
    assert row.reasons == ("adversarial_blocker",)


def test_machine_schema_forbids_human_review_status_and_orcid(tmp_path):
    manifest, occurrences, _, _, _ = campaign_fixture(tmp_path)
    occurrence = next(read_jsonl(occurrences, Occurrence))
    payload = _review(manifest, occurrence, "claude").model_dump()
    payload["review_status"] = "reviewed"
    payload["curator_orcid"] = "https://orcid.org/0000-0001-8149-5890"
    payload["proposed_signature"]["curator_orcid"] = (
        "https://orcid.org/0000-0001-8149-5890"
    )
    with pytest.raises(ValidationError) as error:
        ReviewDecision.model_validate(payload)
    message = str(error.value)
    assert "review_status" in message
    assert "curator_orcid" in message


def test_local_validation_rejects_dead_terms_and_invented_evidence(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    occurrence_rows = list(read_jsonl(occurrences, Occurrence))
    occurrence = occurrence_rows[0]
    dead_signature = {
        "kind": "existing_term_mapping",
        "target_id": "PATO_9999999",
        "target_scope": "quality",
    }
    reviews = [
        _review(manifest, occurrence, "claude", signature=dead_signature),
        _review(manifest, occurrence, "gpt", signature=dead_signature),
    ]
    _, consensus_path, _, _ = _run(
        tmp_path, manifest, occurrences, clusters, evidence, reviews
    )
    row = next(
        row
        for row in read_jsonl(consensus_path, ConsensusDecision)
        if row.item_id == occurrence.cluster_id
    )
    assert row.status == "held"
    assert "mapping_target_not_live" in row.reasons

    other_occurrence = next(
        row for row in occurrence_rows if row.cluster_id != occurrence.cluster_id
    )
    crossed = [
        _review(manifest, occurrence, "claude").model_copy(
            update={"evidence_ids": (other_occurrence.evidence_id,)}
        ),
        _review(manifest, occurrence, "gpt").model_copy(
            update={"evidence_ids": (other_occurrence.evidence_id,)}
        ),
    ]
    crossed_dir = tmp_path / "crossed"
    crossed_dir.mkdir()
    _, consensus_path, _, _ = _run(
        crossed_dir, manifest, occurrences, clusters, evidence, crossed
    )
    row = next(
        row
        for row in read_jsonl(consensus_path, ConsensusDecision)
        if row.item_id == occurrence.cluster_id
    )
    assert row.status == "held"
    assert "cross_item_evidence" in row.reasons


def test_no_decisions_still_conserves_every_occurrence_as_held(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    counts, _, exceptions, ledger_path = _run(
        tmp_path, manifest, occurrences, clusters, evidence, []
    )
    ledger = list(read_jsonl(ledger_path, LedgerEntry))
    assert counts == {"held": manifest.starting_occurrences}
    assert len(ledger) == manifest.starting_occurrences
    assert {row.status for row in ledger} == {"held"}
    assert len(list(read_jsonl(exceptions, ConsensusDecision))) == manifest.starting_clusters

    report = campaign_report(
        manifest,
        occurrences,
        clusters,
        evidence,
        tmp_path / "consensus.jsonl",
        ledger_path,
    )
    assert report["integrity_ok"] is True
    assert report["review_complete"] is False
    assert report["ok"] is False
    assert report["conservation"] == {
        "ledger_rows": manifest.starting_occurrences,
        "unique_occurrences": manifest.starting_occurrences,
        "complete": True,
    }

    # Conservation by ID alone is insufficient: a fabricated cross-cluster ledger route fails.
    rows = list(read_jsonl(ledger_path, LedgerEntry))
    other_item = next(row.item_id for row in rows if row.item_id != rows[0].item_id)
    rows[0] = rows[0].model_copy(update={"item_id": other_item})
    fabricated = tmp_path / "fabricated-ledger.jsonl"
    _write(fabricated, rows)
    fabricated_report = campaign_report(
        manifest,
        occurrences,
        clusters,
        evidence,
        tmp_path / "consensus.jsonl",
        fabricated,
    )
    assert fabricated_report["conservation"]["complete"] is True
    assert fabricated_report["integrity_ok"] is False
    assert fabricated_report["ok"] is False


def test_external_response_schema_and_ingestion_are_strict(tmp_path):
    manifest, occurrences, _, _, _ = campaign_fixture(tmp_path)
    occurrence = next(read_jsonl(occurrences, Occurrence))
    response = ReviewBatchResponse(
        decisions=(
            _review(manifest, occurrence, "claude"),
            _review(manifest, occurrence, "gpt"),
        )
    )
    response_path = tmp_path / "response.json"
    response_path.write_text(response.model_dump_json(), encoding="utf-8")
    output = tmp_path / "reviews.jsonl"
    assert ingest_response(response_path, output, role="reviewer") == 2
    assert len(list(read_jsonl(output, ReviewDecision))) == 2
    review_schema = tmp_path / "review-schema.json"
    adversarial_schema = tmp_path / "adversarial-schema.json"
    write_response_schemas(review_schema, adversarial_schema)
    assert json.loads(review_schema.read_text())["additionalProperties"] is False

    bad = tmp_path / "bad-response.json"
    bad.write_text('{"decisions":[{"review_status":"reviewed"}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid reviewer response"):
        ingest_response(bad, tmp_path / "bad.jsonl", role="reviewer")
