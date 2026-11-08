import json
from pathlib import Path

import numpy as np
import pytest

from flopo2.vision.small import components, partition, NAMES, UNSEEN
from flopo2.vision.pilot import write_jsonl, read_jsonl
from flopo2.vision.leaf_control import ridge_fit, TARGETS
from flopo2.vision.small_train import prepare


def row(i, name=NAMES[0]):
    return dict(photo_id=i,observation_id=i,observer_id=i,sha256=str(i),
                dhash=f'{(255 << (8*i)):x}',name=name)


def test_duplicate_components_are_transitive_across_observers():
    a,b,c,d=[row(i) for i in range(4)]
    b['observer_id']=a['observer_id']
    c['dhash']=b['dhash']  # Different observer but same photograph.
    roots=components([a,b,c,d])
    assert roots[0]==roots[1]==roots[2]
    assert roots[3]!=roots[0]


def test_rejected_view_still_prevents_observer_leakage(tmp_path):
    a,b,c=row(0),row(1),row(2,UNSEEN)
    b['observation_id']=a['observation_id']
    b['observer_id']=c['observer_id']  # Rejected view bridges A to held-out observer.
    write_jsonl(tmp_path/'images.jsonl',[a,b,c])
    (tmp_path/'extraction').mkdir()
    write_jsonl(tmp_path/'extraction/regions.jsonl',[
        {'photo_id':r['photo_id'],'regions':[] if r is b else
         [{'organ':'leaf','score':.9,'box':[0,0,200,200]}]} for r in (a,b,c)])
    (tmp_path/'extraction/run.json').write_text('{}')
    (tmp_path/'protocol.json').write_text(json.dumps({'visibility_gate':
        {'minimum_detector_score':.4,'minimum_side_pixels':192}}))
    partition(tmp_path)
    output=read_jsonl(tmp_path/'splits.jsonl')
    assert len(output)==2
    assert all(r['split']=='zero_shot_test' for r in output)
    assert json.loads((tmp_path/'split-audit.json').read_text())['status']=='insufficient_eligible_observations'


def test_training_refuses_an_underpowered_cohort(tmp_path):
    (tmp_path/'protocol.json').write_text('{}')
    (tmp_path/'split-audit.json').write_text('{"status":"insufficient_eligible_observations"}')
    with pytest.raises(ValueError,match='sample-size gate'):
        prepare(tmp_path,tmp_path,tmp_path/'run')
    assert not (tmp_path/'run').exists()


def test_numeric_probe_is_fit_only_from_training_values():
    x=np.array([[0.,1.],[1.,0.],[2.,3.],[3.,2.]])
    y=(2*x[:,0]-x[:,1])[:,None]
    predict=ridge_fit(x,y,.01)
    before=predict(np.array([[4.,5.]]))
    # Evaluation is a pure operation; extreme validation/test inputs cannot update the fit.
    predict(np.full((10,2),1e8))
    np.testing.assert_array_equal(before,predict(np.array([[4.,5.]])))
    assert abs(float(before[0,0])-3)<.02
    # Published CSV layout: class, specimen, eccentricity, aspect ratio, ... lobedness.
    assert TARGETS=={'aspect_ratio':3,'elongation':4,'solidity':5,'lobedness':9}


def test_weak_loss_accepts_string_states_from_existing_profile_ranker():
    from flopo2.vision.small_train import event_mask
    assert event_mask(['1','3'],5)==[0.,1.,0.,1.,0.]
    assert event_mask([1,3],5)==event_mask(['1','3'],5)
    with pytest.raises(ValueError):event_mask(['5'],5)
