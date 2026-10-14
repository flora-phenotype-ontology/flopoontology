"""Saudi-flora ingest: colour readings, measurement bounds, LLM rule guardrails, vocabulary groups."""

from __future__ import annotations

from pathlib import Path

import pytest

from flopo2.ingest.colour_words import colour_value, load_colour_words
from flopo2.ingest.ncvc_annotate import _mark_approximate
from flopo2.ingest.collenette_llm import expand
from flopo2.ingest.ncvc_annotate import NormalizationRule, ground_phenotype, load_resources
from flopo2.verify.gates import UPPER_BOUND_EVIDENCE


@pytest.fixture(scope="module")
def words():
    return load_colour_words()


@pytest.mark.parametrize(
    "phrase, backbone, scope",
    [
        ("yellow", "FLOPO_0988004", "EXACT"),  # ISCC-NBS level 1, not the level-2 namesake
        ("pale yellow", "FLOPO_0988113", "EXACT"),
        ("orange-red", "FLOPO_0988015", "EXACT"),  # two hues: reddish orange
        ("bright orange-red", "FLOPO_0988015", "NARROW"),
        ("orange-yellow", "PATO_0104054", "EXACT"),  # orange yellow
        ("bluish-green", "PATO_0104020", "EXACT"),
        ("grey-green", "PATO_0104007", "EXACT"),  # grayish green
        ("creamy-white", "FLOPO_0988009", "NARROW"),
        ("silvery", "FLOPO_0988009", "RELATED"),
    ],
)
def test_colour_phrases_read_on_the_backbone(words, phrase, backbone, scope):
    found = colour_value(phrase, words)
    assert found is not None and found[:2] == (backbone, scope)


@pytest.mark.parametrize("phrase", ["hairy", "red-veined leaves", "four-angled"])
def test_non_colour_phrases_are_not_colours(words, phrase):
    assert colour_value(phrase, words) is None


@pytest.mark.parametrize(
    "text, upper",
    [
        ("stems to 1 m long", True),
        ("a shrub to 2 m", True),
        ("to 45 cm tall", True),
        ("up to 3 m", True),
        ("5 to 10 mm", False),
        ("tapering to a point", False),
    ],
)
def test_bare_to_before_a_number_is_an_upper_bound(text, upper):
    assert bool(UPPER_BOUND_EVIDENCE.search(text)) is upper


def test_compact_llm_answer_expands_to_phenotype_rows():
    record = expand(
        {
            "p": [["flower", "width", 1.2, 1.2, "cm", "1.2 cm wide", False, "", "", []]],
            "loc": [["Ad Aridah", "Ad Aridah", "village", "SA-09", "inferred"]],
            "el": [800, 800, "ft", "800 ft"],
        }
    )
    row = record["phenotypes"][0]
    assert (row["entity_en"], row["quality_en"], row["value_low"], row["unit"]) == ("flower", "width", 1.2, "cm")
    assert record["localities"][0]["region_iso_3166_2"] == "SA-09"
    assert record["elevation"]["low"] == 800


def test_value_rule_without_a_bearer_stays_unresolved():
    res = load_resources()
    rule = NormalizationRule("T1", "quality", "orange-red", "", "flopo_value", "", "PATO_0000014",
                             "FLOPO_0988001", "", "red", "test")
    res.rules = [rule, *res.rules]
    grounding = ground_phenotype(res, {"entity_en": "corolla blotch", "quality_en": "orange-red", "pato_label": ""})
    assert grounding.kind == "unresolved" and grounding.reason == "missing_or_unsupported_bearer"


def test_approximate_cue_gets_exact_offsets():
    text = "A herb; reddish flowers 1 cm wide."
    assertion = {"source_start": 8, "source_end": 23, "modality_start": None}
    _mark_approximate(assertion, "reddish", text)
    assert assertion["value_qualifier"] == "approximately"
    assert text[assertion["modality_start"] : assertion["modality_end"]] == "reddish"


