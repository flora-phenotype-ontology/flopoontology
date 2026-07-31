from __future__ import annotations

import csv

import pytest

from flopo2.terminology.curation_table import (
    PROPOSAL_FIELDS,
    build_curation_table,
)
from flopo2.terminology.mapping_validation import REPORT_FIELDS


def _write_tsv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _proposal(**changes):
    row = {field: "" for field in PROPOSAL_FIELDS}
    row.update(
        {
            "proposal_id": "PATO-CAND:campanulate",
            "surface_forms": "campanulate|bell-shaped",
            "corpus_frequency": "2",
            "intended_ontology": "PATO",
            "recommendation": "accept_proposal",
            "preferred_label": "campanulate",
            "definition": "A shape quality with an inflated tube widening distally.",
            "definition_sources": "EVID:UPOV",
            "direct_parent_ids": "PATO:0000052",
            "evidence_status": "verified",
        }
    )
    row.update(changes)
    return row


def test_curation_table_covers_mapping_rows_and_enriches_exact_aliases(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    source_rows = []
    for surface, frequency, recommendation in (
        ("campanulate", "2", "no_lexical_candidate"),
        ("unknown", "1", "no_lexical_candidate"),
        ("head", "3", "deterministic_exact_candidate"),
    ):
        row = {field: "" for field in REPORT_FIELDS}
        row.update(
            {
                "surface_form": surface,
                "corpus_frequency": frequency,
                "recommendation": recommendation,
            }
        )
        source_rows.append(row)
    _write_tsv(mapping, REPORT_FIELDS, source_rows)
    proposals = tmp_path / "proposals.tsv"
    _write_tsv(proposals, PROPOSAL_FIELDS, [_proposal()])
    evidence = tmp_path / "evidence.tsv"
    _write_tsv(evidence, ("evidence_id",), [{"evidence_id": "EVID:UPOV"}])

    rows, summary = build_curation_table(mapping, proposals, evidence)
    by_surface = {row["surface_form"]: row for row in rows}

    assert len(rows) == 3
    assert summary["total_missing_mentions"] == 6
    assert summary["evidence_enriched_surfaces"] == 1
    assert summary["evidence_enriched_mentions"] == 2
    assert summary["pending_mentions"] == 4
    assert by_surface["campanulate"]["proposal_id"] == "PATO-CAND:campanulate"
    assert by_surface["campanulate"]["curator_decision"] == ""
    assert by_surface["unknown"]["recommendation"] == "evidence_review_pending"
    assert by_surface["head"]["recommendation"] == "mapping_candidate_review"


def test_curation_table_rejects_unknown_evidence_and_alias_collisions(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    row = {field: "" for field in REPORT_FIELDS}
    row.update(
        {
            "surface_form": "campanulate",
            "corpus_frequency": "1",
            "recommendation": "no_lexical_candidate",
        }
    )
    _write_tsv(mapping, REPORT_FIELDS, [row])
    evidence = tmp_path / "evidence.tsv"
    _write_tsv(evidence, ("evidence_id",), [{"evidence_id": "EVID:OTHER"}])
    proposals = tmp_path / "proposals.tsv"
    _write_tsv(proposals, PROPOSAL_FIELDS, [_proposal()])

    with pytest.raises(ValueError, match="unknown evidence IDs"):
        build_curation_table(mapping, proposals, evidence)

    _write_tsv(evidence, ("evidence_id",), [{"evidence_id": "EVID:UPOV"}])
    _write_tsv(
        proposals,
        PROPOSAL_FIELDS,
        [_proposal(), _proposal(proposal_id="PATO-CAND:bell", surface_forms="bell shaped")],
    )
    with pytest.raises(ValueError, match="belongs to both"):
        build_curation_table(mapping, proposals, evidence)


def test_curation_table_allows_explicit_noise_rejection_without_definition(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    row = {field: "" for field in REPORT_FIELDS}
    row.update(
        {
            "surface_form": "sandstone",
            "corpus_frequency": "4",
            "recommendation": "no_lexical_candidate",
        }
    )
    _write_tsv(mapping, REPORT_FIELDS, [row])
    evidence = tmp_path / "evidence.tsv"
    _write_tsv(evidence, ("evidence_id",), [{"evidence_id": "EVID:CORPUS"}])
    proposals = tmp_path / "proposals.tsv"
    _write_tsv(
        proposals,
        PROPOSAL_FIELDS,
        [
            _proposal(
                proposal_id="NOISE:habitat_geology",
                surface_forms="sandstone",
                intended_ontology="NONE",
                recommendation="reject_as_noise",
                preferred_label="",
                definition="",
                definition_sources="",
                direct_parent_ids="",
                evidence_status="corpus_context_verified",
            )
        ],
    )

    rows, summary = build_curation_table(mapping, proposals, evidence)

    assert rows[0]["intended_ontology"] == "NONE"
    assert rows[0]["recommendation"] == "reject_as_noise"
    assert rows[0]["definition"] == ""
    assert summary["evidence_enriched_surfaces"] == 1


def test_curation_table_requires_evidence_for_accepted_class_proposal(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    row = {field: "" for field in REPORT_FIELDS}
    row.update(
        {
            "surface_form": "campanulate",
            "corpus_frequency": "1",
            "recommendation": "no_lexical_candidate",
        }
    )
    _write_tsv(mapping, REPORT_FIELDS, [row])
    evidence = tmp_path / "evidence.tsv"
    _write_tsv(evidence, ("evidence_id",), [{"evidence_id": "EVID:UPOV"}])
    proposals = tmp_path / "proposals.tsv"
    _write_tsv(proposals, PROPOSAL_FIELDS, [_proposal(definition_sources="")])

    with pytest.raises(ValueError, match="requires definition evidence"):
        build_curation_table(mapping, proposals, evidence)


def test_curation_table_rejects_machine_authored_curator_decision(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    row = {field: "" for field in REPORT_FIELDS}
    row.update(
        {
            "surface_form": "campanulate",
            "corpus_frequency": "1",
            "recommendation": "no_lexical_candidate",
        }
    )
    _write_tsv(mapping, REPORT_FIELDS, [row])
    evidence = tmp_path / "evidence.tsv"
    _write_tsv(evidence, ("evidence_id",), [{"evidence_id": "EVID:UPOV"}])
    proposals = tmp_path / "proposals.tsv"
    _write_tsv(
        proposals,
        PROPOSAL_FIELDS,
        [_proposal(curator_decision="accept", curator_notes="machine-filled")],
    )

    with pytest.raises(ValueError, match="must leave curator fields blank"):
        build_curation_table(mapping, proposals, evidence)


def test_curation_table_rejects_extra_tsv_columns(tmp_path):
    mapping = tmp_path / "mapping.tsv"
    row = {field: "" for field in REPORT_FIELDS}
    row.update(
        {
            "surface_form": "campanulate",
            "corpus_frequency": "1",
            "recommendation": "no_lexical_candidate",
        }
    )
    _write_tsv(mapping, REPORT_FIELDS, [row])
    evidence = tmp_path / "evidence.tsv"
    _write_tsv(evidence, ("evidence_id",), [{"evidence_id": "EVID:UPOV"}])
    proposals = tmp_path / "proposals.tsv"
    _write_tsv(proposals, PROPOSAL_FIELDS, [_proposal()])
    with proposals.open("a", encoding="utf-8") as handle:
        handle.write("\t".join(["extra"] * (len(PROPOSAL_FIELDS) + 1)) + "\n")

    with pytest.raises(ValueError, match="unexpected extra columns"):
        build_curation_table(mapping, proposals, evidence)
