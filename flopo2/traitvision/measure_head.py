"""Measured colour, with the naming learned from the floras (no observer label is used for training).

The block histogram of the flower boxes of an observation (``colour_measure.py``) is the input; a linear map
to the nine flower colours is fitted to what the floras say about the species (the set loss of ``train.py``),
on the observations of four fifths of the genera, and scored on the colour that observers entered for the
other fifth. Next to it: the trained head on the whole photograph, and both together.

    python -m flopo2.traitvision.measure_head local-corpora/trait-vision [colour-segment-field.npz]
"""
import collections
import csv
import glob
import json
import sys
from pathlib import Path

import numpy as np
import torch

from flopo2.traitvision.score_consensus import balanced, bucket

CLASSES = ['blue', 'brown', 'green', 'orange', 'pink', 'purple', 'red', 'white', 'yellow']


def fit(x, target, epochs=300, seed=0):
    torch.manual_seed(seed)
    x, target = torch.from_numpy(x), torch.from_numpy(target)
    head = torch.nn.Linear(x.shape[1], target.shape[1])
    opt = torch.optim.AdamW(head.parameters(), lr=0.05, weight_decay=1e-3)
    single = target.sum(1) == 1
    freq = target[single].sum(0).clamp(min=1)
    w = ((freq.sum() / freq / len(freq)) * target).max(1).values
    for _ in range(epochs):
        logp = torch.log_softmax(head(x), 1)
        loss = -(torch.logsumexp(logp + torch.log(target + 1e-12), 1) * w).sum() / w.sum()
        opt.zero_grad(); loss.backward(); opt.step()
    return head


def main(folder, measure='colour-measure-field.npz'):
    folder = Path(folder)
    z = np.load(folder / measure)
    masks = 'ring_hist' in z                                # petal masks (segment_colour.py): inside the outline / rest of the box
    ch = z['hist'] if masks else z['centre_hist']
    ring = z['ring_hist'] if masks else None
    bgh = None if masks else z['bg_hist']
    by_photo = collections.defaultdict(list)
    for n, c in enumerate(z['crop_ids']):
        by_photo[int(c) // 16].append(n)
    bg = {} if masks else {int(p): n for n, p in enumerate(z['bg_photo'])}
    flora = {r['taxon']: set(r['allowed'].split('|')) & set(CLASSES)
             for r in csv.DictReader(open(folder / 'colour-labels-v4.tsv'), delimiter='\t') if r['trait'] == 'flower_colour' and r['allowed']}
    model = {}
    for base in sorted(glob.glob(str(folder / 'varms' / 'fold-*' / 'base-flower_colour.npz'))):
        f = int(Path(base).parent.name.split('-')[-1])
        b = np.load(base)
        model[f] = ({int(p): n for n, p in enumerate(b['field_ids'])},
                    np.load(Path(base).parent / 'pred-flower_colour-plain-s0.npz')['field_prob'].astype(np.float32))
    feats, obs = [], []
    for r in csv.DictReader(open(folder / 'field-test-v3.tsv'), delimiter='\t'):
        if r['trait'] != 'flower_colour' or r['class'] not in CLASSES:
            continue
        photos = [int(x) for x in r['photos'].split('|')]
        rows = [n for p in photos for n in by_photo.get(p, ())]
        f = next(k for k in model if (bucket(r['taxon'].split()[0]) - 2 * k) % 10 < 2)
        mrow = [model[f][0][p] for p in photos if p in model[f][0]]
        if not rows or not mrow:
            continue
        inside = ch[rows].mean(0)
        if masks:
            back = ring[rows].mean(0)
        else:
            back = np.mean([bgh[bg[p]] for p in photos if p in bg], 0) if any(p in bg for p in photos) else np.zeros_like(inside)
        feats.append(np.concatenate([inside, inside - back]) * 10)
        obs.append((r['class'], r['taxon'], f, model[f][1][mrow].mean(0)))
    x = np.array(feats, np.float32)
    res = collections.defaultdict(list)
    weights = []
    for fold in sorted(model):
        test = np.array([o[2] == fold for o in obs])
        train = np.array([o[2] != fold and bool(flora.get(o[1])) for o in obs])
        target = np.zeros((len(obs), len(CLASSES)), np.float32)
        for n, o in enumerate(obs):
            for c in flora.get(o[1], ()):
                target[n, CLASSES.index(c)] = 1
        head = fit(x[train], target[train])
        weights.append(head.weight.detach().numpy())
        with torch.no_grad():
            p = torch.softmax(head(torch.from_numpy(x[test])), 1).numpy()
        for (value, taxon, _, mp), q in zip([o for o, t in zip(obs, test) if t], p):
            res['measured, naming learned from floras'].append((value, CLASSES[int(q.argmax())]))
            res['trained head on the photograph'].append((value, CLASSES[int(mp.argmax())]))
            res['both'].append((value, CLASSES[int((np.log(mp + 1e-4) + np.log(q + 1e-4)).argmax())]))
            fl = flora.get(taxon)
            if fl and len(fl) == 1:
                res['flora of the species (one colour stated)'].append((value, next(iter(fl))))
                res['  same observations: both'].append((value, CLASSES[int((np.log(mp + 1e-4) + np.log(q + 1e-4)).argmax())]))
    out = {}
    for name, pairs in res.items():
        tot, hit = collections.Counter(t for t, _ in pairs), collections.Counter(t for t, p in pairs if t == p)
        out[name] = {'balanced': balanced(pairs)[0], 'accuracy': float(np.mean([t == p for t, p in pairs])), 'n': len(pairs)}
        print(f"{name:42s} n={len(pairs):5d} balanced {out[name]['balanced']:.3f} plain {out[name]['accuracy']:.3f}  "
              + ' '.join(f'{c[:3]} {hit[c] / tot[c]:.2f}' for c in CLASSES if tot[c]))
    np.save(folder / (Path(measure).stem + '-naming.npy'), np.mean(weights, 0))
    (folder / (Path(measure).stem + '-head-scores.json')).write_text(json.dumps(out, indent=1) + '\n')


if __name__ == '__main__':
    main(*sys.argv[1:3])
