from __future__ import annotations

import json

from flopo2.terminology.annotate import TerminologyIndex
from flopo2.terminology.audit import registry_statistics, unresolved_corpus_statistics
from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.model import RegistryEntry


def test_registry_statistics_separates_included_excluded_and_missing_definitions(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "normalized_form\tlanguage\tdefinition\tnotes\tsource_id\tmapping_relation\t"
        "review_status\tsemantic_role\n"
        "silver\ten\tAn operational definition.\t\tlicensed\tskos:exactMatch\treviewed\tquality\n"
        "silver\ten\t\tdefinition_excluded_by_source_manifest\tprivate\tflopo:unmapped\t"
        "proposed\tquality\n"
        "silvery\ten\t\t\tlicensed\tflopo:unmapped\tproposed\tquality\n",
        encoding="utf-8",
    )

    stats = registry_statistics(registry)

    assert stats["rows"] == 3
    assert stats["distinct_normalized_form_language"] == 2
    assert stats["definition_rows"] == {
        "included": 1,
        "none": 1,
        "source_definition_excluded": 1,
    }
    assert stats["definition_unique_groups"] == {"included": 1, "none": 1}


def test_unresolved_statistics_separates_nil_low_score_and_non_equivalent(tmp_path):
    catalog = OntologyCatalog(
        {
            "PATO_red": OntologyTerm("PATO_red", "red", "PATO"),
            "PATO_green": OntologyTerm("PATO_green", "green", "PATO"),
        }
    )
    entries = [
        RegistryEntry(
            term_id="low",
            surface_form="reddish",
            normalized_form="reddish",
            language="en",
            semantic_role="quality",
            candidate_ids="PATO_red",
            candidate_labels="red",
            candidate_scores="0.5",
        ),
        RegistryEntry(
            term_id="related",
            surface_form="verdant",
            normalized_form="verdant",
            language="en",
            semantic_role="quality",
            target_id="PATO_green",
            target_label="green",
            target_namespace="PATO",
            mapping_relation="skos:relatedMatch",
            mapping_confidence=0.9,
            review_status="proposed",
        ),
        RegistryEntry(
            term_id="nil",
            surface_form="mysterious",
            normalized_form="mysterious",
            language="en",
            semantic_role="quality",
            mapping_relation="flopo:unmapped",
        ),
    ]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps(
            {"text": "reddish verdant mysterious", "language": "en", "organ": "leaf"}
        )
        + "\n",
        encoding="utf-8",
    )

    stats = unresolved_corpus_statistics(corpus, TerminologyIndex(entries, catalog))

    assert stats["longest_mentions"] == 3
    assert stats["eligible_mentions"] == 0
    assert stats["missing_mentions"] == 3
    assert stats["distinct_missing_surfaces"] == 3
    assert stats["causes"] == {
        "low_score": 1,
        "nil": 1,
        "non_equivalent_relation": 1,
    }
