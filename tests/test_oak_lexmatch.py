from __future__ import annotations

import csv

from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.oak_lexmatch import write_catalog_obo, write_surface_obo


def test_oak_lexmatch_inputs_are_import_free_scoped_and_deterministic(tmp_path):
    report = tmp_path / "mapping.tsv"
    with report.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("surface_form", "corpus_frequency"),
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerow({"surface_form": "trunk", "corpus_frequency": "7"})
        writer.writerow({"surface_form": "bright yellow", "corpus_frequency": "31"})

    query = tmp_path / "query.obo"
    query_map = tmp_path / "query-map.tsv"
    assert write_surface_obo(report, query, query_map) == 2
    assert "id: BTERM:LEX000001\nname: bright yellow" in query.read_text()

    catalog = OntologyCatalog(
        {
            "PO_0009047": OntologyTerm(
                "PO_0009047",
                "stem",
                "PO",
                synonyms=("trunk", "culm"),
                synonym_scopes=(("trunk", "NARROW"), ("culm", "EXACT")),
                definition='A primary axis called a "stem".',
            ),
            "PATO_9999999": OntologyTerm(
                "PATO_9999999", "obsolete value", "PATO", deprecated=True
            ),
        }
    )
    target = tmp_path / "target.obo"
    repeated = tmp_path / "target-repeated.obo"
    assert write_catalog_obo(catalog, target) == 1
    assert write_catalog_obo(catalog, repeated) == 1

    text = target.read_text()
    assert text == repeated.read_text()
    assert "import:" not in text
    assert "id: PO:0009047" in text
    assert 'synonym: "trunk" NARROW []' in text
    assert 'synonym: "culm" EXACT []' in text
    assert '\\"stem\\"' in text
    assert "obsolete value" not in text

    compact = tmp_path / "po-labels-only.obo"
    assert write_catalog_obo(
        catalog, compact, namespaces={"PO"}, include_definitions=False
    ) == 1
    assert "def:" not in compact.read_text()
