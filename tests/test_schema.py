"""Contract tests for the LinkML trait schema (via generated Pydantic models).

These lock the extraction contract both engines must satisfy: required grounding fields, the
provenance anchor, enum-constrained modifiers, and the numeric range fields.
"""

from __future__ import annotations

import pytest

models = pytest.importorskip("flopo2.schema.flopo_trait_models")


def test_minimal_valid_assertion():
    a = models.TraitAssertion(anatomical_entity="leaf", quality="red", source_text="leaves red")
    assert a.negated is False  # ifabsent default


def test_source_text_required():
    # source_text is the anti-hallucination anchor — extraction MUST provide it.
    with pytest.raises(Exception):
        models.TraitAssertion(anatomical_entity="leaf", quality="red")


def test_entity_and_quality_required():
    with pytest.raises(Exception):
        models.TraitAssertion(quality="red", source_text="x")
    with pytest.raises(Exception):
        models.TraitAssertion(anatomical_entity="leaf", source_text="x")


def test_numeric_range_and_modifier():
    a = models.TraitAssertion(
        anatomical_entity="leaf",
        quality="length",
        value_low=3.0,
        value_high=7.0,
        unit="cm",
        modifier=models.FrequencyModifier.usually,
        source_text="leaves 3-7 cm",
    )
    assert a.value_low == 3.0 and a.value_high == 7.0
    assert a.modifier == models.FrequencyModifier.usually


def test_invalid_modifier_rejected():
    with pytest.raises(Exception):
        models.TraitAssertion(
            anatomical_entity="leaf", quality="red", source_text="x", modifier="frequently"
        )
