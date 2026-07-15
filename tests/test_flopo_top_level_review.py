from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "curation" / "flopo_top_level_and_local_extension_proposals.tsv"

FIELDS = (
    "proposal_key",
    "current_id",
    "action",
    "model_role",
    "preferred_label",
    "textual_definition",
    "asserted_parents",
    "logical_pattern_or_constraint",
    "evidence",
    "migration_note",
    "curator_decision",
    "curator_notes",
)


def _rows() -> list[dict[str, str]]:
    with PROPOSALS.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        assert tuple(reader.fieldnames or ()) == FIELDS
        rows = list(reader)
    assert all(row.get(None) is None for row in rows)
    return rows


def _by_key() -> dict[str, dict[str, str]]:
    return {row["proposal_key"]: row for row in _rows()}


def test_top_level_review_is_complete_unique_and_unadjudicated():
    rows = _rows()
    keys = [row["proposal_key"] for row in rows]

    assert len(keys) == len(set(keys))
    assert all(row["preferred_label"] for row in rows)
    assert all(row["textual_definition"] for row in rows)
    assert all(not row["curator_decision"] and not row["curator_notes"] for row in rows)
    assert all(
        not parent.strip().startswith("BFO:")
        for row in rows
        for parent in row["asserted_parents"].split(";")
        if parent.strip()
    )


def test_top_level_separates_phenotypes_from_quality_and_process_vocabularies():
    rows = _by_key()

    assert rows["TOP:continuant_target_phenotype"]["model_role"] == "bearer_facet"
    assert rows["TOP:occurrent_target_phenotype"]["model_role"] == "bearer_facet"
    assert all(row["model_role"] != "aspect_facet" for row in rows.values())
    assert rows["VOCAB:quality_root"]["current_id"] == "PATO:0000001"
    assert rows["VOCAB:quality_root"]["asserted_parents"] == ""
    assert rows["VOCAB:continuant_quality_root"]["current_id"] == "PATO:0001241"
    assert rows["VOCAB:process_quality_root"]["current_id"] == "PATO:0001236"
    assert rows["VOCAB:biological_process_root"]["current_id"] == "GO:0008150"
    assert rows["VOCAB:biological_process_root"]["asserted_parents"] == ""

    process_pattern = rows["TOP:occurrent_target_phenotype"][
        "logical_pattern_or_constraint"
    ]
    assert "RO:0000056" in process_pattern
    assert "GO:0008150" in process_pattern
    assert "RO:0000053" in process_pattern
    assert "PATO:0001236" in process_pattern
    assert "Never use has_part" in process_pattern
    assert "RO:0000086" not in process_pattern

    phenotype_keys = {
        key
        for key, row in rows.items()
        if row["model_role"] in {"phenotype", "phenotype_branch", "bearer_facet"}
    }
    assert all(
        not parent.startswith(("PATO:", "GO:"))
        for key in phenotype_keys
        for parent in rows[key]["asserted_parents"].split(";")
        if parent
    )
    assert all(
        "disjoint" not in row["logical_pattern_or_constraint"].lower()
        or "do not assert disjointness" in row["logical_pattern_or_constraint"].lower()
        for row in rows.values()
    )


def test_local_extensions_use_imported_biological_parents_and_existing_branches():
    rows = _by_key()

    assert rows["LOCAL:trifoliolate_quality"]["asserted_parents"] == "PATO:0001555"
    assert "exactly 3 PO:0020049" in rows["LOCAL:trifoliolate_leaf"][
        "logical_pattern_or_constraint"
    ]
    assert rows["LOCAL:trifoliolate_leaf"]["current_id"] == "FLOPO:0900067"
    assert rows["LOCAL:bifoliolate_quality"]["asserted_parents"] == "PATO:0001555"
    assert "exactly 2 PO:0020049" in rows["LOCAL:bifoliolate_leaf"][
        "logical_pattern_or_constraint"
    ]
    assert rows["LOCAL:stinging_disposition"]["asserted_parents"] == "PATO:0001727"
    assert "PO:0004509" in rows["LOCAL:stinging_trichome"][
        "logical_pattern_or_constraint"
    ]
    assert rows["LOCAL:foliage_entity"]["asserted_parents"] == "PO:0025131"
    foliage_pattern = rows["LOCAL:foliage_entity"]["logical_pattern_or_constraint"]
    assert "BFO:0000115" in foliage_pattern
    assert "some PO:0025034" in foliage_pattern
    assert "only PO:0025034" in foliage_pattern
    assert rows["LOCAL:plant_latex_entity"]["asserted_parents"] == "PO:0025161"
    assert rows["LOCAL:latex_phenotype"]["current_id"] == "FLOPO:0900048"
    assert rows["LOCAL:whole_plant_growth_form"]["current_id"] == "FLOPO:0900032"
