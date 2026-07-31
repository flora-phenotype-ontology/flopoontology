from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "curation" / "botanical_concept_proposals.tsv"


def _proposals_by_id() -> dict[str, dict[str, str]]:
    with PROPOSALS.open(encoding="utf-8", newline="") as handle:
        return {
            row["proposal_id"]: row
            for row in csv.DictReader(handle, delimiter="\t")
        }


def test_sensitive_botanical_proposals_keep_semantically_safe_parents():
    proposals = _proposals_by_id()

    winged = proposals["PATO-CAND:winged"]
    assert winged["direct_parent_ids"] == "PATO:0000052"
    assert "PATO:0002358" not in winged["direct_parent_ids"]

    stinging = proposals["FLOPO-CAND:stinging_trichome"]
    assert stinging["intended_ontology"] == "FLOPO"
    assert stinging["direct_parent_ids"] == "FLOPO:0000355"
    assert "PO:0004509" not in stinging["direct_parent_ids"]
    assert "PATO:0001727" in stinging["other_axioms"]

    for proposal_id in ("PATO-CAND:ascending", "PATO-CAND:spreading"):
        assert proposals[proposal_id]["direct_parent_ids"] == "PATO:0000133"


def test_collective_and_substance_models_are_routed_to_flopo_local_extensions():
    proposals = _proposals_by_id()

    foliage = proposals["FLOPO-CAND:foliage"]
    assert foliage["intended_ontology"] == "FLOPO"
    assert foliage["recommendation"] == "new_local_entity_and_phenotype_branch"
    assert foliage["direct_parent_ids"] == "FLOPO:0000000"
    assert "PO:0025131" in foliage["other_axioms"]
    assert "PO:0025497" in foliage["current_ontology_status"]

    latex = proposals["FLOPO-CAND:plant_latex"]
    assert latex["intended_ontology"] == "FLOPO"
    assert latex["recommendation"] == "revise_existing"
    assert latex["direct_parent_ids"] == "FLOPO:0900048"
    assert "PO:0025161" in latex["other_axioms"]
    assert "PO:0025538" in latex["other_axioms"]


def test_leaflet_count_combinations_are_flopo_cardinality_phenotypes():
    proposals = _proposals_by_id()

    trifoliolate = proposals["FLOPO-CAND:trifoliolate_leaf"]
    assert trifoliolate["recommendation"] == "revise_existing"
    assert trifoliolate["direct_parent_ids"] == "FLOPO:0000004"
    assert "FLOPO:0900067" in trifoliolate["other_axioms"]
    assert "exactly 3 PO:0020049" in trifoliolate["other_axioms"]
    assert "FLOPO:0000149" in trifoliolate["current_ontology_status"]

    bifoliolate = proposals["FLOPO-CAND:bifoliolate_leaf"]
    assert bifoliolate["recommendation"] == "new_compositional_phenotype"
    assert bifoliolate["direct_parent_ids"] == "FLOPO:0000004"
    assert "exactly 2 PO:0020049" in bifoliolate["other_axioms"]

    assert "PO-CAND:trifoliolate_leaf" not in proposals
    assert "PO-CAND:bifoliolate_leaf" not in proposals
    assert "PO-CAND:stinging_hair" not in proposals


def test_contextual_surface_forms_are_not_promoted_to_exact_synonyms():
    proposals = _proposals_by_id()

    for proposal_id, surface in (
        ("PATO-CAND:lanate", "woolly"),
        ("PATO-CAND:sericeous", "silky"),
        ("PATO-CAND:plicate", "pleated"),
    ):
        axioms = proposals[proposal_id]["other_axioms"].lower()
        assert f"{surface} as an exact synonym" not in axioms
        assert "related synonym" in axioms


def test_life_span_and_spreading_definitions_do_not_shift_bearers():
    proposals = _proposals_by_id()

    for proposal_id in (
        "PATO-CAND:annual_life_span",
        "PATO-CAND:perennial_life_span",
    ):
        assert "expected natural life span" in proposals[proposal_id]["definition"]

    spreading = proposals["PATO-CAND:spreading"]
    assert "or its parts" not in spreading["definition"]
    assert "whole-plant spreading growth form" in spreading["other_axioms"]
