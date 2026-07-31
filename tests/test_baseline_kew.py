"""Kew treatment-block coverage for the deterministic full-corpus rehearsal."""

from __future__ import annotations


def test_description_segment_uses_nearest_explicit_bearer():
    from flopo2.extract.baseline import extract_segment_with_unresolved

    seg = {
        "organ": "description",
        "language": "en",
        "text": (
            "Leaves pinnate; leaflets ovate to oblong-ovate, acute and pubescent to glabrous. "
            "Inflorescences with 1-3 flowers; pedicels 3-4 cm long; flower buds globose. "
            "Sepals yellow."
        ),
    }
    out, unresolved = extract_segment_with_unresolved(seg)
    pairs = {(row["po_id"], row["pato_id"]) for row in out}

    assert ("PO_0020049", "PATO_0001891") not in pairs  # shape transition withheld
    assert ("PO_0020049", "PATO_0001320") not in pairs  # pilosity transition withheld
    assert ("PO_0030112", "PATO_0000122") in pairs  # generic pedicel length
    assert ("PO_0000056", "PATO_0001499") in pairs  # flower bud globose
    assert ("PO_0009031", "PATO_0000324") in pairs  # sepal yellow
    assert all(row["source_text"] in seg["text"] for row in out)
    assert {row["candidate_pato_id"] for row in unresolved} >= {
        "PATO_0001891",
        "PATO_0001320",
        "PATO_0000453",
    }


def test_description_segment_does_not_guess_missing_bearer():
    from flopo2.extract.baseline import extract_segment

    seg = {
        "organ": "description",
        "language": "en",
        "text": "Glabrous, red, and 3 cm long.",
    }
    assert extract_segment(seg) == []


def test_description_segment_supports_quality_before_bearer():
    from flopo2.extract.baseline import extract_segment

    seg = {
        "organ": "description",
        "language": "en",
        "text": "Glabrous leaves; pubescent stems.",
    }
    pairs = {(row["po_id"], row["pato_id"]) for row in extract_segment(seg)}
    assert ("PO_0009025", "PATO_0000453") in pairs
    assert ("PO_0009047", "PATO_0001320") in pairs


def test_explicit_nested_bearer_overrides_section_heading():
    from flopo2.extract.baseline import extract_segment

    segment = {
        "organ": "inflorescences",
        "language": "en",
        "text": "Flowers yellow; bracts pubescent; sessile.",
    }
    pairs = {(row["po_id"], row["pato_id"]) for row in extract_segment(segment)}
    assert ("PO_0009046", "PATO_0000324") in pairs
    assert ("PO_0009055", "PATO_0001320") in pairs
    assert ("PO_0009049", "PATO_0001436") in pairs  # heading fallback for terse clause


def test_leaf_blade_related_synonym_is_not_auto_grounded():
    from flopo2.extract.baseline import extract_segment

    segment = {
        "organ": "description",
        "language": "en",
        "text": "Leaf blades elliptic and 3-5 cm long.",
    }
    assert extract_segment(segment) == []


def test_description_segment_emits_one_disjunctive_class_description():
    from flopo2.extract.baseline import extract_segment

    segment = {
        "organ": "description",
        "language": "en",
        "text": "Leaves green; flowers red or yellow; stems branched.",
    }
    assertions = extract_segment(segment)
    pairs = {(row["po_id"], row["pato_id"]) for row in assertions}
    assert ("PO_0009025", "PATO_0000320") in pairs
    assert ("PO_0009047", "PATO_0000402") in pairs
    assert ("PO_0009046", "PATO_0000322") not in pairs
    assert ("PO_0009046", "PATO_0000324") not in pairs
    disjunction = next(row for row in assertions if row.get("value_operator") == "one_of")
    assert disjunction["po_id"] == "PO_0009046"
    assert disjunction["pato_id"] == "PATO_0000014"
    assert disjunction["value_terms"] == ["PATO_0000322", "PATO_0000324"]
    assert disjunction["source_text"] == "red or yellow"


def test_description_segment_skips_reversed_source_range():
    from flopo2.extract.baseline import extract_segment

    seg = {
        "organ": "description",
        "language": "en",
        "text": "Bracts 8-6 mm wide; petals 6-10 mm wide.",
    }
    out = extract_segment(seg)
    measurements = [row for row in out if row.get("extractor") == "deterministic_measurement"]
    assert len(measurements) == 1
    assert measurements[0]["po_id"] == "PO_0009032"
    assert measurements[0]["value_low"] == 6.0
    assert measurements[0]["value_high"] == 10.0


def test_baseline_does_not_silently_truncate_supported_assertions():
    from flopo2.extract.baseline import extract_segment

    seg = {
        "organ": "leaf",
        "language": "en",
        "text": "; ".join(f"{value} cm long" for value in range(1, 31)),
    }
    assert len(extract_segment(seg)) == 30
    assert len(extract_segment(seg, max_assertions=24)) == 24
