"""Tests for the bearer-attachment review campaign (inventory, dispatch, consensus, delta)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flopo2.review import bearer_attachment_dispatch as dispatch
from flopo2.review.bearer_attachment_consensus import ADMISSION_RULE, build_consensus, decide
from flopo2.review.bearer_attachment_inventory import (
    HOLD,
    CandidateBuilder,
    _labels,
    _pato_labels,
    disjunction_items,
    missing_bearer_items,
)
from flopo2.verify import recover_claude_explicit_disjunction as disj
from flopo2.verify.materialize_bearer_attachment_consensus import (
    EXTRACTOR,
    choose_mention,
    materialize,
)
from flopo2.verify.recover_claude_missing_bearer import Recoverer


def _record(text: str, surfaces: list[tuple[str, str, str]], *, organ: str = "description",
            family: str = "Rubiaceae", language: str = "en", source: str = "kew-african") -> dict:
    spans = []
    for surface, reason, pato in surfaces:
        start = text.index(surface)
        spans.append({"start": start, "end": start + len(surface), "surface_form": surface,
                      "reason": reason, "candidate_pato_id": pato,
                      "extractor": "deterministic_baseline"})
    return {"source": source, "source_id": "1", "source_segment_index": 0, "taxon": "Genus species",
            "taxon_family": family, "organ": organ, "language": language, "char_start": 0,
            "char_end": len(text), "text": text, "assertions": [], "source_statements": [],
            "unresolved_spans": spans}


@pytest.fixture(scope="module")
def builder() -> CandidateBuilder:
    return CandidateBuilder(Recoverer.from_config(), _labels())


@pytest.fixture(scope="module")
def pato_labels() -> dict[str, str]:
    return _pato_labels()


def test_bearerless_union_excludes_nested_head() -> None:
    text = "Calyx 5 mm long; lobes of the calyx white or pink. Stamens 5."
    record = _record(text, [("white", disj.TARGET_REASON, "PATO_0000323")])
    span = record["unresolved_spans"][0]
    candidate, reason = disj.find_candidate(record, span["start"], span["end"])
    assert candidate is None and reason in {"no_clause_head_bearer", "unsafe_gap_between_head_and_union"}
    union, why = disj.find_candidate(record, span["start"], span["end"], bearerless=True)
    assert why == ""
    assert union.bearer_po == ""
    assert text[union.start:union.end] == "white or pink"
    assert [op.pato_id for op in union.operands] == ["PATO_0000323", "PATO_0000954"]


def test_bearerless_union_keeps_non_bearer_guards() -> None:
    text = "Lobes whitish, white or pink."
    record = _record(text, [("white ", disj.TARGET_REASON, "PATO_0000323")])
    span = record["unresolved_spans"][0]
    span["end"] -= 1
    union, why = disj.find_candidate(record, span["start"], span["end"], bearerless=True)
    assert union is None and why


def test_disjunction_item_offers_subpart_composite(builder, pato_labels) -> None:
    text = "Calyx 5 mm long; lobes glabrous or pubescent. Stamens 5."
    record = _record(text, [("glabrous", disj.TARGET_REASON, "PATO_0000453")])
    rows = [row for status, row in disjunction_items(record, builder, pato_labels) if status == "item"]
    assert len(rows) == 1
    item = rows[0]
    ids = [c["bearer_id"] for c in item["candidates"]]
    assert ids[0] == "FLOPO_0986005"  # calyx lobe, composite of ``lobes`` and the previous head
    assert "PO_0009060" in ids  # the calyx itself is offered (and must be rejected by review)
    assert item["quality"]["value_terms"] == ["PATO_0000453", "PATO_0001320"]
    assert not item["leaf_surface"]


def test_leaf_surface_items_are_flagged(builder, pato_labels) -> None:
    text = "Leaves 5 cm long; lower surface glabrous or pubescent. Flowers 5."
    record = _record(text, [("glabrous", disj.TARGET_REASON, "PATO_0000453")])
    rows = [row for status, row in disjunction_items(record, builder, pato_labels) if status == "item"]
    assert rows and rows[0]["leaf_surface"]


def test_missing_bearer_item_requires_named_subpart(builder, pato_labels) -> None:
    text = "Corolla white, 8 mm long; lobes ovate, 2 mm long."
    record = _record(text, [("ovate", "missing_or_unsupported_bearer", "PATO_0001891")])
    rows = list(missing_bearer_items(record, builder, pato_labels))
    assert rows and rows[0][1]["subparts_named"] == ["lobe"]
    assert rows[0][1]["candidates"][0]["bearer_id"] == "FLOPO_0986006"


def _item(candidates: list[str]) -> dict:
    return {"item_id": "bearer_x", "candidates": [{"bearer_id": c} for c in candidates]}


def test_validate_decisions_is_closed() -> None:
    items = [_item(["PO_0009032"])]
    ok = dispatch.validate_decisions(items, [{"item_id": "bearer_x", "bearer_id": "hold", "reason": "r"}])
    assert ok[0]["bearer_id"] == HOLD
    with pytest.raises(ValueError):
        dispatch.validate_decisions(items, [{"item_id": "bearer_x", "bearer_id": "PO_1", "reason": ""}])
    with pytest.raises(ValueError):
        dispatch.validate_decisions(items, [])


def test_response_schema_binds_each_position() -> None:
    schema = dispatch.response_schema([_item(["PO_0009032", "PO_0009060"])], per_item_enum=True)
    decision = schema["properties"]["decisions"]["prefixItems"][0]
    assert decision["properties"]["bearer_id"]["enum"] == ["PO_0009032", "PO_0009060", HOLD]
    assert schema["properties"]["decisions"]["minItems"] == 1


def test_decide_two_of_three() -> None:
    admitted = decide({"a": "PO_1", "b": "PO_1", "c": HOLD})
    assert admitted["status"] == "admitted_for_gates" and admitted["bearer_id"] == "PO_1"
    assert admitted["reasons"] == [ADMISSION_RULE]
    dissent = decide({"a": "PO_1", "b": "PO_1", "c": "PO_2"})
    assert dissent["status"] == "admitted_for_gates" and "dissent_other_bearer" in dissent["reasons"]
    assert decide({"a": "PO_1", "b": "PO_2", "c": HOLD})["status"] == "held"
    assert decide({"a": HOLD, "b": HOLD, "c": HOLD})["status"] == "held"
    assert decide({"a": "PO_1", "b": "invalid", "c": HOLD})["status"] == "held"


def test_review_batch_checkpoints_and_resumes(tmp_path: Path) -> None:
    batch = tmp_path / "batches" / "batch-00001.json"
    batch.parent.mkdir()
    batch.write_text(json.dumps({"items": [_item(["PO_0009032"])]}))
    prompt = tmp_path / "prompt.md"
    prompt.write_text("review")
    calls = []

    def fake(spec, prompt_text, items):
        calls.append(1)
        return ([{"item_id": "bearer_x", "bearer_id": "PO_0009032", "reason": "petals"}],
                {"served_model": "fake-model"})

    for _ in range(2):
        dispatch.review_batch(
            "claude-opus", batch, tmp_path / "checkpoints" / "claude-opus", prompt, backend=fake
        )
    assert len(calls) == 1
    report = dispatch.collect("claude-opus", batch.parent, tmp_path, prompt_path=prompt)
    assert report["counts"]["bearer"] == 1
    row = json.loads((tmp_path / "reviews-claude-opus.jsonl").read_text())
    assert row["model"] == "fake-model" and row["bearer_id"] == "PO_0009032"


def test_materialize_admitted_union_end_to_end(tmp_path: Path, builder, pato_labels) -> None:
    text = "Calyx 5 mm long; white or pink. Stamens 5."
    record = _record(text, [("white", disj.TARGET_REASON, "PATO_0000323")])
    stage = tmp_path / "stage.jsonl"
    stage.write_text(json.dumps(record) + "\n")
    items = [row for status, row in disjunction_items(record, builder, pato_labels) if status == "item"]
    inventory = tmp_path / "inventory.jsonl"
    inventory.write_text("".join(json.dumps(item) + "\n" for item in items))
    item_id = items[0]["item_id"]
    reviews = []
    for reviewer, bearer in (("a", "PO_0009060"), ("b", "PO_0009060"), ("c", HOLD)):
        path = tmp_path / f"reviews-{reviewer}.jsonl"
        path.write_text(json.dumps({"reviewer_id": reviewer, "item_id": item_id, "bearer_id": bearer}) + "\n")
        reviews.append(path)
    consensus = tmp_path / "consensus.jsonl"
    report = build_consensus(inventory, reviews, consensus)
    assert report["status_items"] == {"admitted_for_gates": 1}
    assert choose_mention(items[0], "PO_0009060")["surface"] == "Calyx"
    result = materialize(stage, inventory, consensus, tmp_path / "out")
    assert result["counts"]["admitted_items"] == 1
    delta = json.loads((tmp_path / "out" / "delta.jsonl").read_text())
    assertion = delta["add_assertions"][0]
    assert assertion["po_id"] == "PO_0009060" and assertion["value_operator"] == "one_of"
    assert assertion["extractor"] == EXTRACTOR
    assert text[assertion["source_start"]:assertion["source_end"]] == assertion["source_text"]
    assert delta["remove_unresolved"][0]["surface_form"] == "white"
