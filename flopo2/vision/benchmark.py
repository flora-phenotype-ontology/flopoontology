"""Prepare and score the independent pxGPT photo-set trait benchmark.

Preparation uses only published human references and codebooks. Predictions are
produced separately; species profiles and the published model outputs are never
evaluation references. All splits are by cultivar across acquisition stages.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from .extract import digest


HAIR_FIELDS = {'seedling': 'leaf_trichome_density',
               'mature_v1': 'leaf_surface_pubescence', 'mature_v2': 'leaf_pubescence'}
HAIR_VALUES = {'seedling': {'1': 0, '2': 1, '3': 1},
               'mature_v1': {'glabrous': 0, 'pubescent': 1},
               'mature_v2': {'0': 0, '1': 1, '2': 1}}
# Complete unions of existing output terms only. In particular, reniform and
# lobed/dissected categories have no complete representation and are excluded.
SHAPES = {
    'seedling': {'ovate': [0], 'orbicular': [22], 'lanceolate': [1],
                 'obovate_spatulate': [14, 29]},
    'mature_v1': {'ovate': [0], 'orbicular': [22], 'lanceolate': [1],
                  'obovate_spatulate': [14, 29]},
    'mature_v2': {'ovate_obovate': [0, 14], 'spatulate': [29],
                  'oblong_elliptic_lanceolate': [2, 10, 1]},
}
EXPECTED = {0: 'leaf ovate', 1: 'leaf lanceolate', 2: 'leaf oblong',
            10: 'leaf elliptic', 12: 'leaf glabrous', 14: 'leaf obovate',
            22: 'leaf orbicular', 29: 'leaf spatulate', 32: 'leaf hairy'}
PRIMARY_MODES = ['baseline', 'flora', 'teacher', 'combined', 'flopo',
                 'shuffled_rules', 'shuffled_profiles']


def read_csv(path):
    with path.open() as handle:
        return list(csv.DictReader(handle))


def split_for(cultivar):
    h = hashlib.sha256(('flopo-pxgpt-v1:' + cultivar).encode()).hexdigest()
    return 'development' if int(h[:16], 16) / 2**64 < .25 else 'test'


def usable(row, strict=True):
    if row['reference_value'] in ('', 'not_assessable'):
        return False
    if strict:
        return (int(row['n_scores']) >= 2 and row['reference_status'] == 'majority'
                and float(row['agreement_fraction']) > .5)
    return row['reference_status'] in ('majority', 'ordinal_median_tiebreak')


def target(row, strict=True):
    if not usable(row, strict):
        return None
    ds = row['dataset_id']
    if row['trait'] == HAIR_FIELDS[ds]:
        return HAIR_VALUES[ds].get(row['reference_value'])
    if row['trait'] == 'leaf_blade_shape' and row['reference_value'] in SHAPES[ds]:
        return row['reference_value']
    return None


def prepare(args):
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / 'protocol.json').exists():
        raise ValueError('Protocol already frozen; use a new version for changes')
    inv = json.loads(args.inventory.read_text())
    for k, name in EXPECTED.items():
        if inv['traits'][k]['label'] != name:
            raise ValueError('Incompatible model vocabulary')
    tables = args.release / 'tables'
    records = read_csv(tables / 'records.csv')
    images = read_csv(tables / 'images.csv')
    refs = read_csv(tables / 'reference_labels.csv')
    manifest = read_csv(args.release / 'manifests/files_manifest.csv')
    # The downloaded release manifest records hashes of the original JPEGs.
    by_path = {r['path']: r for r in manifest}
    scored = {(r['dataset_id'], r['record_id']) for r in refs}
    output = []
    for r in records:
        if (r['dataset_id'], r['record_id']) not in scored:
            continue
        output.append({k: r[k] for k in ('dataset_id', 'record_id', 'cultivar_id')} |
                      {'split': split_for(r['cultivar_id']), 'n_images': int(r['n_images'])})
    expected_keys = {(r['dataset_id'], r['record_id']) for r in output}
    image_rows = []
    for r in images:
        if (r['dataset_id'], r['record_id']) not in expected_keys:
            continue
        image_rows.append({k: r[k] for k in ('dataset_id', 'record_id', 'cultivar_id', 'image_file')} |
                          {'bytes': int(r['bytes']), 'sha512': by_path[r['image_file']]['sha512']})
    annotations = []
    for r in refs:
        task = 'hair' if r['trait'] == HAIR_FIELDS[r['dataset_id']] else 'shape'
        if task == 'shape' and r['trait'] != 'leaf_blade_shape':
            continue
        annotations.append({k: r[k] for k in ('dataset_id', 'record_id', 'cultivar_id', 'trait',
                           'reference_value', 'reference_status', 'n_scores', 'agreement_fraction')} |
                           {'task': task, 'strict_target': target(r), 'all_target': target(r, False)})
    for name, rows in [('records', output), ('images', image_rows), ('annotations', annotations)]:
        (args.out / (name + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (args.out / 'inventory.json').write_text(json.dumps(inv, indent=2) + '\n')
    protocol = {
        'version': 'flopo-pxgpt-v1', 'source': 'https://zenodo.org/records/22907554',
        'goal': 'Evaluate useful FLOPO-derived flora supervision of visible qualitative traits.',
        'records': len(output), 'images': len(image_rows), 'splits': dict(Counter(r['split'] for r in output)),
        'split_policy': 'SHA256 flopo-pxgpt-v1:cultivar_id; first 64 bits below .25 => development. All stages/views stay together.',
        'references': 'Published human scores only. Strict: >=2 raters and >.5 agreement, no ordinal tiebreak. All assessable references are sensitivity only.',
        'primary_endpoint': 'Equal-dataset mean of hairy/glabrous macro AP on strict TEST references; each dataset requires >=5 hairy and >=5 glabrous cases.',
        'primary_comparisons': ['flora minus baseline', 'combined minus teacher'],
        'secondary_comparisons': ['flopo minus combined', 'combined minus shuffled_profiles'],
        'encoders': ['fgclip2', 'bioclip2'], 'modes': PRIMARY_MODES, 'seeds': [20261027, 20261028, 20261029],
        'selection': 'Report all primary arms and seeds. No checkpoint, encoder, mapping or aggregation selection on test results.',
        'hair_indices': {'hairy': 32, 'glabrous': 12}, 'shape_groups': SHAPES,
        'shape_scope': 'Source categorical task restricted to completely represented categories; not complete OWL truth assignments. Max probability within a grouped category; no splitting grouped references.',
        'views': ['detected_leaf', 'whole_image'], 'primary_view': 'detected_leaf',
        'detector': 'Existing pinned detector; leaf. petal. flower. fruit.; threshold .4, text .25; highest selected leaf with both dimensions >=96 pixels.',
        'spatial_features': 'Existing five spatial tiles and pinned encoders; identical views across heads.',
        'aggregation': 'Arithmetic mean across every photograph of a set. Missing leaf detection gives zero evidence for every trait. Whole-image results are secondary.',
        'threshold': 'Maximize balanced accuracy on strict development references when each class has >=5 cases; otherwise .5. Never tune on test.',
        'uncertainty': '2000 paired cultivar-cluster bootstrap replicates, seed 20261028; two-sided 95% percentile intervals, exploratory multiple comparisons.',
        'overlap': 'Brassica tournefortii occurs in fine-tuning; no unseen-genus claim. Audit exact and perceptual image overlap before scoring. Foundation pretraining overlap unknown.',
        'source_tables_sha256': {n: digest(tables / n) for n in ['records.csv', 'images.csv', 'reference_labels.csv', 'human_scores.csv', 'trait_dictionary.csv']},
        'source_sha256': digest(__file__),
        'sha256': {n: digest(args.out / n) for n in ['records.jsonl', 'images.jsonl', 'annotations.jsonl', 'inventory.json']},
    }
    (args.out / 'protocol.json').write_text(json.dumps(protocol, indent=2) + '\n')
    print(json.dumps({k: protocol[k] for k in ['version', 'records', 'images', 'splits']}))


def average_precision(y, p):
    """Tie-grouped noninterpolated AP; undefined without both classes."""
    import numpy as np
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    if not len(y) or y.sum() in (0, len(y)):
        return None
    order = np.argsort(-p, kind='stable'); y, p = y[order], p[order]
    ends = np.r_[np.flatnonzero(p[:-1] != p[1:]), len(p)-1]
    tp = np.cumsum(y)[ends]; added = np.diff(np.r_[0, tp])
    return float(np.sum(added / y.sum() * tp / (ends+1)))


def binary(y, p, threshold=.5):
    import numpy as np
    y, p = np.asarray(y, dtype=int), np.asarray(p)
    pos, neg = int(y.sum()), int((1-y).sum())
    tp, tn = int(((p >= threshold) & (y == 1)).sum()), int(((p < threshold) & (y == 0)).sum())
    return {'positive': pos, 'negative': neg, 'AP': average_precision(y, p),
            'balanced_accuracy': (tp/pos+tn/neg)/2 if pos and neg else None,
            'threshold': float(threshold)}


def fit_threshold(y, p):
    import numpy as np
    y, p = np.asarray(y, int), np.asarray(p, float)
    if (y == 0).sum() < 5 or (y == 1).sum() < 5:
        return .5
    candidates = np.r_[.5, np.unique(p), np.nextafter(p.max(), np.inf)]
    return float(max(candidates, key=lambda t: (binary(y, p, t)['balanced_accuracy'], -abs(t-.5))))


def aggregate(records, images, per_image, detected):
    """Missing detections contribute zero and stay in the photo-set denominator."""
    import numpy as np
    index = {(r['dataset_id'], r['record_id']): i for i, r in enumerate(records)}
    result = np.zeros((len(records), per_image.shape[1]), dtype=np.float64)
    counts = np.zeros(len(records), int); seen = np.zeros(len(records), int)
    for j, r in enumerate(images):
        i = index[(r['dataset_id'], r['record_id'])]
        result[i] += per_image[j] if detected[j] else 0
        counts[i] += 1; seen[i] += int(detected[j])
    if any(counts[i] != r['n_images'] for i, r in enumerate(records)):
        raise ValueError('Incomplete photo-set predictions')
    return result / counts[:, None], seen / counts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    for n in ['release', 'inventory', 'out']:
        prep.add_argument('--'+n, type=Path, required=True)
    a = p.parse_args()
    if a.command == 'prepare':
        prepare(a)


if __name__ == '__main__':
    main()