def test_llm_rule_guardrails():
    from flopo2.ingest.llm_term_rules import Candidates, guardrail

    cands = Candidates()
    assert guardrail("quality", "red-veined", "PATO_0000322", "exact", cands)  # pattern, not colour
    assert guardrail("quality", "number 2-5", "PATO_0001555", "exact", cands)
    assert guardrail("quality", "widespread", "FLOPO_0985006", "synonym", cands)
    assert guardrail("bearer", "corolla base", "PO_0009059", "broader", cands)
    assert not guardrail("quality", "four-angled", "PATO_0001988", "exact", cands)


def test_organ_and_trait_groups():
    from flopo2.saudi.vocab import Vocabulary

    vocab = Vocabulary()
    assert vocab.organ_group("PO_0009032") == "flower"  # petal
    assert vocab.organ_group("PO_0030100") == "fruit"  # legume
    assert vocab.organ_group("PO_0020038") == "leaf"  # petiole
    assert vocab.trait_group("FLOPO_0988004") == "colour"
    assert vocab.trait_group("PATO_0000122") == "size"
    assert vocab.trait_group("PATO_0001891") == "shape"


def test_build_script_exists():
    assert Path("tools/build_saudi_flora.sh").exists()


def _atlas_resources():
    from flopo2.ingest.ncvc_annotate import enable_atlas_options, merge_rules

    res = load_resources()
    res.rules = merge_rules(
        res.rules,
        [],
        [Path("flopo2/ingest/flora_value_term_rules.tsv"), Path("flopo2/ingest/collenette_normalization.tsv")],
    )
    enable_atlas_options(res)
    return res


def _record(description: str, phenotypes: list[dict]) -> dict:
    return {"source": "test", "source_id": "test:page-1", "pdf_page": 1, "scientific_name": "Anisotes trisulcus",
            "family": "Acanthaceae", "description_en": description, "phenotypes": phenotypes}


def _row(entity, quality, source, pato="", alternatives=(), negated=False):
    return {"entity_en": entity, "quality_en": quality, "po_label": entity, "pato_label": pato,
            "value_low": None, "value_high": None, "unit": "", "source_en": source,
            "qualifiers": {"negated": negated, "stage": "", "frequency": "", "alternatives": list(alternatives)}}


def test_alternatives_become_qualitative_relations():
    from flopo2.ingest.ncvc_annotate import annotate_record

    text = "The leaves are petiolate, ovate to strap-shaped oblong. The flowers are axillary, red tending to orange-yellow."
    rec = _record(text, [
        _row("leaf", "ovate to strap-shaped oblong", "ovate to strap-shaped oblong", "ovate", ["oblong"]),
        _row("flower", "red tending to orange-yellow", "red tending to orange-yellow", "red", ["orange-yellow"]),
        _row("leaf", "petiolate", "leaves are petiolate"),
    ])
    segments, _ = annotate_record(rec, _atlas_resources())
    assertions = [a for s in segments for a in s["assertions"]]
    relations = {a["qualitative_value_relation"]["to_value"]: a for a in assertions if a.get("qualitative_value_relation")}
    shape = relations["PATO_0000946"]["qualitative_value_relation"]
    assert (shape["from_value"], shape["interpretation"], shape["to_text"]) == ("FLOPO_0991024", "continuum", "strap-shaped oblong")  # plane ovate
    colour = relations["PATO_0104054"]
    assert colour["pato_id"] == "PATO_0000014" and colour["qualitative_value_relation"]["from_value"] == "FLOPO_0988001"
    assert all(not a.get("phenotype_class_iri") for a in relations.values())
    petiolate = next(a for a in assertions if a["value_terms"] == ["FLOPO_0991023"])
    assert petiolate["po_id"] == "PO_0025034"  # leaf petiolate, not 'petiole present'


