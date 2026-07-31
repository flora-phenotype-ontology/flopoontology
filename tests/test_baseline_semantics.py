"""Semantic guards for deterministic PATO cue grounding.

These tests intentionally go beyond identifier/schema validity: every identifier can exist while
still denoting the wrong quality (for example PATO:0001234 is ``distal to``, not ``obtuse``).
"""

from __future__ import annotations

from flopo2.extract.baseline import (
    QUALITY_CUES,
    extract_segment,
    extract_segment_with_unresolved,
)


def _pato_ids(text: str) -> list[str]:
    return [
        row["pato_id"]
        for row in extract_segment({"organ": "leaves", "language": "en", "text": text})
    ]


def test_corrected_obtuse_coriaceous_and_spherical_cues():
    ids = _pato_ids(
        "Leaves obtuse and coriaceous; others subglobose; others globular; "
        "still others spherical and leathery."
    )
    assert "PATO_0001935" in ids  # obtuse shape, never PATO:0001234 distal-to
    assert ids.count("PATO_0104032") == 2  # coriaceous/leathery
    assert "PATO_0005014" in ids  # subspherical
    assert ids.count("PATO_0001499") == 2  # globular/spherical


def test_unambiguous_ovate_and_elliptic_are_retained():
    ids = _pato_ids("Leaves ovate; other leaves elliptic.")
    assert ids == ["PATO_0000947", "PATO_0001891"]


def test_conflicting_or_contextual_terms_are_not_auto_promoted():
    ids = _pato_ids(
        "Leaves oval, ovoid, acute, caducous, persistent, brownish, blackish, and simple; "
        "shoots simple or branched."
    )
    assert ids == []


def test_french_gender_and_number_variants_are_supported():
    ids = _pato_ids(
        "Feuilles lancéolées; apex acuminées; bases atténuées; surfaces côtelées; "
        "rameaux ramifiés; tiges dressées."
    )
    assert ids == [
        "PATO_0001877",
        "PATO_0002228",
        "PATO_0001982",
        "PATO_0002358",
        "PATO_0000402",
        "PATO_0000622",
    ]


def test_known_wrong_pato_ids_cannot_reenter_cue_table():
    ids = {pato_id for pato_id, _pattern in QUALITY_CUES}
    assert ids.isdisjoint(
        {
            "PATO_0001234",  # distal to
            "PATO_0001548",  # quality of a liquid
            "PATO_0001731",  # deciduous plant/foliage
            "PATO_0001732",  # plant that sheds no body parts
        }
    )


def _extract(text: str, organ: str = "leaves", language: str = "en"):
    return extract_segment_with_unresolved(
        {"organ": organ, "language": language, "text": text}
    )


def test_negated_quality_cues_are_withheld_with_audit_evidence():
    for text, language in (
        ("Leaves not white.", "en"),
        ("Leaves never tomentose.", "en"),
        ("Feuilles non ramifiées.", "fr"),
    ):
        assertions, unresolved = _extract(text, language=language)
        assert assertions == []
        assert unresolved
        assert {row["reason"] for row in unresolved} == {"negated_context"}


def test_compounds_transitions_and_unmapped_alternatives_are_not_atomized():
    for text in (
        "Leaves linear-oblong.",
        "Leaves elliptic to broadly ovate.",
        "Leaves elliptic or oval.",
        "Leaves yellow to orange.",
        "Leaves pubescent to glabrous.",
        "Leaves white and black.",
        "Leaves red brown.",
        "Leaves brown grey.",
        "Leaves elliptic oblong.",
    ):
        assertions, unresolved = _extract(text)
        assert assertions == []
        assert unresolved


def test_independent_qualities_and_different_bearers_remain_atomic():
    assertions, unresolved = _extract("Leaves glabrous and smooth.")
    assert unresolved == []
    assert {row["pato_id"] for row in assertions} == {"PATO_0000453", "PATO_0000701"}

    assertions, unresolved = _extract(
        "Petals red and sepals yellow.", organ="description"
    )
    assert unresolved == []
    assert {(row["po_id"], row["pato_id"]) for row in assertions} == {
        ("PO_0009032", "PATO_0000322"),
        ("PO_0009031", "PATO_0000324"),
    }


