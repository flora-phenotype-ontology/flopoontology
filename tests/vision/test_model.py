import json

import numpy as np
import pytest
import torch

from flopo2.vision.logic import Expr, probability
from flopo2.vision.model import PrimitiveHead, localized_scene, rank_profiles, trait_query, ungrounded_atoms, weak_loss
from flopo2.vision.train import fit, load_anchors, load_events, sha


@pytest.fixture
def vocabulary():
    return {'organs': [{'name': 'leaf', 'iri': 'leaf'}, {'name': 'petal', 'iri': 'petal'}],
            'colours': [{'name': 'green', 'iri': 'green'}, {'name': 'yellow', 'iri': 'yellow'}, {'name': 'unknown', 'iri': ''}]}


def test_joint_choices_preserve_organ_colour_dependence(vocabulary):
    scene = localized_scene(vocabulary, ['a'], {'a': True}, {})
    # Either a green leaf OR a yellow petal, never a yellow leaf.
    ps = {'a.joint': [.5, 0, 0, 0, .5, 0]}
    assert probability(scene.ground(trait_query('leaf', ['yellow']), 'plant'), ps) == 0
    assert probability(scene.ground(trait_query('petal', ['yellow']), 'plant'), ps) == .5
    assert scene.ground(Expr('atom', 'yellow'), 'a') is False
    assert scene.ground(Expr('atom', 'leaf'), 'a.quality') is False


def test_fixed_visibility_blocks_weak_gradient(vocabulary):
    scene = localized_scene(vocabulary, ['a'], {'a': False}, {})
    logits = torch.zeros(6, requires_grad=True)
    formula = scene.ground(trait_query('leaf', ['yellow']), 'plant')
    loss = weak_loss(formula, {'a.joint': logits.softmax(0)}, eligible=False, epsilon=.1)
    loss.backward()
    assert torch.equal(logits.grad, torch.zeros(6))
    with pytest.raises(ValueError, match='fixed'):
        weak_loss(formula, {'a.joint': logits.softmax(0)}, eligible=torch.tensor(True), epsilon=.1)


def test_allowed_alternatives_move_probability_without_inventing_state(vocabulary):
    scene = localized_scene(vocabulary, ['a'], {'a': True}, {})
    logits = torch.zeros(6, requires_grad=True)
    formula = scene.ground(trait_query('leaf', ['green', 'yellow']), 'plant')
    weak_loss(formula, {'a.joint': logits.softmax(0)}, eligible=True, epsilon=.1).backward()
    assert logits.grad[0] < 0 and logits.grad[1] < 0
    assert logits.grad[0] == logits.grad[1]
    assert logits.grad[4] > 0  # wrong bearer cannot satisfy the weak event


def test_profile_scorer_missing_data_ties_and_intervention():
    profiles = {'A': {'leaf.colour': {'allowed': ['green'], 'reliability': 1}},
                'B': {'leaf.colour': {'allowed': ['yellow'], 'reliability': 1}}, 'C': {}}
    ref = {'leaf.colour': {'green': .5, 'yellow': .5}}
    result = rank_profiles({'leaf.colour': {'green': .9, 'yellow': .1}}, profiles, ref)
    assert result['ranking'][0]['taxon'] == 'A' and not result['abstain']
    assert next(r for r in result['ranking'] if r['taxon'] == 'C')['score'] == 0
    switched = rank_profiles({'leaf.colour': {'green': .1, 'yellow': .9}}, profiles, ref)
    assert switched['ranking'][0]['taxon'] == 'B'
    assert rank_profiles(ref, profiles, ref)['abstain']
    assert rank_profiles({}, profiles, ref)['abstain']


def test_small_training_smoke_uses_local_features_and_logic(vocabulary):
    torch.set_num_threads(1)
    samples = {}
    # Constructed tensors are implementation fixtures, not plant images or test accuracy.
    for photo, (feature, label) in enumerate([(0, 0), (1, 1), (2, 3)]):
        samples[photo] = {'features': torch.eye(4)[feature:feature+1], 'labels': torch.tensor([label]),
                         'gold_mask': [True], 'assessable': [True], 'regions': [{}]}
    samples[3] = {'features': torch.eye(4)[3:4], 'labels': torch.tensor([5]),
                  'gold_mask': [False], 'assessable': [True], 'regions': [{}]}
    scene = localized_scene(vocabulary, ['r0'], {'r0': True}, {})
    events = [{'photo_id': 3, 'regions': [0], 'formula': scene.ground(trait_query('petal', ['yellow']), 'plant'),
               'epsilon': .1, 'reliability': 1}]
    head, history = fit(samples, vocabulary, events, epochs=80)
    assert history[-1]['loss'] < history[0]['loss']
    assert history[-1]['weak'] < history[0]['weak']
    assert torch.allclose(head(torch.eye(4)).sum(-1), torch.ones(4))


