from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, Graph, URIRef

from flopo2.review.adversarial import build_adversarial_batches
from flopo2.review.consensus import build_consensus
from flopo2.review.inventory import model_spec
from flopo2.review.io import read_jsonl
from flopo2.review.models import (
    AdversarialVerdict,
    Cluster,
    ConsensusDecision,
    EvidenceRecord,
    Occurrence,
    ReviewDecision,
)
from flopo2.review.support_inventory import build_support_inventory
from flopo2.review.support_occurrence_inventory import build_support_occurrence_inventory
from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals
from flopo2.verify.materialize_support_consensus import materialize_support_consensus
from flopo2.verify.materialize_support_occurrence_consensus import (
    materialize_support_occurrence_consensus,
)


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _fixture(tmp_path: Path):
    authority = tmp_path / "orchid-source.txt"
    authority.write_text(
        "The labellum is the specialised median petal of the inner orchid perianth whorl.\n",
        encoding="utf-8",
    )
    authority_sha = hashlib.sha256(authority.read_bytes()).hexdigest()
    catalog = tmp_path / "evidence.tsv"
    with catalog.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "evidence_id",
                "title",
                "doi_or_identifier",
                "url",
                "local_file",
                "sha256",
                "access_status",
                "claims_verified",
                "verification_date",
            ],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "evidence_id": "EVID:ORCHID",
                "title": "Fixture orchid source",
                "local_file": authority,
                "sha256": authority_sha,
                "access_status": "fixture",
                "claims_verified": "An orchid labellum is a specialised petal.",
                "verification_date": "2026-08-04",
            }
        )
    mapping = tmp_path / "support-evidence.tsv"
    mapping.write_text(
        "proposal_key\tevidence_id\nFLOPO_LOCAL:orchid_labellum\tEVID:ORCHID\n",
        encoding="utf-8",
    )
    curation = tmp_path / "curation.jsonl"
    base = {
        "decision": "propose_flopo_local_bearer",
        "src_candidate_po_id": "",
        "definition": (
            "A petal that is the specialised median member of the inner perianth whorl "
            "of an orchid flower."
        ),
        "direct_superclass_ids": "PO_0009032",
        "parthood_relation": "part_of",
        "part_of_target_ids": "PO_0009059",
        "_sources_used": [{"claim": "Machine proposal claim; not authority."}],
    }
    _jsonl(
        curation,
        [
            {
                **base,
                "proposal_key": "FLOPO_LOCAL:orchid_labellum",
                "preferred_label": "orchid labellum",
                "src_group_key": "heading:labellum",
                "src_evidence_count": 2,
            },
            {
                **base,
                "proposal_key": "FLOPO_LOCAL:unsupported_part",
                "preferred_label": "unsupported part",
                "src_group_key": "heading:unsupported",
                "src_evidence_count": 1,
            },
        ],
    )
    bearer_occurrences = tmp_path / "bearers.jsonl"
    occurrences = []
    for index, text in enumerate(("labellum red", "labellum spotted")):
        surface = text.split()[-1]
        start = text.index(surface)
        occurrences.append(
            {
                "occurrence_id": f"bearer-occurrence-{index}",
                "source": "fixture",
                "source_id": str(index),
                "source_segment_index": 0,
                "taxon": f"Orchid {index}",
                "organ": "labellum",
                "language": "en",
                "segment_document_start": 0,
                "segment_document_end": len(text),
                "text": text,
                "quality": {
                    "start": start,
                    "end": len(text),
                    "surface_form": surface,
                    "candidate_pato_id": "PATO_0000322",
                    "extractor": "fixture",
                },
                "routing": {"group_key": "heading:labellum", "candidate_po_id": ""},
            }
        )
    _jsonl(bearer_occurrences, occurrences)
    po = tmp_path / "po_lexicon.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\tnamespace\n"
        "PO_0009032\tpetal\t\tplant_anatomy\n"
        "PO_0009059\tcorolla\t\tplant_anatomy\n",
        encoding="utf-8",
    )
    pato = tmp_path / "pato_lexicon.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tnamespace\nPATO_0000322\tred\t\tquality\n",
        encoding="utf-8",
    )
    flopo = tmp_path / "flopo.owl"
    flopo.write_text("Ontology(<http://purl.obolibrary.org/obo/flopo.owl>)\n", encoding="utf-8")
    flopo_registry = tmp_path / "flopo_id_registry.tsv"
    flopo_registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000000\t0\tflora phenotype\tOTHER\t0\n",
        encoding="utf-8",
    )
    combinations = tmp_path / "valid_combinations.tsv"
    combinations.write_text("po_id\tpato_id\tstatus\n", encoding="utf-8")
    reviewer_prompt = tmp_path / "reviewer.md"
    reviewer_prompt.write_text("Review the exact support candidate.\n", encoding="utf-8")
    adversarial_prompt = tmp_path / "adversarial.md"
    adversarial_prompt.write_text("Find a concrete blocker.\n", encoding="utf-8")
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
        model_spec(
            reviewer_id="adversary",
            provider="openrouter",
            model="z-ai/glm-5.2",
            model_family="glm-5",
            role="adjudicator",
        ),
    ]
    output = tmp_path / "campaign"
    output.mkdir()
    manifest = build_support_inventory(
        curation_path=curation,
        bearer_occurrence_path=bearer_occurrences,
        evidence_map_path=mapping,
        evidence_catalog_path=catalog,
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        exclusion_path=output / "exclusions.jsonl",
        report_path=output / "report.json",
        manifest_path=output / "manifest.json",
        ontology_paths=[po, pato, flopo, combinations, flopo_registry],
        prompt_paths={"reviewer": reviewer_prompt, "adversarial": adversarial_prompt},
        models=models,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    return manifest, output


def _review(manifest, cluster, occurrence, authority_id, reviewer_id):
    model = next(row for row in manifest.models if row.reviewer_id == reviewer_id)
    prompt = next(row for row in manifest.prompts if row.prompt_id == "reviewer")
    return ReviewDecision(
        campaign_id=manifest.campaign_id,
        item_id=cluster.cluster_id,
        reviewer_id=model.reviewer_id,
        provider=model.provider,
        model=model.model,
        model_family=model.model_family,
        reasoning_effort=model.reasoning_effort,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        disposition="reusable_flopo_support_class",
        proposed_signature={
            "kind": "reusable_flopo_support_class",
            "support_class": cluster.support_class_candidate.signature.model_dump(mode="json"),
        },
        rationale="The archived source supports the exact genus and differentia.",
        confidence=0.95,
        evidence_ids=(occurrence.evidence_id, authority_id),
        validation_passed=True,
    )


def test_support_inventory_requires_archived_authority_and_conserves_occurrences(tmp_path):
    manifest, output = _fixture(tmp_path)
    occurrences = list(read_jsonl(output / "occurrences.jsonl", Occurrence))
    clusters = list(read_jsonl(output / "clusters.jsonl", Cluster))
    exclusions = [json.loads(line) for line in (output / "exclusions.jsonl").read_text().splitlines()]
    report = json.loads((output / "report.json").read_text())

    assert manifest.starting_occurrences == 2
    assert manifest.starting_clusters == 1
    assert len(occurrences) == 2
    assert clusters[0].support_class_candidate.proposal_key == "FLOPO_LOCAL:orchid_labellum"
    assert clusters[0].support_class_candidate.occurrence_count == 2
    assert exclusions[0]["proposal_key"] == "FLOPO_LOCAL:unsupported_part"
    assert exclusions[0]["reason"] == "authority_evidence_not_verified"
    assert report["conservation"]["eligible_plus_excluded_equals_local_proposals"]
    assert manifest.sources


def test_support_class_needs_two_families_and_adversarial_no_blocker(tmp_path):
    manifest, output = _fixture(tmp_path)
    occurrence = next(read_jsonl(output / "occurrences.jsonl", Occurrence))
    cluster = next(read_jsonl(output / "clusters.jsonl", Cluster))
    authority_id = next(
        row.evidence_id
        for row in read_jsonl(output / "evidence.jsonl", EvidenceRecord)
        if row.kind == "authority"
    )
    reviews = [
        _review(manifest, cluster, occurrence, authority_id, "claude"),
        _review(manifest, cluster, occurrence, authority_id, "gpt"),
    ]
    review_path = output / "reviews.jsonl"
    review_path.write_text(
        "".join(row.model_dump_json() + "\n" for row in reviews), encoding="utf-8"
    )
    adversarial_index = build_adversarial_batches(
        manifest=manifest,
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        review_paths=[review_path],
        output_dir=output / "adversarial",
    )
    assert adversarial_index["item_count"] == 1
    model = next(row for row in manifest.models if row.reviewer_id == "adversary")
    prompt = next(row for row in manifest.prompts if row.prompt_id == "adversarial")
    verdict = AdversarialVerdict(
        campaign_id=manifest.campaign_id,
        item_id=cluster.cluster_id,
        reviewer_id=model.reviewer_id,
        provider=model.provider,
        model=model.model,
        model_family=model.model_family,
        reasoning_effort=model.reasoning_effort,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        candidate_signature_sha256=reviews[0].signature_sha256,
        verdict="no_blocker",
        rationale="No duplicate, scope, definition, parent, parthood, or source blocker remains.",
        evidence_ids=(occurrence.evidence_id, authority_id),
        validation_passed=True,
    )
    verdict_path = output / "verdicts.jsonl"
    verdict_path.write_text(verdict.model_dump_json() + "\n", encoding="utf-8")
    consensus_path = output / "consensus.jsonl"
    build_consensus(
        manifest=manifest,
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        review_paths=[review_path],
        adjudication_paths=[verdict_path],
        consensus_path=consensus_path,
        exception_path=output / "exceptions.jsonl",
        ledger_path=output / "ledger.jsonl",
    )
    decision = next(read_jsonl(consensus_path, ConsensusDecision))
    assert decision.status == "llm_consensus"
    assert decision.disposition == "reusable_flopo_support_class"
    assert decision.adjudicator_id == "adversary"

    result = materialize_support_consensus(
        manifest_path=output / "manifest.json",
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        consensus_path=consensus_path,
        ledger_path=output / "ledger.jsonl",
        candidate_report_path=output / "report.json",
        flopo_registry_path=tmp_path / "flopo_id_registry.tsv",
        allocation_path=output / "allocations.tsv",
        module_path=output / "support.ttl",
        held_path=output / "materialization-held.jsonl",
        report_path=output / "materialization-report.json",
        release_date="2026-08-04",
    )
    assert result["accepted_classes"] == 1
    assert result["accepted_occurrences"] == 2
    graph = Graph().parse(output / "support.ttl")
    support = URIRef("http://purl.obolibrary.org/obo/FLOPO_0000001")
    assert (support, RDF.type, OWL.Class) in graph
    assert (
        support,
        RDFS.subClassOf,
        URIRef("http://purl.obolibrary.org/obo/PO_0009032"),
    ) in graph
    assert not list(graph.objects(support, DCTERMS.contributor))


def test_accepted_support_class_still_requires_exact_occurrence_consensus(tmp_path):
    manifest, output = _fixture(tmp_path)
    support_occurrences = list(read_jsonl(output / "occurrences.jsonl", Occurrence))
    support_cluster = next(read_jsonl(output / "clusters.jsonl", Cluster))
    authority_id = next(
        row.evidence_id
        for row in read_jsonl(output / "evidence.jsonl", EvidenceRecord)
        if row.kind == "authority"
    )
    class_reviews = [
        _review(manifest, support_cluster, support_occurrences[0], authority_id, "claude"),
        _review(manifest, support_cluster, support_occurrences[0], authority_id, "gpt"),
    ]
    class_review_path = output / "class-reviews.jsonl"
    _jsonl(class_review_path, [row.model_dump(mode="json") for row in class_reviews])
    model = next(row for row in manifest.models if row.reviewer_id == "adversary")
    prompt = next(row for row in manifest.prompts if row.prompt_id == "adversarial")
    verdict = AdversarialVerdict(
        campaign_id=manifest.campaign_id,
        item_id=support_cluster.cluster_id,
        reviewer_id=model.reviewer_id,
        provider=model.provider,
        model=model.model,
        model_family=model.model_family,
        reasoning_effort=model.reasoning_effort,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        candidate_signature_sha256=class_reviews[0].signature_sha256,
        verdict="no_blocker",
        rationale="The exact class has no remaining blocker.",
        evidence_ids=(support_occurrences[0].evidence_id, authority_id),
        validation_passed=True,
    )
    verdict_path = output / "class-adversary.jsonl"
    verdict_path.write_text(verdict.model_dump_json() + "\n", encoding="utf-8")
    class_consensus_path = output / "class-consensus.jsonl"
    class_ledger_path = output / "class-ledger.jsonl"
    build_consensus(
        manifest=manifest,
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        review_paths=[class_review_path],
        adjudication_paths=[verdict_path],
        consensus_path=class_consensus_path,
        exception_path=output / "class-exceptions.jsonl",
        ledger_path=class_ledger_path,
    )
    allocation_path = output / "allocations.tsv"
    module_path = output / "support.ttl"
    support_report_path = output / "support-materialization.json"
    materialize_support_consensus(
        manifest_path=output / "manifest.json",
        occurrence_path=output / "occurrences.jsonl",
        cluster_path=output / "clusters.jsonl",
        evidence_path=output / "evidence.jsonl",
        consensus_path=class_consensus_path,
        ledger_path=class_ledger_path,
        candidate_report_path=output / "report.json",
        flopo_registry_path=tmp_path / "flopo_id_registry.tsv",
        allocation_path=allocation_path,
        module_path=module_path,
        held_path=output / "support-held.jsonl",
        report_path=support_report_path,
        release_date="2026-08-04",
    )

    stage13_path = tmp_path / "stage13.jsonl"
    stage_rows = []
    for source in support_occurrences:
        text = "labellum red" if source.source_id == "0" else "labellum spotted"
        stage_rows.append(
            {
                "source": source.source,
                "source_id": source.source_id,
                "source_segment_index": source.source_segment_index,
                "taxon": source.taxon,
                "organ": "labellum",
                "language": "en",
                "char_start": 0,
                "char_end": len(text),
                "text": text,
                "assertions": [],
                "source_statements": [],
                "unresolved_spans": [
                    {
                        "start": source.span_start,
                        "end": source.span_end,
                        "surface_form": source.surface_form,
                        "reason": "missing_or_unsupported_bearer",
                        "candidate_pato_id": source.candidate_pato_id,
                        "extractor": "fixture",
                    }
                ],
            }
        )
    _jsonl(stage13_path, stage_rows)
    occurrence_prompt = tmp_path / "occurrence-reviewer.md"
    occurrence_prompt.write_text("Copy the exact expression or hold it.\n", encoding="utf-8")
    occurrence_output = tmp_path / "occurrence-campaign"
    occurrence_output.mkdir()
    occurrence_manifest = build_support_occurrence_inventory(
        stage13_path=stage13_path,
        support_manifest_path=output / "manifest.json",
        support_occurrence_path=output / "occurrences.jsonl",
        support_cluster_path=output / "clusters.jsonl",
        support_evidence_path=output / "evidence.jsonl",
        support_consensus_path=class_consensus_path,
        support_ledger_path=class_ledger_path,
        support_allocation_path=allocation_path,
        support_module_path=module_path,
        support_materialization_report_path=support_report_path,
        occurrence_path=occurrence_output / "occurrences.jsonl",
        cluster_path=occurrence_output / "clusters.jsonl",
        evidence_path=occurrence_output / "evidence.jsonl",
        exclusion_path=occurrence_output / "exclusions.jsonl",
        report_path=occurrence_output / "report.json",
        manifest_path=occurrence_output / "manifest.json",
        ontology_paths=[
            tmp_path / "po_lexicon.tsv",
            tmp_path / "pato_lexicon.tsv",
            tmp_path / "flopo.owl",
            tmp_path / "valid_combinations.tsv",
            tmp_path / "flopo_id_registry.tsv",
            module_path,
        ],
        prompt_paths={"reviewer": occurrence_prompt},
        models=[row for row in manifest.models if row.role == "reviewer"],
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    occurrence_rows = list(
        read_jsonl(occurrence_output / "occurrences.jsonl", Occurrence)
    )
    occurrence_clusters = list(read_jsonl(occurrence_output / "clusters.jsonl", Cluster))
    assert occurrence_manifest.starting_occurrences == 2
    assert occurrence_manifest.starting_clusters == 2
    assert all(row.occurrence_count == 1 for row in occurrence_clusters)
    assert {
        row.phenotype_expression_candidate.signature.bearer_id for row in occurrence_rows
    } == {"FLOPO_0000001"}

    occurrence_reviews = []
    occurrence_prompt_spec = next(
        row for row in occurrence_manifest.prompts if row.prompt_id == "reviewer"
    )
    for cluster, occurrence in zip(occurrence_clusters, occurrence_rows, strict=True):
        for reviewer in occurrence_manifest.models:
            accept = occurrence.surface_form == "red"
            occurrence_reviews.append(
                ReviewDecision(
                    campaign_id=occurrence_manifest.campaign_id,
                    item_id=cluster.cluster_id,
                    reviewer_id=reviewer.reviewer_id,
                    provider=reviewer.provider,
                    model=reviewer.model,
                    model_family=reviewer.model_family,
                    reasoning_effort=reviewer.reasoning_effort,
                    prompt_id=occurrence_prompt_spec.prompt_id,
                    prompt_sha256=occurrence_prompt_spec.sha256,
                    disposition="annotation_expression" if accept else "hold",
                    proposed_signature=(
                        {
                            "kind": "annotation_expression",
                            "expression": (
                                occurrence.phenotype_expression_candidate.signature.model_dump(
                                    mode="json"
                                )
                            ),
                        }
                        if accept
                        else {"kind": "hold", "reason": "The marked word is not red."}
                    ),
                    rationale="Exact source-bound occurrence decision.",
                    confidence=0.99,
                    evidence_ids=(occurrence.evidence_id,),
                    validation_passed=True,
                )
            )
    occurrence_review_path = occurrence_output / "reviews.jsonl"
    _jsonl(
        occurrence_review_path,
        [row.model_dump(mode="json") for row in occurrence_reviews],
    )
    occurrence_consensus_path = occurrence_output / "consensus.jsonl"
    occurrence_ledger_path = occurrence_output / "ledger.jsonl"
    build_consensus(
        manifest=occurrence_manifest,
        occurrence_path=occurrence_output / "occurrences.jsonl",
        cluster_path=occurrence_output / "clusters.jsonl",
        evidence_path=occurrence_output / "evidence.jsonl",
        review_paths=[occurrence_review_path],
        adjudication_paths=[],
        consensus_path=occurrence_consensus_path,
        exception_path=occurrence_output / "exceptions.jsonl",
        ledger_path=occurrence_ledger_path,
    )
    proposals_path = occurrence_output / "proposals.jsonl"
    occurrence_materialization = materialize_support_occurrence_consensus(
        manifest_path=occurrence_output / "manifest.json",
        occurrence_path=occurrence_output / "occurrences.jsonl",
        cluster_path=occurrence_output / "clusters.jsonl",
        evidence_path=occurrence_output / "evidence.jsonl",
        consensus_path=occurrence_consensus_path,
        ledger_path=occurrence_ledger_path,
        candidate_report_path=occurrence_output / "report.json",
        stage13_path=stage13_path,
        proposals_path=proposals_path,
        held_path=occurrence_output / "held.jsonl",
        report_path=occurrence_output / "materialization.json",
        combinations_path=tmp_path / "valid_combinations.tsv",
        registry_path=tmp_path / "flopo_id_registry.tsv",
        po_lexicon_path=tmp_path / "po_lexicon.tsv",
        pato_lexicon_path=tmp_path / "pato_lexicon.tsv",
    )
    assert occurrence_materialization["proposals"] == 1
    assert occurrence_materialization["held"] == 1
    assert occurrence_materialization["provenance"]["human_reviewed"] is False
    stage14_path = occurrence_output / "stage14.jsonl"
    applied = apply_reviewed_proposals(stage13_path, proposals_path, stage14_path)
    assert applied["assertions_added"] == 1
    rows = [json.loads(line) for line in stage14_path.read_text().splitlines()]
    rows_by_source = {row["source_id"]: row for row in rows}
    assert len(rows_by_source["0"]["assertions"]) == 1
    assert rows_by_source["0"]["assertions"][0]["po_id"] == "FLOPO_0000001"
    assert rows_by_source["1"]["unresolved_spans"][0]["surface_form"] == "spotted"
