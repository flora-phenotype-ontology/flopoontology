"""Third-reviewer (two_of_three) paths for the leaf-base/leaf-apex/shape campaigns.

Covers the ``--tiebreak`` option of the qualitative-relation materializer, the reviewer
provenance both consensus materializers attach to tie-break admissions, and the
correction-aware delta utilities in :mod:`flopo2.verify.tiebreak_delta`.
"""

from __future__ import annotations

import json

import pytest
from test_expression_consensus_materialization import _campaign as _expression_campaign
from test_qualitative_consensus_materialization import _campaign as _qualitative_campaign

from flopo2.review.io import read_jsonl
from flopo2.review.models import Cluster, Occurrence
from flopo2.verify.tiebreak_delta import (
    apply_correction_record,
    apply_deltas,
    normalize_tiebreak_file,
    normalize_tiebreak_row,
    remove_assertions,
)

THIRD = {
    "reviewer_id": "reviewer_third",
    "provider": "anthropic",
    "model": "claude-opus-5",
    "model_family": "claude-third",
}
RULE_REASON = "two_of_three_exact_agreement"


def _flat_tiebreak_row(fixture, *, kind: str, accept: bool = True) -> dict:
    """A tie-break row in the flat form the shape-tiebreak files use."""

    occurrence = next(read_jsonl(fixture["occurrences"], Occurrence))
    cluster = next(read_jsonl(fixture["clusters"], Cluster))
    if kind == "structured_qualitative_relation":
        signature = {
            "kind": kind,
            "qualitative_relation": cluster.qualitative_relation_candidate.signature.model_dump(
                mode="json"
            ),
        }
    else:
        signature = {
            "kind": kind,
            "expression": cluster.phenotype_expression_candidate.signature.model_dump(
                mode="json"
            ),
        }
    return {
        "item_id": occurrence.cluster_id,
        "occurrence_id": occurrence.occurrence_id,
        "reviewer_id": "reviewer_claude_tiebreak",
        "disposition": kind if accept else "hold",
        "proposed_signature": (
            signature if accept else {"kind": "hold", "reason": "Bearer is a leaflet."}
        ),
        "evidence_ids": [occurrence.evidence_id],
        "validation_passed": accept,
        "rationale": "Exact candidate re-read against the full segment.",
        "agrees_with": "claude",
        "revised_after_spot_check": False,
    }


def _tiebreak_file(tmp_path, fixture, *, kind: str, accept: bool = True):
    manifest = json.loads(fixture["manifest"].read_text(encoding="utf-8"))
    flat = tmp_path / "flat-tiebreak.jsonl"
    flat.write_text(
        json.dumps(_flat_tiebreak_row(fixture, kind=kind, accept=accept)) + "\n",
        encoding="utf-8",
    )
    normalized = tmp_path / "tiebreak.jsonl"
    assert normalize_tiebreak_file(flat, normalized, manifest["campaign_id"]) == 1
    row = json.loads(normalized.read_text(encoding="utf-8"))
    row["reviewer"] = THIRD
    normalized.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return normalized


def _materialize_qualitative(tmp_path, fixture, **kwargs):
    from flopo2.verify.materialize_qualitative_consensus import (
        materialize_qualitative_consensus,
    )

    proposals = tmp_path / "q-proposals.jsonl"
    held = tmp_path / "q-held.jsonl"
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
        report_path=tmp_path / "q-report.json",
        combinations_path=fixture["combinations"],
        registry_path=fixture["registry"],
        po_lexicon_path=fixture["po"],
        pato_lexicon_path=fixture["pato"],
        **kwargs,
    )
    return report, proposals, held


def _assert_machine_provenance(row: dict) -> None:
    assertion = row["assertion"]
    assert row["machine_review"]["reviewer_ids"] == ["claude", "gpt", "reviewer_third"]
    assert row["machine_review"]["admission_rule"] == RULE_REASON
    assert assertion["composition"]["reasons"] == [RULE_REASON]
    provenance = assertion["mapping_provenance"]
    assert f"llm_review_rule:{RULE_REASON}" in provenance
    assert {item for item in provenance if item.startswith("llm_reviewer:")} == {
        "llm_reviewer:claude",
        "llm_reviewer:gpt",
        "llm_reviewer:reviewer_third",
    }
    serialized = json.dumps(row).casefold()
    assert "orcid" not in serialized
    assert "curator" not in serialized
    assert "human" not in serialized