def test_negated_presence_is_absence_and_negated_quality_is_complement():
    from flopo2.ingest.ncvc_annotate import annotate_record

    text = "A shrub; flowers with no scent; petals absent."
    rec = _record(text, [
        _row("flower", "scented", "no scent", negated=True),
        _row("petal", "present", "petals absent", "present", negated=True),
    ])
    segments, _ = annotate_record(rec, _atlas_resources())
    scopes = {a["pato_id"]: a.get("negation_scope") for s in segments for a in s["assertions"] if a["negated"]}
    assert scopes.get("PATO_0001331") == "quality"


def test_endpoint_modifiers_are_kept():
    from flopo2.ingest.ncvc_annotate import annotate_record

    rec = _record("Leaves narrowly ovate to broadly elliptic. Fruit greenish red to purplish red.", [
        _row("leaf", "ovate", "narrowly ovate to broadly elliptic", "ovate", ["elliptic"]),
        _row("fruit", "red", "greenish red to purplish red", "red", ["purplish red"]),
    ])
    segments, _ = annotate_record(rec, _atlas_resources())
    rels = [a["qualitative_value_relation"] for s in segments for a in s["assertions"] if a.get("qualitative_value_relation")]
    shape = next(r for r in rels if r["from_value"] == "FLOPO_0991024")  # plane ovate
    assert shape["from_text"] == "narrowly ovate" and shape["from_operand"]["degree_qualifier"] == "narrowly"
    assert shape["to_text"] == "broadly elliptic" and shape["to_operand"]["degree_qualifier"] == "broadly"
    colour = next(r for r in rels if r["to_value"] == "PATO_0104311")  # purplish red
    assert colour["from_text"] == "greenish red"


def test_lists_of_three_values_become_a_chain_of_relations():
    from flopo2.ingest.ncvc_annotate import relations_from_chain

    res = _atlas_resources()
    text = "Flowers white, pink or purple."
    answer = {"values": [{"text": "white", "term": "white"}, {"text": "pink", "term": "pink"}, {"text": "purple", "term": "purple"}],
              "connectors": [{"text": ",", "interpretation": "taxon_level_alternatives"},
                             {"text": "or", "interpretation": "taxon_level_alternatives"}]}
    chain = relations_from_chain(res, answer, text, 8, 29, "PO_0009046", ["flower"])
    assert [(c["relation"]["from_text"], c["relation"]["to_text"]) for c in chain] == [("white", "pink"), ("pink", "purple")]
    assert all(c["pato_id"] == "PATO_0000014" for c in chain)
    wrong = {**answer, "values": [*answer["values"][:2], {"text": "violet", "term": "violet"}]}
    assert relations_from_chain(res, wrong, text, 8, 29, "PO_0009046", ["flower"]) == []  # not verbatim


def test_short_phrase_is_not_anchored_inside_a_later_statement():
    from flopo2.ingest.ncvc_annotate import annotate_record

    # Ecbolium gymnostachyum: the transcription lists "terminal" before "long" ("long terminal
    # spikes"); "long" must not take the one of "10.5 mm long".
    text = ("the flowers are 5–8 cm long, in long terminal spikes; the seeds are 2, 7.5–10.5 mm long "
            "and 6–8 [mm] wide.")
    rec = _record(text, [
        _row("inflorescence", "terminal", "terminal"),
        _row("inflorescence", "long", "long"),
        {**_row("seed", "length", "7.5–10.5 mm long"), "value_low": 7.5, "value_high": 10.5, "unit": "mm"},
    ])
    segments, _ = annotate_record(rec, _atlas_resources())
    long = next(a for s in segments for a in s["assertions"] if a["source_text"] == "long")
    assert text[long["source_start"] - 3 : long["source_start"]] == "in "


def test_context_sentence_does_not_split_at_a_decimal_point():
    from flopo2.saudi.build import _sentence

    text = "Leaves ovate; the seeds are 2, 7.5–10.5 mm long and 6–8 mm wide, broadly ovoid. Flowers red."
    start = text.index("6–8")
    assert _sentence(text, start, start + 3) == "the seeds are 2, 7.5–10.5 mm long and 6–8 mm wide, broadly ovoid."


