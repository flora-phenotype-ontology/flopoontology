import numpy as np
from flopo2.vision.full_diagnostic import expected_runs, shape_metrics, paired_control_metrics


def test_all_declared_models_are_included_once():
    runs=expected_runs()
    assert len(runs)==len(set(runs))==31
    assert all(f'{mode}-200-{seed}' in runs for mode in ['direct','mil','hierarchy','projected','shuffled'] for seed in range(20261026,20261029))


def test_unknown_and_ambiguous_shapes_do_not_become_negative_examples():
    annotations=[{'outline_allowed':x} for x in [['ovate'],['oblong'],[],['ovate','oblong']]]
    q=np.array([[.8,.2],[.2,.8],[.99,.99],[.99,.99]])
    traits=[{'quality_label':'ovate'},{'quality_label':'oblong'}]
    r=shape_metrics(annotations,q,traits)
    assert r['assessable']==3 and r['correct']==3 and r['macro_AP']==1.
    assert all(v['n']==2 for v in r['per_literal_shape'].values())


def test_erasure_control_is_paired_and_bearer_specific():
    traits=[{'index':0,'organ':'leaf','label':'leaf green','quality_label':'green'},
            {'index':1,'organ':'fruit','label':'fruit red','quality_label':'red'}]
    original=np.array([[.8,.99],[.99,.3]]);erased=np.array([[.2,.01],[.01,.5]])
    r=paired_control_metrics(original,erased,traits,[{'organ':'leaf'},{'organ':'fruit'}])
    assert np.isclose(r['leaf green']['mean_paired_change'],.6)
    assert np.isclose(r['fruit red']['mean_paired_change'],-.2)
    assert r['fruit red']['fraction_lower_after_erasure']==0.
