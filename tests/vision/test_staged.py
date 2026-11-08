import json
import numpy as np
import pytest
import torch
from flopo2.vision.staged_teacher import prompt,request_payload,validate
from flopo2.vision.staged_train import teacher_arrays,evidence_weights,soft_source_loss,masked_bce,SpatialTraits,sample_batch,balanced_events

TRAITS=[{'index':0,'organ':'leaf','label':'leaf green','quality_label':'green','quality':'q0','bearer':'leaf'},
        {'index':1,'organ':'leaf','label':'leaf hairy','quality_label':'hairy','quality':'q1','bearer':'leaf'},
        {'index':2,'organ':'fruit','label':'fruit green','quality_label':'green','quality':'q0','bearer':'fruit'}]


def record():
    return {'row_index':0,'image_sha256':'abc','crop_box':[0,0,10,10],'annotation':{'traits':[
      {'id':0,'state':'present','confidence':'high','box':[0,0,1,1],'evidence':'Green blade.'},
      {'id':1,'state':'unobservable','confidence':'high','box':None,'evidence':'Too small.'}]}}


def test_teacher_payload_excludes_identity_and_rejects_bad_evidence():
    body=request_payload(b'bytes',prompt(TRAITS,'leaf'),'model')
    assert set(body['messages'][0])=={'role','content'}
    assert 'image_url' not in body['messages'][0]['content'][0]['text']
    value=record()['annotation'];validate(value,TRAITS,'leaf')
    value['traits'][0]['box']=[1,0,0,1]
    with pytest.raises(ValueError):validate(value,TRAITS,'leaf')


def test_unknown_visibility_is_not_trait_absence_and_heldouts_are_masked():
    rows=[{'split':'train','sha256':'abc','box':[0,0,10,10],'organ':'leaf'}]
    y,v,a=teacher_arrays([record()],rows,TRAITS)
    assert y[0,0]==1 and np.isnan(y[0,1]) and v[0,1]==0
    assert a[0,0].sum()==pytest.approx(1)
    y,v,a=teacher_arrays([record()],rows,TRAITS,[0]);assert np.isnan(y[0,0]) and np.isnan(v[0,0]) and a[0,0].sum()==0
    rows[0]['split']='test'
    with pytest.raises(ValueError):teacher_arrays([record()],rows,TRAITS)


def test_soft_source_uses_all_observations_instead_of_only_maximum():
    q=torch.tensor([[.9],[.3],[.2],[.1],[.2],[.3],[.3],[.2]],requires_grad=True)
    loss=soft_source_loss(q,[([], [0], 'a')]);loss.backward()
    assert (q.grad<0).all() and torch.allclose(q.grad,q.grad[0].expand_as(q.grad))


def test_missing_teacher_targets_have_no_gradient():
    x=torch.zeros(2,3,requires_grad=True);target=torch.tensor([[1.,float('nan'),0.],[float('nan'),float('nan'),1.]])
    masked_bce(x,target).backward();assert (x.grad[:,1]==0).all() and x.grad[1,0]==0


def test_composition_shares_quality_across_bearers_without_taxon_input():
    head=SpatialTraits(4,TRAITS,torch.zeros(3,4),torch.zeros(3,4))
    assert head.quality_ids.tolist()==[0,1,0]
    x=torch.randn(2,5,4);q,v,a=head(x)
    assert q.shape==v.shape==(2,3) and a.shape==(2,3,5)
    assert torch.allclose(a.sum(-1),torch.ones(2,3))
    assert torch.allclose(q[:,0],q[:,2])


def test_balanced_sampling_is_reproducible_and_heldout_events_removed():
    rows=[{'split':'train','organ':'leaf','taxon':'a','observation_id':i} for i in range(12)]
    inv={'traits':TRAITS,'events':[{'taxon':'a','organ':'leaf','any_of':[0]},{'taxon':'a','organ':'leaf','any_of':[1]}]}
    events,groups=balanced_events(rows,inv,[1]);assert list(groups)==[0]
    a=sample_batch(np.random.default_rng(3),events,groups,rows)[0]
    b=sample_batch(np.random.default_rng(3),events,groups,rows)[0]
    assert a==b and len(a)==32 and len(set(a[:8]))==8


def test_strict_teacher_schema_requires_every_id_and_normalizes_without_guessing():
    body=request_payload(b'image',prompt(TRAITS,'leaf'),'model',[0,1])
    schema=body['response_format']['json_schema']['schema']
    assert schema['properties']['traits']['required']==['0','1']
    assert not schema['properties']['traits']['additionalProperties']
    value={'traits':{'0':{'s':'p','c':'h','b':[0,0,1,1]},'1':{'s':'u','c':'l','b':None}},'evidence':'Green blade; hairs unresolved.'}
    result=validate(value,TRAITS,'leaf');assert result['traits'][0]['state']=='present'
    del value['traits']['1']
    with pytest.raises(ValueError):validate(value,TRAITS,'leaf')
