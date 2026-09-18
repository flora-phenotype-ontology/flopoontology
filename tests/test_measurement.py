from flopo2.extract.measurement import parse_measurements


def _one(text: str, language: str = "en"):
    result = parse_measurements(text, language)
    assert len(result) == 1
    assert result[0].source_text in text
    return result[0]


def test_english_postposed_measurements():
    width = _one("Flowers 1.2 cm wide.")
    assert (width.attribute_id, width.value_low, width.value_high) == (
        "PATO_0000921",
        1.2,
        1.2,
    )
    assert (width.unit_text, width.unit_id) == ("cm", "UO:0000015")

    height = _one("Herb 45 cm tall.")
    assert height.attribute_id == "PATO_0000119"
    assert height.value_low == height.value_high == 45.0

    thickness = _one("Stems 2-2.5 mm thick.")
    assert thickness.attribute_id == "PATO_0000915"
    assert (thickness.value_low, thickness.value_high) == (2.0, 2.5)


def test_french_decimal_range_and_diameter():
    diameter = _one("Fruit 2-2,5 cm de diamètre.", "fr")
    assert diameter.attribute_id == "PATO_0001334"
    assert (diameter.value_low, diameter.value_high) == (2.0, 2.5)
    assert diameter.source_text == "2-2,5 cm de diamètre"


def test_preposed_and_upper_bound_measurements():
    width = _one("Leaf width: 2 cm.")
    assert width.attribute_id == "PATO_0000921"
    assert width.value_low == width.value_high == 2.0

    length = _one("Petals up to 4 mm long.")
    assert length.attribute_id == "PATO_0000122"
    assert length.value_low is None
    assert length.value_high == 4.0


def test_non_measurement_adjectives_are_not_promoted():
    for text in (
        "A large grove beside a stream.",
        "Known from high altitude.",
        "Growing on a wide plain.",
    ):
        assert parse_measurements(text, "en") == []

    measurements = parse_measurements("A large shrub 2 m tall.", "en")
    assert [item.attribute_id for item in measurements] == ["PATO_0000119"]


def test_descending_range_is_rejected_as_ambiguous_source_error():
    assert parse_measurements("Rhizome 8-7 mm thick.", "en") == []


def test_language_prevents_english_large_becoming_width():
    measurements = parse_measurements("A large plant 2 cm tall.", "en")
    assert [item.attribute_id for item in measurements] == ["PATO_0000119"]


def test_approximate_measurement_retains_modifier():
    english = _one("Petals about 4 mm long.")
    french = _one("Pétales environ 4 mm de longueur.", "fr")
    assert english.modifier == "approximately"
    assert french.modifier == "approximately"
    assert english.modifier_text == "about"
    assert french.modifier_text == "environ"
