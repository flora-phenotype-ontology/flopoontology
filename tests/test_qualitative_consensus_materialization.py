from __future__ import annotations

import json
from datetime import datetime, timezone

from flopo2.review.consensus import build_consensus
from flopo2.review.inventory import build_inventory, model_spec
from flopo2.review.io import read_jsonl, sha256_file
from flopo2.review.models import Occurrence, ReviewDecision


TEXT = "Leaves ovate to lanceolate."


def _candidate():
    return {
        "signature": {
            "bearer_id": "PO_0009025",
            "attribute_id": "PATO_0000052",
            "interpretation": "continuum",
            "from_value": "PATO_0001891",
            "to_value": "PATO_0001877",
        },
        "bearer_method": "explicit_local_mention",
        "bearer_text": "Leaves",
        "bearer_start": 0,
        "bearer_end": 6,
        "expression_start": 7,
        "expression_end": 26,
        "expression_text": "ovate to lanceolate",
        "from_text": "ovate",
        "from_start": 7,
        "from_end": 12,
        "connector_text": "to",
        "connector_start": 13,
        "connector_end": 15,
        "to_text": "lanceolate",
        "to_start": 16,
        "to_end": 26,
        "clear_unresolved_spans": [[7, 12], [16, 26]],
    }


def _stage_record():
    return {
        "source": "fixture",
        "source_id": "flora.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplaris",
        "organ": "leaves",
        "language": "en",
        "char_start": 100,
        "char_end": 100 + len(TEXT),
        "text": TEXT,
        "source_statements": [],
        "term_mentions": [],
        "assertions": [],
        "unresolved_spans": [
            {
                "start": 7,
                "end": 12,
                "surface_form": "ovate",
                "reason": "unsupported_alternative_or_transition",
                "candidate_pato_id": "PATO_0001891",
                "extractor": "fixture",
            },
            {
                "start": 16,
                "end": 26,
                "surface_form": "lanceolate",
                "reason": "unsupported_alternative_or_transition",
                "candidate_pato_id": "PATO_0001877",
                "extractor": "fixture",
            },
        ],
    }


