from __future__ import annotations

import json

import pytest


def _record(source: str, taxon: str, status: str = "accepted") -> dict:
    return {
        "source": source,
        "source_id": "volume",
        "taxon": taxon,
        "organ": "leaf",
        "char_start": 0,
        "char_end": 12,
        "text": "Leaves green",
        "assertions": [{"gate": {"status": status}}],
    }


def test_merge_jsonl_preserves_all_distinct_segments(tmp_path):
    from flopo2.verify.merge_jsonl import merge_jsonl

    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text(json.dumps(_record("flora-a", "Taxon a")) + "\n")
    second.write_text(json.dumps(_record("flora-b", "Taxon b", "review")) + "\n")
    output = tmp_path / "merged.jsonl"

    report = merge_jsonl([first, second], output)

    assert report["segments"] == 2
    assert report["assertions"] == 2
    assert report["gate_statuses"] == {"accepted": 1, "review": 1}
    assert len(output.read_text().splitlines()) == 2


def test_merge_jsonl_rejects_duplicate_segment_identity(tmp_path):
    from flopo2.verify.merge_jsonl import merge_jsonl

    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    row = json.dumps(_record("flora-a", "Taxon a")) + "\n"
    first.write_text(row)
    second.write_text(row)

    with pytest.raises(ValueError, match="duplicate segment identity"):
        merge_jsonl([first, second], tmp_path / "merged.jsonl")


def test_merge_jsonl_distinguishes_repeated_source_blocks_by_index(tmp_path):
    from flopo2.verify.merge_jsonl import merge_jsonl

    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    row_a = _record("flora-a", "Taxon a")
    row_b = _record("flora-a", "Taxon a")
    row_a["source_segment_index"] = 17
    row_b["source_segment_index"] = 18
    first.write_text(json.dumps(row_a) + "\n")
    second.write_text(json.dumps(row_b) + "\n")

    report = merge_jsonl([first, second], tmp_path / "merged.jsonl")
    assert report["segments"] == 2