def test_review_gate_refuses_unreviewed_and_changed_crops(tmp_path, vocabulary):
    extraction = tmp_path / 'extraction'; (extraction / 'features').mkdir(parents=True)
    region = {'box': [0, 0, 10, 10], 'organ': 'leaf', 'colour': 'green', 'confirmed': True, 'assessable': True}
    metadata = {'photo_id': 1, 'sha256': 'abc', 'regions': [region]}
    (extraction / 'regions.jsonl').write_text(json.dumps(metadata) + '\n')
    np.savez(extraction / 'features/1.npz', region_features=np.ones((1, 4)))
    row = {**metadata, 'regions': [dict(region)], 'split': 'development_audit', 'reviewer': 'test', 'review_status': 'unreviewed'}
    packet = {'schema': 'flopo-visual-review-v1', 'purpose': 'development_audit', 'images': [row]}
    path = tmp_path / 'review.json'
    def write(): path.write_text(json.dumps(packet))
    write()
    with pytest.raises(ValueError, match='Unreviewed'):
        load_anchors(path, extraction, vocabulary)
    row['review_status'] = 'reviewed'; write()
    assert len(load_anchors(path, extraction, vocabulary)) == 1
    row['regions'][0]['box'] = [0, 0, 9, 9]; write()
    with pytest.raises(ValueError, match='re-extraction'):
        load_anchors(path, extraction, vocabulary)


def test_invalid_state_is_rejected():
    with pytest.raises(ValueError, match='state'):
        probability(('eq', 'x', 5), {'x': [.5, .5]})


def test_partial_union_cannot_silently_discard_unmodelled_allowed_state(vocabulary):
    query = trait_query('petal', ['yellow', 'cream'])
    assert ungrounded_atoms(query, vocabulary, {}) == {'cream'}
    assert not ungrounded_atoms(trait_query('leaf', ['green', 'yellow']), vocabulary, {})


def test_invalid_reference_distribution_cannot_be_hidden_by_valid_evidence():
    with pytest.raises(ValueError, match='distribution'):
        rank_profiles({'g': {'green': .5, 'yellow': .5}}, {}, {'g': {'green': 1, 'yellow': 1}})


def test_weak_events_verify_source_scope_and_deduplicate(tmp_path, vocabulary):
    source = tmp_path / 'profiles.json'
    source.write_text(json.dumps([{'records': [{'r': 'record1', 't': 'taxon1', 'pc': 'query1', 'b': 'leaf'}]}]))
    samples = {1: {'regions': [{'organ': 'leaf'}], 'assessable': [True]}}
    query = {'supported': {'query1': trait_query('leaf', ['yellow']).json()}, 'ancestors': {}}
    event = {'photo_id': 1, 'query_iri': 'query1', 'source_record_ids': ['record1'],
             'source_snapshot_sha256': sha(source), 'regions': [0], 'scope_compatible': True,
             'reviewer': 'test', 'review_status': 'reviewed', 'epsilon': .1, 'reliability': .8}
    path = tmp_path / 'events.json'; path.write_text(json.dumps([event, event]))
    manifest = [{'photo_id': 1, 'taxon': 'taxon1'}]
    assert len(load_events(path, samples, vocabulary, query, source, manifest)) == 1
    samples[1]['regions'][0]['organ'] = 'petal'
    with pytest.raises(ValueError, match='bearer'):
        load_events(path, samples, vocabulary, query, source, manifest)
    samples[1]['regions'][0]['organ'] = 'leaf'
    event['source_snapshot_sha256'] = 'bad';path.write_text(json.dumps([event]))
    with pytest.raises(ValueError, match='provenance'):
        load_events(path, samples, vocabulary, query, source, manifest)