def test_qualitative_default_behaviour_is_unchanged(tmp_path):
    fixture = _qualitative_campaign(tmp_path)
    report, proposals, _ = _materialize_qualitative(tmp_path, fixture)
    assert report["proposals"] == 1 and "tiebreak" not in report
    row = json.loads(proposals.read_text(encoding="utf-8"))
    assert "admission_rule" not in row["machine_review"]
    assert row["assertion"]["composition"]["reasons"] == [
        "two_family_llm_exact_signature_consensus"
    ]
    assert not any(
        item.startswith(("llm_reviewer:", "llm_review_rule:"))
        for item in row["assertion"]["mapping_provenance"]
    )


def test_qualitative_tiebreak_admits_held_item_with_three_reviewer_provenance(tmp_path):
    from flopo2.verify.data_model import validate_jsonl
    from flopo2.verify.proposal_delta import build_delta

    fixture = _qualitative_campaign(tmp_path, second_holds=True)
    (tmp_path / "base").mkdir()
    held_report, _, _ = _materialize_qualitative(tmp_path / "base", fixture)
    assert held_report["proposals"] == 0 and held_report["held"] == 1

    tiebreak = _tiebreak_file(tmp_path, fixture, kind="structured_qualitative_relation")
    report, proposals, held = _materialize_qualitative(
        tmp_path,
        fixture,
        tiebreak_path=tiebreak,
        tiebreak_rule="two_of_three",
        review_paths=(tmp_path / "reviews.jsonl",),
    )
    assert report["proposals"] == 1 and report["held"] == 0 and report["conserved"]
    assert report["tiebreak"]["admitted"] == 1
    assert report["tiebreak"]["admission_reason"] == RULE_REASON
    assert held.read_text(encoding="utf-8") == ""
    row = json.loads(proposals.read_text(encoding="utf-8"))
    _assert_machine_provenance(row)
    assert row["assertion"]["gate"]["flopo_status"] == "structured_annotation_only"

    delta = tmp_path / "delta.jsonl"
    assert build_delta(proposals, fixture["stage"], delta)["assertions"] == 1
    output = tmp_path / "patched.jsonl"
    applied = apply_deltas(fixture["stage"], [delta], output)
    assert applied["assertions_added"] == 1 and applied["segments_patched"] == 1
    validation = validate_jsonl(
        output,
        po_lexicon=fixture["po"],
        pato_lexicon=fixture["pato"],
        flopo_registry=fixture["registry"],
        strict_source_statements=True,
    )
    assert validation["ok"], validation


def test_qualitative_tiebreak_hold_keeps_item_held(tmp_path):
    fixture = _qualitative_campaign(tmp_path, second_holds=True)
    tiebreak = _tiebreak_file(
        tmp_path, fixture, kind="structured_qualitative_relation", accept=False
    )
    report, proposals, held = _materialize_qualitative(
        tmp_path,
        fixture,
        tiebreak_path=tiebreak,
        tiebreak_rule="two_of_three",
        review_paths=(tmp_path / "reviews.jsonl",),
    )
    assert report["proposals"] == 0 and report["held"] == 1
    assert report["tiebreak"]["held_first_reasons"] == {"tiebreak_reviewer_hold": 1}
    assert proposals.read_text(encoding="utf-8") == ""


def test_qualitative_tiebreak_requires_rule_and_file_together(tmp_path):
    fixture = _qualitative_campaign(tmp_path, second_holds=True)
    with pytest.raises(ValueError, match="supplied together"):
        _materialize_qualitative(tmp_path, fixture, tiebreak_rule="two_of_three")


def test_expression_tiebreak_names_all_three_reviewers(tmp_path):
    from flopo2.verify.materialize_expression_consensus import (
        materialize_expression_consensus,
    )

    fixture = _expression_campaign(tmp_path, second_holds=True)
    tiebreak = _tiebreak_file(tmp_path, fixture, kind="annotation_expression")
    proposals = tmp_path / "e-proposals.jsonl"
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
        held_path=tmp_path / "e-held.jsonl",
        report_path=tmp_path / "e-report.json",
        combinations_path=fixture["combinations"],
        registry_path=fixture["registry"],
        po_lexicon_path=fixture["po"],
        pato_lexicon_path=fixture["pato"],
        tiebreak_path=tiebreak,
        tiebreak_rule="two_of_three",
        review_paths=(tmp_path / "reviews.jsonl",),
    )
    assert report["proposals"] == 1
    _assert_machine_provenance(json.loads(proposals.read_text(encoding="utf-8")))


def test_normalize_tiebreak_row_forms():
    flat = {
        "item_id": "cluster_x",
        "reviewer_id": "reviewer_claude_tiebreak",
        "disposition": "hold",
        "proposed_signature": {"kind": "hold", "reason": "r"},
        "evidence_ids": ["evidence_x"],
        "validation_passed": False,
        "rationale": "r",
    }
    row = normalize_tiebreak_row(flat, "campaign_a")
    assert row["campaign_id"] == "campaign_a"
    assert row["decision"]["disposition"] == "hold"
    assert row["source_reviewer_label"] == "reviewer_claude_tiebreak"
    assert normalize_tiebreak_row(row, "campaign_a")["decision"] == row["decision"]
    with pytest.raises(ValueError, match="another campaign"):
        normalize_tiebreak_row(row, "campaign_b")
    with pytest.raises(ValueError, match="lacks"):
        normalize_tiebreak_row({"item_id": "cluster_x"}, "campaign_a")


