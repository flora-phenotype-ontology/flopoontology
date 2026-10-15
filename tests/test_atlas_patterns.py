from flopo2.ingest.ncvc_annotate import (
    alternatives_as_union,
    count_from_text,
    normalize_counts,
    split_inline_alternatives,
)
from flopo2.extract.measurement import is_supported_count


def _row(entity, quality, low=None, high=None, unit=""):
    return {"entity_en": entity, "quality_en": quality, "value_low": low, "value_high": high, "unit": unit,
            "source_en": "", "qualifiers": {}}


def test_counts_name_the_counted_part():
    rec = {"phenotypes": [
        _row("seed", "count per fruit", 1, 1),
        _row("inflorescence", "number of flowers", 4, 5, "flowers"),
        _row("fruit", "has number of seed", 1, 1, "seed"),
        _row("fruit locule", "number (three-celled)", 3, 3, "locules"),
        _row("leaflet", "amount", 11, 15, "pairs"),
        _row("leaf", "length", 2, 3, "cm"),
    ]}
    normalize_counts(rec)
    seen = [(p["entity_en"], p["quality_en"], p["unit"], p.get("count_container", "")) for p in rec["phenotypes"]]
    assert seen[:4] == [
        ("seed", "amount", "count", ""),
        ("flower", "amount", "count", "inflorescence"),
        ("seed", "amount", "count", "fruit"),
        ("fruit locule", "amount", "count", ""),
    ]
    assert seen[4][1:3] == ("amount", "pairs")  # pairs are not counts of the parts
    assert seen[5][1:3] == ("length", "cm")


def test_count_phrases_and_unit():
    assert count_from_text("four petals") == (4.0, 4.0, "petal")
    assert count_from_text("containing 2 to 3 seeds") == (2.0, 3.0, "seed")
    assert count_from_text("a single seed") == (1.0, 1.0, "seed")
    assert count_from_text("five-parted") is None
    assert is_supported_count("count", "PATO_0000070")
    assert not is_supported_count("count", "PATO_0000122")


def test_inline_alternatives_are_split():
    rec = {"phenotypes": [_row("whole plant", "shrub or small tree"), _row("fruit", "ovate to subglobose"),
                          _row("leaf", "linear, ovate or lanceolate"), _row("leaf", "dark green")]}
    split_inline_alternatives(rec)
    assert [(p["quality_en"], p["qualifiers"].get("alternatives")) for p in rec["phenotypes"]] == [
        ("shrub", ["small tree"]), ("ovate", ["subglobose"]), ("linear", ["ovate", "lanceolate"]), ("dark green", None)]


def _relation(interpretation, connector, a, b, pato="PATO_0000052"):
    return {"pato_id": pato, "relation": {"interpretation": interpretation, "connector_text": connector,
                                          "from_value": a, "to_value": b, "from_start": 0, "to_end": 10}}


def test_only_or_alternatives_become_unions():
    union = alternatives_as_union(_relation("taxon_level_alternatives", " or ", "A", "B"), [])
    assert union["values"] == ["A", "B"]
    chain = alternatives_as_union(_relation("taxon_level_alternatives", ", ", "A", "B"),
                                  [_relation("taxon_level_alternatives", " or ", "B", "C")])
    assert chain["values"] == ["A", "B", "C"]
    assert alternatives_as_union(_relation("taxon_level_alternatives", " and ", "A", "B"), []) is None
    assert alternatives_as_union(_relation("continuum", " to ", "A", "B"), []) is None
    assert alternatives_as_union(_relation("taxon_level_alternatives", " or ", "A", "B"),
                                 [_relation("taxon_level_alternatives", " or ", "B", "C", "PATO_0000014")]) is None
