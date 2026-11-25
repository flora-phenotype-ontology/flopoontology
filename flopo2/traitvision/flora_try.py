"""Sizes that the floras state, learned from photographs, tested against TRY: no TRY value is used for training.

Labels (``labels``): per species, from the measurements of ``extract_measures.py``: plant height (upper end of the
stated range), leaf length and leaf width (middle of the range), as log10 metres, median over the statements.

Head (``fit``): frozen BioCLIP 2 embedding -> small MLP -> the three sizes, fitted on the photographs of species
with a flora value. The species name is a training label only; it is never an input, and every prediction is made
by a model that saw no species of the photograph's genus (five folds over genera).

Tests, all on unseen genera:
* flora values of held-out species (photographs pooled per species);
* TRY values on the PlantTraitNet benchmark photographs (validation set and field reference): plant height against
  predicted height, leaf area against predicted length x width. The benchmark's genus only decides which fold's
  model answers.
Also printed: how well the flora value itself agrees with TRY for species that have both (no image involved).

    python3 -m flopo2.traitvision.flora_try labels local-corpora/trait-vision
    python flora_try.py fit --data DIR --emb-val DIR/sota-out/emb-ptn-val --emb-ref DIR/sota-out/emb-ptn-ref --out DIR/flora-try
"""
import argparse
import collections
import csv
import json
import math
import statistics
import sys
from pathlib import Path

SIZES = ('height', 'leaf_length', 'leaf_width')
RULES = {('whole plant', 'height'): ('height', 'high'), ('stem', 'height'): ('height', 'high'),
         ('leaf lamina', 'length'): ('leaf_length', 'mid'), ('leaf', 'length'): ('leaf_length', 'mid'),
         ('leaf lamina', 'width'): ('leaf_width', 'mid'), ('leaf', 'width'): ('leaf_width', 'mid')}
BOUNDS = {'height': (0.005, 130.0), 'leaf_length': (0.0005, 6.0), 'leaf_width': (0.0002, 4.0)}