def _record() -> dict:
    text = "Leaflets 3-jugate; lamina attenuate towards the base."
    wrong = {
        "po_id": "PO_0020040",
        "pato_id": "PATO_0001982",
        "source_text": "attenuate towards the base",
        "source_start": 26,
        "source_end": 52,
        "source_statement_id": "statement-a",
        "gate": {"assertion_index": 0},
    }
    return {
        "source": "fixture",
        "source_id": "f.xml",
        "source_segment_index": 0,
        "taxon": "Planta",
        "organ": "leaves",
        "char_start": 0,
        "char_end": len(text),
        "text": text,
        "source_statements": [{"statement_id": "statement-a", "start": 26, "end": 52}],
        "assertions": [dict(wrong, pato_id="PATO_0000001"), wrong],
        "unresolved_spans": [],
    }


def _removal(**overrides) -> dict:
    return {
        "source_statement_id": "statement-a",
        "po_id": "PO_0020040",
        "pato_id": "PATO_0001982",
        "source_start": 26,
        "source_end": 52,
        **overrides,
    }


def test_remove_assertions_matches_exactly_one():
    record = _record()
    out = remove_assertions(record, [_removal()])
    assert [row["pato_id"] for row in out["assertions"]] == ["PATO_0000001"]
    assert len(record["assertions"]) == 2
    with pytest.raises(ValueError, match="matched 0"):
        remove_assertions(record, [_removal(source_start=25)])
    with pytest.raises(ValueError, match="lacks"):
        remove_assertions(record, [{"po_id": "PO_0020040"}])


def test_correction_record_replaces_bearer_and_reindexes_gate():
    corrected = dict(_record()["assertions"][1], po_id="PO_0020049", gate={"assertion_index": 9})
    delta = {"remove_assertions": [_removal()], "add_assertions": [corrected]}
    out = apply_correction_record(_record(), delta)
    assert [row["po_id"] for row in out["assertions"]] == ["PO_0020040", "PO_0020049"]
    assert out["assertions"][0]["pato_id"] == "PATO_0000001"
    assert [row["gate"]["assertion_index"] for row in out["assertions"]] == [0, 1]


def test_apply_deltas_runs_files_in_order_and_fails_closed(tmp_path):
    stage = tmp_path / "stage.jsonl"
    stage.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
    key = {name: _record()[name] for name in (
        "source", "source_id", "source_segment_index", "taxon", "organ", "char_start", "char_end"
    )}
    first = tmp_path / "first.jsonl"
    first.write_text(json.dumps({"key": key, "remove_assertions": [_removal()]}) + "\n")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    out = tmp_path / "out.jsonl"
    counts = apply_deltas(stage, [first, empty], out)
    assert counts["assertions_removed"] == 1 and counts["segments_patched"] == 1
    assert len(json.loads(out.read_text())["assertions"]) == 1
    # The same removal twice (second file) no longer matches: fail closed.
    with pytest.raises(ValueError, match="matched 0"):
        apply_deltas(stage, [first, first], tmp_path / "out2.jsonl")
    stray = tmp_path / "stray.jsonl"
    stray.write_text(json.dumps({"key": dict(key, source_id="other.xml")}) + "\n")
    with pytest.raises(ValueError, match="matched no segment"):
        apply_deltas(stage, [stray], tmp_path / "out3.jsonl")
    with pytest.raises(ValueError, match="differ"):
        apply_deltas(stage, [first], stage)


def test_leaflet_correction_removes_assertion_and_restores_unresolved_span():
    from flopo2.verify.tiebreak_delta import add_unresolved

    span = {
        "start": 26,
        "end": 35,
        "surface_form": "attenuate",
        "reason": "missing_or_unsupported_bearer",
        "candidate_pato_id": "PATO_0001982",
        "extractor": "leaflet_bearer_correction_v1",
    }
    delta = {"remove_assertions": [_removal()], "add_unresolved": [span]}
    out = apply_correction_record(_record(), delta)
    assert [row["pato_id"] for row in out["assertions"]] == ["PATO_0000001"]
    assert out["unresolved_spans"] == [span]
    with pytest.raises(ValueError, match="already unresolved"):
        add_unresolved(out, [span])
    with pytest.raises(ValueError, match="does not match"):
        add_unresolved(_record(), [dict(span, surface_form="acuminate")])