def _campaign(tmp_path, *, second_holds: bool = False, omit_second: bool = False):
    stage = tmp_path / "stage13.jsonl"
    stage.write_text(json.dumps(_stage_record()) + "\n", encoding="utf-8")
    review_record = {
        **_stage_record(),
        "source_statements": [],
        "assertions": [],
        "unresolved_spans": [
            {
                "start": 7,
                "end": 26,
                "surface_form": "ovate to lanceolate",
                "reason": "qualitative_value_relation_candidate",
                "candidate_pato_id": "PATO_0000052",
                "pending_bearer": "PO_0009025",
                "extractor": "qualitative_relation_candidate_v1",
                "qualitative_relation_candidate": _candidate(),
            }
        ],
    }
    review_input = tmp_path / "review-input.jsonl"
    review_input.write_text(json.dumps(review_record) + "\n", encoding="utf-8")
    po = tmp_path / "po_lexicon.tsv"
    po.write_text("id\tlabel\nPO_0009025\tvascular leaf\n", encoding="utf-8")
    pato = tmp_path / "pato_lexicon.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_0000052\tshape\tattribute_slim\n"
        "PATO_0001891\tovate\tshape_slim\n"
        "PATO_0001877\tlanceolate\tshape_slim\n",
        encoding="utf-8",
    )
    registry = tmp_path / "flopo_id_registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n", encoding="utf-8"
    )
    combinations = tmp_path / "valid_combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0009025\tPATO_0000052\tallowed\tfixture\tleaf shape\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "reviewer.md"
    prompt.write_text("Validate only the exact qualitative candidate.\n", encoding="utf-8")
    models = [
        model_spec(
            reviewer_id="claude",
            provider="anthropic",
            model="claude-opus-4-8",
            model_family="claude-opus",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="gpt",
            provider="openai",
            model="gpt-5.6",
            model_family="gpt-5",
            role="reviewer",
        ),
    ]
    occurrences = tmp_path / "occurrences.jsonl"
    clusters = tmp_path / "clusters.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    manifest_path = tmp_path / "manifest.json"
    manifest = build_inventory(
        stage13_path=review_input,
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        manifest_path=manifest_path,
        ontology_paths=[po, pato, registry, combinations],
        prompt_paths={"reviewer": prompt},
        models=models,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    occurrence = next(read_jsonl(occurrences, Occurrence))
    signature = {
        "kind": "structured_qualitative_relation",
        "qualitative_relation": _candidate()["signature"],
    }
    reviews = []
    for model in models:
        if omit_second and model.reviewer_id == "gpt":
            continue
        hold = second_holds and model.reviewer_id == "gpt"
        reviews.append(
            ReviewDecision(
                campaign_id=manifest.campaign_id,
                item_id=occurrence.cluster_id,
                reviewer_id=model.reviewer_id,
                provider=model.provider,
                model=model.model,
                model_family=model.model_family,
                reasoning_effort=model.reasoning_effort,
                prompt_id="reviewer",
                prompt_sha256=manifest.prompts[0].sha256,
                disposition="hold" if hold else "structured_qualitative_relation",
                proposed_signature=(
                    {"kind": "hold", "reason": "Bearer remains uncertain."}
                    if hold
                    else signature
                ),
                rationale="Exact source-bound candidate checked against the frozen catalogs.",
                confidence=0.9,
                evidence_ids=(occurrence.evidence_id,),
                validation_passed=not hold,
            )
        )
    reviews_path = tmp_path / "reviews.jsonl"
    reviews_path.write_text(
        "".join(row.model_dump_json() + "\n" for row in reviews), encoding="utf-8"
    )
    consensus = tmp_path / "consensus.jsonl"
    exceptions = tmp_path / "exceptions.jsonl"
    ledger = tmp_path / "ledger.jsonl"
    build_consensus(
        manifest=manifest,
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        review_paths=[reviews_path],
        consensus_path=consensus,
        exception_path=exceptions,
        ledger_path=ledger,
    )
    decisions = tmp_path / "expression-decisions.tsv"
    decisions.write_text("fixture\n", encoding="utf-8")
    candidate_ledger = tmp_path / "candidate-ledger.jsonl"
    candidate_ledger.write_text("{}\n", encoding="utf-8")
    exclusions = tmp_path / "candidate-exclusions.jsonl"
    exclusions.write_text("", encoding="utf-8")
    candidate_report = tmp_path / "candidate-report.json"
    candidate_report.write_text(
        json.dumps(
            {
                "schema_version": "flopo-qualitative-candidate-report-v1",
                "candidates": 1,
                "exclusions": 0,
                "conserved": True,
                "artifacts": {
                    "stage13": sha256_file(stage).model_dump(mode="json"),
                    "decisions": sha256_file(decisions).model_dump(mode="json"),
                    "review_input": sha256_file(review_input).model_dump(mode="json"),
                    "candidate_ledger": sha256_file(candidate_ledger).model_dump(mode="json"),
                    "exclusions": sha256_file(exclusions).model_dump(mode="json"),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": manifest_path,
        "occurrences": occurrences,
        "clusters": clusters,
        "evidence": evidence,
        "consensus": consensus,
        "ledger": ledger,
        "candidate_report": candidate_report,
        "stage": stage,
        "po": po,
        "pato": pato,
        "registry": registry,
        "combinations": combinations,
    }


def _materialize(tmp_path, fixture, *, allow_incomplete_review=False):
    from flopo2.verify.materialize_qualitative_consensus import (
        materialize_qualitative_consensus,
    )

    proposals = tmp_path / "proposals.jsonl"
    held = tmp_path / "held.jsonl"
    report_path = tmp_path / "materialization.json"
    report = materialize_qualitative_consensus(
        manifest_path=fixture["manifest"],
        occurrence_path=fixture["occurrences"],
        cluster_path=fixture["clusters"],
        evidence_path=fixture["evidence"],
        consensus_path=fixture["consensus"],
        ledger_path=fixture["ledger"],
        candidate_report_path=fixture["candidate_report"],
        stage13_path=fixture["stage"],
        proposals_path=proposals,
        held_path=held,
        report_path=report_path,
        combinations_path=fixture["combinations"],
        registry_path=fixture["registry"],
        po_lexicon_path=fixture["po"],
        pato_lexicon_path=fixture["pato"],
        allow_incomplete_review=allow_incomplete_review,
    )
    return report, proposals, held


def test_exact_two_family_consensus_materializes_structured_relation(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals
    from flopo2.verify.data_model import validate_jsonl

    fixture = _campaign(tmp_path)
    report, proposals, held = _materialize(tmp_path, fixture)
    assert report["conserved"] is True
    assert report["proposals"] == 1
    assert report["held"] == 0
    proposal = json.loads(proposals.read_text(encoding="utf-8"))
    assertion = proposal["assertion"]
    assert assertion["qualitative_value_relation"]["interpretation"] == "continuum"
    assert assertion["gate"]["flopo_status"] == "structured_annotation_only"
    assert "phenotype_class_iri" not in assertion
    assert len(proposal["machine_review"]["reviewer_ids"]) == 2
    assert held.read_text(encoding="utf-8") == ""

    stage14 = tmp_path / "stage14.jsonl"
    applied = apply_reviewed_proposals(fixture["stage"], proposals, stage14)
    row = json.loads(stage14.read_text(encoding="utf-8"))
    assert applied["assertions_added"] == 1
    assert applied["unresolved_spans_removed"] == 2
    assert row["unresolved_spans"] == []
    validation = validate_jsonl(
        stage14,
        po_lexicon=fixture["po"],
        pato_lexicon=fixture["pato"],
        flopo_registry=fixture["registry"],
        require_annotation_class=True,
        strict_source_statements=True,
    )
    assert validation["ok"], validation


def test_disputed_candidate_is_conserved_as_held_without_proposal(tmp_path):
    fixture = _campaign(tmp_path, second_holds=True)
    report, proposals, held = _materialize(tmp_path, fixture)
    assert report["proposals"] == 0
    assert report["held"] == 1
    assert proposals.read_text(encoding="utf-8") == ""
    row = json.loads(held.read_text(encoding="utf-8"))
    assert row["reason"] == "campaign_exception"
    assert row["consensus"]["status"] == "held"


def test_missing_review_requires_explicit_terminal_hold_recovery_mode(tmp_path):
    import pytest

    fixture = _campaign(tmp_path, omit_second=True)
    with pytest.raises(ValueError, match="incomplete"):
        _materialize(tmp_path, fixture)

    report, proposals, held = _materialize(
        tmp_path,
        fixture,
        allow_incomplete_review=True,
    )
    assert report["review_mode"] == "conserved_partial_with_terminal_holds"
    assert report["proposals"] == 0
    assert report["held"] == 1
    assert proposals.read_text(encoding="utf-8") == ""
    row = json.loads(held.read_text(encoding="utf-8"))
    assert row["details"] == ["missing_independent_review"]


def test_materializer_rejects_stage13_hash_drift(tmp_path):
    import pytest

    fixture = _campaign(tmp_path)
    fixture["stage"].write_text(
        json.dumps({**_stage_record(), "text": "Leaves changed."}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="stage13"):
        _materialize(tmp_path, fixture)
