from __future__ import annotations

import csv

import pytest

from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.curation_table import PROPOSAL_FIELDS
from flopo2.terminology.proposal_validation import validate_proposal_references


def _write_proposals(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=PROPOSAL_FIELDS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _proposal(**changes):
    row = {field: "" for field in PROPOSAL_FIELDS}
    row.update(
        {
            "proposal_id": "PATO-CAND:test",
            "surface_forms": "test",
            "corpus_frequency": "1",
            "intended_ontology": "PATO",
            "recommendation": "accept_proposal",
            "preferred_label": "test",
            "definition": "A test quality.",
            "definition_sources": "EVID:test",
            "direct_parent_ids": "PATO:0000001",
        }
    )
    row.update(changes)
    return row


def _catalog():
    return OntologyCatalog(
        {
            "PATO_0000001": OntologyTerm(
                "PATO_0000001", "quality", "PATO"
            ),
            "PO_0000001": OntologyTerm("PO_0000001", "plant", "PO"),
            "PO_0000999": OntologyTerm(
                "PO_0000999", "obsolete structure", "PO", deprecated=True
            ),
        }
    )


def test_proposal_reference_validation_accepts_current_and_provisional_ids(tmp_path):
    path = tmp_path / "proposals.tsv"
    _write_proposals(
        path,
        [
            _proposal(other_axioms="compare PO:0000999"),
            _proposal(
                proposal_id="PO-CAND:test_part",
                intended_ontology="PO",
                direct_parent_ids="PO:0000001",
                part_of_ids="PATO-CAND:test",
            ),
        ],
    )

    summary = validate_proposal_references(path, _catalog())

    assert summary["accepted_class_proposals"] == 2
    assert summary["accepted_class_proposals_with_definition_evidence"] == 2
    assert summary["unknown_references"] == 0
    assert summary["deprecated_narrative_references"] == ["PO:0000999"]


def test_proposal_reference_validation_rejects_unknown_and_obsolete_assertions(tmp_path):
    path = tmp_path / "proposals.tsv"
    _write_proposals(path, [_proposal(direct_parent_ids="PATO:9999999")])
    with pytest.raises(ValueError, match="unknown direct_parent_ids reference"):
        validate_proposal_references(path, _catalog())

    _write_proposals(
        path,
        [
            _proposal(
                intended_ontology="PO",
                direct_parent_ids="PO:0000999",
            )
        ],
    )
    with pytest.raises(ValueError, match="obsolete direct_parent_ids reference"):
        validate_proposal_references(path, _catalog())


def test_proposal_reference_validation_requires_parent_for_acceptance(tmp_path):
    path = tmp_path / "proposals.tsv"
    _write_proposals(path, [_proposal(direct_parent_ids="")])

    with pytest.raises(ValueError, match="requires a direct parent"):
        validate_proposal_references(path, _catalog())
