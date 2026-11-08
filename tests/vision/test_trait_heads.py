import torch
from flopo2.vision.trait_heads import make_head, organ_centers


def test_offset_changes_preferences_but_preserves_per_trait_ranking():
    text = torch.eye(2); x = torch.tensor([[.1, .8], [.8, .3], [.4, .4]])
    head = make_head(text, 'offset')
    before = head(x).detach()
    with torch.no_grad(): head.offset.copy_(torch.tensor([5., -5.]))
    after = head(x).detach()
    assert torch.equal(before.argsort(0), after.argsort(0))
    assert not torch.equal(before.argmax(1), after.argmax(1))


def test_centered_adjustment_cannot_shift_training_organ_mean():
    x = torch.tensor([[.1, .8], [.8, .3], [.4, .4], [999., 999.]])
    rows = [{'split': s, 'organ': o} for s, o in [('train','leaf'),('train','leaf'),('train','fruit'),('test','leaf')]]
    traits = [{'index': 0, 'organ': 'leaf'}, {'index': 1, 'organ': 'fruit'}]
    text = torch.eye(2); centers = organ_centers(x, rows, traits)
    head = make_head(text, 'centered', centers)
    baseline = head(x).detach()
    with torch.no_grad(): head.residual.copy_(torch.tensor([[2., -1.], [-1., 3.]]))
    delta = (head(x) - baseline).detach()
    assert abs(float(delta[:2, 0].mean())) < 1e-6
    assert abs(float(delta[2, 1])) < 1e-6
    assert float(delta[:2, 0].std()) > .1
    restored = make_head(text, 'centered'); restored.load_state_dict(head.state_dict())
    assert torch.equal(restored(x), head(x))
