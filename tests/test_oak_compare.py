from __future__ import annotations

import csv

from flopo2.terminology.mapping_validation import REPORT_FIELDS
from flopo2.terminology.oak_compare import compare_oak_lexmatch


def _write(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_oak_comparison_preserves_directional_obo_synonym_scope(tmp_path):
    report = tmp_path / "report.tsv"
    row = {field: "" for field in REPORT_FIELDS}
    row.update(
        {
            "surface_form": "trunk",
            "scoped_target_ids": "PO_0009047",
            "scoped_relations": "skos:broadMatch",
        }
    )
    exact = {field: "" for field in REPORT_FIELDS}
    exact.update(
        {
            "surface_form": "leaf",
            "exact_target_ids": "PO_0025034",
        }
    )
    _write(report, REPORT_FIELDS, [row, exact])
    query_map = tmp_path / "queries.tsv"
    _write(
        query_map,
        ("query_id", "surface_form", "corpus_frequency"),
        [
            {"query_id": "BTERM:1", "surface_form": "trunk", "corpus_frequency": "1"},
            {"query_id": "BTERM:2", "surface_form": "leaf", "corpus_frequency": "1"},
        ],
    )
    sssom = tmp_path / "oak.tsv"
    sssom.write_text(
        "# mapping_set_id: test\n"
        "subject_id\tpredicate_id\tobject_id\tobject_match_field\n"
        "BTERM:1\tskos:closeMatch\tPO:0009047\toio:hasNarrowSynonym\n"
        "BTERM:2\tskos:exactMatch\tPO:0025034\trdfs:label\n",
        encoding="utf-8",
    )

    rows, summary = compare_oak_lexmatch(report, query_map, [sssom])

    by_surface = {result["surface_form"]: result for result in rows}
    assert summary["expected_pairs"] == 2
    assert summary["oak_pairs"] == 2
    assert summary["shared_pairs"] == 2
    assert summary["pair_recall"] == 1.0
    assert summary["pair_precision"] == 1.0
    assert summary["surface_recall"] == 1.0
    assert summary["statuses"] == {"relation_agrees": 1, "relation_differs": 1}
    assert by_surface["trunk"]["expected_relation"] == "skos:broadMatch"
    assert by_surface["trunk"]["oak_object_match_field"] == "oio:hasNarrowSynonym"
