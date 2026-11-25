"""Flora labels and observers' labels together, all photographs (MLP head, bags).

Flora labels give one bag per species (the label is a set of allowed values); observers' labels give one bag
per observation (one value). Arms, on the same held-out genera (five folds):

* ``flora``            species bags only;
* ``observers``        observation bags only;
* ``joint<A>``         both; the observation bags together weigh A times the species bags (A = 0.3, 1, 3).

Photographs: those with a detected box of the trait's organ, else all (leaf traits and spines); all photographs
otherwise. Tests: species on which 2+ floras agree, and observers' labels of held-out genera.

    python joint_train.py --data DIR --out DIR/joint [--traits a,b]      (needs train.py, regime_tests.py)
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

ORGAN_SET = {'leaf_margin', 'leaf_complexity', 'leaf_arrangement', 'spines'}
ARMS = (('flora', None), ('observers', None), ('joint0.3', 0.3), ('joint1', 1.0), ('joint3', 3.0))
DEV = R.DEV


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--traits', default='')
    p.add_argument('--folds', default='0,1,2,3,4')
    p.add_argument('--seed', type=int, default=0)
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
        how = 'organ, else all' if trait in ORGAN_SET else 'all'
        mask = masks[how]
        xa = torch.cat([x, femb_t])                                # observers' photographs follow the species' photographs
        off = len(pid)
        print(trait, 'species', len(names), 'photos', int(mask.sum()), 'observations', len(obs), 'photographs:', how, flush=True)
        pairs = collections.defaultdict(list)
        for fold in (int(f) for f in a.folds.split(',')):
            bk = (gb - 2 * fold) % 10
            tr, held = bk >= 2 , bk < 2
            is_held = lambda o: (T.bucket(o[1]) - 2 * fold) % 10 < 2
            fobs, tobs = [o for o in obs if is_held(o)], [o for o in obs if not is_held(o)]
            use = tr & mask
            sp, sinv = np.unique(taxa[use], return_inverse=True)
            idx = np.flatnonzero(use)
            order = np.argsort(sinv, kind='stable')
            start = np.r_[0, np.flatnonzero(np.diff(sinv[order])) + 1, len(order)]
            m = int(min(np.bincount(sinv).max(), 64))
            member = np.stack([np.resize(idx[order[start[k]:start[k + 1]]], m) for k in range(len(sp))])
            hard = np.stack([tset[t] for t in sp])
            freq = np.maximum(hard[hard.sum(1) == 1].sum(0), 1)
            spw = (hard * (freq.sum() / freq / C)).max(1).astype(np.float32)
            omember = np.stack([np.resize([off + frow[q] for q in choose(o[2], how)], m) for o in tobs]) if tobs else np.zeros((0, m), np.int64)
            ohard = np.zeros((len(tobs), C), np.float32)
            ohard[np.arange(len(tobs)), [cidx[o[0]] for o in tobs]] = 1
            ofreq = np.maximum(ohard.sum(0), 1)
            ow = (ohard * (ofreq.sum() / ofreq / C)).max(1).astype(np.float32) if tobs else np.zeros(0, np.float32)
            for arm, alpha in ARMS:
                if arm != 'flora' and len(tobs) < 100:
                    continue
                if arm == 'flora':
                    mem, tg, w = member, hard, spw
                elif arm == 'observers':
                    mem, tg, w = omember, ohard, ow
                else:
                    mem, tg = np.concatenate([member, omember]), np.concatenate([hard, ohard])
                    w = np.concatenate([spw, ow * (alpha * spw.sum() / ow.sum())])
                tt = torch.from_numpy(tg).to(DEV)
                head = R.fit(xa, tt, None, 'mlp', 'set', seed=a.seed, bags=(tt, torch.from_numpy(w).to(DEV), torch.from_numpy(mem).to(DEV)))
                sel = held & mask
                g = R.group_mean(R.prob(head, x[torch.from_numpy(sel).to(DEV)]), taxa[sel])
                pairs[arm, 'agreed'] += [(agreed[trait][t], classes[int(np.argmax(v))]) for t, v in g.items() if agreed[trait].get(t) in cidx]
                pf = R.prob(head, femb_t)
                for v, _, photos in fobs:
                    pairs[arm, 'observers'].append((v, classes[int(pf[[frow[q] for q in choose(photos, how)]].mean(0).argmax())]))
                print(trait, 'fold', fold, arm, 'species bags', len(sp), 'observation bags', len(tobs), flush=True)
        out = {}
        for arm, _ in ARMS:
            if (arm, 'agreed') in pairs:
                out[arm] = {t: R.bal(pairs[arm, t]) for t in ('agreed', 'observers')}
                print(f"RESULT {trait:17s} {arm:10s} agreed (n={len(pairs[arm, 'agreed'])}) {out[arm]['agreed']:.3f}   observers (n={len(pairs[arm, 'observers'])}) "
                      + ('  -' if out[arm]['observers'] is None else f"{out[arm]['observers']:.3f}"), flush=True)
        report[trait] = {'photographs': how, 'scores': out}
        (a.out / f'joint-s{a.seed}{"-" + a.traits.replace(",", "+") if a.traits else ""}.json').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main()
