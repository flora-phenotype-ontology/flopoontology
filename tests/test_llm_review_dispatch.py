import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from flopo2.review.batches import build_batches
from flopo2.review.consensus import build_consensus
from flopo2.review.dispatch import (
    _bind_response_schema_to_packet,
    collect_completed_decisions,
    dispatch_batch,
)
from flopo2.review.io import read_jsonl
from flopo2.review.io import sha256_file
from flopo2.review.inventory import build_inventory, model_spec
from flopo2.review.models import (
    AdversarialBatchResponse,
    AdversarialVerdict,
    Cluster,
    Occurrence,
    ReviewBatchResponse,
    ReviewDecision,
)
from flopo2.review.responses import response_schema, write_response_schemas
from test_llm_review_inventory import campaign_fixture


def _packet(tmp_path: Path):
    manifest, occurrences, clusters, evidence, manifest_path = campaign_fixture(tmp_path)
    batch_dir = tmp_path / "batches"
    build_batches(manifest, clusters, batch_dir, batch_size=2)
    batch_path = batch_dir / "batch-00001.json"
    packet = json.loads(batch_path.read_text(encoding="utf-8"))
    return (
        manifest,
        occurrences,
        clusters,
        evidence,
        manifest_path,
        batch_dir / "index.json",
        batch_path,
        packet,
    )


def _response(manifest, packet, reviewer_id="claude", **overrides):
    model = next(row for row in manifest.models if row.reviewer_id == reviewer_id)
    prompt = next(row for row in manifest.prompts if row.prompt_id == "reviewer")
    decisions = []
    for item in packet["items"]:
        values = {
            "campaign_id": manifest.campaign_id,
            "item_id": item["cluster_id"],
            "reviewer_id": reviewer_id,
            "provider": model.provider,
            "model": model.model,
            "model_family": model.model_family,
            "reasoning_effort": model.reasoning_effort,
            "prompt_id": prompt.prompt_id,
            "prompt_sha256": prompt.sha256,
            "disposition": "existing_term_mapping",
            "proposed_signature": {
                "kind": "existing_term_mapping",
                "target_id": item.get("candidate_pato_id") or "PATO_0000322",
                "target_scope": "quality",
            },
            "rationale": "The supplied ontology and occurrence contexts support this mapping.",
            "confidence": 0.95,
            "evidence_ids": (item["context_samples"][0]["evidence_id"],),
            "validation_passed": True,
        }
        values.update(overrides)
        decisions.append(ReviewDecision(**values))
    return ReviewBatchResponse(decisions=tuple(decisions))


def _dispatch_args(tmp_path, manifest_path, index_path, batch_path, reviewer_id):
    return {
        "manifest_path": manifest_path,
        "batch_index_path": index_path,
        "batch_path": batch_path,
        "reviewer_id": reviewer_id,
        "prompt_id": "reviewer",
        "checkpoint_root": tmp_path / "checkpoints",
        "cwd": tmp_path,
    }


