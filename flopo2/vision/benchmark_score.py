"""Score frozen pxGPT predictions against independent human photo-set labels."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from .benchmark import aggregate, average_precision, binary, fit_threshold, SHAPES
from .extract import digest


def read_rows(path):
    return [json.loads(s) for s in path.read_text().splitlines()]


def hair_endpoint(y, q, dataset, eligible=None):
    values = {}
    for ds in sorted(set(dataset)) if eligible is None else eligible:
        mask = (dataset == ds) & np.isfinite(y)
        yy = y[mask].astype(int)
        if eligible is None and min(int(yy.sum()), int((1-yy).sum())) < 5:
            continue
        ap = [average_precision(yy, q[mask, 32]), average_precision(1-yy, q[mask, 12])]
        if None in ap:
            return None, values
        values[ds] = float(np.mean(ap))
    return (float(np.mean(list(values.values()))) if values else None), values


def paired_bootstrap(y, qa, qb, datasets, cultivars, repetitions=2000):
    """Resample the same cultivar clusters for both arms and every stage."""
    estimate_a, strata = hair_endpoint(y, qa, datasets)
    estimate_b, _ = hair_endpoint(y, qb, datasets, sorted(strata))
    if estimate_a is None or estimate_b is None:
        return {'difference': None, 'CI95': None, 'valid_replicates': 0}
    eligible = sorted(strata)
    included = np.isfinite(y) & np.isin(datasets, eligible)
    y, qa, qb, datasets, cultivars = (x[included] for x in (y, qa, qb, datasets, cultivars))
    ids = sorted(set(cultivars))
    clusters = {c: np.flatnonzero(cultivars == c) for c in ids}
    rng = np.random.default_rng(20261028); values = []
    for _ in range(repetitions):
        draw = np.concatenate([clusters[c] for c in rng.choice(ids, size=len(ids), replace=True)])
        aa, _ = hair_endpoint(y[draw], qa[draw], datasets[draw], eligible)
        bb, _ = hair_endpoint(y[draw], qb[draw], datasets[draw], eligible)
        if aa is not None and bb is not None:
            values.append(aa-bb)
    return {'difference': estimate_a-estimate_b,
            'CI95': np.quantile(values, [.025, .975]).tolist() if values else None,
            'valid_replicates': len(values), 'requested_replicates': repetitions,
            'eligible_datasets': eligible}


def evaluate(records, annotations, q, coverage, reference='strict_target'):
    keys = {(r['dataset_id'], r['record_id']): i for i, r in enumerate(records)}
    ds = np.array([r['dataset_id'] for r in records])
    splits = np.array([r['split'] for r in records])
    hair = np.full(len(records), np.nan); strict_hair = hair.copy()
    shape = np.full(len(records), '', object)
    for r in annotations:
        index = keys[r['dataset_id'], r['record_id']]
        if r['task'] == 'hair' and r['strict_target'] is not None:
            strict_hair[index] = r['strict_target']
        value = r[reference]
        if value is not None:
            if r['task'] == 'hair': hair[index] = value
            else: shape[index] = value
    output = {'hair': {}, 'shape': {}}
    for stage in sorted(set(ds)):
        test = (ds == stage) & (splits == 'test') & np.isfinite(hair)
        dev = (ds == stage) & (splits == 'development') & np.isfinite(strict_hair)
        yy = hair[test].astype(int)
        output['hair'][stage] = {'hairy': binary(yy, q[test, 32], fit_threshold(strict_hair[dev], q[dev, 32])),
            'glabrous': binary(1-yy, q[test, 12], fit_threshold(1-strict_hair[dev], q[dev, 12])),
            'development_records': int(dev.sum()), 'test_records': int(test.sum()),
            'mean_detected_view_fraction': float(coverage[test].mean()) if test.any() else None,
            'sets_with_no_detection': int((coverage[test] == 0).sum())}
        mask = (ds == stage) & (splits == 'test') & (shape != '')
        yy = shape[mask]; categories = list(SHAPES[stage])
        qq = np.stack([q[mask][:, ids].max(1) for ids in SHAPES[stage].values()], axis=1)
        per_class = {c: binary((yy == c).astype(int), qq[:, i]) for i, c in enumerate(categories)}
        supported = [m['AP'] for m in per_class.values() if min(m['positive'], m['negative']) >= 5]
        output['shape'][stage] = {'per_class': per_class,
            'macro_AP_min5': float(np.mean(supported)) if supported else None,
            'top_choice_accuracy': float((np.array(categories)[qq.argmax(1)] == yy).mean()) if len(yy) else None,
            'test_records': len(yy), 'supported_classes': len(supported)}
    primary_y = hair.copy(); primary_y[splits != 'test'] = np.nan
    primary, strata = hair_endpoint(primary_y, q, ds)
    output['primary_hair_macro_AP'] = primary
    output['primary_datasets'] = strata
    return output, primary_y


def validate_shard(identity, meta, protocol, canonical=None):
    """Require the complete declared model grid and identical checkpoints per shard."""
    expected = {'primary-baseline-0'} | {
        f'primary-{mode}-{seed}' for mode in protocol['modes'] if mode != 'baseline'
        for seed in protocol['seeds']}
    if set(identity['models']) != set(protocol['encoders']):
        raise ValueError('Shard has an incomplete encoder grid')
    for encoder in protocol['encoders']:
        names = [m['name'] for m in identity['models'][encoder]]
        if set(names) != expected or len(names) != len(expected):
            raise ValueError('Shard has an incomplete or repeated model grid')
        required = {encoder+'/'+name+'.npz' for name in expected}
        if not required <= meta['sha256'].keys():
            raise ValueError('Prediction files missing from shard hash manifest')
    if identity.get('preflight_limit'):
        raise ValueError('Preflight inference cannot be scored as a full benchmark')
    if canonical is not None:
        for key in ['models', 'source_sha256', 'dependencies', 'detector',
                    'encoder_manifests_sha256', 'shards']:
            if identity[key] != canonical[key]:
                raise ValueError('Incompatible inference shards: '+key)


def score(a):
    protocol = json.loads((a.benchmark / 'protocol.json').read_text())
    for f, h in protocol['sha256'].items():
        if digest(a.benchmark / f) != h:
            raise ValueError('Changed frozen benchmark')
    if not a.overlap.exists():
        raise ValueError('Image overlap audit is required before scoring')
    audit = json.loads(a.overlap.read_text())
    if audit['images_manifest_sha256'] != digest(a.benchmark / 'images.jsonl'):
        raise ValueError('Wrong image overlap audit')
    records = read_rows(a.benchmark / 'records.jsonl')
    images = read_rows(a.benchmark / 'images.jsonl')
    annotations = read_rows(a.benchmark / 'annotations.jsonl')
    excluded = set(audit['excluded_cultivars'])
    keep = np.array([r['cultivar_id'] not in excluded for r in records])
    # Merge all shards in the original image order, checking every prediction hash.
    ids = {r['image_file']: i for i, r in enumerate(images)}
    predictions = {}; detected = np.zeros(len(images), bool); seen = set(); manifests = {}
    canonical = None; shard_ids = set()
    for folder in sorted(a.inference.glob('shard-*')):
        meta = json.loads((folder / 'complete.json').read_text())
        for name, h in meta['sha256'].items():
            if digest(folder / name) != h:
                raise ValueError('Changed inference output: '+name)
        identity = json.loads((folder / 'inference.json').read_text())
        if identity['protocol_sha256'] != digest(a.benchmark / 'protocol.json'):
            raise ValueError('Inference used another protocol')
        validate_shard(identity, meta, protocol, canonical)
        if canonical is None: canonical = identity
        shard_id, shard_count = identity['shard_index'], identity['shards']
        if not 0 <= shard_id < shard_count or shard_id in shard_ids:
            raise ValueError('Invalid or repeated shard index')
        shard_ids.add(shard_id)
        manifests[folder.name] = digest(folder / 'complete.json')
        rows = read_rows(folder / 'images.jsonl')
        if rows != images[shard_id::shard_count]:
            raise ValueError('Shard does not contain its complete assigned image slice')
        positions = []
        for r in rows:
            i = ids[r['image_file']]
            if i in seen or r != images[i]: raise ValueError('Repeated or inconsistent image')
            seen.add(i); positions.append(i)
        mask = np.load(folder / 'detected.npy')
        if mask.shape != (len(rows),) or mask.dtype != np.bool_:
            raise ValueError('Invalid detector coverage mask')
        detected[positions] = mask
        for encoder in protocol['encoders']:
            for model in identity['models'][encoder]:
                key = encoder + '/' + model['name']
                arrays = np.load(folder / encoder / (model['name']+'.npz'))
                if key not in predictions:
                    predictions[key] = {v: np.zeros((len(images), 36), np.float32) for v in protocol['views']}
                for view in protocol['views']:
                    values = arrays[view]
                    if values.shape != (len(rows), 36) or not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
                        raise ValueError('Invalid probability array')
                    predictions[key][view][positions] = values
    if canonical is None or shard_ids != set(range(canonical['shards'])) or len(seen) != len(images):
        raise ValueError('Incomplete inference')
    if len(predictions) != 38: raise ValueError('Missing declared models')
    # Preserve every individual seed and add the predeclared probability ensemble.
    for encoder in protocol['encoders']:
        for mode in protocol['modes']:
            if mode == 'baseline': continue
            keys = [f'{encoder}/primary-{mode}-{s}' for s in protocol['seeds']]
            predictions[f'{encoder}/ensemble-{mode}'] = {
                v: np.mean([predictions[k][v] for k in keys], axis=0) for v in protocol['views']}
    results = {}; record_predictions = {}; primary_y = None
    kept_records = [r for r, yes in zip(records, keep) if yes]
    kept_keys = {(r['dataset_id'], r['record_id']) for r in kept_records}
    kept_annotations = [r for r in annotations if (r['dataset_id'], r['record_id']) in kept_keys]
    for name, views in predictions.items():
        results[name] = {}; record_predictions[name] = {}
        for view, values in views.items():
            q, coverage = aggregate(records, images, values, detected if view == 'detected_leaf' else np.ones(len(images), bool))
            q, coverage = q[keep], coverage[keep]
            results[name][view] = {}
            for reference in ['strict_target', 'all_target']:
                result, y = evaluate(kept_records, kept_annotations, q, coverage, reference)
                results[name][view][reference] = result
                if reference == 'strict_target': primary_y = y
            record_predictions[name][view] = q
    comparisons = {}
    ds = np.array([r['dataset_id'] for r in kept_records]); cultivars = np.array([r['cultivar_id'] for r in kept_records])
    for encoder in protocol['encoders']:
        comparisons[encoder] = {}
        for first, second in [('flora', 'baseline'), ('combined', 'teacher'), ('flopo', 'combined'), ('combined', 'shuffled_profiles')]:
            ka = f'{encoder}/ensemble-{first}'
            kb = f'{encoder}/primary-baseline-0' if second == 'baseline' else f'{encoder}/ensemble-{second}'
            comparisons[encoder][first+' minus '+second] = paired_bootstrap(primary_y,
                record_predictions[ka]['detected_leaf'], record_predictions[kb]['detected_leaf'], ds, cultivars)
    a.out.mkdir(parents=True, exist_ok=False)
    output = {'protocol_sha256': digest(a.benchmark / 'protocol.json'), 'scoring_source_sha256': digest(__file__),
              'overlap_audit_sha256': digest(a.overlap), 'inference_manifests': manifests,
              'excluded_cultivars': sorted(excluded), 'records_evaluated': len(kept_records),
              'reference': 'Independent human photo-set annotations; no taxon profiles or teacher predictions as truth.',
              'results': results, 'paired_primary_comparisons': comparisons}
    (a.out / 'results.json').write_text(json.dumps(output, indent=2, allow_nan=False)+'\n')
    np.savez_compressed(a.out / 'record-predictions.npz',
                        **{n+'__'+v: x for n, views in record_predictions.items() for v, x in views.items()})
    (a.out / 'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in kept_records))
    print(json.dumps(comparisons, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ['benchmark', 'inference', 'overlap', 'out']:
        p.add_argument('--'+n, type=Path, required=True)
    score(p.parse_args())


if __name__ == '__main__': main()
