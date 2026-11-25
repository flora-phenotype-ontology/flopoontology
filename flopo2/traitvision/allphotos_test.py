"""Does it help to use every photograph of an observation, and to know which photograph shows the organ?

For the observations with an observer's value (all their photographs, ``field-obs-photos.tsv``), the heads
trained on flora labels (``folds/run-fold-K/head-<trait>.pt``; the run that held the genus out) predict every
photograph; the observation's prediction is then pooled in several ways:

  first two        mean over the first two photographs (what was downloaded before)
  all              mean over all photographs
  organ, else all  mean over the photographs with a detected box of the trait's organ; all when there is none
  organ weighted   every photograph weighted by its best box score for the organ (plus a small constant)
  best photo       the single most confident photograph

Scored against the observer's value, for all observations and for those with three or more photographs.

    python -m flopo2.traitvision.allphotos_test local-corpora/trait-vision
"""
import collections
import csv
import sys
from pathlib import Path

import numpy as np
import torch

from flopo2.traitvision.score_consensus import balanced, bucket

ORGAN = {'flower_colour': {'flower'}, 'fruit_colour': {'fruit'}, 'leaf_margin': {'leaf'}, 'leaf_complexity': {'leaf'},
         'leaf_arrangement': {'leaf', 'stem'}, 'spines': {'thorn', 'stem'}, 'habit': set()}


def main(folder):
    folder = Path(folder)
    embs, ids = [], []
    for f in sorted((folder / 'emb-field').glob('emb-*.npy')):
        embs.append(np.load(f).astype(np.float32))
        ids += [int(x) for x in f.with_suffix('.ids').read_text().split()]
    emb = np.concatenate(embs)
    row = {p: n for n, p in enumerate(ids)}
    score = collections.defaultdict(dict)                     # organ -> photo -> best box score
    for f in sorted(folder.glob('field-boxes*.tsv')):
        for r in csv.DictReader(open(f), delimiter='\t'):
            p = int(r['photo_id'])
            score[r['organ']][p] = max(score[r['organ']].get(p, 0), float(r['score']))
    photos = collections.defaultdict(list)
    for r in csv.DictReader(open(folder / 'field-obs-photos.tsv'), delimiter='\t'):
        if int(r['photo_id']) in row:
            photos[r['observation']].append((int(r['position']), int(r['photo_id'])))
    heads = {}
    for trait in ORGAN:
        res = collections.defaultdict(list)
        for r in csv.DictReader(open(folder / 'field-test-v3.tsv'), delimiter='\t'):
            if r['trait'] != trait:
                continue
            fold = next(k for k in range(5) if (bucket(r['taxon'].split()[0]) - 2 * k) % 10 < 2)
            if (trait, fold) not in heads:
                h = torch.load(folder / 'folds' / f'run-fold-{fold}' / f'head-{trait}.pt', map_location='cpu')
                w, b = h['state']['weight'].numpy(), h['state']['bias'].numpy()
                z = emb @ w.T + b
                z = np.exp(z - z.max(1, keepdims=True))
                heads[trait, fold] = (z / z.sum(1, keepdims=True), list(h['classes']))
            prob, classes = heads[trait, fold]
            ph = [p for _, p in sorted(photos.get(r['observation'], []))]
            if not ph or r['class'] not in classes:
                continue
            p = prob[[row[x] for x in ph]]
            s = np.array([max([score[o].get(x, 0) for o in ORGAN[trait]] or [0]) for x in ph])
            has = s >= 0.3
            pools = {'first two': p[:2].mean(0), 'all': p.mean(0),
                     'organ, else all': p[has].mean(0) if has.any() else p.mean(0),
                     'organ weighted': ((s + 0.05)[:, None] * p).sum(0),
                     'best photo': p[p.max(1).argmax()]}
            for name, v in pools.items():
                pred = classes[int(v.argmax())]
                res[name, 'all'].append((r['class'], pred))
                if len(ph) >= 3:
                    res[name, '3+'].append((r['class'], pred))
                if ORGAN[trait] and has.any() and not has.all():
                    res[name, 'mixed'].append((r['class'], pred))
        if not res:
            continue
        n = lambda g: len(res['all', g])
        print(f"\n{trait}: observations {n('all')}; with 3+ photographs {n('3+')}; organ in some photographs only {n('mixed')}")
        for name in ('first two', 'all', 'organ, else all', 'organ weighted', 'best photo'):
            print(f"  {name:16s} all {balanced(res[name, 'all'])[0]:.3f}   3+ photographs {balanced(res[name, '3+'])[0]:.3f}"
                  + (f"   organ in some only {balanced(res[name, 'mixed'])[0]:.3f}" if res[name, 'mixed'] else ''))


if __name__ == '__main__':
    main(sys.argv[1])
