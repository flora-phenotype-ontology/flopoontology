from __future__ import annotations

import csv
import json


def test_missing_bearer_groups_separate_existing_po_from_local_extensions(tmp_path):
    from flopo2.verify.missing_bearers import group_missing_bearers

    records = [
        {
            "source": "flora-a",
            "source_id": "one.xml",
            "taxon": "Quercus alpha",
            "organ": "leaves",
            "text": "Leaves green, margins red.",
            "unresolved_spans": [
                {
                    "start": 22,
                    "end": 25,
                    "surface_form": "red",
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": "PATO_0000322",
                    "extractor": "test",
                }
            ],
        },
        {
            "source": "flora-b",
            "source_id": "two.xml",
            "taxon": "Quercus beta",
            "organ": "corolla",
            "text": "Corolla red in the throat.",
            "unresolved_spans": [
                {
                    "start": 8,
                    "end": 11,
                    "surface_form": "red",
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": "PATO_0000322",
                    "extractor": "test",
                }
            ],
        },
        {
            "source": "flora-c",
            "source_id": "three.xml",
            "taxon": "Quercus gamma",
            "organ": "seeds",
            "text": "Seeds with white hairs.",
            "unresolved_spans": [
                {
                    "start": 11,
                    "end": 16,
                    "surface_form": "white",
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": "PATO_0000323",
                    "extractor": "test",
                }
            ],
        },
        {
            "source": "flora-d",
            "source_id": "four.xml",
            "taxon": "Habenaria alpha",
            "organ": "labellum",
            "text": "Labellum white.",
            "unresolved_spans": [
                {
                    "start": 9,
                    "end": 14,
                    "surface_form": "white",
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": "PATO_0000323",
                    "extractor": "test",
                }
            ],
        },
    ]
    source = tmp_path / "records.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in records))
    output = tmp_path / "groups.tsv"

    stats = group_missing_bearers(source, output)
    with output.open(encoding="utf-8", newline="") as handle:
        rows = {row["group_key"]: row for row in csv.DictReader(handle, delimiter="\t")}

    assert stats["evidence"] == 4
    assert rows["margin"]["candidate_po_id"] == "PO_0020128"
    assert rows["margin"]["definition"]
    assert rows["margin"]["superclass_ids"]
    assert rows["margin"]["part_of_ids"]
    assert rows["margin"]["semantics_complete"] == "true"
    assert rows["trichome"]["candidate_po_id"] == "PO_0000282"
    assert rows["throat"]["disposition"] == "flopo_extension_candidate"
    assert rows["throat"]["candidate_po_id"] == ""
    assert rows["throat"]["semantics_complete"] == "false"
    assert rows["throat"]["review_status"] == "needs_definition_superclass_and_parthood_review"
    labellum = rows["heading:labellum"]
    assert labellum["curation_proposal_id"] == "PO-CAND:orchid_labellum"
    assert labellum["definition_source_ids"]
    assert labellum["definition"]
    assert labellum["superclass_ids"] == "PO_0009032"
    assert labellum["part_of_ids"] == "PO_0009059"
    assert labellum["semantics_complete"] == "true"
    assert labellum["candidate_flopo_iri"] == ""
    assert labellum["review_status"] == "ready_for_scope_and_curator_review"
