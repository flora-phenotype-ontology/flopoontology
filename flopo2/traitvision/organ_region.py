"""Flower colour and the leaf traits from the detector's organ box instead of (or beside) the whole photograph.

Counterpart of ``fruit_region.py`` for organs whose boxes need no gating. Regions are embedded with BioCLIP 2
(``embed_crops.py``); the species name is a training label only.

``select``   writes the boxes to embed: ``organ-region/boxes-train.tsv`` and ``boxes-field.tsv`` (new crop ids):
             per photograph the two highest-scoring "flower" boxes and the two highest-scoring "leaf" boxes.
``fit``      per trait, with the protocol of ``baseline_v2.py`` (MLP head, species bags from the floras with the
             set loss, observation bags at weight ALPHA, class weights capped at CAP, held-out genera, five
             folds; agreed species and observers), arms:
               whole            the baseline's photographs (flower colour: all; leaf traits: those with a box
                                of the organ, else all)
               region           the regions only; a species or observation without one keeps its photographs
               region + whole   regions and photographs in one bag
               concat           region joined with its photograph (a photograph alone is joined with itself)
             Regions: flower colour from flower boxes ("box"), and from flower boxes on photographs that
             PhenoVision calls flowering (>= 0.6, "phenovision"); leaf complexity, margin and arrangement from
             leaf boxes.

    python organ_region.py select --data DIR
    python organ_region.py fit --data DIR [--seeds 0,1,2] [--traits a,b]     (needs train.py, regime_tests.py)
"""
import argparse
import collections
import csv
import json
from pathlib import Path

import numpy as np

TRAITS = {'flower_colour': 'flower', 'leaf_complexity': 'leaf', 'leaf_margin': 'leaf', 'leaf_arrangement': 'leaf'}
REGIONS = {'flower_colour': ('box', 'phenovision')}
ORGAN_SET = {'leaf_margin', 'leaf_complexity', 'leaf_arrangement'}       # baseline: organ photographs, else all
ARMS = ('whole', 'region', 'region + whole', 'concat')
ALPHA, CAP, PER_ORGAN = 0.3, 10.0, 2


def select(a):
    D = a.data
    out = D / 'organ-region'
    out.mkdir(exist_ok=True)
    nid = 0
    for name, files in (('train', sorted((D / 'crops-v3').glob('boxes-*.tsv'))),
                        ('field', [D / 'crops-field' / 'boxes-0.tsv', D / 'crops-field' / 'boxes-rest.tsv'])):
        seen, by = set(), collections.defaultdict(list)
        for f in files:
            here = set()
            for r in csv.DictReader(open(f), delimiter='\t'):
                p = int(r['photo_id'])
                if p in seen:                              # a photograph detected twice: the first file counts
                    continue
                here.add(p)
                if r['organ'] in ('flower', 'leaf'):
                    by[p, r['organ']].append(r)
            seen |= here
        n = collections.Counter()
        with open(out / f'boxes-{name}.tsv', 'w') as w:
            w.write('crop_id\tphoto_id\torgan\tscore\tx0\ty0\tx1\ty1\n')
            for (p, organ), rows in sorted(by.items()):
                rows.sort(key=lambda r: -float(r['score']))
                n[organ + ' photographs'] += 1
                for r in rows[:PER_ORGAN]:
                    w.write(f"{nid}\t{p}\t{organ}\t{r['score']}\t{r['x0']}\t{r['y0']}\t{r['x1']}\t{r['y1']}\n")
                    nid += 1; n[organ + ' regions'] += 1
        print(name, 'photographs seen', len(seen), dict(n), flush=True)


