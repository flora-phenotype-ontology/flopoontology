from __future__ import annotations

import csv
import json
from pathlib import Path


def _decision(text: str, *, source_id: str = "flora.xml") -> dict[str, str]:
    from flopo2.verify.recover_qualitative_relations import _expression_digest

    row = {
        "expression_uid": f"fixture|{source_id}|0|7|24",
        "source": "fixture",
        "source_id": source_id,
        "source_segment_index": "0",
        "expression_start": "7",
        "expression_end": "24",
        "expression_text": text[7:24],
        "operator_interpretation": "continuum",
        "range_rule": "R6_grounded_same_family_endpoints",
        "bearer_po_id": "",
        "bearer_method": "",
        "bearer_surface": "",
        "attribute_pato_id": "PATO_0000052",
        "family": "shape",
        "operand_surfaces": "elliptic|ovate",
        "operand_normalized": "elliptic|ovate",
        "operand_term_ids": "PATO_0000947|PATO_0001891",
        "modifiers": "",
        "negation_guard": "",
        "decision": "recover_qualitative_range",
    }
    row["expression_digest"] = _expression_digest(row, row["expression_text"])
    return row


def test_recovers_live_local_bearer_and_exact_current_clear_targets(tmp_path: Path):
    from flopo2.review.inventory import build_inventory, model_spec
    from flopo2.review.io import read_jsonl
    from flopo2.review.models import Occurrence
    from flopo2.verify.recover_contextual_qualitative_relations import (
        prepare_contextual_review_input,
    )

    text = "Leaves elliptic to ovate."
    stage = tmp_path / "stage.jsonl"
    stage.write_text(
        json.dumps(
            {
                "source": "fixture",
                "source_id": "flora.xml",
                "source_segment_index": 0,
                "taxon": "Planta exemplaris",
                "organ": "description",
                "language": "en",
                "char_start": 0,
                "char_end": len(text),
                "text": text,
                "assertions": [],
                "unresolved_spans": [
                    {
                        "start": 7,
                        "end": 15,
                        "surface_form": "elliptic",
                        "reason": "unsupported_alternative_or_transition",
                        "candidate_pato_id": "PATO_0000947",
                        "extractor": "fixture",
                    },
                    {
                        "start": 19,
                        "end": 24,
                        "surface_form": "ovate",
                        "reason": "unsupported_alternative_or_transition",
                        "candidate_pato_id": "PATO_0001891",
                        "extractor": "fixture",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    decisions = tmp_path / "decisions.tsv"
    row = _decision(text)
    with decisions.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), delimiter="\t")
        writer.writeheader()
        writer.writerow(row)
    prior = tmp_path / "prior.jsonl"
    prior.write_text("", encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009025\tleaf\tleaves\n", encoding="utf-8")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_0000052\tshape\tattribute_slim\n"
        "PATO_0000947\telliptic\tshape_slim\n"
        "PATO_0001891\tovate\tshape_slim\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n", encoding="utf-8"
    )
    combinations = tmp_path / "combinations.tsv"
    combinations.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_0009025\tPATO_0000052\tallowed\tfixture\tleaf shape\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    report = prepare_contextual_review_input(
        stage_path=stage,
        decisions_path=decisions,
        prior_candidate_ledger_path=prior,
        review_input_path=output / "review.jsonl",
        candidate_ledger_path=output / "ledger.jsonl",
        exclusions_path=output / "excluded.jsonl",
        report_path=output / "report.json",
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    assert report["conserved"] is True
    assert report["candidates"] == 1
    assert report["exclusions"] == 0
    ledger = json.loads((output / "ledger.jsonl").read_text(encoding="utf-8"))
    candidate = ledger["candidate"]
    assert candidate["signature"]["bearer_id"] == "PO_0009025"
    assert candidate["bearer_text"] == "Leaves"
    assert candidate["bearer_start"] == 0
    assert candidate["bearer_end"] == 6
    assert candidate["clear_unresolved_spans"] == [[7, 15], [19, 24]]
    assert "live_bearer_recovery" in ledger["risk_flags"]

    prompt = tmp_path / "prompt.md"
    prompt.write_text("Review exact qualitative ranges.\n", encoding="utf-8")
    occurrences = output / "occurrences.jsonl"
    clusters = output / "clusters.jsonl"
    evidence = output / "evidence.jsonl"
    manifest_path = output / "manifest.json"
    build_inventory(
        stage13_path=output / "review.jsonl",
        occurrence_path=occurrences,
        cluster_path=clusters,
        evidence_path=evidence,
        manifest_path=manifest_path,
        ontology_paths=[po, pato, registry, combinations],
        prompt_paths={"reviewer": prompt},
        models=[
            model_spec(
                reviewer_id="claude",
                provider="anthropic",
                model="claude-opus-4-8",
                model_family="claude-opus",
                role="reviewer",
            )
        ],
    )
    occurrence = next(read_jsonl(occurrences, Occurrence))
    assert occurrence.qualitative_relation_candidate is not None
    assert occurrence.qualitative_relation_candidate.signature.bearer_id == "PO_0009025"


def test_prior_campaign_expression_is_not_requeued(tmp_path: Path):
    from flopo2.verify.recover_contextual_qualitative_relations import _eligible_decisions

    text = "Leaves elliptic to ovate."
    row = _decision(text)
    decisions = tmp_path / "decisions.tsv"
    with decisions.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), delimiter="\t")
        writer.writeheader()
        writer.writerow(row)
    prior = tmp_path / "prior.jsonl"
    prior.write_text(json.dumps({"expression_uid": row["expression_uid"]}) + "\n")
    grouped, counts = _eligible_decisions(decisions, prior)
    assert grouped == {}
    assert counts["prior_candidate_skipped"] == 1
    assert counts["structurally_eligible"] == 0