@pytest.mark.parametrize(
    "quality, text, word",
    [("PATO:0000573", "in long terminal spikes", "long"), ("PATO:0000587", "tiny white flowers", "tiny"),
     ("PATO:0000574", "short-petioled", "short"), ("PATO:0000599", "leaves narrow", "narrow"),
     ("PATO:0000122", "2 cm long", "")],
)
def test_comparative_qualities_are_labelled_with_the_source_word(quality, text, word):
    from flopo2.saudi.build import descriptive_word

    assert descriptive_word(quality, text) == word


def test_privative_words_are_negations():
    from flopo2.ingest.ncvc_annotate import annotate_record

    text = "A leafless herb; spineless stems; unscented flowers; petals absent."
    rec = _record(text, [
        _row("whole plant", "leafless", "leafless"),
        _row("stem", "spineless", "spineless stems"),
        _row("flower", "unscented", "unscented flowers"),
        _row("petal", "absent", "petals absent", "absent"),
    ])
    segments, _ = annotate_record(rec, _atlas_resources())
    got = {(a["po_id"], a["pato_id"], a.get("negation_scope")) for s in segments for a in s["assertions"] if a["negated"]}
    assert ("PO_0025034", "PATO_0000467", "absence") in got  # leaf: not has_part some leaf
    assert ("PO_0009047", "PATO_0001365", "quality") in got  # stem not spiny
    assert ("PO_0009046", "PATO_0001331", "quality") in got  # flower not odorous
    assert ("PO_0009032", "PATO_0000467", "absence") in got  # "absent" read as absence, like "no petals"


@pytest.mark.parametrize(
    "text, rows, expected",
    [
        ("An erect grazed woody herb 60 cm high.", [("erect", "An erect grazed woody herb"), ("woody", "An erect grazed woody herb"),
                                                     ("herb", "An erect grazed woody herb")], ["erect", "woody herb", "merged"]),
        ("A herbaceous shrub 1 m tall.", [("herbaceous", "herbaceous"), ("shrub", "herbaceous shrub")], ["woody herb", "merged"]),
        ("A shrubby tree 5 m tall.", [("shrub", "A shrubby tree"), ("tree", "A shrubby tree")], ["tree", "merged"]),
        ("A shrub; herb layer absent.", [("shrub", "A shrub")], ["shrub"]),
    ],
)
def test_compound_habit_words_are_one_habit(text, rows, expected):
    from flopo2.ingest.ncvc_annotate import merge_compound_habits

    rec = _record(text, [_row("whole plant", q, src) for q, src in rows])
    merge_compound_habits(rec)
    assert [("merged" if p.get("merged_into") else p["quality_en"]) for p in rec["phenotypes"]] == expected
    if "woody herb" in expected:
        row = next(p for p in rec["phenotypes"] if p["quality_en"] == "woody herb")
        assert ground_phenotype(_atlas_resources(), row).value_terms == ["FLOPO_0987003"]  # suffrutescent


def test_exclusive_values_table_uses_known_terms():
    import csv

    from flopo2.saudi.build import EXCLUSIVE
    from flopo2.saudi.vocab import Vocabulary, curie

    vocab = Vocabulary()
    with EXCLUSIVE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows
    for row in rows:
        for value in (row["value_a"], row["value_b"]):
            assert vocab.label(value) != curie(value), value


def test_compound_habit_with_ocr_digit_and_transcribed_compound():
    from flopo2.ingest.ncvc_annotate import merge_compound_habits

    rec = _record("A woody herb5 tall.", [_row("whole plant", "herb", "woody herb5"), _row("whole plant", "woody", "woody herb5")])
    merge_compound_habits(rec)
    assert [p.get("merged_into") or p["quality_en"] for p in rec["phenotypes"]] == ["woody herb", "woody herb"]
    rec = _record("A woody-based perennial herbaceous subshrub 75 cm tall.",
                  [_row("whole plant", "herbaceous subshrub", "herbaceous shrub")])
    merge_compound_habits(rec)
    assert rec["phenotypes"][0]["quality_en"] == "woody herb"
