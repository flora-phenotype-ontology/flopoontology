from __future__ import annotations

import json


def test_projection_keeps_all_unions_and_only_their_source_statements(tmp_path):
    from flopo2.annotation.provenance import ensure_source_statements
    from flopo2.verify.project_disjunctions import project_disjunctions

    text = "Flowers red or green; leaves white."
    record = ensure_source_statements(
        {
            "source": "flora-test",
            "source_id": "one.xml",
            "text": text,
            "assertions": [
                {
                    "po_id": "PO_0009046",
                    "pato_id": "PATO_0000014",
                    "source_text": "red or green",
                    "source_start": 8,
                    "source_end": 20,
                    "value_operator": "one_of",
                    "value_terms": ["PATO_0000322", "PATO_0000320"],
                    "gate": {"status": "accepted"},
                },
                {
                    "po_id": "PO_0009025",
                    "pato_id": "PATO_0000323",
                    "source_text": "white",
                    "source_start": 29,
                    "source_end": 34,
                    "gate": {"status": "accepted"},
                },
            ],
            "unresolved_spans": [
                {
                    "start": 0,
                    "end": 7,
                    "surface_form": "Flowers",
                    "reason": "test",
                    "extractor": "test",
                }
            ],
        }
    )
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record) + "\n")
    output = tmp_path / "unions.jsonl"

    stats = project_disjunctions(source, output)
    projected = json.loads(output.read_text())

    assert stats["assertions"] == 1
    assert stats["gate_statuses"] == {"accepted": 1}
    assert len(projected["assertions"]) == 1
    assert projected["assertions"][0]["value_operator"] == "one_of"
    assert len(projected["source_statements"]) == 1
    assert (
        projected["source_statements"][0]["statement_id"]
        == projected["assertions"][0]["source_statement_id"]
    )
    assert projected["unresolved_spans"] == []
