from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "curation" / "botanical_colour_sensu_proposals.tsv"
REVIEW = ROOT / "curation" / "BOTANICAL_COLOUR_SENSU_REVIEW.md"
EVIDENCE = ROOT / "curation" / "botanical_evidence.tsv"

FIELDS = (
    "proposal_key",
    "surface_family",
    "class_role",
    "preferred_label",
    "intended_ontology",
    "current_id",
    "asserted_parent",
    "definition_or_recognition_rule",
    "standard",
    "standard_designation",
    "logical_pattern",
    "definition_sources",
    "annotation_policy",
    "caveat",
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


def test_colour_sensu_proposals_are_complete_unique_and_unadjudicated():
    rows = _rows()
    keys = [row["proposal_key"] for row in rows]

    assert len(keys) == len(set(keys))
    assert all(row["preferred_label"] for row in rows)
    assert all(row["definition_or_recognition_rule"] for row in rows)
    assert all(row["definition_sources"] for row in rows)
    assert all(not row["curator_decision"] and not row["curator_notes"] for row in rows)
    assert all("disjoint" not in row["logical_pattern"].lower() for row in rows)


def test_colour_sensu_evidence_references_resolve():
    with EVIDENCE.open(encoding="utf-8", newline="") as handle:
        evidence_ids = {
            row["evidence_id"] for row in csv.DictReader(handle, delimiter="\t")
        }

    references = {
        reference
        for row in _rows()
        for reference in row["definition_sources"].split("|")
    }
    assert all(
        reference in evidence_ids or reference.startswith("DOI:")
        for reference in references
    )


def test_every_sensu_colour_has_an_operational_source_and_generic_parent():
    rows = _rows()
    by_key = _by_key()
    sensu_rows = [row for row in rows if row["class_role"] == "sensu_colour"]

    assert sensu_rows
    for row in sensu_rows:
        assert row["intended_ontology"] == "FLOPO"
        assert not row["current_id"]
        assert " sensu " in row["preferred_label"]
        assert row["standard"]
        assert row["standard_designation"]
        assert row["definition_sources"]
        assert row["asserted_parent"].startswith("COLOR:")
        assert by_key[row["asserted_parent"]]["class_role"] == "lexical_umbrella"
        assert "Use only when" in row["annotation_policy"]
        assert "RGB" not in row["definition_or_recognition_rule"]


def test_every_generic_colour_is_open_and_has_a_sensu_child():
    rows = _rows()
    umbrellas = [row for row in rows if row["class_role"] == "lexical_umbrella"]
    child_parents = {
        row["asserted_parent"]
        for row in rows
        if row["class_role"] == "sensu_colour"
    }

    assert umbrellas
    for row in umbrellas:
        assert row["intended_ontology"] == "PATO"
        assert row["asserted_parent"] == "PATO:0000014"
        assert row["proposal_key"] in child_parents
        assert not row["standard"]
        assert not row["standard_designation"]
        assert "Primitive superclass" in row["logical_pattern"]
        assert "EquivalentTo unionOf" not in row["logical_pattern"]
        assert "Map an unqualified" in row["annotation_policy"]


def test_scarlet_has_three_sensu_children_and_only_the_optional_view_is_closed():
    rows = _rows()
    by_key = _by_key()
    children = {
        row["proposal_key"]
        for row in rows
        if row["class_role"] == "sensu_colour"
        and row["asserted_parent"] == "COLOR:scarlet"
    }
    expected = {
        "COLOR:scarlet_saccardo_1891",
        "COLOR:scarlet_ridgway_1912",
        "COLOR:scarlet_wilson_h19",
    }

    assert children == expected
    assert "EquivalentTo unionOf" not in by_key["COLOR:scarlet"]["logical_pattern"]

    union_view = by_key["COLOR:scarlet_reviewed_union"]
    assert union_view["class_role"] == "closed_union_view"
    members = set(re.findall(r"COLOR:[a-z0-9_]+", union_view["logical_pattern"]))
    assert members == expected | {"COLOR:scarlet"}
    assert "Never use" in union_view["annotation_policy"]


def test_existing_cream_identifier_is_generic_and_rhs_sense_moves_to_flopo():
    rows = _by_key()

    assert rows["COLOR:cream"]["current_id"] == "PATO:0104031"
    assert rows["COLOR:cream"]["intended_ontology"] == "PATO"
    assert rows["COLOR:cream_rhs_5"]["current_id"] == ""
    assert rows["COLOR:cream_rhs_5"]["intended_ontology"] == "FLOPO"
    assert rows["COLOR:cream_rhs_5"]["asserted_parent"] == "COLOR:cream"
    assert "158A or 158B" in rows["COLOR:cream_rhs_5"][
        "definition_or_recognition_rule"
    ]


def test_cross_category_silver_and_gold_exceptions_are_explicit():
    review = REVIEW.read_text(encoding="utf-8")

    assert "`silvery` and `golden` do not fit one pure-colour hierarchy" in review
    assert "FLOPO appearance" in review
    assert "`Old Gold`" in review
    assert "it must not be made a subclass" in review
    assert "FLOPO appearance phenotype" in review.replace("\n", " ")
