from __future__ import annotations

import csv
import json

import pytest


def _lexicons(tmp_path):
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_1\tleaf\nPO_2\tpetal\n")
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tslim\n"
        "PATO_color\tcolour\tattribute_slim\n"
        "PATO_length\tlength\tattribute_slim\n"
        "PATO_red\tred\tvalue_slim\n"
        "PATO_yellow\tyellow\tvalue_slim\n"
        "PATO_white\twhite\tvalue_slim\n"
    )
    return po, pato


def _read_tsv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_full_expression_queue_keeps_logical_signatures_distinct_and_pending(tmp_path):
    from flopo2.verify.novel_expressions import build_review_queues

    po, pato = _lexicons(tmp_path)
    one_of_signature = "EQV|PO_1|ONE_OF|PATO_red&PATO_yellow"
    records = [
        {
            "source": "flora-A",
            "source_id": "one.xml",
            "taxon": "Alpha",
            "assertions": [
                {
                    "po_id": "PO_1",
                    "pato_id": "PATO_color",
                    "value_operator": "one_of",
                    "value_terms": ["PATO_yellow", "PATO_red"],
                    "source_text": "leaves red or yellow",
                    "composition": {"status": "accept"},
                    "phenotype_class_iri": (
                        "https://w3id.org/flopo/annotation-class/FAC_logical"
                    ),
                    "gate": {
                        "status": "accepted",
                        "flopo_status": "new_class_candidate",
                        "flopo_signature": one_of_signature,
                    },
                },
                {
                    "po_id": "PO_1",
                    "pato_id": "PATO_color",
                    "source_text": "leaf colour",
                    "gate": {
                        "status": "review",
                        "flopo_status": "new_class_candidate",
                        "flopo_signature": "EQ|PO_1|PATO_color",
                    },
                },
                {
                    "po_id": "PO_2",
                    "pato_id": "PATO_white",
                    "source_text": "petals white",
                    "gate": {
                        "status": "accepted",
                        "flopo_status": "existing",
                        "flopo_signature": "EQ|PO_2|PATO_white",
                    },
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
                    "pato_id": "PATO_color",
                    "value_operator": "one_of",
                    "value_terms": ["PATO_red", "PATO_yellow"],
                    "source_text": "usually yellow or red",
                    "frequency_qualifier": "usually",
                    "composition": {"status": "accept"},
                    "phenotype_class_iri": (
                        "https://w3id.org/flopo/annotation-class/FAC_logical"
                    ),
                    "gate": {
                        "status": "accepted",
                        "flopo_status": "new_class_candidate",
                        "flopo_signature": one_of_signature,
                    },
                },
                {
                    "po_id": "PO_1",
                    "pato_id": "PATO_color",
                    "value_operator": "all_of",
                    "value_terms": ["PATO_red", "PATO_white"],
                    "source_text": "red and white leaves",
                    "composition": {"status": "review"},
                    "gate": {
                        "status": "review",
                        "flopo_status": "new_class_candidate",
                        "flopo_signature": "EQV|PO_1|ALL_OF|PATO_red&PATO_white",
                    },
                },
            ],
        },
    ]
    source = tmp_path / "gated.jsonl"
    source.write_text("".join(json.dumps(record) + "\n" for record in records))
    review = tmp_path / "expressions.tsv"
    fac = tmp_path / "fac.tsv"

    stats = build_review_queues(source, review, po, pato, fac)
    rows = _read_tsv(review)
    fac_rows = _read_tsv(fac)

    assert stats["candidates"] == 3
    assert stats["evidence"] == 4
    assert stats["disjunctive_candidates"] == 1
    assert stats["conjunctive_candidates"] == 1
    assert [row["flopo_signature"] for row in rows].count(one_of_signature) == 1
    one_of = next(row for row in rows if row["flopo_signature"] == one_of_signature)
    assert one_of["expression_kind"] == "disjunctive_phenotype"
    assert one_of["review_scope"] == "reusable_composite_phenotype"
    assert one_of["value_operator"] == "one_of"
    assert one_of["value_term_ids"] == "PATO_red|PATO_yellow"
    assert one_of["evidence_count"] == "2"
    assert one_of["source_collection_count"] == "2"
    assert one_of["taxon_count"] == "2"
    assert one_of["qualified_count"] == "1"
    assert one_of["fac_expression_count"] == "1"
    assert one_of["fac_iri_count"] == "1"
    assert one_of["phenotype_class_iris"].endswith("FAC_logical")
    assert one_of["reusability_evidence"] == (
        "repeated_occurrence|multiple_source_collections|"
        "multiple_source_documents|multiple_taxa"
    )
    assert one_of["review_status"] == "pending"
    assert one_of["ontology_action"] == "review_only_no_flopo_id_minted"
    assert "flopo_iri" not in one_of

    all_of = next(row for row in rows if row["expression_kind"] == "conjunctive_phenotype")
    assert all_of["reusability_evidence"] == "single_corpus_occurrence_only"
    assert all_of["reusability_review_status"] == "pending_curator_review"
    assert all_of["composition_review_count"] == "1"
    assert all(row["ontology_action"] == "fac_evidence_only_no_flopo_id_minted" for row in fac_rows)
    assert len(fac_rows) == 3