def test_claude_dispatch_extracts_structured_envelope_and_resumes(tmp_path):
    manifest, _, _, _, manifest_path, index_path, batch_path, packet = _packet(tmp_path)
    response = _response(manifest, packet)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        envelope = {"type": "result", "structured_output": response.model_dump(mode="json")}
        return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")

    args = _dispatch_args(tmp_path, manifest_path, index_path, batch_path, "claude")
    result = dispatch_batch(**args, runner=runner)
    assert result["status"] == "completed"
    assert result["decisions"] == packet["item_count"]
    command, call = calls[0]
    assert command[:4] == ["claude", "--print", "--model", "claude-opus-4-8"]
    assert command[command.index("--output-format") + 1] == "json"
    assert "--json-schema" in command
    assert command[command.index("--permission-mode") + 1] == "plan"
    assert command[command.index("--tools") + 1] == "Read,Glob,Grep"
    assert command[command.index("--allowedTools") + 1] == "Read,Glob,Grep"
    assert "Bash,Edit,Write" in command[command.index("--disallowedTools") + 1]
    assert manifest.campaign_id in call["input"]
    assert json.loads(batch_path.read_text())["batch_id"] in call["input"]

    directory = Path(result["directory"])
    decisions = list(read_jsonl(directory / "decisions.jsonl", ReviewDecision))
    assert [row.item_id for row in decisions] == [row["cluster_id"] for row in packet["items"]]
    assert json.loads((directory / "raw-response.json").read_text()) == response.model_dump(
        mode="json"
    )
    assert (directory / "completion.json").is_file()
    provider_envelope = json.loads((directory / "provider-envelope.json").read_text())
    assert provider_envelope["requested_model"] == "claude-opus-4-8"
    assert provider_envelope["reasoning_effort"] == "high"
    assert provider_envelope["model_verification"] == "command_pinned"
    assert not (directory / "failure.json").exists()

    def must_not_run(*args, **kwargs):
        raise AssertionError("valid checkpoint should be skipped")

    resumed = dispatch_batch(**args, runner=must_not_run)
    assert resumed["status"] == "skipped"

    # A corrupt normalized artifact invalidates the checkpoint and triggers a clean retry.
    (directory / "decisions.jsonl").write_text("not-json\n", encoding="utf-8")
    retried = dispatch_batch(**args, runner=runner)
    assert retried["status"] == "completed"
    assert len(calls) == 2
    history = list((directory / "attempt-history").glob("*/raw-response.json"))
    assert len(history) == 1


