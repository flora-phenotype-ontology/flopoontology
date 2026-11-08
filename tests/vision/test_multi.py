import copy
import numpy as np
import torch

from flopo2.vision.expand import split_rows
from flopo2.vision.multi import MultiHead, compile_profiles, fit, evaluate
from flopo2.vision.model import trait_query
from flopo2.vision.predict import predict


def schema():
    return {'groups':{'colour':{'organs':[{'name':'leaf','iri':'leaf'},{'name':'other','iri':''}],
        'colours':[{'name':'green','iri':'green'},{'name':'yellow','iri':'yellow'},{'name':'unknown','iri':''}],
        'organs_in_scope':['leaf']}}}


def test_group_split_excludes_observer_overlap_and_original_pilot():
    rows=[{'genus':f'g{i}','taxon':f't{i}','observation_id':i,'observer_id':i,'photo_id':i,
            'sha256':str(i),'dhash':f'{(1 << (i*8)) * 255:016x}'} for i in range(8)]
    out,_=split_rows(rows,{'g0'})
    test=next(r for r in out if r['split']=='test')
    rows[0]['observer_id']=test['observer_id']
    out,_=split_rows(rows,{'g0'})
    assert not any(r['genus']=='g0' for r in out)
    out,_=split_rows(rows,{'g0'},prior_observers={test['observer_id']})
    assert not any(r['genus']==test['genus'] and r['split']=='test' for r in out)
    for a in out:
        for b in out:
            if a['split']!=b['split']:assert a['observer_id']!=b['observer_id']


def test_single_eq_fallback_does_not_turn_complex_text_into_exact_label():
    r={'r':'r','q':'yellow','ql':'yellow','bl':'leaf','b':'leaf','status':'accepted','text':'yellow'}
    p=[{'taxon':'t','records':[r]}];q={'supported':{},'ancestors':{}}
    c,_=compile_profiles(p,q,schema())
    assert c['t']['leaf.colour']['origins']==['exact_normalized_EQ']
    p[0]['records'][0]['text']='yellow or cream'
    assert not compile_profiles(p,q,schema())[0]


def test_partial_profiles_retain_whole_supported_events_without_truncating_unions():
    base={'b':'leaf','bl':'leaf','status':'accepted','ql':'yellow','q':'yellow','text':'yellow'}
    profiles=[{'taxon':'t','records':[{**base,'r':'known','pc':'known'},
                                     {**base,'r':'incomplete','pc':'incomplete'}]}]
    queries={'supported':{'known':trait_query('leaf',['yellow']).json(),
                          'incomplete':trait_query('leaf',['yellow','cream']).json()},'ancestors':{}}
    assert not compile_profiles(profiles,queries,schema())[0]
    retained,_=compile_profiles(profiles,queries,schema(),allow_partial=True)
    assert retained['t']['leaf.colour']['source_records']==['known']
    assert retained['t']['leaf.colour']['incomplete_source_group']


def test_validation_images_never_enter_training_or_prior_loss():
    torch.manual_seed(3);torch.set_num_threads(1)
    s=schema();initial=MultiHead(s,feature_dim=3)
    x=torch.eye(3);samples=[{'split':'train','taxon':'a','observation_id':1},
                           {'split':'validation','taxon':'b','observation_id':2},
                           {'split':'test','taxon':'c','observation_id':3}]
    events=[{'attribute':'colour','sample_index':0,'mask':[0,1,0,0,0,0], 'taxon':'a','observation_id':1}]
    a,h=fit(initial,x,samples,events,epochs=5)
    x[1:]=1000
    b,_=fit(initial,x,samples,events,epochs=5)
    assert all(torch.equal(v,b.state_dict()[k]) for k,v in a.state_dict().items())
    assert h[-1]['weak_loss']<h[0]['weak_loss']
    assert abs(h[-1]['objective']-h[-1]['weak_loss']-h[-1]['prior_kl'])<1e-5


def test_species_ranking_uses_trait_predictions_and_abstains_without_regions():
    s=schema();rows=[{'split':'test','observation_id':1,'taxon':'green_species','genus':'G'},
                    {'split':'test','observation_id':2,'taxon':'yellow_species','genus':'Y'}]
    samples=[{**rows[0],'organ':'leaf','detector_score':.8,'box':[0,0,100,100]}]
    p={'colour':np.array([[.8,.1,.1,0,0,0]])}
    cat={'green_species':{'leaf.colour':{'allowed':['0'],'reliability':1}},
         'yellow_species':{'leaf.colour':{'allowed':['1'],'reliability':1}}}
    ref={'leaf.colour':{'0':.4,'1':.4,'2':.2}}
    metrics,results=evaluate(p,samples,rows,s,cat,ref,'test')
    assert metrics['coverage']==.5 and metrics['top1']==.5
    assert results[1]['abstain']
    p['colour'][0]=[.1,.8,.1,0,0,0]
    _,changed=evaluate(p,samples,rows,s,cat,ref,'test')
    assert changed[0]['top_candidates'][0]['taxon']=='yellow_species'


def test_inference_has_no_species_input_and_keeps_flopo_witness_bound():
    s=schema();head=MultiHead(s,feature_dim=3)
    bundle={'schema':s,'feature_dim':3,'state_dict':head.state_dict(),'catalogue':{},
            'reference':{},'taxon_names':{},'status':'test'}
    queries={'supported':{'leaf-green':{'attribute':'colour','label':'leaf green','mask':[1,0,0,0,0,0]},
                          'other-yellow':{'attribute':'colour','label':'other yellow','mask':[0,0,0,0,1,0]}}}
    result=predict(bundle,np.ones((1,3)),[{'organ':'leaf','box':[0,0,100,100],'score':.8}],queries)
    assert [r['iri'] for r in result['flopo_phenotypes']]==['leaf-green']
    assert result['species']['abstain']
