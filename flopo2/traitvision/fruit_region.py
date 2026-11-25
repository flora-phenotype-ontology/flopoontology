"""Fruit colour from the fruit region instead of the whole photograph: trained and tested on regions.

The detector's boxes of a reproductive structure ("fruit", and "flower", under which the ambiguous answer
"a flower a fruit" was filed) are the candidate regions; a photograph's fruiting score (our phenology head, or
PhenoVision) says whether the structure is a fruit. Regions are embedded with BioCLIP 2 (``embed_crops.py``).

``select``   writes the boxes to embed: ``fruit-region/boxes-train.tsv`` and ``boxes-field.tsv`` (new crop ids):
             every "fruit" box, and the "flower" boxes of photographs whose fruiting score (either source) passes 0.3;
             at most three boxes per photograph (highest detector score).
``fit``      fruit colour with the protocol of ``allphotos_train.py`` (MLP head, one bag per species, set loss,
             held-out genera, five folds; agreed species and observers), arms:
               whole            every photograph (the existing baseline)
               region           the regions only; a species or observation without one keeps its photographs
               region + whole   regions and photographs in one bag
               concat           region joined with its photograph (a photograph alone is joined with itself)
               late             mean of the answers of ``whole`` and ``region``
             under four definitions of a fruit region:
               fruit box        a box the detector called "a fruit"
               phenovision      a fruit or flower box on a photograph with PhenoVision fruit >= 0.6
               ours             the same with our phenology head > 0.5
               box or pheno     fruit box, or phenovision

    python fruit_region.py select --data DIR
    python fruit_region.py fit --data DIR [--seeds 0,1,2]            (needs train.py, regime_tests.py)
"""
import argparse
import collections
import csv
import json
from pathlib import Path

import numpy as np

TRAIT = 'fruit_colour'
REGIONS = ('fruit box', 'phenovision', 'ours', 'box or pheno')
ARMS = ('whole', 'region', 'region + whole', 'concat', 'late')


def scores(D):
    out = {}
    for name, f in (('ours', D / 'phenology-scores.npz'), ('pv', D / 'sota-out' / 'phenovision' / 'phenovision-as-pheno.npz')):
        z = np.load(f)
        k = list(z['values']).index('fruiting')
        d = {}
        for ids, pr in ((z['ids'], z['prob']), (z['field_ids'], z['field_prob'])):
            for i, v in zip(ids, pr[:, k].astype(np.float32)):
                d[int(i)] = max(float(v), d.get(int(i), 0.0))
        out[name] = d
    return out


def select(a):
    D = a.data
    out = D / 'fruit-region'
    out.mkdir(exist_ok=True)
    sc = scores(D)
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
                if r['organ'] == 'fruit' or (r['organ'] == 'flower' and max(sc['ours'].get(p, 0), sc['pv'].get(p, 0)) > 0.3):
                    by[p].append(r)
            seen |= here
        n = 0
        with open(out / f'boxes-{name}.tsv', 'w') as w:
            w.write('crop_id\tphoto_id\torgan\tscore\tx0\ty0\tx1\ty1\tphrase\n')
            for p, rows in by.items():
                rows.sort(key=lambda r: (r['organ'] != 'fruit', -float(r['score'])))
                for r in rows[:3]:
                    w.write(f"{nid}\t{p}\t{r['organ']}\t{r['score']}\t{r['x0']}\t{r['y0']}\t{r['x1']}\t{r['y1']}\t{r.get('phrase') or ''}\n")
                    nid += 1; n += 1
        print(name, 'photographs seen', len(seen), 'with a candidate region', len(by), 'regions', n, flush=True)


