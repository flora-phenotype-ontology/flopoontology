"""Tests for multi-flora ingestion, annotation, Spanish/French gate cues, and FLOPO candidate staging."""

from __future__ import annotations

import json
from pathlib import Path

from flopo2.ingest.external import FLORA_SOURCES
from flopo2.ingest.flora_annotate import extractor_name, run as run_flora_annotate
from flopo2.ingest.flora_candidates import extract_for_source, suggest_pato_parent
from flopo2.ingest.flora_llm import build_prompt
from flopo2.saudi.build import SOURCES
from flopo2.verify.gates import NEGATION_EVIDENCE, UPPER_BOUND_EVIDENCE


def test_all_external_floras_are_registered_in_atlas_sources():
    assert {"ncvc", "collenette"}.issubset(SOURCES)
    for key in FLORA_SOURCES:
        assert key in SOURCES, f"{key} missing from flopo2.saudi.build.SOURCES"


def test_multilingual_prompt_and_spanish_french_gate_cues():
    fr_prompt = build_prompt({"source": "fdac", "language": "fr", "taxon": "Coffea", "text": "Feuilles glabres."})
    assert "French" in fr_prompt and "verbatim" in fr_prompt
    en_prompt = build_prompt({"source": "eflora-fna", "language": "en", "taxon": "Quercus", "text": "Leaves glabrous."})
    assert "French" not in en_prompt

    assert NEGATION_EVIDENCE.search("hojas sin pecíolo")
    assert NEGATION_EVIDENCE.search("pétalos ausentes")
    assert NEGATION_EVIDENCE.search("feuilles sans stipules")
    assert UPPER_BOUND_EVIDENCE.search("arbusto hasta 2 m de alto")
    assert UPPER_BOUND_EVIDENCE.search("arbrisseau jusqu'à 3 m")


def test_flora_annotate_and_candidates_end_to_end(tmp_path: Path):
    raw_path = tmp_path / "test-qwen.jsonl"
    derived_dir = tmp_path / "derived"
    cand_dir = tmp_path / "candidates"

    sample_row = {
        "source": "powo-fiq",
        "source_id": "powo-fiq:1:1",
        "taxon": "Quercus infectoria",
        "family": "Fagaceae",
        "language": "en",
        "segment_text": (
            "A deciduous shrub or small tree up to 4 m tall; leaves petiolate, ovate, "
            "coriaceous, glaucous beneath; acorns mucronulate."
        ),
        "phenotypes": [
            {
                "entity_en": "whole plant",
                "quality_en": "deciduous",
                "value_low": None,
                "value_high": None,
                "unit": "",
                "source_en": "deciduous shrub",
                "qualifiers": {"negated": False, "stage": "", "frequency": "", "alternatives": []},
            },
            {
                "entity_en": "whole plant",
                "quality_en": "height",
                "value_low": None,
                "value_high": 4.0,
                "unit": "m",
                "source_en": "up to 4 m tall",
                "qualifiers": {"negated": False, "stage": "", "frequency": "", "alternatives": []},
            },
            {
                "entity_en": "leaf",
                "quality_en": "petiolate",
                "value_low": None,
                "value_high": None,
                "unit": "",
                "source_en": "leaves petiolate",
                "qualifiers": {"negated": False, "stage": "", "frequency": "", "alternatives": []},
            },
            {
                "entity_en": "leaf",
                "quality_en": "super-verrucose-testword",
                "value_low": None,
                "value_high": None,
                "unit": "",
                "source_en": "coriaceous",
                "qualifiers": {"negated": False, "stage": "", "frequency": "", "alternatives": []},
            },
        ],
    }
    raw_path.write_text(json.dumps(sample_row) + "\n", encoding="utf-8")

    summary = run_flora_annotate("powo-fiq", raw_path=raw_path, out_dir=derived_dir)
    assert summary["records"] == 1
    assert summary["assertions"] >= 2
    assert extractor_name("powo-fiq") == "qwen3.8-27b_powo_fiq_transcription"

    cand = extract_for_source("powo-fiq", derived_dir=derived_dir, out_dir=cand_dir)
    assert cand["value_term_candidates"] >= 1
    assert (cand_dir / "value_term_candidates.tsv").exists()
    assert (cand_dir / "bearer_candidates.tsv").exists()
    assert (cand_dir / "novel_po_pato_combinations.tsv").exists()
    assert (cand_dir / "CANDIDATES.md").exists()
    assert suggest_pato_parent("tomentulose")[0] == "PATO:0000066"
    assert suggest_pato_parent("subsessile")[0] == "PATO:0001435"
