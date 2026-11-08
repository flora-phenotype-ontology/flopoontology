import numpy as np
from flopo2.vision.full_eval import score_arrays


def test_test_labels_do_not_choose_threshold_and_unknown_is_not_negative():
    truth=np.array([[0.]]*5+[[1.]]*5+[[1.],[0.],[np.nan]])
    q=np.array([[.1]]*5+[[.3]]*5+[[.4],[.2],[.99]])
    splits=np.array(['validation']*10+['test']*3)
    a=score_arrays(truth,q,splits)['0']
    changed=truth.copy();changed[10:12]=1-changed[10:12]
    b=score_arrays(changed,q,splits)['0']
    assert a['threshold']==b['threshold']
    assert a['test']['n']==2 and a['test']['average_precision']==1.
    assert a['test']['f1']==1.


def test_no_negative_references_cannot_establish_trait_discrimination():
    result=score_arrays(np.array([[1.],[1.]]),np.array([[.8],[.9]]),np.array(['test','test']))['0']
    assert result['threshold']==.5
    assert result['test']['average_precision'] is None
    assert result['test']['f1'] is None
