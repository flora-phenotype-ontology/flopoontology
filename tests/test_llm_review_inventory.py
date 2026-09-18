import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flopo2.review.inventory import build_inventory, model_spec
from flopo2.review.io import read_jsonl, sha256_file
from flopo2.review.models import ArtifactHash, Cluster, Occurrence
from flopo2.review.validation import _artifact_path
from flopo2.review.batches import build_batches, build_stratified_pilot_batch


def test_content_addressed_snapshot_preserves_completed_campaign_locator(
    tmp_path, monkeypatch
):
    declared = tmp_path / "live.tsv"
    declared.write_text("frozen\n", encoding="utf-8")
    frozen = sha256_file(declared)
    artifact = ArtifactHash(path=str(declared), sha256=frozen.sha256, bytes=frozen.bytes)
    store = tmp_path / "store"
    store.mkdir()
    snapshot = store / frozen.sha256
    snapshot.write_bytes(declared.read_bytes())
    declared.write_text("published replacement\n", encoding="utf-8")
    monkeypatch.setenv("FLOPO_REVIEW_ARTIFACT_ROOT", str(store))
    assert _artifact_path(artifact) == snapshot


def _write_stage(path: Path) -> None:
    records = [
        {
            "source": "fixture",
            "source_id": "a",
            "source_segment_index": 0,
            "taxon": "Plant one",
            "organ": "leaf",
            "language": "en",
            "char_start": 10,
            "char_end": 20,
            "text": "leaves red",
            "unresolved_spans": [
                {
                    "start": 7,
                    "end": 10,
                    "surface_form": "red",
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": "PATO_0000322",
                    "extractor": "fixture",
                },
            ],
        },
        {
            "source": "fixture",
            "source_id": "a-duplicate",
            "source_segment_index": 0,
            "taxon": "Plant duplicate",
            "organ": "leaf",
            "language": "en",
            "char_start": 0,
            "char_end": 10,
            "text": "leaves red",
            "unresolved_spans": [
                {
                    "start": 7,
                    "end": 10,
                    "surface_form": "red",
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": "PATO_0000322",
                    "extractor": "fixture",
                }
            ],
        },
        {
            "source": "fixture",
            "source_id": "b",
            "source_segment_index": 0,
            "taxon": "Plant two",
            "organ": "flower",
            "language": "en",
            "char_start": 0,
            "char_end": 12,
            "text": "flowers blue",
            "unresolved_spans": [
                {
                    "start": 8,
                    "end": 12,
                    "surface_form": "blue",
                    "reason": "explicit_disjunction",
                    "candidate_pato_id": "PATO_0000318",
                    "extractor": "fixture",
                }
            ],
        },
        {
            "source": "fixture",
            "source_id": "c",
            "source_segment_index": 0,
            "taxon": "Plant three",
            "organ": "flower",
            "language": "en",
            "char_start": 0,
            "char_end": 11,
            "text": "flowers red",
            "unresolved_spans": [
                {
                    "start": 8,
                    "end": 11,
                    "surface_form": "red",
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": "PATO_0000322",
                    "extractor": "fixture",
                }
            ],
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")


def campaign_fixture(tmp_path: Path):
    stage = tmp_path / "stage13.jsonl"
    _write_stage(stage)
    ontology = tmp_path / "flopo.owl"
    ontology.write_text("http://purl.obolibrary.org/obo/FLOPO_0000001\n", encoding="utf-8")
    po_lexicon = tmp_path / "po_lexicon.tsv"
    po_lexicon.write_text("id\tlabel\nPO_0009025\tleaf\n", encoding="utf-8")
    pato_lexicon = tmp_path / "pato_lexicon.tsv"
    pato_lexicon.write_text(
        "id\tlabel\nPATO_0000322\tred\nPATO_0000318\tblue\n", encoding="utf-8"
    )
    combinations = tmp_path / "valid_combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\n"
        "PO_0009025\tPATO_0000322\tallowed\n"
        "PO_0009025\tPATO_0000318\tallowed\n",
        encoding="utf-8",
    )
    authority = tmp_path / "authority.txt"
    authority.write_text(
        "Fixture glossary: a reusable phenotype has a source-backed definition.\n",
        encoding="utf-8",
    )
    reviewer_prompt = tmp_path / "reviewer.txt"
    reviewer_prompt.write_text("Review conservatively.\n", encoding="utf-8")
    adversarial_prompt = tmp_path / "adversarial.txt"
    adversarial_prompt.write_text("Find a blocker.\n", encoding="utf-8")
    occurrences = tmp_path / "occurrences.jsonl"
    clusters = tmp_path / "clusters.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    manifest_path = tmp_path / "manifest.json"
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
            reviewer_id="gpt-same-family",
            provider="azure-openai",
            model="gpt-5.6-high",
            model_family="gpt-5",
            role="reviewer",
        ),
        model_spec(
            reviewer_id="adversary",
            provider="independent",
            model="reasoner-x",
            model_family="reasoner-x",
            role="adjudicator",
        ),
    ]
    manifest = build_inventory(
        stage13_path=stage,
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        manifest_path=manifest_path,
        ontology_paths=[ontology, po_lexicon, pato_lexicon, combinations],
        authority_paths=[authority],
        prompt_paths={"reviewer": reviewer_prompt, "adversarial": adversarial_prompt},
        models=models,
        created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    return manifest, occurrences, clusters, evidence, manifest_path


def test_inventory_is_lossless_clustered_and_hash_frozen(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    occurrence_rows = list(read_jsonl(occurrences, Occurrence))
    cluster_rows = list(read_jsonl(clusters, Cluster))

    assert manifest.starting_occurrences == 4
    assert manifest.starting_clusters == 3
    assert len({row.occurrence_id for row in occurrence_rows}) == 4
    red = next(
        row for row in cluster_rows if row.normalized_form == "red" and row.organ == "leaf"
    )
    assert red.occurrence_count == 2
    red_member_ids = {
        row.occurrence_id
        for row in occurrence_rows
        if row.cluster_id == red.cluster_id
    }
    assert len(red_member_ids) == red.occurrence_count
    assert {
        row.organ for row in cluster_rows if row.normalized_form == "red"
    } == {"leaf", "flower"}
    assert all("[[" in row.context and "]]" in row.context for row in occurrence_rows)
    assert manifest.input.sha256
    assert manifest.ontologies[0].sha256
    assert {row.prompt_id for row in manifest.prompts} == {"reviewer", "adversarial"}
    assert all(row.descriptor_sha256 for row in manifest.models)
    assert manifest.evidence_registry.sha256
    assert evidence.is_file()
    assert all(row.occurrence_membership_sha256 for row in cluster_rows)
    assert all(not hasattr(row, "occurrence_ids") for row in cluster_rows)


def test_inventory_resume_preserves_immutable_manifest(tmp_path):
    manifest, occurrences, clusters, evidence, manifest_path = campaign_fixture(tmp_path)
    first = manifest_path.read_text(encoding="utf-8")
    # Same frozen inputs/configuration are safe to replay and retain the original timestamp.
    ontology = tmp_path / "flopo.owl"
    prompts = {
        "reviewer": tmp_path / "reviewer.txt",
        "adversarial": tmp_path / "adversarial.txt",
    }
    replay = build_inventory(
        stage13_path=tmp_path / "stage13.jsonl",
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        manifest_path=manifest_path,
        ontology_paths=[
            ontology,
            tmp_path / "po_lexicon.tsv",
            tmp_path / "pato_lexicon.tsv",
            tmp_path / "valid_combinations.tsv",
        ],
        authority_paths=[tmp_path / "authority.txt"],
        prompt_paths=prompts,
        models=manifest.models,
    )
    assert replay == manifest
    assert manifest_path.read_text(encoding="utf-8") == first

    prompts["reviewer"].write_text("Changed prompt.\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="immutable manifest"):
        build_inventory(
            stage13_path=tmp_path / "stage13.jsonl",
            occurrence_path=occurrences,
            cluster_path=clusters,
            evidence_path=evidence,
            manifest_path=manifest_path,
            ontology_paths=[
                ontology,
                tmp_path / "po_lexicon.tsv",
                tmp_path / "pato_lexicon.tsv",
                tmp_path / "valid_combinations.tsv",
            ],
            authority_paths=[tmp_path / "authority.txt"],
            prompt_paths=prompts,
            models=manifest.models,
        )


def test_inventory_rejects_non_verbatim_span(tmp_path):
    stage = tmp_path / "bad.jsonl"
    stage.write_text(
        json.dumps(
            {
                "source": "x",
                "source_id": "1",
                "text": "red",
                "unresolved_spans": [
                    {
                        "start": 0,
                        "end": 3,
                        "surface_form": "blue",
                        "reason": "test",
                        "extractor": "test",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ontology = tmp_path / "o.owl"
    ontology.write_text("o", encoding="utf-8")
    prompt = tmp_path / "p.txt"
    prompt.write_text("p", encoding="utf-8")
    with pytest.raises(ValueError, match="not verbatim"):
        build_inventory(
            stage13_path=stage,
            occurrence_path=tmp_path / "occ.jsonl",
            cluster_path=tmp_path / "cluster.jsonl",
            evidence_path=tmp_path / "evidence.jsonl",
            manifest_path=tmp_path / "manifest.json",
            ontology_paths=[ontology],
            prompt_paths={"p": prompt},
            models=[],
        )


def test_inventory_rejects_input_output_path_alias_before_writing(tmp_path):
    stage = tmp_path / "stage.jsonl"
    stage.write_text("", encoding="utf-8")
    ontology = tmp_path / "ontology.owl"
    ontology.write_text("Ontology fixture\n", encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Review.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="distinct paths"):
        build_inventory(
            stage13_path=stage,
            occurrence_path=stage,
            cluster_path=tmp_path / "clusters.jsonl",
            evidence_path=tmp_path / "evidence.jsonl",
            manifest_path=tmp_path / "manifest.json",
            ontology_paths=[ontology],
            prompt_paths={"reviewer": prompt},
            models=[],
        )
    assert stage.read_text(encoding="utf-8") == ""


def test_review_batches_are_complete_immutable_and_hash_bound(tmp_path):
    manifest, _, clusters, _, _ = campaign_fixture(tmp_path)
    output = tmp_path / "batches"
    index = build_batches(manifest, clusters, output, batch_size=2)
    assert index["batch_count"] == 2
    assert index["item_count"] == manifest.starting_clusters
    assert index["occurrence_count"] == manifest.starting_occurrences
    assert index["order"] == "priority"
    assert sum(row["item_count"] for row in index["batches"]) == manifest.starting_clusters
    assert all(row["bytes"] <= index["max_bytes"] for row in index["batches"])
    first_packet = json.loads((output / "batch-00001.json").read_text())
    assert "occurrence_ids" not in first_packet["items"][0]
    assert first_packet["items"][0]["occurrence_membership_sha256"]
    assert first_packet["reference_evidence"][0]["evidence_id"].startswith("evidence_")
    assert build_batches(manifest, clusters, output, batch_size=2) == index
    with pytest.raises(FileExistsError, match="review batch"):
        build_batches(manifest, clusters, output, batch_size=3)

    pilot = build_stratified_pilot_batch(
        manifest, clusters, tmp_path / "pilot", per_reason=1
    )
    packet = json.loads((tmp_path / "pilot" / "batch-90001.json").read_text())
    assert pilot["scope"] == "pilot"
    assert packet["item_count"] == len({row["reason"] for row in packet["items"]})
    assert pilot["batches"][0]["bytes"] <= pilot["max_bytes"]
