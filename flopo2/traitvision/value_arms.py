"""On/off test of the colour value space in training (frozen embeddings, one linear head per arm).

Same data, same held-out genera, same loss as ``train.py`` (-log of the probability mass on the target);
only the target changes:

* ``plain``    1 on the basic colours a flora states with a value term (the labels used so far);
* ``ends``     also 1 on the two ends of "X to Y" statements (read as "X or Y");
* ``range``    also 1 on the colours between the two ends;
* ``near<S>``  ``plain``, and exp(-(d/S)^2) on every other colour, d = colour distance to the nearest stated value;
* ``range+near<S>``  both.

Every genus is held out in one of five runs; the predictions for the photographs of the held-out genera are
written per arm and seed, and scored elsewhere (``score_arms.py``).

    python value_arms.py --data DIR --out DIR/varms      (standalone: numpy + torch; needs train.py beside it)
"""
import argparse
import collections
import csv
import json
from pathlib import Path

import numpy as np
import torch

import train as T


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--labels', default='colour-labels-v4.tsv')
    p.add_argument('--photos', default='inat-photos-v3.tsv')
    p.add_argument('--field', default='field-test-v3.tsv')
    p.add_argument('--emb', default='emb')
    p.add_argument('--seeds', type=int, default=3)
    p.add_argument('--sigmas', default='8,12,16')
    p.add_argument('--folds', default='0,1,2,3,4')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    emb, ids = T.load_embeddings(a.data / a.emb)
    keys, text = T.text_embeddings(a.data / a.emb)
    row_of = {int(i): n for n, i in enumerate(ids)}
    photo_taxon = {}
    for r in csv.DictReader(open(a.data / a.photos), delimiter='\t'):
        if int(r['photo_id']) in row_of:
            photo_taxon[int(r['photo_id'])] = r['taxon']
    femb, fids = T.load_embeddings(a.data / (a.emb + '-field'))
    labels = collections.defaultdict(dict)
    for r in csv.DictReader(open(a.data / a.labels), delimiter='\t'):
        split = lambda k: set(filter(None, r[k].split('|')))
        dist = lambda k: {x.split(':')[0]: float(x.split(':')[1]) for x in split(k)}
        labels[r['trait']][r['taxon']] = (split('allowed'), split('to_ends'), split('to_between'), dist('dist'), dist('dist_all'))
    sigmas = [float(s) for s in a.sigmas.split(',')]
    arms = [('plain', 0, None), ('ends', 1, None), ('range', 2, None)]
    arms += [(f'near{s:g}', 0, s) for s in sigmas] + [(f'range+near{s:g}', 2, s) for s in sigmas]
    summary = {}
    for trait, lab in sorted(labels.items()):
        classes = sorted(c for c in {c for v in lab.values() for c in v[0]} if f'zs:{trait}:{c}' in keys)
        cidx = {c: i for i, c in enumerate(classes)}
        pid = np.array([i for i, t in photo_taxon.items() if t in lab])
        rows = np.array([row_of[i] for i in pid])
        taxa = np.array([photo_taxon[i] for i in pid])
        x_all = torch.from_numpy(emb[rows]).to(device)
        zt = np.stack([text[keys.index(f'zs:{trait}:{c}')] for c in classes])
        # the three hard targets and the distance of every photo's species to every class
        hard = np.zeros((3, len(pid), len(classes)), np.float32)
        dist = np.full((2, len(pid), len(classes)), 1e6, np.float32)        # from the plain values; from all stated values
        tcache = {}
        for n, t in enumerate(taxa):
            if t not in tcache:
                al, ends, mid, d, d_all = lab[t]
                h = np.zeros((3, len(classes)), np.float32)
                for level, group in enumerate((al, al | ends, al | ends | mid)):
                    h[level, [cidx[c] for c in group if c in cidx]] = 1
                dd = np.array([[d.get(c, 1e6) for c in classes], [d_all.get(c, 1e6) for c in classes]], np.float32)
                tcache[t] = (h, dd)
            hard[:, n], dist[:, n] = tcache[t]
        for fold in (int(f) for f in a.folds.split(',')):
            bk = np.array([(T.bucket(t.split()[0]) - 2 * fold) % 10 for t in taxa])
            tr, va, held = bk >= 2, bk == 1, bk < 2
            outdir = a.out / f'fold-{fold}'
            outdir.mkdir(exist_ok=True)
            np.savez(outdir / f'base-{trait}.npz', classes=np.array(classes), photo_ids=pid[held], field_ids=fids,
                     zero_shot=torch.softmax(torch.from_numpy(emb[rows][held] @ zt.T) * 100, 1).numpy().astype(np.float16))
            for name, level, sigma in arms:
                target = hard[level].copy()
                if sigma:
                    target = np.maximum(target, np.exp(-(dist[1 if level else 0] / sigma) ** 2).astype(np.float32))
                use = tr & (hard[level].sum(1) > 0)
                h = hard[level][use]
                per_taxon = collections.Counter(taxa[use])
                freq = np.maximum(h[h.sum(1) == 1].sum(0), 1)
                cw = (freq.sum() / freq / len(classes)).astype(np.float32)
                weight = np.array([1 / per_taxon[t] for t in taxa[use]], np.float32) * (h * cw).max(1)
                for seed in range(a.seeds):
                    head = T.fit(emb[rows][use], target[use], weight, len(classes), device, seed=seed)
                    with torch.no_grad():
                        prob = torch.softmax(head(x_all[torch.from_numpy(held).to(device)]), 1).cpu().numpy()
                        fprob = torch.softmax(head(torch.from_numpy(femb).to(device)), 1).cpu().numpy()
                    np.savez(outdir / f'pred-{trait}-{name}-s{seed}.npz', prob=prob.astype(np.float16),
                             field_prob=fprob.astype(np.float16))
                    # validation genera, species with one stated colour (plain labels): balanced accuracy
                    vt = taxa[held][va[held]]
                    agg = T.aggregate(prob[va[held]], np.ones(len(vt), np.float32), vt)
                    vtaxa = sorted(t for t in agg if lab[t][0] & set(classes))
                    bal, _ = T.balanced_accuracy([int(np.argmax(agg[t])) for t in vtaxa],
                                                 [{cidx[c] for c in lab[t][0] if c in cidx} for t in vtaxa], classes)
                    summary.setdefault(trait, {}).setdefault(name, []).append(bal)
                    print(trait, 'fold', fold, name, 'seed', seed, 'train species', len(per_taxon), 'photos', int(use.sum()),
                          'validation', round(bal, 3), flush=True)
    (a.out / 'validation.json').write_text(json.dumps(summary, indent=1) + '\n')
    for trait, s in summary.items():
        print(trait, {k: round(float(np.mean(v)), 3) for k, v in s.items()})


if __name__ == '__main__':
    main()
