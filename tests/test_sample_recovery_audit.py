from __future__ import annotations

import csv
import json

from flopo2.verify.sample_recovery_audit import write_sample


def test_sample_is_reproducible_and_spans_sources_and_po_strata(tmp_path):
    source = tmp_path / "input.jsonl"
    records = []
    for flora in ("a", "b"):
        for index, po_id in enumerate(("PO_1", "PO_1", "PO_2", "PO_3")):
            records.append(
                {
                    "source": flora,
                    "source_id": f"{flora}{index}",
                    "source_segment_index": index,
                    "organ": "leaf",
                    "text": "Leaves red.",
                    "assertions": [
                        {
                            "extractor": "target",
                            "po_id": po_id,
                            "pato_id": "PATO_1",
                            "source_start": 7,
                            "source_end": 10,
                            "source_text": "red",
                        }
                    ],
                }
            )
    source.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    first = tmp_path / "first.tsv"
    second = tmp_path / "second.tsv"
    assert write_sample([source], first, "target", size=6, seed=9) == 6
    assert write_sample([source], second, "target", size=6, seed=9) == 6
    assert first.read_bytes() == second.read_bytes()
    with first.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert {row["source"] for row in rows} == {"a", "b"}
    assert {row["po_id"] for row in rows} == {"PO_1", "PO_2", "PO_3"}
    assert all(not row["review_decision"] for row in rows)


def test_sample_preserves_zero_source_offset(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora",
                "source_id": "1",
                "source_segment_index": 0,
                "organ": "plant",
                "text": "Yellow-green plant.",
                "assertions": [
                    {
                        "extractor": "target",
                        "po_id": "PO_0000003",
                        "pato_id": "PATO_0001941",
                        "source_start": 0,
                        "source_end": 12,
                        "source_text": "Yellow-green",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "audit.tsv"
    assert write_sample([source], output, "target", size=1, seed=9) == 1
    with output.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle, delimiter="\t"))
    assert row["source_start"] == "0"
    assert row["context"] == "Yellow-green plant."
