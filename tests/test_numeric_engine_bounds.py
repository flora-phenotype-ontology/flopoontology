"""Regression tests for the three shared-code numeric defects.

1. ``parse_measurements`` must recognize negated/comparator upper bounds (French ``atteindre`` /
   ``dépasser`` / ``excéder`` negation, English ``not exceeding`` / ``no more than`` / ``up to`` /
   ``at most`` / ``maximum`` families) as upper bounds (``value_low is None``) with the correct
   ``xsd`` inclusivity, instead of collapsing them to an exact scalar.
2. ``engine._repair_measurement`` must never *downgrade* a recognized upper bound: a matching exact
   or range parse may not turn ``< X`` / ``<= X`` into ``= X``.
3. ``ensemble._key`` must be a complete semantic identity so numerically- or logically-incompatible
   phenotypes never vote as the same assertion.
"""

from __future__ import annotations

from flopo2.eval.scoring import Assertion
from flopo2.extract.engine import _repair_measurement
from flopo2.extract.ensemble import _key
from flopo2.extract.measurement import Measurement, parse_measurements


# --------------------------------------------------------------------------------------------------
# DEFECT 1 — deterministic upper-bound recognition and inclusivity
# --------------------------------------------------------------------------------------------------


def _one(text: str, language: str) -> Measurement:
    result = parse_measurements(text, language)
    assert len(result) == 1, result
    assert result[0].source_text in text
    return result[0]


def _tuple(text: str, language: str) -> tuple:
    m = _one(text, language)
    return (m.value_low, m.value_high, m.unit_text, m.value_high_inclusive)


def test_strict_atteignant_negation_is_exclusive_upper_bound():
    m = _one("n'atteignant pas 0,5 mm de diamètre", "fr")
    assert (m.value_low, m.value_high, m.unit_text) == (None, 0.5, "mm")
    assert m.value_high_inclusive is False
    assert m.value_low_inclusive is True
    assert m.attribute_id == "PATO_0001334"


def test_inclusive_upper_bound_comparators_yield_maxinclusive():
    assert _tuple("ne dépassant pas 2 mm de long", "fr") == (None, 2.0, "mm", True)
    assert _tuple("ne dépasse pas 1,5 mm de long", "fr") == (None, 1.5, "mm", True)
    assert _tuple("not exceeding 4 mm long", "en") == (None, 4.0, "mm", True)
    assert _tuple("not more than 4 mm long", "en") == (None, 4.0, "mm", True)
    assert _tuple("no more than 4 mm long", "en") == (None, 4.0, "mm", True)


def test_plus_de_flips_atteindre_negation_back_to_inclusive():
    # "n'atteignant pas plus de 5 mm" means "not reaching more than 5 mm" == <= 5 mm (inclusive).
    assert _tuple("n'atteignant pas plus de 5 mm de long", "fr") == (None, 5.0, "mm", True)


def test_additional_inclusive_comparators_are_upper_bounds():
    for text, language in (
        ("au plus 5 mm long", "fr"),
        ("at most 5 mm long", "en"),
        ("not longer than 4 mm long", "en"),
        ("not surpassing 4 mm long", "en"),
        ("maximum 5 mm long", "en"),
        ("max. 5 mm long", "en"),
        ("n'excédant pas 3 mm de long", "fr"),
        ("ne dépassent pas 2 mm de long", "fr"),
    ):
        m = _one(text, language)
        assert m.value_low is None, (text, m)
        assert m.value_high_inclusive is True, (text, m)


def test_existing_behaviour_is_preserved():
    # ``up to`` stays an inclusive upper bound.
    assert _tuple("up to 5 mm long", "en") == (None, 5.0, "mm", True)
    # A plain ascending range keeps both endpoints, both inclusive.
    rng = _one("3-7 cm long", "en")
    assert (rng.value_low, rng.value_high) == (3.0, 7.0)
    assert rng.value_low_inclusive is True and rng.value_high_inclusive is True
    # A bare value stays an exact (equal-endpoint) inclusive measurement.
    exact = _one("5 mm long", "en")
    assert exact.value_low == exact.value_high == 5.0
    assert exact.value_high_inclusive is True


def test_descending_range_is_still_dropped():
    assert parse_measurements("Rhizome 8-7 mm thick.", "en") == []


# --------------------------------------------------------------------------------------------------
# DEFECT 2 — repair must not downgrade a supported upper bound
# --------------------------------------------------------------------------------------------------


