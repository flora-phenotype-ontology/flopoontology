import torch
import pytest

from flopo2.vision.model import PrimitiveHead, trait_query
from flopo2.vision.weak_train import balanced_weights, optimize, source_events, truth_mask


@pytest.fixture
def vocabulary():
    return {'organs': [{'name': 'leaf', 'iri': 'leaf'}, {'name': 'petal', 'iri': 'petal'}],
            'colours': [{'name': 'green', 'iri': 'green'}, {'name': 'yellow', 'iri': 'yellow'}, {'name': 'unknown', 'iri': ''}]}


def test_exact_truth_mask_preserves_bearer_and_alternatives(vocabulary):
    mask = truth_mask(trait_query('leaf', ['green', 'yellow']), vocabulary, {})
    assert mask == (1, 1, 0, 0, 0, 0)
    with pytest.raises(ValueError, match='alternative'):
        truth_mask(trait_query('leaf', ['yellow', 'cream']), vocabulary, {})


def test_repeated_photos_do_not_multiply_observation_weight():
    rows = [{'taxon': 'a', 'observation_id': 1}] * 3 + [
            {'taxon': 'a', 'observation_id': 2}, {'taxon': 'b', 'observation_id': 3}]
    weights = balanced_weights(rows)
    assert weights[:3].sum().item() == pytest.approx(.25)
    assert weights[3].item() == pytest.approx(.25)
    assert weights[4].item() == pytest.approx(.5)


def test_source_events_are_weak_and_duplicate_records_do_not_multiply_them(vocabulary):
    r = {'r': 'record', 'b': 'leaf', 'attribute': 'http://purl.obolibrary.org/obo/PATO_0000014',
         'pc': 'query', 'status': 'accepted', 'text': 'yellow'}
    p = [{'taxon': 'a', 'records': [r, r]}]
    q = {'supported': {'query': trait_query('leaf', ['yellow']).json()}, 'ancestors': {}}
    events, _ = source_events(p, q, vocabulary)
    assert events[('a', 'leaf')]['source_record_ids'] == ['record']
    p[0]['records'].append({**r, 'text': 'green becoming yellow'})
    assert not source_events(p, q, vocabulary)[0]


def test_unreviewed_weak_events_can_train_without_gold(vocabulary):
    torch.manual_seed(1); torch.set_num_threads(1)
    initial = PrimitiveHead(4, vocabulary['organs'], vocabulary['colours'])
    features = torch.eye(4)
    samples = [{'taxon': str(i), 'observation_id': i, 'review_status': 'unreviewed'} for i in range(4)]
    events = [{'taxon': '0', 'observation_id': 0, 'sample_index': 0,
               'mask': truth_mask(trait_query('leaf', ['yellow']), vocabulary, {}), 'review_status': 'unreviewed'}]
    before = {k: v.detach().clone() for k, v in initial.state_dict().items()}
    head, history, prediction = optimize(initial, features, samples, events, epsilon=.3, epochs=60)
    assert history[-1]['objective'] < history[0]['objective']
    assert history[-1]['training_allowed_event_mass'] > history[0]['training_allowed_event_mass']
    assert all(torch.equal(before[k], v) for k, v in initial.state_dict().items())
    assert torch.allclose(prediction.sum(-1), torch.ones(4))
    assert not torch.equal(head.organ.weight, initial.organ.weight)