def test_numeric_values_stay_fac_only_under_one_reusable_trait_candidate(tmp_path):
    from flopo2.verify.novel_expressions import build_review_queues

    po, pato = _lexicons(tmp_path)
    trait_signature = "EQ|PO_2|PATO_length"
    records = []
    for source, low, unit, fac_iri in (
        (
            "flora-A",
            3,
            "mm",
            "https://w3id.org/flopo/annotation-class/FAC_three_mm",
        ),
        (
            "flora-B",
            3.0,
            "UO:0000016",
            "https://w3id.org/flopo/annotation-class/FAC_three_mm",
        ),
        (
            "flora-C",
            4,
            "millimeter",
            "https://w3id.org/flopo/annotation-class/FAC_four_mm",
        ),
    ):
        records.append(
            {
                "source": source,
                "source_id": f"{source}.xml",
                "taxon": source,
                "assertions": [
                    {
                        "po_id": "PO_2",
                        "pato_id": "PATO_length",
                        "value_low": low,
                        "value_high": low,
                        "unit": unit,
                        "source_text": f"petals {low} {unit} long",
                        "phenotype_class_iri": fac_iri,
                        "composition": {"status": "accept"},
                        "gate": {
                            "status": "accepted",
                            "flopo_status": "new_class_candidate",
                            # This deliberately remains the reusable trait signature.  Exact
                            # bound-sensitive signatures belong only to the FAC evidence queue.
                            "flopo_signature": trait_signature,
                        },
                    }
                ],
            }
        )
    source = tmp_path / "numeric.jsonl"
    source.write_text("".join(json.dumps(record) + "\n" for record in records))
    review = tmp_path / "numeric-review.tsv"
    fac = tmp_path / "numeric-fac.tsv"

    stats = build_review_queues(source, review, po, pato, fac)
    rows = _read_tsv(review)
    fac_rows = _read_tsv(fac)

    assert stats["candidates"] == 1
    assert stats["numeric_trait_candidates"] == 1
    assert stats["numeric_evidence"] == 3
    assert stats["fac_expressions"] == 2
    assert len(rows) == 1
    row = rows[0]
    assert row["flopo_signature"] == trait_signature
    assert row["gate_signature_role"] == "reusable_po_pato_trait"
    assert row["expression_kind"] == "numeric_trait"
    assert row["review_scope"] == "reusable_trait"
    assert row["numeric_handling"] == (
        "review_reusable_trait;exact_bounds_and_units_fac_only"
    )
    assert row["numeric_range_count"] == "2"
    assert row["numeric_ranges"] == "3 UO_0000016|4 UO_0000016"
    assert row["fac_expression_count"] == "2"
    assert row["fac_iri_count"] == "2"
    assert {fac_row["curation_scope"] for fac_row in fac_rows} == {
        "fac_only_numeric_value"
    }
    assert sorted(fac_row["evidence_count"] for fac_row in fac_rows) == ["1", "2"]
    assert all("EQ|PO_2|PATO_length" == fac_row["flopo_signature"] for fac_row in fac_rows)
    assert all(
        fac_row["ontology_action"] == "fac_evidence_only_no_flopo_id_minted"
        for fac_row in fac_rows
    )


def test_expression_queue_rejects_candidate_without_gate_signature(tmp_path):
    from flopo2.verify.novel_expressions import build_review_queues

    source = tmp_path / "broken.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-A",
                "source_id": "one.xml",
                "assertions": [
                    {
                        "po_id": "PO_1",
                        "pato_id": "PATO_red",
                        "source_text": "red",
                        "gate": {"flopo_status": "new_class_candidate"},
                    }
                ],
            }
        )
        + "\n"
    )

    with pytest.raises(ValueError, match=r"line 1, assertion 0"):
        build_review_queues(source, tmp_path / "out.tsv")
