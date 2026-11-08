"""Exploratory paired intervals for every declared pxGPT secondary view/task.

This analysis is added after inspecting the complete primary report. It leaves
that report unchanged and must not be presented as a confirmatory primary test.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from .benchmark import SHAPES, average_precision
from .benchmark_score import evaluate, paired_bootstrap
from .extract import digest


PAIRS = [('flora', 'baseline'), ('combined', 'teacher'),
         ('flopo', 'combined'), ('combined', 'shuffled_profiles')]


def shape_endpoint(truth, probabilities, datasets, groups):
    values = []
    for ds, categories in groups.items():
        valid = (datasets == ds) & (truth != '')
        per_class = []
        for category in categories:
            y = (truth[valid] == category).astype(int)
            scores = probabilities[valid][:, SHAPES[ds][category]].max(axis=1)
            ap = average_precision(y, scores)
            if ap is None: return None
            per_class.append(ap)
        values.append(float(np.mean(per_class)))
    return float(np.mean(values)) if values else None


def shape_comparison(truth, qa, qb, datasets, cultivars, groups, repetitions=2000):
    included = (truth != '') & np.isin(datasets, list(groups))
    truth, qa, qb, datasets, cultivars = (x[included] for x in (truth, qa, qb, datasets, cultivars))
    aa = shape_endpoint(truth, qa, datasets, groups); bb = shape_endpoint(truth, qb, datasets, groups)
    if aa is None or bb is None: return {'difference': None, 'CI95': None}
    unique = sorted(set(cultivars)); clusters = {c: np.flatnonzero(cultivars == c) for c in unique}
    rng = np.random.default_rng(20261028); differences = []
    for _ in range(repetitions):
        indices = np.concatenate([clusters[c] for c in rng.choice(unique, len(unique), replace=True)])
        a = shape_endpoint(truth[indices], qa[indices], datasets[indices], groups)
        b = shape_endpoint(truth[indices], qb[indices], datasets[indices], groups)
        if a is not None and b is not None: differences.append(a-b)
    return {'first_macro_AP': aa, 'second_macro_AP': bb, 'difference': aa-bb,
            'CI95': np.quantile(differences, [.025, .975]).tolist() if differences else None,
            'valid_replicates': len(differences), 'requested_replicates': repetitions,
            'groups': groups, 'test_sets': len(truth), 'cultivars': len(unique)}


def run(a):
    result = json.loads((a.results / 'results.json').read_text())
    if result['protocol_sha256'] != digest(a.benchmark / 'protocol.json'):
        raise ValueError('Wrong benchmark protocol')
    records = [json.loads(s) for s in (a.results / 'records.jsonl').read_text().splitlines()]
    annotations = [json.loads(s) for s in (a.benchmark / 'annotations.jsonl').read_text().splitlines()]
    keys = {(r['dataset_id'], r['record_id']): i for i, r in enumerate(records)}
    annotations = [r for r in annotations if (r['dataset_id'], r['record_id']) in keys]
    datasets = np.array([r['dataset_id'] for r in records])
    cultivars = np.array([r['cultivar_id'] for r in records])
    truth = np.full(len(records), '', object)
    for r in annotations:
        i = keys[r['dataset_id'], r['record_id']]
        if r['task'] == 'shape' and r['strict_target'] is not None and records[i]['split'] == 'test':
            truth[i] = r['strict_target']
    groups = {}
    for ds, categories in SHAPES.items():
        y = truth[(datasets == ds) & (truth != '')]
        supported = [c for c in categories if min(int((y == c).sum()), int((y != c).sum())) >= 5]
        if supported: groups[ds] = supported
    arrays = np.load(a.results / 'record-predictions.npz')
    comparisons = {}
    for encoder in ['fgclip2', 'bioclip2']:
        comparisons[encoder] = {}
        for view in ['detected_leaf', 'whole_image']:
            comparisons[encoder][view] = {}
            for task in ['hair', 'shape']:
                if task == 'hair' and view == 'detected_leaf': continue  # already primary
                comparisons[encoder][view][task] = {}
                for first, second in PAIRS:
                    ka = f'{encoder}/ensemble-{first}__{view}'
                    kb = f'{encoder}/primary-baseline-0__{view}' if second == 'baseline' else f'{encoder}/ensemble-{second}__{view}'
                    qa, qb = arrays[ka], arrays[kb]
                    if task == 'shape':
                        value = shape_comparison(truth, qa, qb, datasets, cultivars, groups)
                    else:
                        _, hair = evaluate(records, annotations, qa, np.ones(len(records)))
                        value = paired_bootstrap(hair, qa, qb, datasets, cultivars)
                    comparisons[encoder][view][task][first+' minus '+second] = value
                    print(encoder, view, task, first+' minus '+second, value['difference'], value['CI95'], flush=True)
    report = {'analysis_role': 'Exploratory intervals computed after inspection of the complete primary point estimates. All declared secondary views and both encoders reported, not a selected winner.',
              'method': 'Equal-dataset mean of within-dataset macro AP; fixed eligible classes; paired cultivar bootstrap. Nominal 95% intervals, not adjusted for multiple comparisons.',
              'primary_results_sha256': digest(a.results / 'results.json'),
              'record_predictions_sha256': digest(a.results / 'record-predictions.npz'),
              'source_sha256': digest(__file__), 'comparisons': comparisons}
    a.out.write_text(json.dumps(report, indent=2)+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ['benchmark', 'results', 'out']: p.add_argument('--'+n, type=Path, required=True)
    run(p.parse_args())


if __name__ == '__main__': main()
