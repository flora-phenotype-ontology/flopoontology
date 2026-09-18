from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone

from flopo2.review.consensus import build_consensus
from flopo2.review.inventory import build_inventory, model_spec
from flopo2.review.io import read_jsonl, sha256_file
from flopo2.review.models import Occurrence, ReviewDecision


TEXT = "Leaves red or blue."


def _expression_candidate() -> dict:
    return {
        "signature": {
            "bearer_id": "PO_0009025",
            "quality_id": "PATO_0000014",
            "value_operator": "one_of",
            "value_terms": ["PATO_0000322", "PATO_0000318"],
            "negated": False,
            "developmental_stage_ids": [],
            "part_restrictions": [],
            "value_low": None,
            "value_high": None,
            "value_low_inclusive": True,
            "value_high_inclusive": True,
            "unit": "",
        },
        "bearer_method": "explicit_local_mention",
        "bearer_text": "Leaves",
        "bearer_start": 0,
        "bearer_end": 6,
        "expression_start": 7,
        "expression_end": 18,
        "expression_text": "red or blue",
        "clear_unresolved_spans": [[7, 10], [14, 18]],
        "support_proposal_key": None,
        "support_class_campaign_id": None,
        "support_class_signature_sha256": None,
    }


def _stage_record() -> dict:
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
                "end": 10,
                "surface_form": "red",
                "reason": "explicit_disjunction",
                "candidate_pato_id": "PATO_0000322",
                "extractor": "fixture",
            },
            {
                "start": 14,
                "end": 18,
                "surface_form": "blue",
                "reason": "explicit_disjunction",
                "candidate_pato_id": "PATO_0000318",
                "extractor": "fixture",
            },
        ],
    }