def fit(a):
    import torch
    import regime_tests as R
    import train as T
    DEV = R.DEV
    D = a.data
    out = D / 'fruit-region'
    sc = scores(D)
    emb, ids = T.load_embeddings(D / 'emb')
    keys, _ = T.text_embeddings(D / 'emb')
    row_of = {}
    for n, i in enumerate(ids):
        row_of.setdefault(int(i), n)
    lab = {r['taxon']: set(r['allowed'].split('|')) for r in csv.DictReader(open(D / 'pilot-labels-v3.tsv'), delimiter='\t') if r['trait'] == TRAIT}
    classes = sorted(c for c in {c for s in lab.values() for c in s} if f'zs:{TRAIT}:{c}' in keys)
    cidx = {c: i for i, c in enumerate(classes)}
    C = len(classes)
    lab = {t: s & set(classes) for t, s in lab.items() if s & set(classes)}
    agreed = {r['taxon']: r['value'] for r in csv.DictReader(open(D / 'agreed-v3.tsv'), delimiter='\t') if r['trait'] == TRAIT and int(r['floras']) >= 2}
    photo_taxon = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t')
                   if int(r['photo_id']) in row_of and r['taxon'] in lab}
    pid = np.array(list(photo_taxon))
    femb, fids = T.load_embeddings(D / 'emb-field')
    frow = {}
    for n, i in enumerate(fids):
        frow.setdefault(int(i), n)
    # one pool of items: [species photographs | observers' photographs | species regions | observers' regions]
    W = emb[[row_of[i] for i in pid]]
    pos = {int(i): n for n, i in enumerate(pid)}
    fpos = {int(i): len(pid) + n for i, n in frow.items()}
    parts, parent, region_rows = [W, femb], [np.arange(len(pid)), len(pid) + np.arange(len(femb))], {}
    base = len(pid) + len(femb)
    for name, where in (('train', pos), ('field', fpos)):
        e, cid = T.load_embeddings(out / f'emb-{name}')
        crow = {int(c): n for n, c in enumerate(cid)}
        keep, par = [], []
        for r in csv.DictReader(open(out / f'boxes-{name}.tsv'), delimiter='\t'):
            p, c = int(r['photo_id']), int(r['crop_id'])
            if p in where and c in crow:
                region_rows.setdefault(p, []).append((base + len(keep), r['organ']))
                keep.append(crow[c]); par.append(where[p])
        parts.append(e[keep]); parent.append(np.array(par, np.int64))
        base += len(keep)
    X = np.concatenate(parts)
    parent = np.concatenate(parent)
    x = torch.from_numpy(X).to(DEV)
    xc = torch.cat([x, x[torch.from_numpy(parent).to(DEV)]], 1)          # region (or photograph) joined with its photograph
    del X

    def regions(p, how):
        rr = region_rows.get(p, ())
        pv, ours = sc['pv'].get(p, 0) >= 0.6, sc['ours'].get(p, 0) > 0.5
        if how == 'fruit box':
            return [i for i, o in rr if o == 'fruit']
        if how == 'phenovision':
            return [i for i, o in rr] if pv else []
        if how == 'ours':
            return [i for i, o in rr] if ours else []
        return [i for i, o in rr if o == 'fruit' or pv]

    taxa = np.array([photo_taxon[int(i)] for i in pid])
    names = np.unique(taxa)
    sp_photos = collections.defaultdict(list)
    for n, t in enumerate(taxa):
        sp_photos[t].append(n)
    tset = {t: np.array([1.0 if c in lab[t] else 0 for c in classes], np.float32) for t in names}
    obs_photos = collections.defaultdict(list)
    for r in csv.DictReader(open(D / 'field-obs-photos.tsv'), delimiter='\t'):
        if int(r['photo_id']) in frow:
            obs_photos[r['observation']].append((int(r['position']), int(r['photo_id'])))
    obs = []
    for r in csv.DictReader(open(D / 'field-test-v3.tsv'), delimiter='\t'):
        ph = [q for _, q in sorted(obs_photos.get(r['observation'], []))]
        if r['trait'] == TRAIT and ph and r['class'] in cidx:
            obs.append((r['class'], r['taxon'].split()[0], ph))
    # per species / observation and region definition: the items of each arm
    def items(photo_ids, whole_idx, how):
        reg = [i for p in photo_ids for i in regions(int(p), how)]
        return {'whole': whole_idx, 'region': reg or whole_idx, 'region + whole': reg + whole_idx, 'has': bool(reg)}
    sp_items = {how: {t: items(pid[sp_photos[t]], sp_photos[t], how) for t in names} for how in REGIONS}
    ob_items = {how: [items(ph, [fpos[q] for q in ph], how) for _, _, ph in obs] for how in REGIONS}
    cover = {how: {'species with a region': sum(v['has'] for v in sp_items[how].values()), 'species': len(names),
                   'photographs with a region': sum(1 for p in pid if regions(int(p), how)), 'photographs': len(pid),
                   'observations with a region': sum(v['has'] for v in ob_items[how]), 'observations': len(obs)} for how in REGIONS}
    for how in REGIONS:
        print('COVER', how, cover[how], flush=True)
    bucket = {t: T.bucket(t.split()[0]) for t in names}

    def train(feat, bags_of, tr_names, seed):
        m = int(min(max(len(bags_of[t]) for t in tr_names), 64))
        member = np.stack([np.resize(np.array(bags_of[t]), m) for t in tr_names])
        hard = np.stack([tset[t] for t in tr_names])
        freq = np.maximum(hard[hard.sum(1) == 1].sum(0), 1)
        spw = torch.from_numpy((hard * (freq.sum() / freq / C)).max(1).astype(np.float32)).to(DEV)
        spt = torch.from_numpy(hard).to(DEV)
        return R.fit(feat, spt, None, 'mlp', 'set', seed=seed, bags=(spt, spw, torch.from_numpy(member).to(DEV)))

    def answer(p, idx):
        return p[torch.as_tensor(idx, device=DEV)].mean(0)
    pairs = collections.defaultdict(list)
    for seed in (int(s) for s in a.seeds.split(',')):
        for fold in range(5):
            tr = [t for t in names if (bucket[t] - 2 * fold) % 10 >= 2]
            held = [t for t in names if (bucket[t] - 2 * fold) % 10 < 2 and agreed.get(t) in cidx]
            fo = [n for n, o in enumerate(obs) if (T.bucket(o[1]) - 2 * fold) % 10 < 2]
            pw = R.prob(train(x, {t: sp_items[REGIONS[0]][t]['whole'] for t in tr}, tr, seed), x)
            for how in REGIONS:
                S, O = sp_items[how], ob_items[how]
                probs = {'whole': pw}
                for arm in ('region', 'region + whole'):
                    probs[arm] = R.prob(train(x, {t: S[t][arm] for t in tr}, tr, seed), x)
                probs['concat'] = R.prob(train(xc, {t: S[t]['region'] for t in tr}, tr, seed), xc)
                for arm in ARMS:
                    for group, units, truth in (('agreed', [S[t] for t in held], [agreed[t] for t in held]),
                                                ('observers', [O[n] for n in fo], [obs[n][0] for n in fo])):
                        for u, v in zip(units, truth):
                            if arm == 'late':
                                q = (answer(probs['whole'], u['whole']) + answer(probs['region'], u['region'])) / 2
                            else:
                                q = answer(probs[arm], u['region' if arm == 'concat' else arm])
                            k = classes[int(q.argmax())]
                            pairs[how, arm, group, seed].append((v, k))
                            if u['has']:
                                pairs[how, arm, group + ', with a region', seed].append((v, k))
            print('seed', seed, 'fold', fold, flush=True)
    seeds = [int(s) for s in a.seeds.split(',')]
    report = {'cover': cover, 'scores': {}, 'confusion': {}}
    for how in REGIONS:
        for group in ('agreed', 'observers', 'agreed, with a region', 'observers, with a region'):
            for arm in ARMS:
                vals = [R.bal(pairs[how, arm, group, s]) for s in seeds]
                vals = [v for v in vals if v is not None]
                key = f'{how}|{arm}|{group}'
                report['scores'][key] = {'mean': float(np.mean(vals)), 'min': float(min(vals)), 'max': float(max(vals)), 'n': len(pairs[how, arm, group, seeds[0]])}
                report['confusion'][key] = collections.Counter(f'{t}>{q}' for s in seeds for t, q in pairs[how, arm, group, s])
                r = report['scores'][key]
                print(f"RESULT {how:13s} {group:26s} n={r['n']:4d} {arm:15s} {r['mean']:.3f}  ({r['min']:.3f}-{r['max']:.3f})", flush=True)
    (out / 'fruit-region.json').write_text(json.dumps(report, indent=1) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('select', 'fit'))
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--seeds', default='0,1,2')
    a = p.parse_args()
    select(a) if a.mode == 'select' else fit(a)


if __name__ == '__main__':
    main()
