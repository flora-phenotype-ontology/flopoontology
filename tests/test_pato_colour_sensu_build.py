from __future__ import annotations

import csv
from pathlib import Path

from tools.apply_pato_colour_sensu_terms import apply_terms
from tools.build_pato_colour_sensu_terms import build_terms


ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "curation" / "botanical_colour_sensu_proposals.tsv"
IDS = ROOT / "config" / "pato_colour_sensu_id_registry.tsv"
EVIDENCE = ROOT / "curation" / "botanical_evidence.tsv"
ORCID = "https://orcid.org/0000-0001-8149-5890"


def _build() -> tuple[str, list[dict[str, str]]]:
    return build_terms(PROPOSALS, IDS, EVIDENCE, "2026-07-15")


def test_approved_colour_build_has_stable_ids_and_definitions():
    rendered, rows = _build()
    new_ids = sorted(
        int(row["pato_id"].split(":", 1)[1])
        for row in rows
        if row["status"] == "new_approved"
    )

    assert len(rows) == 36
    assert new_ids == list(range(104312, 104346))
    assert rendered.count("[Term]\n") == 36
    assert rendered.count("property_value: http://purl.org/dc/terms/contributor") == 36
    assert rendered.count(ORCID) == 36
    assert all(row["definition_or_recognition_rule"] for row in rows)
    assert all(row["definition_sources"] for row in rows)
    assert "standardized scarlet (current reviewed set)" not in rendered
    assert "unionOf" not in rendered


def test_source_specific_colours_are_children_of_open_umbrellas_only():
    _rendered, rows = _build()
    by_key = {row["proposal_key"]: row for row in rows}

    for row in rows:
        if row["class_role"] == "sensu_colour":
            parent = by_key[row["asserted_parent"]]
            assert parent["class_role"] == "lexical_umbrella"
            assert row["parent_id"] == parent["pato_id"]
        else:
            assert row["class_role"] == "lexical_umbrella"
            assert row["parent_id"] == "PATO:0000014"

    assert by_key["COLOR:cream_rhs_5"]["pato_id"] == "PATO:0104031"
    assert by_key["COLOR:rose"]["pato_id"] == "PATO:0001425"
    assert by_key["COLOR:cream"]["pato_id"] == "PATO:0104312"


def test_unqualified_synonyms_stay_on_generic_umbrellas():
    rendered, _rows = _build()
    cream_generic = rendered.split("[Term]\n")[1]
    cream_rhs = rendered.split("[Term]\n")[2]

    assert "id: PATO:0104312" in cream_generic
    assert 'synonym: "creamy" EXACT []' in cream_generic
    assert "id: PATO:0104031" in cream_rhs
    assert 'synonym: "creamy"' not in cream_rhs
    assert "red-plus-yellow definition" in rendered


def test_registry_defers_only_optional_closed_union():
    with IDS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    deferred = [row for row in rows if row["status"].startswith("deferred")]

    assert deferred == [
        {
            "proposal_key": "COLOR:scarlet_reviewed_union",
            "pato_id": "",
            "status": "deferred_optional_closed_union",
        }
    ]


def test_apply_is_idempotent_and_scopes_olive_green_as_related(tmp_path):
    rendered, _rows = _build()
    module = tmp_path / "module.obo"
    module.write_text(rendered, encoding="utf-8")
    pato = tmp_path / "pato-edit.obo"
    pato.write_text(
        "format-version: 1.2\n\n"
        "[Term]\n"
        "id: PATO:0001425\n"
        "name: rosy\n"
        'def: "old rose definition" []\n\n'
        "[Term]\n"
        "id: PATO:0001942\n"
        "name: brown green\n"
        'def: "brown and green" []\n'
        'synonym: "olive green" EXACT []\n\n'
        "[Term]\n"
        "id: PATO:0104031\n"
        "name: cream\n"
        'def: "old cream definition" []\n\n'
        "[Typedef]\n"
        "id: part_of\n"
        "name: part of\n",
        encoding="utf-8",
    )

    replaced, inserted = apply_terms(pato, module)
    first = pato.read_text(encoding="utf-8")
    replaced_again, inserted_again = apply_terms(pato, module)
    second = pato.read_text(encoding="utf-8")

    assert (replaced, inserted) == (2, 34)
    assert (replaced_again, inserted_again) == (36, 0)
    assert first == second
    assert first.count("id: PATO:0001425\n") == 1
    assert first.count("id: PATO:0104031\n") == 1
    assert first.count('synonym: "olive green" RELATED []') == 1
    assert 'synonym: "olive green" EXACT []' not in first
