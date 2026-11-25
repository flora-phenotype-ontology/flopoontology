"""Flora labels, all photographs of every observation, the organ at both ends (MLP head, one bag per species).

Three choices of photographs, made the same way for training and for testing:

* ``first two``        the first two photographs of an observation (the set used so far);
* ``all``              every photograph;
* ``organ, else all``  the photographs with a detected box of the trait's organ; all of a species' (or an
                       observation's) photographs when it has none.

Held-out genera, five folds. Tests: species on which 2+ floras agree (photographs pooled per species) and
observers' labels (photographs pooled per observation). Every training choice is scored under every test choice.

    python allphotos_train.py --data DIR --out DIR/allphotos [--traits a,b]      (needs train.py, regime_tests.py)
"""
import argparse
import collections
import csv
import json
from pathlib import Path

import numpy as np
import torch

import regime_tests as R
import train as T

SETS = ('first two', 'all', 'organ, else all')
DEV = R.DEV


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--traits', default='')
    p.add_argument('--folds', default='0,1,2,3,4')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--pheno', type=Path, help='phenology-scores.npz: a photograph shows fruit when its fruiting score passes --thr')
    p.add_argument('--thr', type=float, default=0.5)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    D = a.data
    emb, ids = T.load_embeddings(D / 'emb')
    keys, _ = T.text_embeddings(D / 'emb')
    row_of = {}
    for n, i in enumerate(ids):
        row_of.setdefault(int(i), n)
    first_two = {int(r['photo_id']) for r in csv.DictReader(open(D / 'inat-photos-v3.tsv'), delimiter='\t')}
    photo_taxon = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t')
                   if int(r['photo_id']) in row_of}
    femb, fids = T.load_embeddings(D / 'emb-field')
    frow = {}
    for n, i in enumerate(fids):
        frow.setdefault(int(i), n)
    femb_t = torch.from_numpy(femb).to(DEV)
    labels = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'pilot-labels-v3.tsv'), delimiter='\t'):
        labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    agreed = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'agreed-v3.tsv'), delimiter='\t'):
        if int(r['floras']) >= 2:
            agreed[r['trait']][r['taxon']] = r['value']
    organ = collections.defaultdict(set)
    for f in sorted((D / 'crops-v3').glob('boxes-*.tsv')) + [D / 'crops-field' / 'boxes-0.tsv', D / 'crops-field' / 'boxes-rest.tsv']:
        for r in csv.DictReader(open(f), delimiter='\t'):
            organ[r['organ']].add(int(r['photo_id']))
    if a.pheno:                                            # fruit: from the phenology head instead of the detector
        z = np.load(a.pheno)
        k = list(z['values']).index('fruiting')
        organ['fruit'] = {int(i) for i in z['ids'][z['prob'][:, k] > a.thr]} | {int(i) for i in z['field_ids'][z['field_prob'][:, k] > a.thr]}
    obs_photos = collections.defaultdict(list)
    for r in csv.DictReader(open(D / 'field-obs-photos.tsv'), delimiter='\t'):
        if int(r['photo_id']) in frow:
            obs_photos[r['observation']].append((int(r['position']), int(r['photo_id'])))
    field = collections.defaultdict(list)
    for r in csv.DictReader(open(D / 'field-test-v3.tsv'), delimiter='\t'):
        ph = [q for _, q in sorted(obs_photos.get(r['observation'], []))]
        if ph:
            field[r['trait']].append((r['class'], r['taxon'].split()[0], ph))
    want = [t for t in sorted(labels) if not a.traits or t in a.traits.split(',')]
    report = {}
    for trait in want:
        lab = labels[trait]
        classes = sorted(c for c in {c for s in lab.values() for c in s} if f'zs:{trait}:{c}' in keys)
        cidx = {c: i for i, c in enumerate(classes)}
        C = len(classes)
        lab = {t: s & set(classes) for t, s in lab.items() if s & set(classes)}
        pid = np.array([i for i, t in photo_taxon.items() if t in lab])
        taxa = np.array([photo_taxon[i] for i in pid])
        gb = np.array([T.bucket(t.split()[0]) for t in taxa])
        x = torch.from_numpy(emb[[row_of[i] for i in pid]]).to(DEV)
        boxes = R.ORGAN_BOX.get(trait) or set()
        has = lambda i: any(i in organ[o] for o in boxes)
        is_first = np.array([int(i) in first_two for i in pid])
        has_box = np.array([has(int(i)) for i in pid]) if boxes else np.ones(len(pid), bool)
        names, inv = np.unique(taxa, return_inverse=True)
        any_box = np.zeros(len(names), bool)
        np.logical_or.at(any_box, inv, has_box)
        masks = {'first two': is_first, 'all': np.ones(len(pid), bool), 'organ, else all': has_box | ~any_box[inv]}
        tset = {t: np.array([1.0 if c in lab[t] else 0 for c in classes], np.float32) for t in names}
        obs = [(v, g, ph) for v, g, ph in field[trait] if v in cidx]

        def choose(ph, how):
            if how == 'first two':
                return ph[:2]
            if how == 'organ, else all' and boxes:
                return [q for q in ph if has(q)] or ph
            return ph
        print(trait, 'species', len(names), 'photos', {k: int(m.sum()) for k, m in masks.items()}, 'observations', len(obs), flush=True)
        pairs = collections.defaultdict(list)
        for fold in (int(f) for f in a.folds.split(',')):
            bk = (gb - 2 * fold) % 10
            tr, held = bk >= 2, bk < 2
            fobs = [o for o in obs if (T.bucket(o[1]) - 2 * fold) % 10 < 2]
            for how in SETS:
                use = tr & masks[how]
                sp, sinv = np.unique(taxa[use], return_inverse=True)
                idx = np.flatnonzero(use)
                order = np.argsort(sinv, kind='stable')
                start = np.r_[0, np.flatnonzero(np.diff(sinv[order])) + 1, len(order)]
                m = int(min(np.bincount(sinv).max(), 64))
                member = np.stack([np.resize(idx[order[start[k]:start[k + 1]]], m) for k in range(len(sp))])
                hard = np.stack([tset[t] for t in sp])
                freq = np.maximum(hard[hard.sum(1) == 1].sum(0), 1)
                spw = torch.from_numpy((hard * (freq.sum() / freq / C)).max(1).astype(np.float32)).to(DEV)
                spt = torch.from_numpy(hard).to(DEV)
                head = R.fit(x, spt, None, 'mlp', 'set', seed=a.seed, bags=(spt, spw, torch.from_numpy(member).to(DEV)))
                ph = R.prob(head, x)
                pf = R.prob(head, femb_t)
                for th in SETS:
                    sel = held & masks[th]
                    g = R.group_mean(ph[torch.from_numpy(sel).to(DEV)], taxa[sel])
                    pairs[how, th, 'agreed'] += [(agreed[trait][t], classes[int(np.argmax(v))]) for t, v in g.items()
                                                 if agreed[trait].get(t) in cidx]
                    for v, _, photos in fobs:
                        r = [frow[q] for q in choose(photos, th)]
                        pairs[how, th, 'observers'].append((v, classes[int(pf[r].mean(0).argmax())]))
                print(trait, 'fold', fold, how, 'species', len(sp), 'photos', int(use.sum()), flush=True)
        out = {}
        for test in ('agreed', 'observers'):
            print(f'{trait} [{test}, n={len(pairs[SETS[0], SETS[0], test])}]   test on: ' + ' | '.join(SETS))
            for how in SETS:
                cells = [R.bal(pairs[how, th, test]) for th in SETS]
                out[f'{test}|{how}'] = dict(zip(SETS, cells))
                print(f'   trained on {how:16s} ' + '   '.join('  -  ' if c is None else f'{c:.3f}' for c in cells), flush=True)
        confusion = {f'{test}|{how}': collections.Counter(f'{t}>{q}' for t, q in pairs[how, how, test]) for test in ('agreed', 'observers') for how in SETS}
        report[trait] = {'confusion': confusion, 'n_agreed': len(pairs[SETS[0], SETS[0], 'agreed']), 'n_observers': len(pairs[SETS[0], SETS[0], 'observers']),
                         'photos': {k: int(m.sum()) for k, m in masks.items()}, 'scores': out}
        (a.out / f'allphotos-s{a.seed}{f"-pheno{a.thr:g}" if a.pheno else ""}{"-" + a.traits.replace(",", "+") if a.traits else ""}.json').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
