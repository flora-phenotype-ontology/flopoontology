from __future__ import annotations

import json

from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.catalog_recovery import compare_catalog_coverage
from flopo2.terminology.model import RegistryEntry
from flopo2.terminology.registry import write_registry


def test_catalog_recovery_holds_baseline_spans_fixed(tmp_path):
    catalog = OntologyCatalog(
        {
            "PO_0000003": OntologyTerm("PO_0000003", "whole plant", "PO"),
            "FLOPO_0900034": OntologyTerm(
                "FLOPO_0900034",
                "whole plant shrub",
                "FLOPO",
                synonyms=("shrub",),
                synonym_scopes=(("shrub", "EXACT"),),
            ),
        }
    )
    registry = tmp_path / "registry.tsv"
    write_registry(
        [
            RegistryEntry(
                term_id="BTERM:shrub",
                surface_form="shrub",
                normalized_form="shrub",
                language="en",
                semantic_role="entity",
                candidate_ids="PO_0000003",
                candidate_labels="whole plant",
                candidate_scores="0.5",
                mapping_relation="flopo:unmapped",
                review_status="proposed",
            )
        ],
        registry,
    )
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps({"text": "shrub", "language": "en", "organ": "whole plant"}) + "\n",
        encoding="utf-8",
    )

    result = compare_catalog_coverage(corpus, registry, catalog)

    assert result["baseline"]["eligible_mentions"] == 0
    assert result["expanded"]["eligible_mentions"] == 1
    assert result["fixed_baseline_span_recovered_mentions"] == 1
    assert result["recovered_surfaces"] == [("shrub", 1)]
    assert result["recovered_targets"] == [("FLOPO_0900034", 1)]
