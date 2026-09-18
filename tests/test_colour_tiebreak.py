"""Two-of-three tie-break admission for held exact-colour EQ-class and expression items."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from rdflib import DCTERMS, OWL, RDF, Graph, Literal, URIRef

from flopo2.review.consensus import build_consensus
from flopo2.review.eq_gap_class_inventory import build_eq_gap_class_inventory
from flopo2.review.inventory import model_spec
from flopo2.review.io import read_jsonl
from flopo2.review.models import (
    AdversarialVerdict,
    Cluster,
    ConsensusDecision,
    Occurrence,
    ReviewDecision,
)
from flopo2.verify.materialize_eq_gap_class_consensus import (
    materialize_eq_gap_class_consensus,
)
from test_eq_gap_class_inventory import _write_fixture


FLOPOANN = "https://w3id.org/flopo/annotation/"


def _class_campaign(tmp_path: Path, *, kimi_accepts: bool = True) -> dict:
    fixture = _write_fixture(tmp_path)
    output = tmp_path / "campaign"
    output.mkdir()
    models = [
        model_spec(
            reviewer_id="reviewer_qwen",
            provider="openrouter",
            model="qwen/qwen3.7-max",
            model_family="qwen-3.7",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="reviewer_kimi",
            provider="openrouter",
            model="moonshotai/kimi-k3",
            model_family="kimi-k3",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="adversary_gpt",
            provider="openai",
            model="gpt-5.6",
            model_family="gpt-5.6",
            role="adjudicator",
        ),
    ]
    manifest = build_eq_gap_class_inventory(
        classes_path=fixture["classes"],
        source_occurrences_path=fixture["source_occurrences"],
        source_report_path=fixture["source_report"],
        flopo_registry_path=fixture["registry"],
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        report_path=output / "candidate-report.json",
        manifest_path=output / "manifest.json",
        ontology_paths=fixture["ontologies"],
        prompt_paths=fixture["prompts"],
        models=models,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    occurrence = next(read_jsonl(output / "occurrences.jsonl", Occurrence))
    cluster = next(read_jsonl(output / "clusters.jsonl", Cluster))
    candidate = cluster.reusable_flopo_class_candidate
    assert candidate is not None
    accept_signature = {
        "kind": "reusable_flopo_class",
        "expression": candidate.signature.model_dump(mode="json"),
        "label": candidate.label,
        "definition": candidate.definition,
        "parent_ids": list(candidate.parent_ids),
        "authoritative_evidence_ids": list(candidate.authoritative_evidence_ids),
    }
    evidence = [occurrence.evidence_id, *candidate.authoritative_evidence_ids]
    reviewer_prompt = next(row for row in manifest.prompts if row.prompt_id == "reviewer")
    reviews = []
    for model in manifest.models:
        if model.role != "reviewer":
            continue
        accepts = model.reviewer_id == "reviewer_kimi" and kimi_accepts
        reviews.append(
            ReviewDecision(
                campaign_id=manifest.campaign_id,
                item_id=cluster.cluster_id,
                reviewer_id=model.reviewer_id,
                provider=model.provider,
                model=model.model,
                model_family=model.model_family,
                reasoning_effort=model.reasoning_effort,
                prompt_id="reviewer",
                prompt_sha256=reviewer_prompt.sha256,
                disposition="reusable_flopo_class" if accepts else "hold",
                proposed_signature=(
                    accept_signature
                    if accepts
                    else {"kind": "hold", "reason": "Colour scope is uncertain."}
                ),
                rationale="Checked the exact candidate against the bound contexts.",
                confidence=0.9,
                evidence_ids=tuple(evidence),
                validation_passed=accepts,
            )
        )
    reviews_path = output / "reviews.jsonl"
    reviews_path.write_text(
        "".join(row.model_dump_json() + "\n" for row in reviews), encoding="utf-8"
    )
    build_consensus(
        manifest=manifest,
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        review_paths=[reviews_path],
        consensus_path=output / "consensus.jsonl",
        exception_path=output / "exceptions.jsonl",
        ledger_path=output / "ledger.jsonl",
    )
    decision = next(read_jsonl(output / "consensus.jsonl", ConsensusDecision))
    assert decision.status != "llm_consensus"
    tiebreak = output / "tiebreak.jsonl"
    tiebreak.write_text(
        json.dumps(
            {
                "campaign": "exact_colour_eq_class",
                "campaign_id": manifest.campaign_id,
                "item_id": cluster.cluster_id,
                "label": candidate.label,
                "decision": {
                    "disposition": "reusable_flopo_class",
                    "proposed_signature": accept_signature,
                    "evidence_ids": evidence,
                    "validation_passed": True,
                },
                "rationale": "The source directly predicates the colour of the bearer.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    adversary = next(row for row in manifest.models if row.reviewer_id == "adversary_gpt")
    adversarial_prompt = next(row for row in manifest.prompts if row.prompt_id == "adversarial")
    block = AdversarialVerdict(
        campaign_id=manifest.campaign_id,
        item_id=cluster.cluster_id,
        reviewer_id=adversary.reviewer_id,
        provider=adversary.provider,
        model=adversary.model,
        model_family=adversary.model_family,
        reasoning_effort=adversary.reasoning_effort,
        prompt_id="adversarial",
        prompt_sha256=adversarial_prompt.sha256,
        candidate_signature_sha256=reviews[-1].signature_sha256,
        verdict="block",
        rationale="The colour belongs to a different structure.",
        evidence_ids=tuple(evidence),
        validation_passed=True,
    )
    blocks = output / "adjudications.jsonl"
    blocks.write_text(block.model_dump_json() + "\n", encoding="utf-8")
    return {"fixture": fixture, "output": output, "reviews": reviews_path,
            "tiebreak": tiebreak, "blocks": blocks}


def _materialize(campaign: dict, name: str, **kwargs):
    output = campaign["output"]
    target = output / name
    target.mkdir()
    result = materialize_eq_gap_class_consensus(
        manifest_path=output / "manifest.json",
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        consensus_path=output / "consensus.jsonl",
        ledger_path=output / "ledger.jsonl",
        candidate_report_path=output / "candidate-report.json",
        flopo_registry_path=campaign["fixture"]["registry"],
        allocation_path=target / "allocations.tsv",
        module_path=target / "eq.ttl",
        held_path=target / "held.jsonl",
        report_path=target / "report.json",
        release_date="2026-09-18",
        **kwargs,
    )
    return result, target


def test_two_of_three_admits_held_class_after_prior_allocations(tmp_path):
    campaign = _class_campaign(tmp_path)
    base, base_dir = _materialize(campaign, "base")
    assert base["accepted_classes"] == 0
    result, target = _materialize(
        campaign,
        "tiebreak",
        tiebreak_path=campaign["tiebreak"],
        tiebreak_rule="two_of_three",
        review_paths=(campaign["reviews"],),
        prior_allocation_paths=(base_dir / "allocations.tsv",),
    )
    assert result["accepted_classes"] == 1
    assert result["class_conserved"] and result["occurrence_conserved"]
    assert result["tiebreak"]["admitted"] == 1
    with (target / "allocations.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows[0]["flopo_id"] == "FLOPO_0000002"
    assert rows[0]["admission_rule"] == "two_of_three_exact_agreement"
    assert rows[0]["adjudicator_id"] == ""
    assert rows[0]["reviewer_ids"].split("|") == [
        "reviewer_claude_opus_5",
        "reviewer_kimi",
        "reviewer_qwen",
    ]
    graph = Graph().parse(target / "eq.ttl")
    cls = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000002")
    assert (cls, RDF.type, OWL.Class) in graph
    assert len(list(graph.objects(cls, URIRef(FLOPOANN + "machine_reviewer")))) == 3
    assert (cls, URIRef(FLOPOANN + "machine_review_rule"),
            Literal("two_of_three_exact_agreement")) in graph
    assert not list(graph.objects(cls, URIRef(FLOPOANN + "machine_adjudicator")))
    assert not list(graph.objects(cls, DCTERMS.contributor))
    note = str(next(graph.objects(cls, URIRef("http://purl.obolibrary.org/obo/IAO_0000116"))))
    assert "not human reviewed" in note


def test_existing_adversarial_block_still_holds(tmp_path):
    campaign = _class_campaign(tmp_path)
    result, _ = _materialize(
        campaign,
        "tiebreak",
        tiebreak_path=campaign["tiebreak"],
        tiebreak_rule="two_of_three",
        review_paths=(campaign["reviews"],),
        adjudication_paths=(campaign["blocks"],),
    )
    assert result["accepted_classes"] == 0
    assert result["tiebreak"]["held_first_reasons"] == {"adversarial_blocker": 1}


def test_curator_override_admits_adversarially_blocked_item(tmp_path):
    campaign = _class_campaign(tmp_path)
    item_id = json.loads(campaign["tiebreak"].read_text(encoding="utf-8").splitlines()[0])[
        "item_id"
    ]
    result, target = _materialize(
        campaign,
        "tiebreak",
        tiebreak_path=campaign["tiebreak"],
        tiebreak_rule="two_of_three",
        review_paths=(campaign["reviews"],),
        adjudication_paths=(campaign["blocks"],),
        curator_overrides={item_id: "curator 2026-09-18"},
    )
    assert result["accepted_classes"] == 1
    assert result["tiebreak"]["held_first_reasons"] == {}
    with (target / "allocations.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows[0]["admission_rule"] == "two_of_three_exact_agreement"
    assert rows[0]["curator_override"] == "curator 2026-09-18"
    graph = Graph().parse(target / "eq.ttl")
    cls = URIRef(f"http://purl.obolibrary.org/obo/{rows[0]['flopo_id']}")
    note = str(next(graph.objects(cls, URIRef("http://purl.obolibrary.org/obo/IAO_0000116"))))
    assert "adversary block overridden by curator 2026-09-18" in note
    assert (
        cls,
        URIRef(FLOPOANN + "curator_override"),
        Literal("curator 2026-09-18"),
    ) in graph


def test_curator_override_unused_entry_raises(tmp_path):
    campaign = _class_campaign(tmp_path)
    with pytest.raises(ValueError, match="curator_overrides names items"):
        _materialize(
            campaign,
            "tiebreak",
            tiebreak_path=campaign["tiebreak"],
            tiebreak_rule="two_of_three",
            review_paths=(campaign["reviews"],),
            adjudication_paths=(campaign["blocks"],),
            curator_overrides={"cluster_" + "0" * 24: "curator 2026-09-18"},
        )


def test_tiebreak_without_matching_partner_holds(tmp_path):
    campaign = _class_campaign(tmp_path, kimi_accepts=False)
    result, _ = _materialize(
        campaign,
        "tiebreak",
        tiebreak_path=campaign["tiebreak"],
        tiebreak_rule="two_of_three",
        review_paths=(campaign["reviews"],),
    )
    assert result["accepted_classes"] == 0
    assert result["tiebreak"]["held_first_reasons"] == {"no_exact_validated_partner": 1}


def test_tiebreak_requires_rule_and_reviews(tmp_path):
    campaign = _class_campaign(tmp_path)
    with pytest.raises(ValueError, match="supplied together"):
        _materialize(campaign, "a", tiebreak_path=campaign["tiebreak"])
    with pytest.raises(ValueError, match="review files"):
        _materialize(
            campaign, "b", tiebreak_path=campaign["tiebreak"], tiebreak_rule="two_of_three"
        )


def test_expression_tiebreak_emits_only_newly_admitted_occurrence(tmp_path):
    from test_expression_consensus_materialization import _campaign

    from flopo2.verify.materialize_expression_consensus import (
        materialize_expression_consensus,
    )
    from flopo2.verify.proposal_delta import apply_delta, build_delta

    fixture = _campaign(tmp_path, second_holds=True)
    occurrence = next(read_jsonl(fixture["occurrences"], Occurrence))
    cluster = next(read_jsonl(fixture["clusters"], Cluster))
    signature = {
        "kind": "annotation_expression",
        "expression": cluster.phenotype_expression_candidate.signature.model_dump(mode="json"),
    }
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    tiebreak = tmp_path / "tiebreak.jsonl"
    tiebreak.write_text(
        json.dumps(
            {
                "campaign_id": manifest["campaign_id"],
                "item_id": occurrence.cluster_id,
                "decision": {
                    "disposition": "annotation_expression",
                    "proposed_signature": signature,
                    "evidence_ids": [occurrence.evidence_id],
                    "validation_passed": True,
                },
                "rationale": "Both colours are alternatives of the leaf colour.",
                "reviewer": {"reviewer_id": "reviewer_third", "model_family": "third"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    proposals = tmp_path / "tb-proposals.jsonl"
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
        held_path=tmp_path / "tb-held.jsonl",
        report_path=tmp_path / "tb-report.json",
        combinations_path=fixture["combinations"],
        registry_path=fixture["registry"],
        po_lexicon_path=fixture["po"],
        pato_lexicon_path=fixture["pato"],
        tiebreak_path=tiebreak,
        tiebreak_rule="two_of_three",
        review_paths=(tmp_path / "reviews.jsonl",),
    )
    assert report["proposals"] == 1 and report["held"] == 0 and report["conserved"]
    row = json.loads(proposals.read_text(encoding="utf-8"))
    assert row["machine_review"]["reviewer_ids"] == ["claude", "gpt", "reviewer_third"]
    assert row["machine_review"]["admission_rule"] == "two_of_three_exact_agreement"
    assert row["assertion"]["composition"]["reasons"] == ["two_of_three_exact_agreement"]
    assert "llm_review_rule:two_of_three_exact_agreement" in row["assertion"][
        "mapping_provenance"
    ]

    delta = tmp_path / "delta.jsonl"
    counts = build_delta(proposals, fixture["stage"], delta)
    assert counts == {
        "segments": 1,
        "assertions": 1,
        "source_statements": 1,
        "unresolved_removed": 2,
    }
    patched = tmp_path / "patched.jsonl"
    assert apply_delta(fixture["stage"], delta, patched) == {"segments_patched": 1}
    record = json.loads(patched.read_text(encoding="utf-8"))
    assert record["unresolved_spans"] == []
    assert record["assertions"][0]["gate"]["assertion_index"] == 0
    with pytest.raises(ValueError, match="already present"):
        build_delta(proposals, patched, tmp_path / "again.jsonl")