def _upper_bound_assertion(**extra) -> Assertion:
    base = dict(
        po_id="PO_0009073",
        pato_id="PATO_0000122",
        value_low=None,
        value_high=0.5,
        value_high_inclusive=False,
        unit="mm",
        source_text="n'atteignant pas 0,5 mm de long",
    )
    base.update(extra)
    return Assertion(**base)


def _length_measurement(**extra) -> Measurement:
    base = dict(
        start=0,
        end=0,
        attribute_id="PATO_0000122",
        value_low=0.5,
        value_high=0.5,
        unit_id="UO:0000016",
        unit_text="mm",
        source_text="0,5 mm de long",
        cue="de long",
    )
    base.update(extra)
    return Measurement(**base)


def test_repair_keeps_upper_bound_when_support_is_also_upper_bound():
    """The exclusive upper bound survives repair and is not turned exact."""
    support = _length_measurement(
        value_low=None,
        value_high=0.5,
        value_high_inclusive=False,
        source_text="n'atteignant pas 0,5 mm de long",
    )
    repaired = _repair_measurement(_upper_bound_assertion(), [support])
    assert repaired.value_low is None
    assert repaired.value_high == 0.5
    assert repaired.value_high_inclusive is False


def test_repair_does_not_downgrade_upper_bound_to_exact_scalar():
    """A stray exact-scalar parse over the same span must not collapse ``< 0.5`` into ``= 0.5``."""
    support = _length_measurement(value_low=0.5, value_high=0.5)  # exact, both endpoints equal
    repaired = _repair_measurement(_upper_bound_assertion(), [support])
    assert repaired.value_low is None
    assert repaired.value_high == 0.5
    assert repaired.value_high_inclusive is False


def test_repair_does_not_downgrade_upper_bound_to_range():
    """A range parse over the same span must not turn an upper bound into a two-sided range."""
    support = _length_measurement(value_low=2.0, value_high=7.0)
    repaired = _repair_measurement(_upper_bound_assertion(), [support])
    assert repaired.value_low is None
    assert repaired.value_high == 0.5


def test_repair_still_upgrades_a_model_scalar_to_a_supported_upper_bound():
    """The primary repair path is intact: a copied exact scalar is fixed to the parsed upper bound."""
    assertion = Assertion(
        po_id="PO_0009073",
        pato_id="PATO_0000122",
        value_low=5.0,
        value_high=5.0,
        unit="mm",
        source_text="up to 5 mm long",
    )
    support = parse_measurements("up to 5 mm long", "en")[0]
    repaired = _repair_measurement(assertion, [support])
    assert repaired.value_low is None
    assert repaired.value_high == 5.0
    assert repaired.value_high_inclusive is True


# --------------------------------------------------------------------------------------------------
# DEFECT 3 — complete semantic vote key
# --------------------------------------------------------------------------------------------------


def _numeric(**extra) -> Assertion:
    base = dict(po_id="PO_0009073", pato_id="PATO_0000122", value_high=5.0, unit="mm")
    base.update(extra)
    return Assertion(**base)


def test_vote_key_separates_distinct_upper_bounds():
    assert _key(_numeric(value_high=5.0)) != _key(_numeric(value_high=10.0))


def test_vote_key_separates_inclusive_from_strict_bound():
    assert _key(_numeric(value_high_inclusive=True)) != _key(_numeric(value_high_inclusive=False))


def test_vote_key_identical_categorical_assertions_collapse():
    a = Assertion(po_id="PO_0009025", pato_id="PATO_0000320", value_operator="atomic",
                  value_term_ids=("PATO_0000320",))
    b = Assertion(po_id="PO_0009025", pato_id="PATO_0000320", value_operator="atomic",
                  value_term_ids=("PATO_0000320",))
    assert _key(a) == _key(b)
    assert hash(_key(a)) == hash(_key(b))  # hashable and stable


def test_vote_key_separates_units_and_negation_scope():
    assert _key(_numeric(unit="mm")) != _key(_numeric(unit="cm"))
    assert _key(_numeric(negated=True, negation_scope="quality")) != _key(
        _numeric(negated=True, negation_scope="absence")
    )


def test_vote_key_one_of_value_order_is_irrelevant():
    forward = Assertion(po_id="PO_1", pato_id="PATO_0000014", value_operator="one_of",
                        value_term_ids=("PATO_0000320", "PATO_0000322"))
    reversed_ = Assertion(po_id="PO_1", pato_id="PATO_0000014", value_operator="one_of",
                          value_term_ids=("PATO_0000322", "PATO_0000320"))
    assert _key(forward) == _key(reversed_)
