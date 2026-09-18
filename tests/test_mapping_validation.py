from __future__ import annotations

import json

from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.mapping_validation import validate_missing_surface_mappings
from flopo2.terminology.model import RegistryEntry
from flopo2.terminology.registry import write_registry


def _row_by_surface(rows):
    return {row["surface_form"]: row for row in rows}


def test_mapping_validation_covers_every_surface_and_preserves_synonym_scope(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "unresolved": {
                    "missing_surfaces": [
                        ["capitulum", 7],
                        ["flower head", 6],
                        ["head", 5],
                        ["silver", 4],
                        ["flower", 3],
                        ["unknown", 2],
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    write_registry(
        [
            RegistryEntry(
                term_id="head",
                surface_form="head",
                normalized_form="head",
                semantic_role="entity",
                source_id="test",
                target_id="PO:0000001",
                mapping_relation="skos:exactMatch",
                review_status="proposed",
            ),
            RegistryEntry(
                term_id="flower",
                surface_form="flower",
                normalized_form="flower",
                semantic_role="quality",
                source_id="test",
            ),
        ],
        registry,
    )
    catalog = OntologyCatalog(
        {
            "PO_0000001": OntologyTerm(
                "PO_0000001",
                "capitulum",
                "PO",
                synonyms=("flower head", "head"),
                synonym_scopes=(("flower head", "EXACT"), ("head", "BROAD")),
            ),
            "PO_0000002": OntologyTerm("PO_0000002", "flower", "PO"),
            "PATO_0000001": OntologyTerm("PATO_0000001", "silver", "PATO"),
            "FLOPO_0000001": OntologyTerm(
                "FLOPO_0000001",
                "silver phenotype",
                "FLOPO",
                synonyms=("silver",),
                synonym_scopes=(("silver", "EXACT"),),
            ),
        }
    )

    rows, summary = validate_missing_surface_mappings(manifest, registry, catalog)
    by_surface = _row_by_surface(rows)

    assert len(rows) == 6
    assert summary["total_surfaces"] == 6
    assert summary["total_missing_mentions"] == 27
    assert by_surface["capitulum"]["recommendation"] == "deterministic_exact_candidate"
    assert by_surface["flower head"]["recommendation"] == "deterministic_exact_candidate"
    assert by_surface["head"]["recommendation"] == "scoped_synonym_review"
    assert by_surface["head"]["scoped_relations"] == "skos:narrowMatch"
    assert "unsafe_exact_over_scoped_synonym" in by_surface["head"][
        "validation_findings"
    ]
    assert by_surface["silver"]["recommendation"] == "ambiguous_exact_candidates"
    assert "lexical_collision" in by_surface["silver"]["validation_findings"]
    assert by_surface["flower"]["recommendation"] == "exact_candidate_role_review"
    assert "semantic_role_namespace_conflict" in by_surface["flower"][
        "validation_findings"
    ]
    assert by_surface["unknown"]["recommendation"] == "no_lexical_candidate"
    assert summary["policy"]["automatic_acceptance"] is False


def test_mapping_validation_rejects_duplicate_folded_manifest_surfaces(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"unresolved": {"missing_surfaces": [["Flower-head", 2], ["flower head", 1]]}}),
        encoding="utf-8",
    )

    try:
        validate_missing_surface_mappings(manifest, tmp_path / "missing.tsv", OntologyCatalog({}))
    except ValueError as error:
        assert "duplicate normalized missing surface" in str(error)
    else:
        raise AssertionError("duplicate folded surfaces must fail closed")
