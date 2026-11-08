import torch
import json
from types import SimpleNamespace
import numpy as np
import pytest
from flopo2.vision.extract import digest
from flopo2.vision.modern_weak import fit
from flopo2.vision.modern_weak import event_probability, bernoulli_kl, source_bags, ontology_edges, negative_pairs


def test_disjunction_leaves_unknown_predicates_without_gradient():
    q = torch.tensor([[.2, .5, .7]], requires_grad=True)
    event = event_probability(q, [0, 1])
    assert torch.allclose(event, torch.tensor([.6]))
    (-event.log()).sum().backward()
    assert q.grad[0, 2] == 0
    assert q.grad[0, 0] < 0 and q.grad[0, 1] < 0


def test_bernoulli_anchor_is_zero_at_reference_and_finite_near_boundary():
    p = torch.tensor([0., .3, 1.])
    assert torch.allclose(bernoulli_kl(p, p), torch.zeros(3))
    assert torch.isfinite(bernoulli_kl(p, 1-p)).all()


def test_only_training_and_matching_organs_enter_source_bags():
    inv = {'traits': [{'quality_label': 'ovate'}],
           'events': [{'taxon': 'a', 'organ': 'leaf', 'any_of': [0]}]}
    rows = [{'taxon': 'a', 'organ': organ, 'split': split} for organ, split in
            [('leaf', 'train'), ('fruit', 'train'), ('leaf', 'test'), ('leaf', 'validation')]]
    assert source_bags(rows, inv) == [([0], [0], 'a')]


def test_hierarchy_does_not_cross_bearers_or_reverse_implication():
    traits = [{'index': i, 'bearer': b, 'quality': q} for i, b, q in
              [(0, 'leaf', 'pubescent'), (1, 'leaf', 'hairy'), (2, 'fruit', 'hairy')]]
    assert ontology_edges(traits, {'pubescent': ['pubescent', 'hairy']}) == [(0, 1)]


def test_crop_context_traits_are_withheld():
    inv = {'traits': [{'quality_label': 'opposite'}],
           'events': [{'taxon': 'a', 'organ': 'leaf', 'any_of': [0]}]}
    assert source_bags([{'taxon': 'a', 'organ': 'leaf', 'split': 'train'}], inv) == []


@pytest.mark.parametrize('followup', [False, True])
def test_changing_heldout_images_cannot_change_fitted_heads(tmp_path, followup):
    data = tmp_path / 'data'; data.mkdir()
    (data / 'queries.json').write_text(json.dumps({'ancestors': {}}))
    inv = {'traits': [{'index': 0, 'label': 'leaf ovate', 'quality_label': 'ovate', 'quality': 'q',
                       'bearer': 'leaf', 'organ': 'leaf'}],
           'events': [{'taxon': 'a', 'organ': 'leaf', 'any_of': [0]}]}
    saved = []
    for run, heldout in enumerate([[0., 1.], [1000., -1000.]]):
        out = tmp_path / str(run); out.mkdir()
        np.savez_compressed(out / 'features.npz', regions=np.array([[1., 0.], heldout]), text=np.array([[1., 0.]]))
        (out / 'regions.jsonl').write_text('\n'.join(json.dumps({'taxon': t, 'organ': 'leaf', 'split': s})
            for t, s in [('a', 'train'), ('b', 'test')]))
        (out / 'inventory.json').write_text(json.dumps(inv))
        ext = {'model': 'synthetic', **{k: digest(out / f) for f, k in
            [('features.npz', 'features_sha256'), ('regions.jsonl', 'regions_sha256'), ('inventory.json', 'inventory_sha256')]}}
        (out / 'extraction.json').write_text(json.dumps(ext))
        fit(SimpleNamespace(data=data, out=out, steps=2, followup=followup))
        saved.append({p.name: torch.load(p, weights_only=False)['state_dict'] for p in out.glob('*.pt')})
    assert saved[0].keys() == saved[1].keys()
    for name in saved[0]:
        assert all(torch.equal(saved[0][name][k], saved[1][name][k]) for k in saved[0][name])