def _campaign(tmp_path, *, second_holds: bool = False) -> dict:
    stage = tmp_path / "stage.jsonl"
    stage.write_text(json.dumps(_stage_record()) + "\n", encoding="utf-8")
    review_record = {
        **_stage_record(),
        "unresolved_spans": [
            {
                "start": 7,
                "end": 18,
                "surface_form": "red or blue",
                "reason": "machine_analyzed_one_of_candidate",
                "candidate_pato_id": "PATO_0000014",
                "pending_bearer": "PO_0009025",
                "extractor": "machine_analyzed_one_of_candidate_v1",
                "phenotype_expression_candidate": _expression_candidate(),
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
        "PATO_0000014\tcolor\tattribute_slim\n"
        "PATO_0000322\tred\tcolour_slim\n"
        "PATO_0000318\tblue\tcolour_slim\n",
        encoding="utf-8",
    )
    registry = tmp_path / "flopo_id_registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n", encoding="utf-8"
    )
    combinations = tmp_path / "valid_combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0009025\tPATO_0000014\tallowed\tfixture\tleaf color\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Validate the exact one-of candidate.\n", encoding="utf-8")
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
        "kind": "annotation_expression",
        "expression": _expression_candidate()["signature"],
    }
    reviews = []
    for model in models:
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
                disposition="hold" if hold else "annotation_expression",
                proposed_signature=(
                    {"kind": "hold", "reason": "Expression scope is uncertain."}
                    if hold
                    else signature
                ),
                rationale="Checked the exact source-bound disjunction and bearer.",
                confidence=0.95,
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
    candidate_ledger = tmp_path / "candidate-ledger.jsonl"
    candidate_ledger.write_text("{}\n", encoding="utf-8")
    exclusions = tmp_path / "exclusions.jsonl"
    exclusions.write_text("", encoding="utf-8")
    candidate_report = tmp_path / "candidate-report.json"
    candidate_report.write_text(
        json.dumps(
            {
                "schema_version": "flopo-one-of-candidate-report-v1",
                "candidates": 1,
                "exclusions": 0,
                "conserved": True,
                "artifacts": {
                    "stage": sha256_file(stage).model_dump(mode="json"),
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


def _materialize(tmp_path, fixture):
    from flopo2.verify.materialize_expression_consensus import (
        materialize_expression_consensus,
    )

    proposals = tmp_path / "proposals.jsonl"
    held = tmp_path / "held.jsonl"
    report_path = tmp_path / "materialization.json"
    report = materialize_expression_consensus(
        manifest_path=fixture["manifest"],
        occurrence_path=fixture["occurrences"],
        cluster_path=fixture["clusters"],
        evidence_path=fixture["evidence"],
        consensus_path=fixture["consensus"],
        ledger_path=fixture["ledger"],
        candidate_report_path=fixture["candidate_report"],
        stage_path=fixture["stage"],
        proposals_path=proposals,
        held_path=held,
        report_path=report_path,
        combinations_path=fixture["combinations"],
        registry_path=fixture["registry"],
        po_lexicon_path=fixture["po"],
        pato_lexicon_path=fixture["pato"],
    )
    return report, proposals, held


def test_exact_consensus_materializes_one_of_without_minting_class(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals
    from flopo2.verify.data_model import validate_jsonl

    fixture = _campaign(tmp_path)
    report, proposals, held = _materialize(tmp_path, fixture)
    assert report["conserved"] is True
    assert report["proposals"] == 1
    assert report["held"] == 0
    proposal = json.loads(proposals.read_text(encoding="utf-8"))
    assertion = proposal["assertion"]
    assert assertion["pato_id"] == "PATO_0000014"
    assert assertion["value_operator"] == "one_of"
    assert assertion["value_terms"] == ["PATO_0000322", "PATO_0000318"]
    assert assertion["gate"]["flopo_status"] == "annotation_extension_only"
    assert assertion["phenotype_class_iri"].startswith(
        "https://w3id.org/flopo/annotation-class/FAC_"
    )
    assert "FLOPO_" not in assertion["phenotype_class_iri"]
    assert len(proposal["machine_review"]["reviewer_ids"]) == 2
    assert held.read_text(encoding="utf-8") == ""

    output = tmp_path / "stage-next.jsonl"
    applied = apply_reviewed_proposals(fixture["stage"], proposals, output)
    row = json.loads(output.read_text(encoding="utf-8"))
    assert applied["assertions_added"] == 1
    assert applied["unresolved_spans_removed"] == 2
    assert row["unresolved_spans"] == []
    validation = validate_jsonl(
        output,
        po_lexicon=fixture["po"],
        pato_lexicon=fixture["pato"],
        flopo_registry=fixture["registry"],
        require_annotation_class=True,
        strict_source_statements=True,
    )
    assert validation["ok"], validation


def test_disputed_expression_is_held_without_proposal(tmp_path):
    fixture = _campaign(tmp_path, second_holds=True)
    report, proposals, held = _materialize(tmp_path, fixture)
    assert report["proposals"] == 0
    assert report["held"] == 1
    assert proposals.read_text(encoding="utf-8") == ""
    row = json.loads(held.read_text(encoding="utf-8"))
    assert row["reason"] == "campaign_exception"
    assert row["consensus"]["status"] == "held"


def test_atomic_expression_candidate_uses_the_same_fail_closed_materializer():
    from flopo2.review.models import (
        ConsensusDecision,
        PhenotypeExpressionCandidate,
        ProposedSignature,
        canonical_json,
    )
    from flopo2.verify.materialize_expression_consensus import _assertion_for

    candidate = PhenotypeExpressionCandidate(
        signature={
            "bearer_id": "PO_0020137",
            "quality_id": "PATO_0002228",
            "value_operator": "atomic",
        },
        bearer_method="explicit_leaf_apex",
        bearer_text="apex",
        bearer_start=12,
        bearer_end=16,
        expression_start=17,
        expression_end=26,
        expression_text="acuminate",
        clear_unresolved_spans=((17, 26),),
    )
    occurrence = Occurrence(
        occurrence_id="occ_" + "1" * 24,
        evidence_id="evidence_" + "2" * 24,
        cluster_id="cluster_" + "3" * 24,
        semantic_fingerprint="4" * 64,
        source="fixture",
        source_id="flora.xml",
        source_segment_index=0,
        taxon="Planta exemplaris",
        organ="leaves",
        language="en",
        segment_char_start=0,
        segment_char_end=27,
        span_start=17,
        span_end=26,
        surface_form="acuminate",
        normalized_form="acuminate",
        reason="leaf_apex_expression_candidate",
        candidate_pato_id="PATO_0002228",
        pending_bearer="PO_0020137",
        extractor="fixture",
        context="Leaves with apex [[acuminate]].",
        phenotype_expression_candidate=candidate,
    )
    signature = ProposedSignature(
        kind="annotation_expression",
        expression=candidate.signature,
    )
    normalized = canonical_json(
        signature.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    )
    decision = ConsensusDecision(
        campaign_id="campaign_" + "5" * 24,
        item_id=occurrence.cluster_id,
        status="llm_consensus",
        disposition="annotation_expression",
        normalized_signature=normalized,
        signature_sha256=hashlib.sha256(normalized.encode()).hexdigest(),
        reviewer_ids=("claude", "gpt"),
        reasons=(),
        validation_passed=True,
    )
    assertion = _assertion_for(occurrence, decision)
    assert assertion["po_id"] == "PO_0020137"
    assert assertion["pato_id"] == "PATO_0002228"
    assert assertion["value_operator"] == "atomic"
    assert assertion["value_terms"] == []
    assert assertion["phenotype_class_iri"].startswith(
        "https://w3id.org/flopo/annotation-class/FAC_"
    )
