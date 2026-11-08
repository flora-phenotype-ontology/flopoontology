import numpy as np
from flopo2.vision.shape_experiments import budgets, excluded_taxa, unit


def test_genus_exclusion_catches_family_and_taxon_aliases():
    rows=[dict(taxon='a',genus='Brassica'),dict(taxon='b',family='Brassicaceae',genus='Sinapis'),dict(taxon='c',name='Brassica napus'),dict(taxon='d',genus='Quercus')]
    assert excluded_taxa(rows)=={'a','b','c'}


def test_budget_splits_keep_test_and_validation_out_and_are_nested():
    records=[];annotations=[]
    for i in range(70):
        for stage in ['seedling','mature_v1']:
            records.append(dict(dataset_id=stage,record_id=str(i),cultivar_id=str(i),split='test' if i>=65 else 'development'))
            annotations.append(dict(dataset_id=stage,record_id=str(i),task='shape',strict_target='ovate' if i%4 else None))
    plan=budgets(records,annotations)
    for sizes in plan['schedules'].values():
        previous=set()
        for n,indices in sizes.items():
            assert previous<=set(indices);previous=set(indices)
            assert len({records[i]['cultivar_id'] for i in indices})==int(n)
            assert all(records[i]['split']=='development' and records[i]['cultivar_id'] not in plan['validation_cultivars'] for i in indices)
            for i in indices:assert (i^1) in indices


def test_normalization_is_finite_and_preserves_direction():
    z=unit(np.array([[3.,4.],[0.,0.]]))
    np.testing.assert_allclose(z[0],[.6,.8]);assert np.isfinite(z).all()


def test_external_hairiness_keeps_scales_separate_and_ignores_intermediate():
    from flopo2.vision.cotleaf_score import metrics
    rows=[];scores=[]
    for population in ['A','B']:
        for target in [0]*5+[1]*5+[None]:
            rows.append(dict(population=population,genotype=population+'-genotype',target=target))
            scores.append(.1 if target==0 else .9)
    q=np.zeros((22,36));q[:,32]=scores
    result=metrics(rows,q)
    assert result['high_hairiness_macro_AP']==1
    assert result['populations']['A']['images']==10
    assert result['populations']['B']['positive']==5


def test_overlap_audit_rejects_empty_training_split(tmp_path):
    import pytest
    from types import SimpleNamespace
    from flopo2.vision.cotleaf_score import audit
    (tmp_path/'records.jsonl').write_text('{}\n')
    (tmp_path/'training.jsonl').write_text('{"split":"development_audit"}\n')
    with pytest.raises(ValueError,match='Nonempty'):
        audit(SimpleNamespace(data=tmp_path,training=tmp_path/'training.jsonl'))