def test_same_bearer_alternatives_become_one_of_attribute_descriptions():
    cases = (
        ("Flowers red or green.", "flowers", "PATO_0000014", ["PATO_0000322", "PATO_0000320"]),
        ("Leaves elliptic or oblong.", "leaves", "PATO_0000052", ["PATO_0000947", "PATO_0000946"]),
        ("Leaves glabrous or pubescent.", "leaves", "PATO_0000066", ["PATO_0000453", "PATO_0001320"]),
    )
    for text, organ, attribute, values in cases:
        assertions, unresolved = _extract(text, organ=organ)
        assert unresolved == []
        assert len(assertions) == 1
        assert assertions[0]["pato_id"] == attribute
        assert assertions[0]["value_operator"] == "one_of"
        assert assertions[0]["value_terms"] == values


def test_degree_idiom_is_not_misread_as_a_logical_disjunction():
    from flopo2.extract.baseline import extract_segment_with_unresolved

    for text, language in (
        ("Calyx ovate, more or less obtuse.", "en"),
        ("Calice elliptique, plus ou moins obtus.", "fr"),
    ):
        assertions, unresolved = extract_segment_with_unresolved(
            {"organ": "calyx", "language": language, "text": text}
        )
        assert not any(row.get("value_operator") == "one_of" for row in assertions)
        assert not any(row["reason"] == "explicit_disjunction" for row in unresolved)


def test_degree_idiom_does_not_hide_a_later_real_disjunction():
    for text, language in (
        ("Calyx more or less linear or lanceolate.", "en"),
        ("Calice plus ou moins linéaire ou lancéolé.", "fr"),
    ):
        assertions, unresolved = _extract(text, organ="calyx", language=language)
        assert unresolved == []
        assert len(assertions) == 1
        assert assertions[0]["pato_id"] == "PATO_0000052"
        assert assertions[0]["value_operator"] == "one_of"
        assert assertions[0]["value_terms"] == ["PATO_0001199", "PATO_0001877"]
        assert assertions[0]["value_qualifier"] == "approximately"


def test_disjunction_recovery_does_not_discard_unmapped_or_staged_components():
    for text in (
        "Young leaves red or green.",
        "Leaves red or green or purple.",
        "Leaves red-orange or green.",
    ):
        assertions, unresolved = _extract(text)
        assert assertions == []
        assert unresolved


def test_nested_colour_bearers_are_scoped_or_withheld():
    assertions, unresolved = _extract(
        "Seed red, hilum black; leaves with brown hairs; petals white, fringed yellow.",
        organ="description",
    )
    pairs = {(row["po_id"], row["pato_id"]) for row in assertions}
    assert ("PO_0009010", "PATO_0000322") in pairs
    assert ("PO_0020063", "PATO_0000317") in pairs
    assert ("PO_0000282", "PATO_0000952") in pairs
    assert ("PO_0009032", "PATO_0000323") in pairs
    assert ("PO_0009032", "PATO_0000324") not in pairs
    assert any(row["candidate_pato_id"] == "PATO_0000324" for row in unresolved)

    assertions, unresolved = _extract("Leaves with hairs pubescent.", organ="description")
    assert assertions == []
    assert unresolved[0]["reason"] == "missing_or_unsupported_bearer"


def test_colour_pattern_subregions_are_not_inherited_by_parent_organ():
    assertions, unresolved = _extract(
        "Sepals white with a green spot.", organ="description"
    )
    assert {(row["po_id"], row["pato_id"]) for row in assertions} == {
        ("PO_0009031", "PATO_0000323")
    }
    assert any(row["candidate_pato_id"] == "PATO_0000320" for row in unresolved)


