from types import SimpleNamespace
import torch
from torch import nn
from flopo2.vision.full_train import training_subset, project_implications, enable_last_blocks


def test_learning_curve_subsets_are_nested_and_training_only():
    rows=[{'taxon':t,'observation_id':i,'split':s} for t in ['a','b'] for i in range(15) for s in ['train','test']]
    small=set(training_subset(rows,5));large=set(training_subset(rows,10))
    assert small<large and len(small)==10 and len(large)==20
    assert all(rows[i]['split']=='train' for i in large)


def test_implication_projection_preserves_valid_unknown_and_moves_both_sides():
    q=torch.tensor([[.8,.2,.7],[.1,.9,.4]],requires_grad=True)
    r=project_implications(q,[(0,1)])
    assert torch.allclose(r[0],torch.tensor([.5,.5,.7]))
    assert torch.equal(r[1],q[1])
    assert not r.requires_grad
    chain=project_implications(torch.tensor([[.9,.7,.1]]),[(0,1),(1,2)])
    assert float((chain[:,0]-chain[:,1]).max())<1e-6
    assert float((chain[:,1]-chain[:,2]).max())<1e-6


def test_only_last_vision_blocks_and_postnorm_are_trainable():
    model=nn.Module();model.text=nn.Linear(2,2);model.vision_model=nn.Module()
    model.vision_model.encoder=nn.Module();model.vision_model.encoder.layers=nn.ModuleList([nn.Linear(2,2) for _ in range(4)])
    model.vision_model.post_layernorm=nn.LayerNorm(2)
    params=enable_last_blocks(model,2)
    assert not any(p.requires_grad for p in model.text.parameters())
    assert not any(p.requires_grad for p in model.vision_model.encoder.layers[0].parameters())
    assert len(params)==6
    assert all(p.requires_grad for p in params.values())
