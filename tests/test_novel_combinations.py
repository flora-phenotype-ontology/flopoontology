from __future__ import annotations

import csv
import json


def test_novel_combination_sheet_aggregates_evidence_without_approving(tmp_path):
    from flopo2.verify.novel_combinations import build_review_sheet

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_1\tleaf\nPO_2\tpetal\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_1\tlength\tattribute_slim\n"
        "PATO_2\tgreen\tvalue_slim\n"
    )
    records = [
        {
            "source": "flora-A",
            "source_id": "one.xml",
            "taxon": "Alpha",
            "assertions": [
                {
                    "po_id": "PO_1",
                    "pato_id": "PATO_1",
                    "source_text": "leaves 2-4 cm long",
                    "value_low": 2,
                    "value_high": 4,
                    "composition": {"status": "accept"},
                    "gate": {"po_pato_status": "novel", "reasons": ["po_pato_novel"]},
                },
                {
                    "po_id": "PO_2",
                    "pato_id": "PATO_2",
                    "source_text": "petals green",
                    "gate": {"po_pato_status": "allowed", "reasons": []},
                },
            ],
        },
        {
            "source": "flora-B",
            "source_id": "two.xml",
            "taxon": "Beta",
            "assertions": [
                {
                    "po_id": "PO_1",
                    "pato_id": "PATO_1",
                    "source_text": "usually 3 cm long",
                    "frequency_qualifier": "usually",
                    "composition": {"status": "review"},
                    "gate": {"po_pato_status": "novel", "reasons": ["po_pato_novel"]},
                }
            ],
        },
    ]
    source = tmp_path / "review.jsonl"
    source.write_text("".join(json.dumps(record) + "\n" for record in records))
    output = tmp_path / "novel.tsv"

    stats = build_review_sheet(source, output, po, pato)
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    assert stats == {
        "combinations": 1,
        "evidence": 2,
        "attribute_combinations": 1,
        "numeric_evidence": 1,
        "qualified_evidence": 1,
        "composition_accepted_evidence": 1,
        "composition_review_evidence": 1,
        "out": str(output),
    }
    assert rows[0]["review_rank"] == "1"
    assert rows[0]["proposed_label"] == "leaf length"
    assert rows[0]["review_scope"] == "reusable_trait"
    assert rows[0]["taxon_count"] == "2"
    assert rows[0]["source_document_count"] == "2"
    assert rows[0]["source_collection_count"] == "2"
    assert rows[0]["accepted_source_collection_count"] == "1"
    assert rows[0]["source_collections"] == "flora-A|flora-B"
    assert rows[0]["evidence_by_source"] == "flora-A:1|flora-B:1"
    assert rows[0]["composition_accepted_count"] == "1"
    assert rows[0]["composition_review_count"] == "1"
    assert rows[0]["example_1_source"] == "flora-A"
    assert rows[0]["example_2_source"] == "flora-B"
    assert rows[0]["review_status"] == "pending"
    assert rows[0]["reviewer"] == ""


def test_novel_combination_sheet_ranks_independent_accepted_sources_first(tmp_path):
    from flopo2.verify.novel_combinations import build_review_sheet

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_1\tleaf\nPO_2\tpetal\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text("id\tlabel\tslim\nPATO_1\tgreen\t\nPATO_2\tred\t\n")
    records = [
        {
            "source": source,
            "source_id": f"{source}.xml",
            "taxon": source,
            "assertions": [
                {
                    "po_id": po_id,
                    "pato_id": pato_id,
                    "source_text": source,
                    "composition": {"status": composition_status},
                    "gate": {"po_pato_status": "novel", "reasons": ["po_pato_novel"]},
                }
            ],
        }
        for source, po_id, pato_id, composition_status in (
            ("flora-A", "PO_1", "PATO_1", "accept"),
            ("flora-B", "PO_1", "PATO_1", "accept"),
            ("flora-C", "PO_2", "PATO_2", "review"),
            ("flora-D", "PO_2", "PATO_2", "review"),
            ("flora-E", "PO_2", "PATO_2", "review"),
        )
    ]
    source = tmp_path / "review.jsonl"
    source.write_text("".join(json.dumps(record) + "\n" for record in records))
    output = tmp_path / "novel.tsv"

    build_review_sheet(source, output, po, pato)
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    assert [(row["po_id"], row["pato_id"]) for row in rows] == [
        ("PO_1", "PATO_1"),
        ("PO_2", "PATO_2"),
    ]
    assert [row["review_rank"] for row in rows] == ["1", "2"]