def test_frequency_value_degree_and_epistemic_contexts_are_structured():
    cases = (
        ("Leaves usually pubescent.", "frequency_qualifier", "usually", "usually"),
        ("Leaves often glabrous.", "frequency_qualifier", "often", "often"),
        ("Leaves nearly globose.", "value_qualifier", "nearly", "nearly"),
        ("Leaves very smooth.", "degree_qualifier", "very", "very"),
        ("Leaves probably green.", "epistemic_modality", "probable", "probably"),
    )
    for text, field, value, cue in cases:
        assertions, unresolved = _extract(text)
        assert unresolved == []
        assert len(assertions) == 1
        assert assertions[0][field] == value
        assert assertions[0]["modality_text"] == cue
        assert assertions[0]["source_text"].startswith(cue)

    assertions, unresolved = _extract(
        "Feuilles le plus souvent vertes.", language="fr"
    )
    assert unresolved == []
    assert assertions[0]["frequency_qualifier"] == "usually"
    assert assertions[0]["modality_text"] == "le plus souvent"

    assertions, unresolved = _extract(
        "Feuilles presque toujours vertes.", language="fr"
    )
    assert unresolved == []
    assert assertions[0]["frequency_qualifier"] == "usually"
    assert "value_qualifier" not in assertions[0]


def test_developmental_stage_contexts_remain_withheld():
    for text in (
        "Young leaves pubescent.",
        "Mature leaves glabrous.",
        "Leaves glabrous when dry.",
        "Old stems ridged.",
        "The youngest branches are yellow.",
        "Leaves later becoming glabrous.",
        "Jeunes rameaux rouge brun, glabres.",
    ):
        assertions, unresolved = _extract(text)
        assert assertions == []
        assert unresolved


def test_named_and_calendar_seasons_are_attached_to_trait_expressions():
    assertions, unresolved = _extract("Leaves usually green in summer.")
    assert unresolved == []
    assert len(assertions) == 1
    assertion = assertions[0]
    assert assertion["source_text"] == "usually green in summer"
    assert assertion["frequency_qualifier"] == "usually"
    assert assertion["season_operator"] == "atomic"
    assert assertion["season_contexts"] == [
        {
            "season_term": "FLOPOANN:summer_season",
            "season_text": "summer",
            "start": 24,
            "end": 30,
            "temporal_relation": "present_during",
        }
    ]

    assertions, unresolved = _extract("Petals red from May to August.", organ="petals")
    assert unresolved == []
    season = assertions[0]["season_contexts"][0]
    assert (season["season_text"], season["start_month"], season["end_month"]) == (
        "May to August",
        5,
        8,
    )

    assertions, unresolved = _extract("Leaves green in spring or summer.")
    assert unresolved == []
    assert assertions[0]["season_operator"] == "one_of"
    assert [row["season_text"] for row in assertions[0]["season_contexts"]] == [
        "spring",
        "summer",
    ]

    assertions, unresolved = _extract(
        "Feuilles généralement vertes pendant la saison sèche.", language="fr"
    )
    assert unresolved == []
    assert assertions[0]["frequency_qualifier"] == "usually"
    assert assertions[0]["season_contexts"][0]["season_term"] == "FLOPOANN:dry_season"

    assertions, unresolved = _extract(
        "La feuille a été observée blanche.", language="fr"
    )
    assert unresolved == []
    assert assertions[0]["season_contexts"] == []


def test_safe_explicit_bearers_are_supported():
    assertions, unresolved = _extract(
        "Seed coat brown; perianth yellow; bark smooth; rhizome 4 cm long.",
        organ="description",
    )
    assert unresolved == []
    assert {(row["po_id"], row["pato_id"]) for row in assertions} == {
        ("PO_0009088", "PATO_0000952"),
        ("PO_0009058", "PATO_0000324"),
        ("PO_0004518", "PATO_0000701"),
        ("PO_0004542", "PATO_0000122"),
    }
