"""Tests for the evaluation harness: matching, metrics, and self-consistency."""

from __future__ import annotations

from flopo2.eval.scoring import Assertion, assertion_vote_key, flip_rate, score_segment

# Tiny PO/PATO ancestry stub for hierarchical matching.
# pink (PATO:X) is a kind of color; flower-part ⊂ flower.
ANC = {
    "PATO_pink": {"PATO_pink", "PATO_color"},
    "PATO_color": {"PATO_color"},
    "PO_petal": {"PO_petal", "PO_flower"},
    "PO_flower": {"PO_flower"},
    "PATO_red": {"PATO_red", "PATO_color"},
}


def anc(curie: str) -> set[str]:
    return ANC.get(curie, {curie})


def A(po, pato, **kw):
    return Assertion(po_id=po, pato_id=pato, **kw)


def test_exact_match_prf():
    gold = [A("PO_flower", "PATO_red", organ="flower"), A("PO_leaf", "PATO_green", organ="leaf")]
    preds = [A("PO_flower", "PATO_red", organ="flower")]  # 1 correct, 1 missed
    r = score_segment(preds, gold)
    assert r.exact.tp == 1 and r.exact.fp == 0 and r.exact.fn == 1
    assert r.exact.recall == 0.5 and r.exact.precision == 1.0


def test_hierarchical_credits_related_terms():
    gold = [A("PO_flower", "PATO_color")]
    preds = [A("PO_petal", "PATO_pink")]  # more specific in both axes
    exact = score_segment(preds, gold)  # no ancestors -> no exact match
    assert exact.exact.tp == 0
    lenient = score_segment(preds, gold, ancestors=anc)
    assert lenient.lenient.tp == 1  # petal⊂flower and pink⊂color


def test_grounding_confusion_recorded():
    # Right region (flower, via hierarchy) but wrong specific PO term -> confusion entry.
    gold = [A("PO_flower", "PATO_red")]
    preds = [A("PO_petal", "PATO_red")]
    r = score_segment(preds, gold, ancestors=anc)
    assert r.lenient.tp == 1
    assert r.grounding_confusion[("PO_flower", "PO_petal")] == 1


def test_negation_accuracy():
    gold = [A("PO_leaf", "PATO_hairy", negated=False)]
    preds = [A("PO_leaf", "PATO_hairy", negated=True)]  # polarity flip
    r = score_segment(preds, gold)
    assert r.negation_total == 1 and r.negation_correct == 0
    assert r.negation_accuracy == 0.0


def test_hallucination_rate():
    gold = [A("PO_leaf", "PATO_green")]
    preds = [
        A("PO_leaf", "PATO_green", source_text="leaves green"),       # grounded in text
        A("PO_leaf", "PATO_blue", source_text="leaves bright blue"),  # not in text -> hallucination
    ]
    r = score_segment(preds, gold, segment_text="The leaves green and smooth.")
    assert r.predictions == 2
    assert r.hallucinations == 1
    assert r.hallucination_rate == 0.5


def test_by_organ_breakdown():
    gold = [A("PO_flower", "PATO_red", organ="flower"), A("PO_leaf", "PATO_green", organ="leaf")]
    preds = [A("PO_flower", "PATO_red", organ="flower")]
    r = score_segment(preds, gold)
    assert r.by_organ["flower"].f1 == 1.0
    assert r.by_organ["leaf"].recall == 0.0


def test_flip_rate():
    run1 = [A("PO_leaf", "PATO_green"), A("PO_flower", "PATO_red")]
    run2 = [A("PO_leaf", "PATO_green")]  # dropped the flower assertion
    run3 = [A("PO_leaf", "PATO_green"), A("PO_flower", "PATO_red")]
    # 2 distinct keys; one (flower red) missing from run2 -> 1/2 unstable.
    assert flip_rate([run1, run2, run3]) == 0.5
    assert flip_rate([run1, run1, run1]) == 0.0
    assert flip_rate([run1]) == 0.0  # single run: trivially stable


def test_vote_key_canonicalizes_value_term_order():
    forward = A(
        "PO_flower",
        "PATO_color",
        value_operator="all_of",
        value_term_ids=("PATO_red", "PATO_yellow"),
    )
    reversed_ = A(
        "PO_flower",
        "PATO_color",
        value_operator="all_of",
        value_term_ids=("PATO_yellow", "PATO_red"),
    )
    assert assertion_vote_key(forward) == assertion_vote_key(reversed_)


def test_vote_key_contains_every_logical_and_numeric_facet():
    assertion = A(
        "PO_leaf",
        "PATO_length",
        negated=True,
        negation_scope="quality",
        value_operator="one_of",
        value_term_ids=("PATO_long", "PATO_short"),
        value_low=2.0,
        value_high=5.0,
        unit="mm",
        value_low_inclusive=False,
        value_high_inclusive=True,
    )
    assert assertion_vote_key(assertion) == (
        "PO_leaf",
        "PATO_length",
        True,
        "quality",
        "one_of",
        ("PATO_long", "PATO_short"),
        2.0,
        5.0,
        "mm",
        False,
        True,
    )


def test_flip_rate_uses_complete_semantic_identity():
    quality_negation = A(
        "PO_leaf",
        "PATO_length",
        negated=True,
        negation_scope="quality",
        value_high=5.0,
        value_high_inclusive=False,
        unit="mm",
    )
    absence_negation = A(
        "PO_leaf",
        "PATO_length",
        negated=True,
        negation_scope="absence",
        value_high=5.0,
        value_high_inclusive=False,
        unit="mm",
    )
    assert flip_rate([[quality_negation], [absence_negation]]) == 1.0

    larger_bound = A(
        "PO_leaf",
        "PATO_length",
        negated=True,
        negation_scope="quality",
        value_high=10.0,
        value_high_inclusive=False,
        unit="mm",
    )
    assert flip_rate([[quality_negation], [larger_bound]]) == 1.0


def test_disjunction_and_numeric_metrics():
    gold = [
        A(
            "PO_flower",
            "PATO_color",
            value_operator="one_of",
            value_term_ids=("PATO_red", "PATO_yellow"),
            value_low=2.0,
            value_high=3.0,
            unit="cm",
        )
    ]
    prediction = [
        A(
            "PO_flower",
            "PATO_color",
            value_operator="one_of",
            value_term_ids=("PATO_yellow", "PATO_red"),
            value_low=2.0,
            value_high=3.0,
            unit="cm",
        )
    ]
    report = score_segment(prediction, gold)
    assert report.disjunction_accuracy == 1.0
    assert report.value_logic_accuracy == 1.0
    assert report.numeric_accuracy == 1.0


def test_stratified_sampler_deterministic():
    from flopo2.eval.gold import stratified_sample
    from flopo2.ingest.models import TextSegment, Taxon

    segs = [
        TextSegment("src", str(i), Taxon(genus="G", species=str(i)), organ=organ,
                    text="x" * 60, char_start=0, char_end=60, language=lang)
        for i in range(20)
        for organ in ("leaves", "flowers")
        for lang in ("fr", "en")
    ]
    a = stratified_sample(segs, n=8)
    b = stratified_sample(segs, n=8)
    assert [s.source_id for s in a] == [s.source_id for s in b]  # reproducible
    assert len(a) == 8
    # Balanced across organ groups (leaf vs flower).
    groups = {s.organ for s in a}
    assert {"leaves", "flowers"} <= groups
