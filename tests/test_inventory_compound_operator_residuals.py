from __future__ import annotations

import json
from pathlib import Path

from flopo2.verify.inventory_compound_operator_residuals import (
    freeze_compound_operator_scope,
)


def test_freezes_only_target_reasons_and_conserves_rows(tmp_path: Path) -> None:
    text = "Leaves ovate or elliptic, not red."
    record = {
        "source": "fixture",
        "source_id": "flora.xml",
        "source_segment_index": 1,
        "taxon": "Planta exemplaris",
        "organ": "leaves",
        "language": "en",
        "text": text,
        "unresolved_spans": [
            {
                "start": 7,
                "end": 12,
                "surface_form": "ovate",
                "reason": "explicit_disjunction",
                "candidate_pato_id": "PATO_0001891",
                "extractor": "fixture",
            },
            {
                "start": 16,
                "end": 24,
                "surface_form": "elliptic",
                "reason": "same_attribute_composite_or_transition",
                "candidate_pato_id": "PATO_0000947",
                "extractor": "fixture",
            },
            {
                "start": 30,
                "end": 33,
                "surface_form": "red",
                "reason": "negated_context",
                "candidate_pato_id": "PATO_0000322",
                "extractor": "fixture",
            },
        ],
    }
    stage = tmp_path / "stage.jsonl"
    stage.write_text(json.dumps(record) + "\n", encoding="utf-8")
    inventory = tmp_path / "inventory.jsonl"
    signatures = tmp_path / "signatures.jsonl"
    report_path = tmp_path / "report.json"
    report = freeze_compound_operator_scope(
        stage_path=stage,
        inventory_path=inventory,
        signatures_path=signatures,
        report_path=report_path,
    )

    assert report["starting_spans"] == 2
    assert report["distinct_span_ids"] == 2
    assert report["duplicate_physical_rows"] == 0
    assert report["conserved"] is True
    rows = [json.loads(line) for line in inventory.read_text().splitlines()]
    assert {row["surface_form"] for row in rows} == {"ovate", "elliptic"}
    assert len(signatures.read_text().splitlines()) == 2
