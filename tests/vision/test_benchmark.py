import numpy as np
import pytest

from flopo2.vision.benchmark import (
    aggregate, average_precision, fit_threshold, split_for, target,
)


def ref(value, trait='leaf_trichome_density', dataset='seedling', **kwargs):
    return dict(dataset_id=dataset, trait=trait, reference_value=value,
                reference_status='majority', n_scores='3', agreement_fraction='0.666666', **kwargs)


def test_unknown_ties_and_low_agreement_are_not_absence():
    for value in ['', 'not_assessable']:
        assert target(ref(value)) is None
    row = ref('1'); row['reference_status'] = 'ordinal_median_tiebreak'
    assert target(row) is None
    assert target(row, strict=False) == 0
    row = ref('1'); row['n_scores'] = '1'
    assert target(row) is None
    assert target(ref('2')) == 1
    assert target(ref('3')) == 1


def test_grouped_shape_is_preserved_and_incomplete_unions_excluded():
    assert target(ref('obovate_spatulate', 'leaf_blade_shape')) == 'obovate_spatulate'
    assert target(ref('cordate_reniform', 'leaf_blade_shape')) is None
    assert target(ref('orbicular_reniform', 'leaf_blade_shape', 'mature_v2')) is None


def test_cultivar_split_is_stage_independent_and_deterministic():
    assert split_for('s0001') == split_for('s0001')
    assert {split_for('s'+str(i)) for i in range(100)} == {'development', 'test'}


def test_tied_ap_is_invariant_to_row_order_and_constant_equals_prevalence():
    assert average_precision([1, 0, 1, 0], [.5]*4) == .5
    assert average_precision([0, 1, 0, 1], [.5]*4) == .5
    assert average_precision([1, 1, 0, 0], [4, 3, 2, 1]) == 1
    assert average_precision([1, 1], [.1, .2]) is None


def test_missing_detection_stays_in_denominator_and_missing_image_fails():
    records = [dict(dataset_id='x', record_id='r', n_images=2)]
    images = [dict(dataset_id='x', record_id='r')]*2
    p, coverage = aggregate(records, images, np.array([[.8], [.9]]), [True, False])
    assert p[0, 0] == .4 and coverage[0] == .5
    with pytest.raises(ValueError):
        aggregate(records, images[:1], np.array([[.8]]), [True])


def test_calibration_requires_support_and_uses_only_supplied_development_data():
    assert fit_threshold([0, 0, 1], [.1, .2, .3]) == .5
    y = [0]*5 + [1]*5
    p = [.1]*5 + [.2]*5
    assert fit_threshold(y, p) == .2


def test_primary_metric_averages_within_stage_and_requires_support():
    from flopo2.vision.benchmark_score import hair_endpoint, paired_bootstrap
    y = np.array([0]*5 + [1]*5 + [0]*5 + [1]*5, dtype=float)
    q = np.full((20, 36), .5); q[:, 32] = y; q[:, 12] = 1-y
    ds = np.array(['a']*10 + ['b']*10)
    value, stages = hair_endpoint(y, q, ds)
    assert value == 1 and stages == {'a': 1, 'b': 1}
    control = np.full_like(q, .5)
    result = paired_bootstrap(y, q, control, ds, np.array([str(i % 10) for i in range(20)]), 40)
    assert result['difference'] == .5 and result['valid_replicates'] > 30
    assert result['CI95'][0] > 0


def test_overlap_index_finds_every_four_bit_neighbour():
    from flopo2.vision.benchmark_overlap import segments
    h = 0x123456789abcdef0
    for bits in [(0, 13, 26, 39), (12, 25, 38, 63), (1, 4, 6, 8)]:
        other = h
        for bit in bits: other ^= 1 << bit
        assert set(segments(h)) & set(segments(other))


def test_sensitivity_uses_strict_development_calibration():
    from flopo2.vision.benchmark_score import evaluate
    records = [dict(dataset_id='seedling', record_id=str(i),
                    split='development' if i < 10 else 'test') for i in range(12)]
    annotations = []
    q = np.full((12, 36), .1)
    for i in range(12):
        value = int(5 <= i < 10 or i == 11)
        annotations.append(dict(dataset_id='seedling', record_id=str(i), task='hair',
                                strict_target=None if 7 <= i < 10 else value, all_target=value))
        q[i, 32] = .2 if value else .1
        q[i, 12] = .1 if value else .2
    strict, _ = evaluate(records, annotations, q, np.ones(12))
    sensitivity, _ = evaluate(records, annotations, q, np.ones(12), 'all_target')
    assert strict['hair']['seedling']['hairy']['threshold'] == .5
    assert sensitivity['hair']['seedling']['hairy']['threshold'] == .5
    assert sensitivity['hair']['seedling']['development_records'] == 7


def test_shards_require_every_model_and_identical_checkpoint_identities():
    import copy
    from flopo2.vision.benchmark_score import validate_shard
    protocol = dict(modes=['baseline', 'flora'], encoders=['e'], seeds=[1])
    identity = dict(models={'e': [dict(name='primary-baseline-0', checkpoint_sha256='a'),
                                  dict(name='primary-flora-1', checkpoint_sha256='b')]},
                    preflight_limit=0, source_sha256='s', dependencies={}, detector={},
                    encoder_manifests_sha256={}, shards=2)
    meta = dict(sha256={'e/primary-baseline-0.npz': 'x', 'e/primary-flora-1.npz': 'y'})
    validate_shard(identity, meta, protocol)
    missing = copy.deepcopy(identity); missing['models']['e'].pop()
    with pytest.raises(ValueError, match='incomplete or repeated model'):
        validate_shard(missing, meta, protocol, identity)
    changed = copy.deepcopy(identity); changed['models']['e'][1]['checkpoint_sha256'] = 'different'
    with pytest.raises(ValueError, match='Incompatible inference shards'):
        validate_shard(changed, meta, protocol, identity)
    partial_manifest = dict(sha256={'e/primary-baseline-0.npz': 'x'})
    with pytest.raises(ValueError, match='missing from shard hash manifest'):
        validate_shard(identity, partial_manifest, protocol)


def test_secondary_shape_intervals_preserve_grouped_categories_and_pairs():
    from flopo2.vision.benchmark_secondary import shape_endpoint, shape_comparison
    truth = np.array(['ovate']*5 + ['obovate_spatulate']*5)
    q = np.zeros((10, 36)); q[:5, 0] = .9
    q[5:8, 14] = .9; q[8:, 29] = .9
    datasets = np.array(['seedling']*10)
    groups = {'seedling': ['ovate', 'obovate_spatulate']}
    assert shape_endpoint(truth, q, datasets, groups) == 1
    comparison = shape_comparison(truth, q, q, datasets, np.array([str(i) for i in range(10)]), groups, 30)
    assert comparison['difference'] == 0 and comparison['CI95'] == [0, 0]
