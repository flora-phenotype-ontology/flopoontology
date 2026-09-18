"""Regression tests for negated / comparator upper bounds in the deterministic measurement parser
and for complete numeric identity in the self-consistency / ensemble vote keys.

Before this fix ``parse_measurements`` ignored the comparator and returned an *exact* scalar for
``n'atteignant pas 0,5 mm`` (0.5, 0.5), and the vote keys omitted the numeric bounds so
incompatible quantitative phenotypes voted as identical.
"""

from __future__ import annotations

from flopo2.eval.scoring import Assertion, assertion_vote_key
from flopo2.extract.measurement import parse_measurements


def _one(text: str, language: str = "fr"):
    ms = parse_measurements(text, language)
    assert len(ms) == 1, ms
    return ms[0]


def test_strict_french_atteignant_is_exclusive_upper_bound():
    m = _one("n'atteignant pas 0,5 mm de diamètre")
    assert m.value_low is None
    assert m.value_high == 0.5
    assert m.value_high_inclusive is False


def test_inclusive_french_depassant_is_inclusive_upper_bound():
    m = _one("ne dépassant pas 2 mm de longueur")
    assert m.value_low is None
    assert m.value_high == 2.0
    assert m.value_high_inclusive is True


def test_atteignant_pas_plus_de_stays_inclusive():
    m = _one("n'atteignant pas plus de 5 mm de longueur")
    assert m.value_low is None
    assert m.value_high == 5.0
    assert m.value_high_inclusive is True


def test_english_not_exceeding_is_inclusive_upper_bound():
    m = _one("not exceeding 4 mm long", language="en")
    assert m.value_low is None
    assert m.value_high == 4.0
    assert m.value_high_inclusive is True


def test_english_not_more_than_is_inclusive_upper_bound():
    m = _one("not more than 3 mm wide", language="en")
    assert m.value_low is None
    assert m.value_high == 3.0
    assert m.value_high_inclusive is True


def test_plain_value_is_exact_and_inclusive():
    m = _one("2 mm de longueur")
    assert m.value_low == 2.0
    assert m.value_high == 2.0
    assert m.value_high_inclusive is True


def test_positive_up_to_limit_remains_inclusive_upper_bound():
    m = _one("up to 6 mm long", language="en")
    assert m.value_low is None
    assert m.value_high == 6.0
    assert m.value_high_inclusive is True


def test_vote_key_separates_distinct_bounds():
    low = Assertion(po_id="PO_1", pato_id="PATO_0000122", value_high=5.0, unit="mm")
    high = Assertion(po_id="PO_1", pato_id="PATO_0000122", value_high=10.0, unit="mm")
    assert assertion_vote_key(low) != assertion_vote_key(high)


def test_vote_key_separates_inclusive_from_exclusive_bound():
    incl = Assertion(
        po_id="PO_1", pato_id="PATO_0000122", value_high=5.0, unit="mm", value_high_inclusive=True
    )
    strict = Assertion(
        po_id="PO_1", pato_id="PATO_0000122", value_high=5.0, unit="mm", value_high_inclusive=False
    )
    assert assertion_vote_key(incl) != assertion_vote_key(strict)


def test_vote_key_separates_units():
    mm = Assertion(po_id="PO_1", pato_id="PATO_0000122", value_high=5.0, unit="mm")
    cm = Assertion(po_id="PO_1", pato_id="PATO_0000122", value_high=5.0, unit="cm")
    assert assertion_vote_key(mm) != assertion_vote_key(cm)


def test_vote_key_identical_for_same_phenotype():
    a = Assertion(po_id="PO_1", pato_id="PATO_0000122", value_high=5.0, unit="mm")
    b = Assertion(po_id="PO_1", pato_id="PATO_0000122", value_high=5.0, unit="mm")
    assert assertion_vote_key(a) == assertion_vote_key(b)
