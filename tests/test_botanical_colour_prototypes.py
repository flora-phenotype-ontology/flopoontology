from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPES = ROOT / "curation" / "botanical_colour_prototypes.tsv"


def _rows() -> list[dict[str, str]]:
    with PROTOTYPES.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert all(row.get(None) is None for row in rows)
    return rows


def test_botanical_colour_words_have_prototypes_and_sources_without_invented_rgb():
    rows = _rows()
    surfaces = "|".join(row["surface_forms"] for row in rows)

    for term in (
        "cream",
        "crimson",
        "scarlet",
        "silvery",
        "golden",
        "lemon",
        "mahogany",
        "salmon",
        "chestnut",
        "chocolate",
        "olive",
        "rose",
        "straw",
    ):
        assert term in surfaces
    assert all(row["standard"] for row in rows)
    assert all(row["standard_designation"] for row in rows)
    assert all(row["recognition_definition"] for row in rows)
    assert all(row["definition_sources"] for row in rows)
    assert all("RGB" not in row["recognition_definition"] for row in rows)
    assert all(not row["curator_decision"] and not row["curator_notes"] for row in rows)


def test_source_qualified_prototypes_feed_sensu_hierarchies_not_one_exact_mapping():
    rows = _rows()
    by_first_surface = {row["surface_forms"].split("|")[0]: row for row in rows}

    for surface in (
        "cream",
        "crimson",
        "scarlet",
        "lemon",
        "mahogany",
        "salmon",
        "chestnut",
        "chocolate",
        "olive",
        "rose",
        "straw",
    ):
        assert by_first_surface[surface]["mapping_status"] == (
            "sensu_hierarchy_required"
        )
    assert "FLOPO appearance composition" in by_first_surface["silver"][
        "ontology_recommendation"
    ]
    assert by_first_surface["gold"]["mapping_status"] == (
        "multiple_source_prototypes_not_one_generic_value"
    )
    assert "generic PATO scarlet umbrella" in by_first_surface["scarlet"][
        "ontology_recommendation"
    ]
    for surface in (
        "cream",
        "crimson",
        "scarlet",
        "lemon",
        "mahogany",
        "salmon",
        "chestnut",
        "chocolate",
        "olive",
        "rose",
        "straw",
    ):
        recommendation = by_first_surface[surface]["ontology_recommendation"]
        assert "PATO" in recommendation
        assert "FLOPO-local sensu" in recommendation