def labels(folder):
    folder = Path(folder)
    vals = collections.defaultdict(list)
    srcs = collections.defaultdict(set)
    for r in csv.DictReader(open(folder / 'measures-all.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
        rule = RULES.get((r['entity'], r['quality']))
        if not rule or r['rank'] != 'species' or r['ctx']:
            continue
        lo = float(r['low_m']) if r['low_m'] else None
        hi = float(r['high_m']) if r['high_m'] else None
        if rule[1] == 'high':
            v = hi if hi is not None else lo
        else:
            v = math.sqrt(lo * hi) if lo and hi else (hi if hi is not None else lo)
        b = BOUNDS[rule[0]]
        if v and b[0] <= v <= b[1]:
            vals[r['taxon'], rule[0]].append(math.log10(v))
            srcs[r['taxon'], rule[0]].add(r['source'])
    with open(folder / 'measure-labels.tsv', 'w') as f:
        f.write('taxon\ttrait\tlog10_m\tstatements\tsources\n')
        for (t, k), v in sorted(vals.items()):
            f.write(f'{t}\t{k}\t{statistics.median(v):.4f}\t{len(v)}\t{len(srcs[t, k])}\n')
    print({k: sum(1 for key in vals if key[1] == k) for k in SIZES})


def fit(a):
    import numpy as np
    import torch
    import train as T
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    D = a.data
    a.out.mkdir(parents=True, exist_ok=True)
    lab = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'measure-labels.tsv'), delimiter='\t'):
        lab[r['taxon']][r['trait']] = float(r['log10_m'])
    emb, ids = T.load_embeddings(D / 'emb')
    row = {}
    for n, i in enumerate(ids):
        row.setdefault(int(i), n)
    rows, taxa = [], []
    for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
        if int(r['photo_id']) in row and r['taxon'] in lab:
            rows.append(row[int(r['photo_id'])]); taxa.append(r['taxon'])
    taxa = np.array(taxa)
    names, inv = np.unique(taxa, return_inverse=True)
    y = np.array([[lab[t].get(k, np.nan) for k in SIZES] for t in names], np.float32)
    mu, sd = np.nanmean(y, 0), np.nanstd(y, 0)
    yz = (y - mu) / sd
    x = torch.from_numpy(emb[rows]).to(dev)
    yt = torch.from_numpy(np.nan_to_num(yz)[inv]).to(dev)
    mt = torch.from_numpy(~np.isnan(yz)[inv]).to(dev)
    wt = torch.from_numpy((1.0 / np.minimum(np.bincount(inv), 50))[inv].astype(np.float32)).to(dev)   # a species counts once (up to 50 photographs)
    gb = np.array([T.bucket(t.split()[0]) for t in taxa])
    print('species', len(names), 'photographs', len(rows), {k: int((~np.isnan(y[:, n])).sum()) for n, k in enumerate(SIZES)}, flush=True)

    # the benchmark photographs
    def bench(folder, listing):
        keys = [k for k in (folder / 'emb-0.keys').read_text().split('\n') if k]
        meta = {r['key']: r for r in csv.DictReader(open(listing), delimiter='\t')}
        return torch.from_numpy(np.load(folder / 'emb-0.npy').astype(np.float32)).to(dev), [meta[k] for k in keys]
    xv, mv = bench(a.emb_val, D / 'sota-out' / 'ptn-val.tsv')
    xr, mr = bench(a.emb_ref, D / 'sota-out' / 'ptn-reference.tsv')
    bv = np.array([T.bucket(m['genus']) for m in mv]); br = np.array([T.bucket(m['genus']) for m in mr])
    pv, pr = np.zeros((len(mv), 3), np.float32), np.zeros((len(mr), 3), np.float32)
    held = np.zeros((len(rows), 3), np.float32)
    for fold in range(5):
        tr = torch.from_numpy(np.flatnonzero((gb - 2 * fold) % 10 >= 2)).to(dev)
        preds = []
        for seed in range(3):
            torch.manual_seed(seed)
            net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 2048), torch.nn.GELU(), torch.nn.Dropout(0.3),
                                      torch.nn.Linear(2048, 512), torch.nn.GELU(), torch.nn.Linear(512, 3)).to(dev)
            opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-2)
            steps = a.epochs * (len(tr) // 4096 + 1)
            sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=steps)
            net.train()
            for _ in range(a.epochs):
                perm = tr[torch.randperm(len(tr), device=dev)]
                for i in range(0, len(perm), 4096):
                    b = perm[i:i + 4096]
                    l = torch.nn.functional.smooth_l1_loss(net(x[b]), yt[b], reduction='none') * mt[b] * wt[b][:, None]
                    loss = l.sum() / (mt[b] * wt[b][:, None]).sum()
                    opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            net.eval()
            with torch.no_grad():
                te = torch.from_numpy(np.flatnonzero((gb - 2 * fold) % 10 < 2)).to(dev)
                preds.append((torch.cat([net(x[te[i:i + 65536]]) for i in range(0, len(te), 65536)]).cpu().numpy(),
                              net(xv[torch.from_numpy(np.flatnonzero((bv - 2 * fold) % 10 < 2)).to(dev)]).cpu().numpy(),
                              net(xr[torch.from_numpy(np.flatnonzero((br - 2 * fold) % 10 < 2)).to(dev)]).cpu().numpy()))
        held[(gb - 2 * fold) % 10 < 2] = np.mean([p[0] for p in preds], 0) * sd + mu
        pv[(bv - 2 * fold) % 10 < 2] = np.mean([p[1] for p in preds], 0) * sd + mu
        pr[(br - 2 * fold) % 10 < 2] = np.mean([p[2] for p in preds], 0) * sd + mu
        print('fold', fold, flush=True)

    def rank(v):
        return np.argsort(np.argsort(v))

    def corr(p, t):
        p, t = np.asarray(p, float), np.asarray(t, float)
        return {'n': len(p), 'spearman': round(float(np.corrcoef(rank(p), rank(t))[0, 1]), 3), 'pearson_log10': round(float(np.corrcoef(p, t)[0, 1]), 3)}
    report = {}
    # 1. flora values of held-out species
    sp = np.zeros((len(names), 3)); np.add.at(sp, inv, held); sp /= np.bincount(inv)[:, None]
    for n, k in enumerate(SIZES):
        ok = ~np.isnan(y[:, n])
        report[f'flora, held-out genera: {k}'] = corr(sp[ok, n], y[ok, n])
    # 2. TRY on the benchmark photographs; 3. the flora value itself against TRY
    def try_rows(meta, pred, trait, col):
        t, p, s = [], [], []
        for m, q in zip(meta, pred):
            v = m.get(trait) if 'trait' not in m else (m['value'] if m['trait'] == trait else None)
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v > 0:
                t.append(math.log10(v)); p.append(col(q)); s.append(m['species'])
        return np.array(p), np.array(t), s
    for name, meta, pred in (('validation', mv, pv), ('reference', mr, pr)):
        for trait, col, fl in (('Height', lambda q: q[0], lambda d: d.get('height')),
                               ('LeafArea', lambda q: q[1] + q[2], lambda d: d['leaf_length'] + d['leaf_width'] if 'leaf_length' in d and 'leaf_width' in d else None)):
            p, t, s = try_rows(meta, pred, trait, col)
            if len(p) < 20:
                continue
            report[f'TRY {trait}, {name} photographs: image -> flora-trained head'] = corr(p, t)
            by = collections.defaultdict(list)
            for pp, tt, ss in zip(p, t, s):
                by[ss].append((pp, tt))
            if name == 'validation':
                report[f'TRY {trait}, {name}: per species'] = corr([np.mean([q[0] for q in v]) for v in by.values()], [np.mean([q[1] for q in v]) for v in by.values()])
            pairs = [(fl(lab[ss]), np.mean([q[1] for q in v])) for ss, v in by.items() if ss in lab and fl(lab[ss]) is not None]
            if len(pairs) >= 20:
                report[f'TRY {trait}, {name}: the flora value itself (species with both, no image)'] = corr(*zip(*pairs))
    for k, v in report.items():
        print('RESULT', k, v, flush=True)
    (a.out / 'flora-try.json').write_text(json.dumps(report, indent=1) + '\n')


def main():
    if sys.argv[1] == 'labels':
        return labels(sys.argv[2])
    p = argparse.ArgumentParser()
    p.add_argument('mode')
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--emb-val', type=Path, required=True)
    p.add_argument('--emb-ref', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--epochs', type=int, default=15)
    fit(p.parse_args())


if __name__ == '__main__':
    main()
