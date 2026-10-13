"""FLOPO flora value terms (FLOPO_0991xxx): PATO grounding, embedding, rules and rule precedence."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.compare import isomorphic

from flopo2.ingest.ncvc_annotate import NormalizationRule, load_resources, merge_rules
from flopo2.saudi.vocab import parse_obo
from flopo2.verify.gates import load_pato_attribute_terms
from tools.build_flopo_flora_value_extension import (
    OUTPUT,
    RULES,
    build_graph,
    read_spec,
    rule_rows,
)

ROOT = Path(__file__).resolve().parents[1]
OBO = "http://purl.obolibrary.org/obo/"


@pytest.fixture(scope="module")
def spec():
    return read_spec(ROOT)


@pytest.fixture(scope="module")
def pato():
    return parse_obo(ROOT / "ont/quality.obo")


def test_module_is_the_build_of_the_spec(spec, pato):
    committed = Graph().parse((ROOT / OUTPUT).as_posix())
    assert isomorphic(committed, build_graph(spec, pato))


def test_every_value_sits_directly_under_a_live_pato_class(spec, pato):
    for row in spec:
        assert row["parent"] in pato, row
        assert not pato[row["parent"]].name.startswith("obsolete"), row


def test_values_are_embedded_live_in_the_release(spec):
    release = (ROOT / "ontology/flopo.owl").read_text(encoding="utf-8")
    assert release.count("BEGIN GENERATED FLOPO FLORA VALUE TERMS") == 1
    graph = Graph().parse(ROOT / "ontology/flopo-flora-value-extension.ttl")
    for row in spec:
        cls = URIRef(OBO + row["flopo_id"].replace(":", "_"))
        assert (cls, RDF.type, OWL.Class) in graph
        assert (cls, RDFS.label, None) in graph
        assert f'rdf:about="{cls}"' in release


def test_labels_and_synonyms_are_unique_and_not_pato_names(spec, pato):
    names = {t.name.lower() for t in pato.values()}
    seen = set()
    for row in spec:
        for word in [row["label"], *filter(None, row["exact_synonyms"].split("|"))]:
            assert word.lower() not in seen, word
            seen.add(word.lower())
        assert row["label"].lower() not in names, f"PATO already has {row['label']!r}"


def test_rules_use_attribute_slim_top_level_terms(spec, pato):
    attributes = load_pato_attribute_terms(ROOT / "config/pato_lexicon.tsv")
    rules = rule_rows(spec, pato, attributes)
    assert rules and all(rule["pato_id"] in attributes for rule in rules)
    with (ROOT / RULES).open(encoding="utf-8", newline="") as handle:
        committed = list(csv.DictReader(handle, delimiter="\t"))
    assert committed == rules


def test_bare_taste_words_are_not_odour_rules(spec, pato):
    attributes = load_pato_attribute_terms(ROOT / "config/pato_lexicon.tsv")
    keys = {r["match_key"] for r in rule_rows(spec, pato, attributes)}
    assert not {"sour", "sweet", "spicy", "head", "single", "rosette", "pairs"} & keys  # 2026-10-13 review
    assert {"sour smell", "sweet scent", "spicy scent", "dense head", "borne singly"} <= keys


def test_habit_words_are_constrained_to_plant_bearers(spec, pato):
    import re

    attributes = load_pato_attribute_terms(ROOT / "config/pato_lexicon.tsv")
    tufted = next(r for r in rule_rows(spec, pato, attributes) if r["match_key"] == "tufted")
    pattern = re.compile(tufted["bearer_constraint"], re.IGNORECASE)
    assert pattern.search("whole plant") and not pattern.search("hair")


def test_retired_identifier_is_not_reused(spec):
    from tools.build_flopo_flora_value_extension import RETIRED_IDS

    assert not RETIRED_IDS.keys() & {row["flopo_id"] for row in spec}


def test_grounding_rule_overrides_an_older_hold():
    hold = NormalizationRule("Q90", "quality", "spreading", "", "hold", "", "", "", "", "no PATO term", "")
    other = NormalizationRule("Q91", "quality", "leafy", "", "hold", "", "", "", "", "no PATO term", "")
    merged = merge_rules([hold, other], [ROOT / "flopo2/ingest/collenette_normalization.tsv"])
    keys = {(r.rule_id, r.match_key) for r in merged}
    assert ("Q90", "spreading") not in keys  # superseded: FLOPO:0985006 spreading grounds it
    assert ("Q91", "leafy") in keys  # no grounding rule in that table


def test_value_terms_are_in_the_live_catalog(spec):
    res = load_resources()
    for row in spec:
        assert row["flopo_id"].replace(":", "_") in res.flopo_labels