def fit(a):
    import torch
    import regime_tests as R
    import train as T
    DEV = R.DEV
    D = a.data
    out = D / 'organ-region'
    z = np.load(D / 'sota-out' / 'phenovision' / 'phenovision-as-pheno.npz')
    k = list(z['values']).index('flowering')
    pv = {}
    for ids, pr in ((z['ids'], z['prob']), (z['field_ids'], z['field_prob'])):
        for i, v in zip(ids, pr[:, k].astype(np.float32)):
            pv[int(i)] = max(float(v), pv.get(int(i), 0.0))
    emb, ids = T.load_embeddings(D / 'emb')
    keys, _ = T.text_embeddings(D / 'emb')
    row_of = {}
    for n, i in enumerate(ids):
        row_of.setdefault(int(i), n)
    pid, taxa = [], []
    for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
        if int(r['photo_id']) in row_of:
            pid.append(int(r['photo_id'])); taxa.append(r['taxon'])
    pid, taxa = np.array(pid), np.array(taxa)
    N = len(pid)
    W = emb[[row_of[int(i)] for i in pid]]
    del emb
    femb, fids = T.load_embeddings(D / 'emb-field')
    frow = {}
    for n, i in enumerate(fids):
        frow.setdefault(int(i), n)
    pos = {int(i): n for n, i in enumerate(pid)}
    fpos = {int(i): N + n for i, n in frow.items()}
    # regions: embedding rows and, per organ, {photograph: [row in the region table]}
    remb, rparent, rorgan, rphoto = [], [], [], []
    for name, where in (('train', pos), ('field', fpos)):
        e, cid = T.load_embeddings(out / f'emb-{name}')
        crow = {int(c): n for n, c in enumerate(cid)}
        keep = []
        for r in csv.DictReader(open(out / f'boxes-{name}.tsv'), delimiter='\t'):
            p, c = int(r['photo_id']), int(r['crop_id'])
            if p in where and c in crow:
                keep.append(crow[c]); rparent.append(where[p]); rorgan.append(r['organ']); rphoto.append(p)
        remb.append(e[keep])
        del e
    remb = np.concatenate(remb)
    rparent, rorgan, rphoto = np.array(rparent, np.int64), np.array(rorgan), np.array(rphoto)
    labels_ = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'pilot-labels-v3.tsv'), delimiter='\t'):
        labels_[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    agreed_ = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'agreed-v3.tsv'), delimiter='\t'):
        if int(r['floras']) >= 2:
            agreed_[r['trait']][r['taxon']] = r['value']
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
    seeds = [int(s) for s in a.seeds.split(',')]
    path = out / 'organ-region.json'
    report = json.loads(path.read_text()) if path.exists() else {}
    whole_t = torch.from_numpy(np.concatenate([W, femb])).to(DEV)
    base = len(whole_t)
    for trait in (a.traits.split(',') if a.traits else TRAITS):
        if trait in report:
            continue
        org = TRAITS[trait]
        sel = np.flatnonzero(rorgan == org)
        x = torch.cat([whole_t, torch.from_numpy(remb[sel]).to(DEV)])
        parent = torch.cat([torch.arange(base, device=DEV), torch.from_numpy(rparent[sel]).to(DEV)])
        xc = torch.cat([x, x[parent]], 1)
        reg_of = collections.defaultdict(list)                  # photograph -> its region items
        for n, s in enumerate(sel):
            reg_of[int(rphoto[s])].append(base + n)
        lab = labels_[trait]
        classes = sorted(c for c in {c for s in lab.values() for c in s} if f'zs:{trait}:{c}' in keys)
        cidx = {c: i for i, c in enumerate(classes)}
        C = len(classes)
        lab = {t: s & set(classes) for t, s in lab.items() if s & set(classes)}
        agreed = agreed_[trait]
        boxes = R.ORGAN_BOX[trait] if trait in ORGAN_SET else set()
        has = lambda i: any(i in organ[o] for o in boxes)
        sp_photos = collections.defaultdict(list)
        for n, t in enumerate(taxa):
            if t in lab:
                sp_photos[t].append(n)
        names = sorted(sp_photos)
        tset = {t: np.array([1.0 if c in lab[t] else 0 for c in classes], np.float32) for t in names}
        obs = [(v, g, ph) for v, g, ph in field[trait] if v in cidx]

        def regions(p, how):
            return reg_of.get(p, []) if how == 'box' or pv.get(p, 0) >= 0.6 else []

        def unit(photos, where, how):
            """photos: photograph ids of a species or an observation; where: id -> item."""
            whole = [where[p] for p in photos if has(p)] if boxes else []
            whole = whole or [where[p] for p in photos]
            reg = [i for p in photos for i in regions(p, how)]
            return {'whole': whole, 'region': reg or whole, 'region + whole': reg + whole, 'concat': reg or whole, 'has': bool(reg)}
        hows = REGIONS.get(trait, ('box',))
        S = {how: {t: unit([int(pid[n]) for n in sp_photos[t]], pos, how) for t in names} for how in hows}
        O = {how: [unit(ph, fpos, how) for _, _, ph in obs] for how in hows}
        cover = {how: {'species with a region': sum(v['has'] for v in S[how].values()), 'species': len(names),
                       'photographs with a region': sum(1 for t in names for n in sp_photos[t] if regions(int(pid[n]), how)),
                       'photographs': sum(len(v) for v in sp_photos.values()),
                       'regions': sum(len(regions(int(pid[n]), how)) for t in names for n in sp_photos[t]),
                       'observations with a region': sum(v['has'] for v in O[how]), 'observations': len(obs)} for how in hows}
        for how in hows:
            print('COVER', trait, how, cover[how], flush=True)
        bucket = {t: T.bucket(t.split()[0]) for t in names}
        cw = lambda h: np.minimum((lambda f: f.sum() / f / C)(np.maximum(h[h.sum(1) == 1].sum(0), 1)), CAP)

        def train(feat, sp_units, tr, ob_units, tobs, arm, seed):
            bags = [sp_units[t][arm] for t in tr]
            hard = np.stack([tset[t] for t in tr])
            w = (hard * cw(hard)).max(1).astype(np.float32)
            if len(tobs) >= 100:
                bags += [ob_units[n][arm] for n in tobs]
                ohard = np.zeros((len(tobs), C), np.float32)
                ohard[np.arange(len(tobs)), [cidx[obs[n][0]] for n in tobs]] = 1
                ow = (ohard * cw(ohard)).max(1).astype(np.float32)
                w = np.concatenate([w, ow * (ALPHA * w.sum() / ow.sum())])
                hard = np.concatenate([hard, ohard])
            m = int(min(max(len(b) for b in bags), 64))
            member = np.stack([np.resize(np.array(b), m) for b in bags])
            tt = torch.from_numpy(hard).to(DEV)
            return R.fit(feat, tt, None, 'mlp', 'set', seed=seed, bags=(tt, torch.from_numpy(w).to(DEV), torch.from_numpy(member).to(DEV)))

        pairs = collections.defaultdict(list)
        for seed in seeds:
            for fold in range(5):
                tr = [t for t in names if (bucket[t] - 2 * fold) % 10 >= 2]
                held = [t for t in names if (bucket[t] - 2 * fold) % 10 < 2 and agreed.get(t) in cidx]
                fo = [n for n, o in enumerate(obs) if (T.bucket(o[1]) - 2 * fold) % 10 < 2]
                to = [n for n, o in enumerate(obs) if (T.bucket(o[1]) - 2 * fold) % 10 >= 2]
                pw = R.prob(train(x, S[hows[0]], tr, O[hows[0]], to, 'whole', seed), x)
                for how in hows:
                    probs = {'whole': pw}
                    for arm in ('region', 'region + whole'):
                        probs[arm] = R.prob(train(x, S[how], tr, O[how], to, arm, seed), x)
                    probs['concat'] = R.prob(train(xc, S[how], tr, O[how], to, 'concat', seed), xc)
                    for arm in ARMS:
                        for group, units, truth in (('agreed', [S[how][t] for t in held], [agreed[t] for t in held]),
                                                    ('observers', [O[how][n] for n in fo], [obs[n][0] for n in fo])):
                            for u, v in zip(units, truth):
                                q = classes[int(probs[arm][torch.as_tensor(u[arm], device=DEV)].mean(0).argmax())]
                                pairs[how, arm, group, seed].append((v, q))
                                if u['has']:
                                    pairs[how, arm, group + ', with a region', seed].append((v, q))
                    del probs
                print(trait, 'seed', seed, 'fold', fold, flush=True)
        rep = {'cover': cover, 'scores': {}}
        for how in hows:
            for group in ('agreed', 'observers', 'agreed, with a region', 'observers, with a region'):
                for arm in ARMS:
                    vals = [v for v in (R.bal(pairs[how, arm, group, s]) for s in seeds) if v is not None]
                    if not vals:
                        continue
                    r = rep['scores'][f'{how}|{arm}|{group}'] = {'mean': float(np.mean(vals)), 'min': float(min(vals)), 'max': float(max(vals)),
                                                                 'n': len(pairs[how, arm, group, seeds[0]])}
                    print(f"RESULT {trait:16s} {how:11s} {group:26s} n={r['n']:5d} {arm:15s} {r['mean']:.3f}  ({r['min']:.3f}-{r['max']:.3f})", flush=True)
        report[trait] = rep
        path.write_text(json.dumps(report, indent=1) + '\n')
        del x, xc, parent
        torch.cuda.empty_cache()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('select', 'fit'))
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--seeds', default='0,1,2')
    p.add_argument('--traits', default='')
    a = p.parse_args()
    select(a) if a.mode == 'select' else fit(a)


if __name__ == '__main__':
    main()
