import numpy as np
from flopo2.vision.trait_eval import binary_metrics,partial_target,wilson,score


def test_unassessable_labels_never_become_negatives():
    result=binary_metrics([1,0,None],[.9,.8,.99])
    assert result['n']==2 and result['tp']==1 and result['fp']==1
    assert result['precision']==.5
    assert partial_target([], [0]) is None


def test_ambiguous_parent_does_not_assert_a_child_absent():
    assert partial_target([1,7],[1,7])==1
    assert partial_target([1,7],[7]) is None
    assert partial_target([1,7],[9])==0


def test_positive_only_audit_cannot_claim_precision_or_discrimination():
    result=binary_metrics([1,1,None],[.9,.1,.9])
    assert result['positive_detection_rate']==.5
    assert result['precision'] is None and result['f1'] is None and result['auroc'] is None


def test_unknown_predictions_count_as_errors_on_assessable_shapes():
    vocab={'outline':{'colours':[{'name':'ovate'},{'name':'unknown'}]},
           'hairiness':{'colours':[{'name':'glabrous'},{'name':'hairy'},{'name':'unknown'}]}}
    phen={'o':{'label':'leaf ovate','mask':[1,0]},'h':{'label':'leaf hairy','mask':[0,1,0]}}
    ann=[{'audit_id':'a','outline_allowed':['ovate'],'hair_present':None,'notes':''},
         {'audit_id':'b','outline_allowed':[],'hair_present':None,'notes':''}]
    prob={'leaf.outline':np.array([[.1,.9],[.9,.1]]),'leaf.hairiness':np.array([[.2,.3,.5],[.2,.3,.5]])}
    result,_=score(ann,prob,vocab,phen)
    assert result['outline']['assessable']==1 and result['outline']['coverage']==.5
    assert result['outline']['set_compatible_correct']==0
    assert result['flopo_class_metrics']['o']['n']==1
    assert wilson(0,1)[0]==0
