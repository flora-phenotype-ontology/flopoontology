"""Score measured flower colour (``colour_measure.py``) against the colour iNaturalist observers entered.

    python -m flopo2.traitvision.score_measure local-corpora/trait-vision

Several ways of reading the colour from the boxes are compared with the trained head (``plain`` arm of
``value_arms.py``, each observation scored by the run that held its genus out) on the same observations.
"""
import collections
import csv
import glob
import json
import sys
from pathlib import Path

import numpy as np

from flopo2.traitvision.score_consensus import balanced, bucket

ROOT = Path(__file__).resolve().parents[2]
FOLD_INTO = {'gray': 'white', 'olive': 'green', 'yellow green': 'green'}


def main(folder):
    folder = Path(folder)
    z = np.load(folder / 'colour-measure-field.npz')
    numbers = [int(b) for b in z['blocks']]
    level1 = {}
    for r in csv.DictReader(open(ROOT / 'config/iscc_nbs_backbone.tsv'), delimiter='\t'):
        if r['level'] == '1':
            for b in r['level3_blocks'].split():
                level1[int(b)] = r['name']
    names13 = sorted(set(level1.values()))
    to13 = np.zeros((len(numbers), len(names13)), np.float32)
    for i, b in enumerate(numbers):
        to13[i, names13.index(level1[b])] = 1
    classes = ['blue', 'brown', 'green', 'orange', 'pink', 'purple', 'red', 'white', 'yellow']
    fold = np.zeros((len(names13), len(classes)), np.float32)      # 13 level-1 colours -> the 9 flower classes
    plainmap = np.zeros_like(fold)
    for i, n in enumerate(names13):
        if FOLD_INTO.get(n, n) in classes:
            fold[i, classes.index(FOLD_INTO.get(n, n))] = 1
        if n in classes:
            plainmap[i, classes.index(n)] = 1
    row = {int(c): n for n, c in enumerate(z['crop_ids'])}
    by_photo = collections.defaultdict(list)
    for c, n in row.items():
        by_photo[c // 16].append(n)
    bg = {int(p): n for n, p in enumerate(z['bg_photo'])}
    centres = z['centres']
    nearest = lambda lab: ((lab[:, None, :] - centres[None]) ** 2).sum(-1).argmin(1)
    onehot = lambda idx: np.eye(len(numbers), dtype=np.float32)[idx]
    h13 = {'box mean colour': onehot(nearest(z['mean'])) @ to13, 'centre mean colour': onehot(nearest(z['centre_mean'])) @ to13,
           'box pixels': z['hist'] @ to13, 'centre pixels': z['centre_hist'] @ to13}
    bg13 = z['bg_hist'] @ to13
    obs = [(r['class'], r['taxon'], [int(x) for x in r['photos'].split('|')])
           for r in csv.DictReader(open(folder / 'field-test-v3.tsv'), delimiter='\t') if r['trait'] == 'flower_colour' and r['class'] in classes]
    model = {}
    for base in sorted(glob.glob(str(folder / 'varms' / 'fold-*' / 'base-flower_colour.npz'))):
        f = int(Path(base).parent.name.split('-')[-1])
        b = np.load(base)
        assert [str(c) for c in b['classes']] == classes
        model[f] = ({int(p): n for n, p in enumerate(b['field_ids'])},
                    np.load(Path(base).parent / 'pred-flower_colour-plain-s0.npz')['field_prob'].astype(np.float32))
    res = collections.defaultdict(list)
    for value, taxon, photos in obs:
        rows = [n for p in photos for n in by_photo.get(p, ())]
        f = next(k for k in model if (bucket(taxon.split()[0]) - 2 * k) % 10 < 2)
        mrow = [model[f][0][p] for p in photos if p in model[f][0]]
        if not rows or not mrow:
            res['no flower box'].append(value)
            continue
        mp = model[f][1][mrow].mean(0)
        res['trained head'].append((value, classes[int(mp.argmax())]))
        scores = {}
        for name, h in h13.items():
            for tag, m in (('', plainmap), (', grey as white, olive as green', fold)):
                scores[name + tag] = h[rows].sum(0) @ m
        # contrast with the background of the same photographs: what the boxes have more of
        b = np.mean([bg13[bg[p]] for p in photos if p in bg], 0) if any(p in bg for p in photos) else np.zeros(len(names13))
        inside = h13['centre pixels'][rows].mean(0)
        scores['centre pixels minus background'] = np.maximum(inside - b, 0) @ fold
        scores['centre pixels minus background, not grey'] = np.maximum(inside - b, 0) @ plainmap
        for name, s in scores.items():
            res[name].append((value, classes[int(s.argmax())]))
        s = scores['centre pixels minus background']
        res['trained head x measured'].append((value, classes[int((np.log(mp + 1e-3) + np.log(s / (s.sum() + 1e-9) + 0.05)).argmax())]))
    print('observations with a colour label:', len(obs), '; without a flower box:', len(res.pop('no flower box', [])))
    out = {}
    for name, pairs in sorted(res.items(), key=lambda kv: -balanced(kv[1])[0]):
        tot, hit = collections.Counter(t for t, _ in pairs), collections.Counter(t for t, p in pairs if t == p)
        out[name] = {'balanced': balanced(pairs)[0], 'accuracy': float(np.mean([t == p for t, p in pairs])), 'n': len(pairs)}
        print(f"{name:55s} balanced {out[name]['balanced']:.3f}  plain {out[name]['accuracy']:.3f}  "
              + ' '.join(f'{c[:3]} {hit[c] / tot[c]:.2f}' for c in classes if tot[c]))
    (folder / 'colour-measure-scores.json').write_text(json.dumps(out, indent=1) + '\n')


if __name__ == '__main__':
    main(sys.argv[1])