def test_codex_dispatch_uses_exact_model_read_only_schema(tmp_path):
    manifest, _, _, _, manifest_path, index_path, batch_path, packet = _packet(tmp_path)
    response = _response(manifest, packet, reviewer_id="gpt")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(response.model_dump_json(), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

    args = _dispatch_args(tmp_path, manifest_path, index_path, batch_path, "gpt")
    result = dispatch_batch(**args, runner=runner)
    assert result["status"] == "completed"
    command, call = calls[0]
    assert command[:2] == ["codex", "exec"]
    assert command[command.index("--model") + 1] == "gpt-5.6"
    assert "--ignore-user-config" in command
    assert "--strict-config" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert command[-1] == "-"
    schema_path = Path(command[command.index("--output-schema") + 1])
    assert schema_path.is_file()
    expected_schema = response_schema("reviewer")
    expected_schema["properties"]["decisions"].update(
        minItems=packet["item_count"], maxItems=packet["item_count"]
    )
    assert json.loads(schema_path.read_text()) == expected_schema
    assert call["input"].startswith("FLOPO MACHINE REVIEW")
    assert (Path(result["directory"]) / "provider-output.txt").read_text().startswith("{")


def test_collect_completed_decisions_requires_and_conserves_every_batch(tmp_path):
    manifest, _, _, _, manifest_path = campaign_fixture(tmp_path)
    batch_dir = tmp_path / "collect-batches"
    index = build_batches(manifest, tmp_path / "clusters.jsonl", batch_dir, batch_size=2)
    checkpoint_root = tmp_path / "collect-checkpoints"

    for indexed_batch in index["batches"]:
        batch_path = Path(indexed_batch["path"])
        packet = json.loads(batch_path.read_text(encoding="utf-8"))
        response = _response(manifest, packet)

        def runner(command, **kwargs):
            envelope = {"structured_output": response.model_dump(mode="json")}
            return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")

        result = dispatch_batch(
            manifest_path=manifest_path,
            batch_index_path=batch_dir / "index.json",
            batch_path=batch_path,
            reviewer_id="claude",
            prompt_id="reviewer",
            checkpoint_root=checkpoint_root,
            cwd=tmp_path,
            runner=runner,
        )
        assert result["status"] == "completed"

    output = tmp_path / "reviews-claude.jsonl"
    report = collect_completed_decisions(
        manifest_path=manifest_path,
        batch_index_path=batch_dir / "index.json",
        checkpoint_root=checkpoint_root,
        reviewer_id="claude",
        output_path=output,
        cwd=tmp_path,
    )
    rows = list(read_jsonl(output, ReviewDecision))
    assert report["batches"] == 2
    assert report["decisions"] == manifest.starting_clusters == len(rows)
    assert len({row.item_id for row in rows}) == len(rows)
    assert report["sha256"] == sha256_file(output).sha256

    # A previously collected file does not make a now-corrupt checkpoint acceptable.
    corrupt = checkpoint_root / "claude" / "batch_00002" / "decisions.jsonl"
    corrupt.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or corrupt"):
        collect_completed_decisions(
            manifest_path=manifest_path,
            batch_index_path=batch_dir / "index.json",
            checkpoint_root=checkpoint_root,
            reviewer_id="claude",
            output_path=output,
            cwd=tmp_path,
        )


def test_partial_collection_emits_only_valid_checkpoints_and_conserves_missing(tmp_path):
    manifest, _, _, _, manifest_path = campaign_fixture(tmp_path)
    batch_dir = tmp_path / "partial-batches"
    index = build_batches(manifest, tmp_path / "clusters.jsonl", batch_dir, batch_size=2)
    checkpoint_root = tmp_path / "partial-checkpoints"
    first = index["batches"][0]
    batch_path = Path(first["path"])
    packet = json.loads(batch_path.read_text(encoding="utf-8"))
    response = _response(manifest, packet)

    def runner(command, **kwargs):
        envelope = {"structured_output": response.model_dump(mode="json")}
        return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")

    dispatch_batch(
        manifest_path=manifest_path,
        batch_index_path=batch_dir / "index.json",
        batch_path=batch_path,
        reviewer_id="claude",
        prompt_id="reviewer",
        checkpoint_root=checkpoint_root,
        cwd=tmp_path,
        runner=runner,
    )
    output = tmp_path / "partial-reviews.jsonl"
    report_path = tmp_path / "partial-report.json"
    report = collect_completed_decisions(
        manifest_path=manifest_path,
        batch_index_path=batch_dir / "index.json",
        checkpoint_root=checkpoint_root,
        reviewer_id="claude",
        output_path=output,
        cwd=tmp_path,
        allow_partial=True,
        report_path=report_path,
    )

    assert report["partial"] is True
    assert report["completed_batch_count"] == 1
    assert report["missing_batch_count"] == 1
    assert report["decisions"] + report["missing_items"] == manifest.starting_clusters
    assert [row.item_id for row in read_jsonl(output, ReviewDecision)] == [
        item["cluster_id"] for item in packet["items"]
    ]
    assert json.loads(report_path.read_text()) == report

    # A purported completion is corruption, never an omitted batch.
    missing_id = report["missing_batches"][0]
    missing_dir = checkpoint_root / "claude" / missing_id
    missing_dir.mkdir(parents=True)
    (missing_dir / "completion.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing or invalid dispatch binding"):
        collect_completed_decisions(
            manifest_path=manifest_path,
            batch_index_path=batch_dir / "index.json",
            checkpoint_root=checkpoint_root,
            reviewer_id="claude",
            output_path=output,
            cwd=tmp_path,
            allow_partial=True,
        )


def test_openrouter_adjudicator_requires_explicit_dispatch_and_uses_fake_client(tmp_path):
    base, _, _, _, _ = campaign_fixture(tmp_path)
    models = [
        *[row for row in base.models if row.role == "reviewer"],
        model_spec(
            reviewer_id="glm-adversary",
            provider="openrouter",
            model="z-ai/glm-5.2",
            model_family="glm-5",
            role="adjudicator",
        ),
    ]
    manifest_path = tmp_path / "openrouter-manifest.json"
    occurrences = tmp_path / "openrouter-occurrences.jsonl"
    clusters = tmp_path / "openrouter-clusters.jsonl"
    evidence = tmp_path / "openrouter-evidence.jsonl"
    manifest = build_inventory(
        stage13_path=tmp_path / "stage13.jsonl",
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        manifest_path=manifest_path,
        ontology_paths=[
            tmp_path / "flopo.owl",
            tmp_path / "po_lexicon.tsv",
            tmp_path / "pato_lexicon.tsv",
            tmp_path / "valid_combinations.tsv",
        ],
        prompt_paths={
            "reviewer": tmp_path / "reviewer.txt",
            "adversarial": tmp_path / "adversarial.txt",
        },
        models=models,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    batch_dir = tmp_path / "openrouter-batches"
    batch_dir.mkdir()
    cluster_rows = list(read_jsonl(clusters, Cluster))
    candidate_set_sha256 = "a" * 64
    packet = {
        "schema_version": "flopo-adversarial-batch-v1",
        "campaign_id": manifest.campaign_id,
        "batch_id": "batch_00001",
        "item_count": len(cluster_rows),
        "candidate_set_sha256": candidate_set_sha256,
        "items": [
            {
                "cluster_id": row.cluster_id,
                "candidate_signature": {
                    "kind": "reusable_flopo_class",
                    "label": "fixture phenotype",
                    "definition": "A reusable phenotype used only by this dispatch fixture.",
                },
                "candidate_signature_sha256": "b" * 64,
                "reviewers": [],
                "cluster": row.model_dump(mode="json"),
            }
            for row in cluster_rows
        ],
    }
    batch_path = batch_dir / "batch-00001.json"
    batch_path.write_text(json.dumps(packet, sort_keys=True) + "\n", encoding="utf-8")
    index = {
        "schema_version": "flopo-adversarial-batch-index-v1",
        "campaign_id": manifest.campaign_id,
        "cluster_sha256": manifest.clusters.sha256,
        "evidence_sha256": manifest.evidence_registry.sha256,
        "candidate_set_sha256": candidate_set_sha256,
        "batch_count": 1,
        "item_count": len(cluster_rows),
        "batches": [{
            "batch_id": "batch_00001",
            "path": str(batch_path),
            "sha256": sha256_file(batch_path).sha256,
        }],
    }
    (batch_dir / "index.json").write_text(json.dumps(index) + "\n", encoding="utf-8")
    model = next(row for row in manifest.models if row.reviewer_id == "glm-adversary")
    prompt = next(row for row in manifest.prompts if row.prompt_id == "adversarial")
    decisions = tuple(
        AdversarialVerdict(
            campaign_id=manifest.campaign_id,
            item_id=item["cluster_id"],
            reviewer_id=model.reviewer_id,
            provider=model.provider,
            model=model.model,
            model_family=model.model_family,
            reasoning_effort=model.reasoning_effort,
            prompt_id=prompt.prompt_id,
            prompt_sha256=prompt.sha256,
            candidate_signature_sha256="b" * 64,
            verdict="no_blocker",
            rationale="No blocker found in the pinned evidence.",
            evidence_ids=(item["cluster"]["context_samples"][0]["evidence_id"],),
            validation_passed=True,
        )
        for item in packet["items"]
    )
    batch_response = AdversarialBatchResponse(decisions=decisions)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "request-fixture",
                "model": "z-ai/glm-5.2",
                "choices": [{"message": {"content": batch_response.model_dump_json()}}],
            }

    class FakeClient:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse()

    arguments = {
        "manifest_path": manifest_path,
        "batch_index_path": batch_dir / "index.json",
        "batch_path": batch_path,
        "reviewer_id": "glm-adversary",
        "prompt_id": "adversarial",
        "checkpoint_root": tmp_path / "openrouter-checkpoints",
        "cwd": tmp_path,
    }
    with pytest.raises(ValueError, match="explicitly requested"):
        dispatch_batch(**arguments)

    client = FakeClient()
    result = dispatch_batch(
        **arguments,
        backend="openrouter",
        http_client=client,
        openrouter_api_key="test-key",
        max_output_tokens=12_345,
    )
    assert result["status"] == "completed"
    url, request = client.calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert request["json"]["model"] == "z-ai/glm-5.2"
    assert request["json"]["max_tokens"] == 12_345
    assert request["json"]["response_format"]["json_schema"]["strict"] is True
    dispatched_schema = request["json"]["response_format"]["json_schema"]["schema"]
    assert dispatched_schema["properties"]["decisions"]["minItems"] == packet["item_count"]
    assert dispatched_schema["properties"]["decisions"]["maxItems"] == packet["item_count"]
    assert request["headers"]["Authorization"] == "Bearer test-key"
    prompt_text = (Path(result["directory"]) / "prompt.txt").read_text()
    assert "one top-level JSON object with exactly `schema_version` and `decisions`" in prompt_text
    assert "put one structured decision for every item in the `decisions` array" in prompt_text
    assert "`disposition` to exactly `structured_qualitative_relation`" in prompt_text
    assert "Keep `confidence` and `validation_passed` outside `proposed_signature`" in prompt_text
    assert "Copy every campaign, reviewer, provider, model, model-family" in prompt_text
    assert "into each decision object—not into the top-level wrapper" in prompt_text

    json_client = FakeClient()
    json_result = dispatch_batch(
        **{
            **arguments,
            "checkpoint_root": tmp_path / "openrouter-json-checkpoints",
        },
        backend="openrouter",
        http_client=json_client,
        openrouter_api_key="test-key",
        max_output_tokens=12_345,
        openrouter_response_mode="json_object",
    )
    assert json_result["status"] == "completed"
    _, json_request = json_client.calls[0]
    assert json_request["json"]["response_format"] == {"type": "json_object"}
    binding_dir = Path(json_result["directory"])
    assert "RESPONSE_JSON_SCHEMA" in (binding_dir / "prompt.txt").read_text()

    collected = tmp_path / "adjudications-glm.jsonl"
    collection = collect_completed_decisions(
        manifest_path=manifest_path,
        batch_index_path=batch_dir / "index.json",
        checkpoint_root=tmp_path / "openrouter-checkpoints",
        reviewer_id="glm-adversary",
        output_path=collected,
        cwd=tmp_path,
    )
    collected_rows = list(read_jsonl(collected, AdversarialVerdict))
    assert collection["schema_version"] == "flopo-adjudication-collection-v1"
    assert collection["role"] == "adjudicator"
    assert collection["decisions"] == len(cluster_rows) == len(collected_rows)
    assert [row.item_id for row in collected_rows] == [
        row.cluster_id for row in cluster_rows
    ]


def test_qualitative_packet_schema_excludes_class_only_signature_fields():
    schema = response_schema("reviewer")
    packet = {
        "items": [
            {
                "qualitative_relation_candidate": {"signature": {}},
                "phenotype_expression_candidate": None,
                "support_class_candidate": None,
            }
        ]
    }

    _bind_response_schema_to_packet(schema, packet, role="reviewer")

    assert schema["properties"]["decisions"]["minItems"] == 1
    assert schema["properties"]["decisions"]["maxItems"] == 1
    definitions = schema["$defs"]
    assert definitions["ReviewDecision"]["properties"]["disposition"]["enum"] == [
        "structured_qualitative_relation",
        "hold",
    ]
    signature = definitions["ProposedSignature"]["properties"]
    assert signature["kind"]["enum"] == ["structured_qualitative_relation", "hold"]
    assert set(signature) == {"kind", "qualitative_relation", "reason", "missing_evidence"}
    assert set(definitions["ProposedSignature"]["required"]) == set(signature)


def test_reusable_class_packet_schema_exposes_only_exact_candidate_fields():
    schema = response_schema("reviewer")
    packet = {
        "items": [
            {
                "reusable_flopo_class_candidate": {"signature": {}},
                "qualitative_relation_candidate": None,
                "phenotype_expression_candidate": None,
                "support_class_candidate": None,
            }
        ]
    }

    _bind_response_schema_to_packet(schema, packet, role="reviewer")

    definitions = schema["$defs"]
    assert definitions["ReviewDecision"]["properties"]["disposition"]["enum"] == [
        "reusable_flopo_class",
        "hold",
    ]
    variants = definitions["ProposedSignature"]["anyOf"]
    assert len(variants) == 2
    accepted, hold = variants
    assert accepted["properties"]["kind"] == {
        "const": "reusable_flopo_class",
        "type": "string",
    }
    assert set(accepted["properties"]) == {
        "kind",
        "expression",
        "label",
        "definition",
        "parent_ids",
        "authoritative_evidence_ids",
    }
    assert set(accepted["required"]) == set(accepted["properties"])
    assert accepted["additionalProperties"] is False
    assert hold["properties"]["kind"] == {"const": "hold", "type": "string"}
    assert set(hold["properties"]) == {"kind", "reason", "missing_evidence"}
    assert set(hold["required"]) == set(hold["properties"])
    assert hold["additionalProperties"] is False


def test_expression_packet_schema_separates_exact_candidate_from_hold():
    schema = response_schema("reviewer")
    packet = {
        "items": [
            {
                "phenotype_expression_candidate": {"signature": {}},
                "reusable_flopo_class_candidate": None,
                "qualitative_relation_candidate": None,
                "support_class_candidate": None,
            }
        ]
    }

    _bind_response_schema_to_packet(schema, packet, role="reviewer")

    definitions = schema["$defs"]
    assert definitions["ReviewDecision"]["properties"]["disposition"]["enum"] == [
        "annotation_expression",
        "hold",
    ]
    accepted, hold = definitions["ProposedSignature"]["anyOf"]
    assert accepted["properties"]["kind"] == {
        "const": "annotation_expression",
        "type": "string",
    }
    assert set(accepted["properties"]) == {"kind", "expression"}
    assert set(accepted["required"]) == {"kind", "expression"}
    assert hold["properties"]["kind"] == {"const": "hold", "type": "string"}
    assert set(hold["properties"]) == {"kind", "reason", "missing_evidence"}


@pytest.mark.parametrize("failure_kind", ["missing", "duplicate", "provenance"])
def test_invalid_provider_output_records_failure_without_decisions(tmp_path, failure_kind):
    manifest, _, _, _, manifest_path, index_path, batch_path, packet = _packet(tmp_path)
    if failure_kind == "missing":
        response = ReviewBatchResponse(decisions=_response(manifest, packet).decisions[:-1])
    elif failure_kind == "duplicate":
        first = _response(manifest, packet).decisions[0]
        response = ReviewBatchResponse(decisions=(first, first))
    else:
        response = _response(manifest, packet, model="wrong-model")

    def runner(command, **kwargs):
        envelope = {"structured_output": response.model_dump(mode="json")}
        return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")

    result = dispatch_batch(
        **_dispatch_args(tmp_path, manifest_path, index_path, batch_path, "claude"),
        runner=runner,
    )
    assert result["status"] == "failed"
    assert result["decisions"] == 0
    directory = Path(result["directory"])
    failure = json.loads((directory / "failure.json").read_text())
    assert failure["batch_sha256"]
    assert failure["assembled_prompt_sha256"]
    assert not (directory / "decisions.jsonl").exists()
    assert not (directory / "completion.json").exists()


def test_provider_process_failure_is_checkpointed_without_fabrication(tmp_path):
    manifest, _, _, _, manifest_path, index_path, batch_path, _ = _packet(tmp_path)

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 17, "partial provider output", "quota exceeded")

    result = dispatch_batch(
        **_dispatch_args(tmp_path, manifest_path, index_path, batch_path, "claude"),
        runner=runner,
    )
    assert result["status"] == "failed"
    directory = Path(result["directory"])
    failure = json.loads((directory / "failure.json").read_text())
    assert failure["error_type"] == "RuntimeError"
    assert "exited 17" in failure["error"]
    assert (directory / "provider-output.txt").read_text() == "partial provider output"
    assert not (directory / "decisions.jsonl").exists()


