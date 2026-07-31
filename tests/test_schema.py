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

    approximate = models.TraitAssertion(
        anatomical_entity="leaf",
        quality="length",
        value_high=4.0,
        unit="mm",
        modifier=models.FrequencyModifier.approximately,
        source_text="about 4 mm long",
    )
    assert approximate.modifier == "approximately"


def test_invalid_modifier_rejected():
    with pytest.raises(Exception):
        models.TraitAssertion(
            anatomical_entity="leaf", quality="red", source_text="x", modifier="frequently"
        )


def test_terminology_mentions_and_disjunctive_values():
    mention = models.TermMention(
        mention_id="m1",
        start=0,
        end=19,
        surface_form="greenish or pinkish",
        normalized_form="greenish or pinkish",
        logical_operator=models.ValueOperator.one_of,
        component_ids=["FLOPO_1", "FLOPO_2"],
        candidates=[
            models.TermCandidate(
                target_id="FLOPO_3",
                label="greenish or pinkish",
                namespace="FLOPO",
                score=1.0,
            )
        ],
    )
    extraction = models.TraitExtraction(term_mentions=[mention])
    assertion = models.TraitAssertion(
        anatomical_entity="PO:flower",
        quality="PATO:color",
        value_operator=models.ValueOperator.one_of,
        value_terms=["FLOPO:1", "FLOPO:2"],
        source_text="greenish or pinkish flowers",
    )
    assert extraction.term_mentions[0].component_ids == ["FLOPO_1", "FLOPO_2"]
    assert assertion.value_operator == "one_of"


def test_unresolved_trait_span_is_first_class_schema_data():
    unresolved = models.UnresolvedTraitSpan(
        start=7,
        end=12,
        surface_form="green",
        reason="unsupported_composition",
        candidate_pato_id="PATO_0000320",
        extractor="deterministic_baseline",
    )
    extraction = models.TraitExtraction(unresolved_spans=[unresolved])
    assert extraction.unresolved_spans[0].reason == "unsupported_composition"


def test_source_segment_index_is_first_class_provenance():
    extraction = models.TraitExtraction(source_segment_index=12)
    assert extraction.source_segment_index == 12


def test_materialized_annotation_uses_a_distinct_fac_class_iri():
    class_iri = "https://w3id.org/flopo/annotation-class/FAC_0123456789abcdef0123456789abcdef"
    assertion = models.TraitAssertion(
        phenotype_class_iri=class_iri,
        anatomical_entity="PO_0025034",
        quality="PATO_0000320",
        source_text="leaves green",
    )
    extraction = models.TraitExtraction(
        annotation_extension_iri="https://w3id.org/flopo/annotation-extension",
        assertions=[assertion],
    )
    assert extraction.assertions[0].phenotype_class_iri == class_iri
    assert "FLOPO_" not in class_iri
