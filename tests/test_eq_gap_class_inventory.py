from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, Graph, URIRef

from flopo2.review.adversarial import build_adversarial_batches
from flopo2.review.consensus import build_consensus
from flopo2.review.eq_gap_class_inventory import build_eq_gap_class_inventory
from flopo2.review.eq_gap_occurrence_inventory import build_eq_gap_occurrence_inventory
from flopo2.review.inventory import model_spec
from flopo2.review.io import read_jsonl, sha256_file
from flopo2.review.models import (
    AdversarialVerdict,
    Cluster,
    ConsensusDecision,
    EvidenceRecord,
    Occurrence,
    ReviewDecision,
    canonical_json,
)
from flopo2.review.validation import load_validation_context, validate_review_decision
from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals
from flopo2.verify.materialize_eq_gap_class_consensus import (
    materialize_eq_gap_class_consensus,
)
from flopo2.verify.materialize_eq_gap_occurrence_consensus import (
    materialize_eq_gap_occurrence_consensus,
)


def _json_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_fixture(tmp_path: Path):
    classes = tmp_path / "classes.jsonl"
    source_occurrences = tmp_path / "source-occurrences.jsonl"
    source_report = tmp_path / "source-report.json"
    registry = tmp_path / "flopo_id_registry.tsv"
    flopo = tmp_path / "flopo.owl"
    po_obo = tmp_path / "plant_ontology.obo"
    pato_obo = tmp_path / "quality.obo"
    po_lexicon = tmp_path / "po_lexicon.tsv"
    pato_lexicon = tmp_path / "pato_lexicon.tsv"
    combinations = tmp_path / "valid_combinations.tsv"
    reviewer_prompt = tmp_path / "reviewer.md"
    adversarial_prompt = tmp_path / "adversarial.md"

    source_ids = ["eqgapocc_" + "1" * 24, "eqgapocc_" + "2" * 24]
    membership_hash = hashlib.sha256(canonical_json(source_ids).encode()).hexdigest()
    class_row = {
        "class_candidate_id": "eqgap_" + "a" * 24,
        "po_id": "PO_0000001",
        "po_label": "test leaf",
        "pato_id": "PATO_0000002",
        "pato_label": "greyish green",
        "proposed_label": "test leaf greyish green",
        "proposed_signature": "EQ|PO_0000001|PATO_0000002",
        "occurrence_count": 2,
        "occurrence_membership_sha256": membership_hash,
    }
    classes.write_text(json.dumps(class_row) + "\n", encoding="utf-8")
    occurrence_rows = [
        {
            "occurrence_id": source_id,
            "source": "fixture",
            "source_id": str(index),
            "source_segment_index": 0,
            "taxon": f"Fixture {index}",
            "organ": "leaf",
            "language": "en",
            "start": 5,
            "end": 15,
            "surface_form": "grey-green",
            "po_id": "PO_0000001",
            "pato_id": "PATO_0000002",
            "clear_unresolved_spans": [[5, 9], [10, 15]],
            "context": "leaf [[grey-green]] in the source description",
            "extractor": "fixture",
        }
        for index, source_id in enumerate(source_ids, 1)
    ]
    source_occurrences.write_text(
        "".join(json.dumps(row) + "\n" for row in occurrence_rows), encoding="utf-8"
    )
    source_report.write_text(
        json.dumps(
            {
                "schema_version": "flopo-exact-colour-eq-gap-inventory-v1",
                "conserved": True,
                "gap_classes": 1,
                "gap_occurrences": 2,
                "artifacts": {
                    "classes": sha256_file(classes).model_dump(mode="json"),
                    "occurrences": sha256_file(source_occurrences).model_dump(mode="json"),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000000\t0\tflora phenotype\tOTHER\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\ttest leaf phenotype\t"
        "PHENO|PO_0000001\t0\n",
        encoding="utf-8",
    )
    flopo.write_text(
        "<http://purl.obolibrary.org/obo/FLOPO_0000000> a "
        "<http://www.w3.org/2002/07/owl#Class> .\n",
        encoding="utf-8",
    )
    po_obo.write_text("[Term]\nid: PO:0000001\nname: test leaf\n", encoding="utf-8")
    pato_obo.write_text(
        "[Term]\nid: PATO:0000002\nname: greyish green\n", encoding="utf-8"
    )
    po_lexicon.write_text(
        "id\tlabel\tsynonyms\tslim\nPO_0000001\ttest leaf\t\t\n", encoding="utf-8"
    )
    pato_lexicon.write_text(
        "id\tlabel\tsynonyms\tslim\nPATO_0000002\tgreyish green\t\t\n",
        encoding="utf-8",
    )
    combinations.write_text(
        "po_id\tpato_id\tstatus\nPO_0000001\tPATO_0000002\tnovel\n",
        encoding="utf-8",
    )
    reviewer_prompt.write_text("Review the exact candidate.\n", encoding="utf-8")
    adversarial_prompt.write_text("Adversarially inspect the candidate.\n", encoding="utf-8")
    return {
        "classes": classes,
        "source_occurrences": source_occurrences,
        "source_report": source_report,
        "registry": registry,
        "ontologies": [
            flopo,
            po_obo,
            pato_obo,
            registry,
            po_lexicon,
            pato_lexicon,
            combinations,
        ],
        "prompts": {"reviewer": reviewer_prompt, "adversarial": adversarial_prompt},
    }


def test_eq_gap_inventory_binds_exact_class_and_validation(tmp_path):
    fixture = _write_fixture(tmp_path)
    occurrences = tmp_path / "occurrences.jsonl"
    clusters = tmp_path / "clusters.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    report = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    models = [
        model_spec(
            reviewer_id="qwen",
            provider="openrouter",
            model="qwen/qwen3.7-max",
            model_family="qwen-3.7",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="kimi",
            provider="openrouter",
            model="moonshotai/kimi-k3",
            model_family="kimi-k3",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="gpt",
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
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        report_path=report,
        manifest_path=manifest_path,
        ontology_paths=fixture["ontologies"],
        prompt_paths=fixture["prompts"],
        models=models,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    assert manifest.starting_clusters == 1
    assert manifest.starting_occurrences == 2
    occurrence_rows = list(read_jsonl(occurrences, Occurrence))
    cluster = next(read_jsonl(clusters, Cluster))
    candidate = cluster.reusable_flopo_class_candidate
    assert candidate is not None
    assert candidate.signature.bearer_id == "PO_0000001"
    assert candidate.signature.quality_id == "PATO_0000002"
    assert candidate.parent_ids == ("FLOPO_0000001",)
    assert candidate.occurrence_count == 2
    assert len(candidate.authoritative_evidence_ids) == 3
    assert all(row.reusable_flopo_class_candidate == candidate for row in occurrence_rows)
    assert len(list(read_jsonl(evidence, EvidenceRecord))) == 11
    assert json.loads(report.read_text())["conservation"] == {
        "all_candidate_authorities_hash_bound": True,
        "all_source_memberships_verified": True,
        "class_count_matches_source": True,
        "occurrence_count_matches_source": True,
    }

    context = load_validation_context(
        manifest,
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
    )
    model = next(row for row in manifest.models if row.reviewer_id == "qwen")
    prompt = next(row for row in manifest.prompts if row.prompt_id == "reviewer")
    exact = ReviewDecision(
        campaign_id=manifest.campaign_id,
        item_id=cluster.cluster_id,
        reviewer_id=model.reviewer_id,
        provider=model.provider,
        model=model.model,
        model_family=model.model_family,
        reasoning_effort=model.reasoning_effort,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        disposition="reusable_flopo_class",
        proposed_signature={
            "kind": "reusable_flopo_class",
            "expression": candidate.signature.model_dump(mode="json"),
            "label": candidate.label,
            "definition": candidate.definition,
            "parent_ids": candidate.parent_ids,
            "authoritative_evidence_ids": candidate.authoritative_evidence_ids,
        },
        rationale="The exact source and ontology evidence support this EQ class.",
        confidence=0.95,
        evidence_ids=(
            occurrence_rows[0].evidence_id,
            *candidate.authoritative_evidence_ids,
        ),
        validation_passed=True,
    )
    assert validate_review_decision(exact, context).passed
    drift = exact.model_copy(
        update={
            "proposed_signature": exact.proposed_signature.model_copy(
                update={"label": "invented label"}
            )
        }
    )
    validation = validate_review_decision(drift, context)
    assert not validation.passed
    assert "reusable_flopo_class_signature_differs_from_runner_candidate" in validation.reasons


def test_eq_gap_class_consensus_allocates_machine_only_owl_class(tmp_path):
    fixture = _write_fixture(tmp_path)
    output = tmp_path / "campaign"
    output.mkdir()
    models = [
        model_spec(
            reviewer_id="qwen",
            provider="openrouter",
            model="qwen/qwen3.7-max",
            model_family="qwen-3.7",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="kimi",
            provider="openrouter",
            model="moonshotai/kimi-k3",
            model_family="kimi-k3",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="gpt",
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
    occurrences = list(read_jsonl(output / "occurrences.jsonl", Occurrence))
    cluster = next(read_jsonl(output / "clusters.jsonl", Cluster))
    candidate = cluster.reusable_flopo_class_candidate
    assert candidate is not None
    reviewer_prompt = next(row for row in manifest.prompts if row.prompt_id == "reviewer")
    reviews = []
    for reviewer_id in ("qwen", "kimi"):
        model = next(row for row in manifest.models if row.reviewer_id == reviewer_id)
        reviews.append(
            ReviewDecision(
                campaign_id=manifest.campaign_id,
                item_id=cluster.cluster_id,
                reviewer_id=model.reviewer_id,
                provider=model.provider,
                model=model.model,
                model_family=model.model_family,
                reasoning_effort=model.reasoning_effort,
                prompt_id=reviewer_prompt.prompt_id,
                prompt_sha256=reviewer_prompt.sha256,
                disposition="reusable_flopo_class",
                proposed_signature={
                    "kind": "reusable_flopo_class",
                    "expression": candidate.signature.model_dump(mode="json"),
                    "label": candidate.label,
                    "definition": candidate.definition,
                    "parent_ids": candidate.parent_ids,
                    "authoritative_evidence_ids": candidate.authoritative_evidence_ids,
                },
                rationale="The exact frozen PO-PATO class candidate is reusable.",
                confidence=0.95,
                evidence_ids=(
                    occurrences[0].evidence_id,
                    *candidate.authoritative_evidence_ids,
                ),
                validation_passed=True,
            )
        )
    reviews_path = output / "reviews.jsonl"
    reviews_path.write_text(
        "".join(row.model_dump_json() + "\n" for row in reviews), encoding="utf-8"
    )
    build_adversarial_batches(
        manifest=manifest,
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        review_paths=[reviews_path],
        output_dir=output / "adversarial",
    )
    adversary = next(row for row in manifest.models if row.reviewer_id == "gpt")
    adversarial_prompt = next(
        row for row in manifest.prompts if row.prompt_id == "adversarial"
    )
    verdict = AdversarialVerdict(
        campaign_id=manifest.campaign_id,
        item_id=cluster.cluster_id,
        reviewer_id=adversary.reviewer_id,
        provider=adversary.provider,
        model=adversary.model,
        model_family=adversary.model_family,
        reasoning_effort=adversary.reasoning_effort,
        prompt_id=adversarial_prompt.prompt_id,
        prompt_sha256=adversarial_prompt.sha256,
        candidate_signature_sha256=reviews[0].signature_sha256,
        verdict="no_blocker",
        rationale="No duplicate, parent, definition, colour, or bearer blocker remains.",
        evidence_ids=(occurrences[0].evidence_id, *candidate.authoritative_evidence_ids),
        validation_passed=True,
    )
    verdict_path = output / "verdicts.jsonl"
    verdict_path.write_text(verdict.model_dump_json() + "\n", encoding="utf-8")
    build_consensus(
        manifest=manifest,
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        review_paths=[reviews_path],
        adjudication_paths=[verdict_path],
        consensus_path=output / "consensus.jsonl",
        exception_path=output / "exceptions.jsonl",
        ledger_path=output / "ledger.jsonl",
    )
    decision = next(read_jsonl(output / "consensus.jsonl", ConsensusDecision))
    assert decision.status == "llm_consensus"
    result = materialize_eq_gap_class_consensus(
        manifest_path=output / "manifest.json",
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        consensus_path=output / "consensus.jsonl",
        ledger_path=output / "ledger.jsonl",
        candidate_report_path=output / "candidate-report.json",
        flopo_registry_path=fixture["registry"],
        allocation_path=output / "allocations.tsv",
        module_path=output / "eq.ttl",
        held_path=output / "held.jsonl",
        report_path=output / "materialization-report.json",
        release_date="2026-08-04",
    )
    assert result["accepted_classes"] == 1
    assert result["accepted_candidate_occurrences"] == 2
    assert result["occurrence_annotations_admitted"] == 0
    graph = Graph().parse(output / "eq.ttl")
    cls = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000002")
    parent = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000001")
    assert (cls, RDF.type, OWL.Class) in graph
    assert (cls, RDFS.subClassOf, parent) in graph
    assert len(list(graph.objects(cls, OWL.equivalentClass))) == 1
    assert not list(graph.objects(cls, DCTERMS.contributor))

    stage = tmp_path / "stage.jsonl"
    stage_rows = []
    for index in (1, 2):
        text = "leaf grey-green in the source description"
        stage_rows.append(
            {
                "source": "fixture",
                "source_id": str(index),
                "source_segment_index": 0,
                "taxon": f"Fixture {index}",
                "organ": "leaf",
                "language": "en",
                "char_start": 0,
                "char_end": len(text),
                "text": text,
                "assertions": [],
                "unresolved_spans": [
                    {
                        "start": 5,
                        "end": 9,
                        "surface_form": "grey",
                        "candidate_pato_id": "PATO_0000003",
                    },
                    {
                        "start": 10,
                        "end": 15,
                        "surface_form": "green",
                        "candidate_pato_id": "PATO_0000004",
                    },
                ],
            }
        )
    stage.write_text(
        "".join(json.dumps(row) + "\n" for row in stage_rows), encoding="utf-8"
    )
    occurrence_output = tmp_path / "occurrence-campaign"
    occurrence_output.mkdir()
    occurrence_manifest = build_eq_gap_occurrence_inventory(
        stage_path=stage,
        class_manifest_path=output / "manifest.json",
        class_occurrence_path=output / "occurrences.jsonl",
        class_cluster_path=output / "clusters.jsonl",
        class_evidence_path=output / "evidence.jsonl",
        class_consensus_path=output / "consensus.jsonl",
        class_ledger_path=output / "ledger.jsonl",
        class_candidate_report_path=output / "candidate-report.json",
        class_allocation_path=output / "allocations.tsv",
        class_module_path=output / "eq.ttl",
        class_materialization_report_path=output / "materialization-report.json",
        source_occurrence_path=fixture["source_occurrences"],
        occurrence_path=occurrence_output / "occurrences.jsonl",
        cluster_path=occurrence_output / "clusters.jsonl",
        evidence_path=occurrence_output / "evidence.jsonl",
        report_path=occurrence_output / "report.json",
        manifest_path=occurrence_output / "manifest.json",
        ontology_paths=[*fixture["ontologies"], output / "eq.ttl"],
        prompt_paths={"reviewer": fixture["prompts"]["reviewer"]},
        models=[row for row in models if row.role == "reviewer"],
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    assert occurrence_manifest.starting_occurrences == 2
    assert occurrence_manifest.starting_clusters == 2
    occurrence_candidates = list(
        read_jsonl(occurrence_output / "occurrences.jsonl", Occurrence)
    )
    assert all(row.phenotype_expression_candidate is not None for row in occurrence_candidates)
    for row in occurrence_candidates:
        expression = row.phenotype_expression_candidate
        assert expression is not None
        assert expression.signature.bearer_id == "PO_0000001"
        assert expression.signature.quality_id == "PATO_0000002"
        assert expression.eq_class_id == "FLOPO_0000002"
        assert expression.eq_class_campaign_id == manifest.campaign_id
        assert expression.clear_unresolved_spans == ((5, 9), (10, 15))
    occurrence_report = json.loads((occurrence_output / "report.json").read_text())
    assert all(occurrence_report["conservation"].values())

    occurrence_reviews = []
    occurrence_prompt = next(
        row for row in occurrence_manifest.prompts if row.prompt_id == "reviewer"
    )
    occurrence_clusters = {
        row.cluster_id: row
        for row in read_jsonl(occurrence_output / "clusters.jsonl", Cluster)
    }
    for reviewer_id in ("qwen", "kimi"):
        model = next(
            row for row in occurrence_manifest.models if row.reviewer_id == reviewer_id
        )
        for occurrence in occurrence_candidates:
            expression = occurrence.phenotype_expression_candidate
            assert expression is not None
            occurrence_reviews.append(
                ReviewDecision(
                    campaign_id=occurrence_manifest.campaign_id,
                    item_id=occurrence.cluster_id,
                    reviewer_id=model.reviewer_id,
                    provider=model.provider,
                    model=model.model,
                    model_family=model.model_family,
                    reasoning_effort=model.reasoning_effort,
                    prompt_id=occurrence_prompt.prompt_id,
                    prompt_sha256=occurrence_prompt.sha256,
                    disposition="annotation_expression",
                    proposed_signature={
                        "kind": "annotation_expression",
                        "expression": expression.signature.model_dump(mode="json"),
                    },
                    rationale="The marked colour is explicitly attached to the test leaf.",
                    confidence=0.95,
                    evidence_ids=(occurrence.evidence_id,),
                    validation_passed=True,
                )
            )
    assert set(occurrence_clusters) == {
        row.cluster_id for row in occurrence_candidates
    }
    occurrence_reviews_path = occurrence_output / "reviews.jsonl"
    occurrence_reviews_path.write_text(
        "".join(row.model_dump_json() + "\n" for row in occurrence_reviews),
        encoding="utf-8",
    )
    build_consensus(
        manifest=occurrence_manifest,
        occurrence_path=occurrence_output / "occurrences.jsonl",
        cluster_path=occurrence_output / "clusters.jsonl",
        evidence_path=occurrence_output / "evidence.jsonl",
        review_paths=[occurrence_reviews_path],
        consensus_path=occurrence_output / "consensus.jsonl",
        exception_path=occurrence_output / "exceptions.jsonl",
        ledger_path=occurrence_output / "ledger.jsonl",
    )
    materialized = materialize_eq_gap_occurrence_consensus(
        manifest_path=occurrence_output / "manifest.json",
        occurrence_path=occurrence_output / "occurrences.jsonl",
        cluster_path=occurrence_output / "clusters.jsonl",
        evidence_path=occurrence_output / "evidence.jsonl",
        consensus_path=occurrence_output / "consensus.jsonl",
        ledger_path=occurrence_output / "ledger.jsonl",
        candidate_report_path=occurrence_output / "report.json",
        class_allocation_path=output / "allocations.tsv",
        class_module_path=output / "eq.ttl",
        stage_path=stage,
        proposals_path=occurrence_output / "proposals.jsonl",
        held_path=occurrence_output / "held.jsonl",
        report_path=occurrence_output / "materialization-report.json",
        combinations_path=fixture["ontologies"][-1],
        registry_path=fixture["registry"],
        po_lexicon_path=fixture["ontologies"][4],
        pato_lexicon_path=fixture["ontologies"][5],
    )
    assert materialized["proposals"] == 2
    assert materialized["held"] == 0
    applied_stage = tmp_path / "stage-applied.jsonl"
    apply_report = apply_reviewed_proposals(
        stage, occurrence_output / "proposals.jsonl", applied_stage
    )
    assert apply_report["assertions_added"] == 2
    assert apply_report["unresolved_spans_removed"] == 4
    assert all(not row["unresolved_spans"] for row in _json_rows(applied_stage))
