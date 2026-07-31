from __future__ import annotations

import csv
import json


def test_write_review_tsv(tmp_path):
    from flopo2.eval.curation import review_tsv_to_gold_jsonl, write_review_tsv

    src = tmp_path / "silver.jsonl"
    rows = [
        {
            "source": "fdac",
            "source_id": "1",
            "taxon": "T",
            "organ": "flowers",
            "language": "en",
            "text": "flowers red",
            "assertions": [{
                "po_id": "PO_0009046",
                "po_label": "flower",
                "pato_id": "PATO_0000322",
                "pato_label": "red",
                "source_text": "flowers red",
            }],
        }
    ]
    src.write_text("\n".join(json.dumps(r) for r in rows))
    out = tmp_path / "review.tsv"
    assert write_review_tsv(src, out, limit=1) == 1

    with out.open(newline="", encoding="utf-8") as fh:
        exported = list(csv.DictReader(fh, delimiter="\t"))
    assert exported[0]["review_id"] == "paul-001"
    assert exported[0]["gold_assertions_json"]

    gold = tmp_path / "gold.jsonl"
    assert review_tsv_to_gold_jsonl(out, gold) == 1
    converted = json.loads(gold.read_text())
    assert converted["assertions"][0]["po_id"] == "PO_0009046"