def test_provider_schema_is_recursively_strict_and_preserves_defaults(tmp_path):
    review_path = tmp_path / "review.json"
    adjudication_path = tmp_path / "adjudication.json"
    write_response_schemas(review_path, adjudication_path)
    schemas = [json.loads(review_path.read_text()), json.loads(adjudication_path.read_text())]

    def assert_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node.get("properties", {}))
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    def schema_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from schema_keys(value)
        elif isinstance(node, list):
            for value in node:
                yield from schema_keys(value)

    for schema in schemas:
        assert_strict(schema)
        assert "oneOf" not in set(schema_keys(schema))
    schema = schemas[0]
    review_definition = schema["$defs"]["ReviewDecision"]
    assert "evidence_ids" in review_definition["required"]
    assert "default" not in review_definition["properties"]["evidence_ids"]
    assert "schema_version" in review_definition["required"]


def test_validation_evidence_and_role_specific_prompts_are_enforced(tmp_path):
    manifest, occurrences, clusters, evidence, _ = campaign_fixture(tmp_path)
    # Validated model output without evidence fails before it can be dispatched or ingested.
    item = next(read_jsonl(clusters, Cluster))
    packet = {"items": [item.model_dump(mode="json")]}
    with pytest.raises(ValidationError, match="evidence_ids"):
        _response(manifest, packet, evidence_ids=())
    adversary = next(row for row in manifest.models if row.reviewer_id == "adversary")
    adversarial_prompt = next(
        row for row in manifest.prompts if row.prompt_id == "adversarial"
    )
    with pytest.raises(ValidationError, match="evidence_ids"):
        AdversarialVerdict(
            campaign_id=manifest.campaign_id,
            item_id="cluster_" + "a" * 24,
            reviewer_id=adversary.reviewer_id,
            provider=adversary.provider,
            model=adversary.model,
            model_family=adversary.model_family,
            reasoning_effort=adversary.reasoning_effort,
            prompt_id=adversarial_prompt.prompt_id,
            prompt_sha256=adversarial_prompt.sha256,
            candidate_signature_sha256="a" * 64,
            verdict="no_blocker",
            rationale="No blocker found.",
            validation_passed=True,
        )

    # Consensus provenance refuses a reviewer decision bearing the adversarial prompt.
    occurrence = next(read_jsonl(occurrences, Occurrence))
    item_id = occurrence.cluster_id
    model = next(row for row in manifest.models if row.reviewer_id == "claude")
    prompt = next(row for row in manifest.prompts if row.prompt_id == "adversarial")
    wrong_prompt = ReviewDecision(
        campaign_id=manifest.campaign_id,
        item_id=item_id,
        reviewer_id=model.reviewer_id,
        provider=model.provider,
        model=model.model,
        model_family=model.model_family,
        reasoning_effort=model.reasoning_effort,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.sha256,
        disposition="hold",
        proposed_signature={"kind": "hold", "reason": "Held pending evidence."},
        rationale="Held pending evidence.",
        confidence=0.2,
        evidence_ids=(occurrence.evidence_id,),
        validation_passed=False,
    )
    reviews = tmp_path / "wrong-prompt.jsonl"
    reviews.write_text(wrong_prompt.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewer must use the reviewer prompt"):
        build_consensus(
            manifest=manifest,
            occurrence_path=occurrences,
            cluster_path=clusters,
            evidence_path=evidence,
            review_paths=[reviews],
            consensus_path=tmp_path / "consensus.jsonl",
            exception_path=tmp_path / "exceptions.jsonl",
            ledger_path=tmp_path / "ledger.jsonl",
        )
