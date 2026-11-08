import pytest
from flopo2.vision.modern import average_precision, trait_prompts


def test_ap_ties_are_order_independent():
    assert average_precision([1, 0], [.5, .5]) == .5
    assert average_precision([0, 1], [.5, .5]) == .5


def test_ap_unknowns_are_not_negatives():
    assert average_precision([1, None, 0], [.8, .9, .2]) == 1.


def test_ap_requires_both_classes():
    assert average_precision([1, None], [.8, .2]) is None
    assert average_precision([0, 0], [.8, .2]) is None


def test_ap_precision_recall_steps():
    assert average_precision([1, 0, 1, 0], [.9, .8, .7, .6]) == pytest.approx(5 / 6)


def test_prompts_use_actual_schema_names_and_keep_unknown():
    schema = {'groups': {g: {'colours': [{'name': n} for n in ns]} for g, ns in
        [('outline', ['heart shaped', 'unknown']), ('hairiness', ['pubescent', 'unknown'])]}}
    p = trait_prompts(schema)
    assert 'basal notch' in p['outline'][0][1]
    assert 'cannot be determined' in p['outline'][1][0]
