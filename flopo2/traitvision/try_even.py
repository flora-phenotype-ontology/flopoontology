"""An even comparison with PlantTraitNet on its benchmark: TRY traits (height, leaf area, specific leaf area, leaf nitrogen).

``score``   every model on the same rows, split by whether PlantTraitNet saw the species (or genus) in training
            (``train/train.csv`` of its data set). All validation species are in its training set, so the split is made on
            the field reference (measured individual plants). Spearman and n per cell.

``fit``     our TRY head on PlantTraitNet's own training photographs (222,590; frozen BioCLIP 2 embedding), with the
            flora network's predictions (sizes, probabilities of the categorical values; flora labels only, our photographs)
            as further inputs. Regimes:
              all     as PlantTraitNet: every training photograph; validation = other photographs of the same species;
              folds   five folds over genera: a test photograph is answered by a model whose TRY head and flora network
                      saw no species of its genus.
            Arms (``+`` joins): ``emb`` embedding; ``f3`` flora network with 3 sizes + categorical traits; ``f8`` with the
            8 sizes of ``measure-labels-v2.tsv``; ``fx`` with leaflet sizes and the traits of ``labels_extra.py`` (leaf
            texture, life span, leaf persistence, leaf shape) as well; ``loc`` the Climplicit climate embedding of the photograph's location (the
            location encoder PlantTraitNet itself uses; ``climplicit`` mode writes it); ``ours`` TRY species values also
            put on our own photographs of the training species.
            The species name is a label and fold key only, never an input; there is no species classifier or lookup.

    python try_even.py lists --root DIR/sota-benchmarks/planttraitnet --out DIR/sota-out            (ptn-train.tsv)
    python try_even.py climplicit --data DIR --models DIR/../sota-models/planttraitnet               (sota-env; loc-*.npy)
    python try_even.py fit --data DIR --out DIR/try-even --arm emb+f8+loc --regime all
    python try_even.py score --data DIR --root DIR/sota-benchmarks/planttraitnet --out DIR/try-even NAME=file.npz ...
"""
import argparse
import collections
import csv
import json
from pathlib import Path

import numpy as np

TRAITS = ['Height', 'LeafArea', 'SLA', 'Leaf_N']
SIZES3 = ('height', 'leaf_length', 'leaf_width')
SIZESX = ('height', 'leaf_length', 'leaf_width', 'fruit_length', 'fruit_width', 'seed_length', 'petal_length', 'flower_diameter',
          'leaflet_length', 'leaflet_width')
SIZES8 = ('height', 'leaf_length', 'leaf_width', 'fruit_length', 'fruit_width', 'seed_length', 'petal_length', 'flower_diameter')


def tsv(path):
    return list(csv.DictReader(open(path, newline=''), delimiter='\t'))


def binomial(name):
    w = name.replace('_', ' ').split()
    return ' '.join(w[:2]) if len(w) > 1 and w[1][:1].islower() and w[1] not in ('sp.', 'sp', 'spp.', 'x') else ''


def spearman(a, b):
    r = lambda v: np.argsort(np.argsort(np.asarray(v, float))).astype(float)
    return float(np.corrcoef(r(a), r(b))[0, 1])


def lists(a):
    n = 0
    with open(a.out / 'ptn-train.tsv', 'w') as f:
        f.write('key\tpath\tlatitude\tlongitude\tspecies\tgenus\tpft\t' + '\t'.join(TRAITS) + '\n')
        for r in csv.DictReader(open(a.root / 'train' / 'train.csv')):
            vals = [r[f'{t}_median'] for t in TRAITS]
            if all(v not in ('', 'NA', 'nan') for v in vals) and (a.root / r['Image']).exists():
                f.write('\t'.join([r['Image'], r['Image'], r['Latitude'], r['Longitude'], r['Species'], r['Species'].split()[0], r['PFT'], *vals]) + '\n')
                n += 1
    print('training photographs', n)


def climplicit(a):
    import torch
    from rshf.climplicit import Climplicit
    m = Climplicit.from_pretrained(str(a.models / 'climplicit'), config={'return_chelsa': False}).eval().cuda()
    for name in ('ptn-train', 'ptn-val', 'ptn-reference'):
        rows = tsv(a.data / 'sota-out' / f'{name}.tsv')
        geo = np.array([[float(r['longitude']), float(r['latitude'])] if r.get('longitude') and r.get('latitude') else [0.0, 0.0] for r in rows], np.float32)
        with torch.no_grad():
            e = torch.cat([m(torch.from_numpy(geo[i:i + 8192]).cuda()).float() for i in range(0, len(geo), 8192)]).cpu().numpy()
        e[~np.array([bool(r.get('longitude') and r.get('latitude')) for r in rows])] = 0
        np.save(a.data / 'sota-out' / f'loc-{name}.npy', e)
        (a.data / 'sota-out' / f'loc-{name}.keys').write_text('\n'.join(r['key'] for r in rows))
        print(name, e.shape, flush=True)


def score(a):
    val = {r['key']: r for r in tsv(a.data / 'sota-out' / 'ptn-val.tsv')}
    ref = {r['key']: r for r in tsv(a.data / 'sota-out' / 'ptn-reference.tsv')}
    seen = {r['Species'] for r in csv.DictReader(open(a.root / 'train' / 'train.csv'))}
    seen_g = {s.split()[0] for s in seen}
    models = {}
    z = [np.load(a.data / 'sota-out' / d / 'pred.npz') for d in ('ptn-val', 'ptn-ref')]
    mt = lambda q: np.mean([q[f'multitrait_seed{s}_mu'] for s in (0, 100, 200)], 0)
    models['PlantTraitNet multi-trait'] = (dict(zip(z[0]['ids'], mt(z[0]))), dict(zip(z[1]['ids'], mt(z[1]))))
    for spec in a.preds:
        name, f = spec.split('=', 1)
        o = np.load(f)
        models[name] = (dict(zip(o['val_keys'], o['val_pred'])), dict(zip(o['ref_keys'], o['ref_pred'])))

    def group(r):
        b = binomial(r['species'])
        g = ['all']
        if b:
            g.append('species in its training set' if b in seen else 'species not in its training set')
        g.append('genus in its training set' if r['genus'] in seen_g else 'genus not in its training set')
        return g
    res = {}
    for name, (dv, dr) in models.items():
        r = res[name] = {}
        for ti, t in enumerate(TRAITS):
            keys = [k for k in dv if k in val]
            if keys:
                r[f'validation {t} | all (every species in its training set)'] = {
                    'n': len(keys), 'spearman': round(spearman([float(val[k][t]) for k in keys], [dv[k][ti] for k in keys]), 3)}
            by = collections.defaultdict(list)
            for k in dr:
                if k in ref and ref[k]['trait'] == t:
                    for g in group(ref[k]):
                        by[g].append(k)
            for g, ks in by.items():
                if len(ks) >= 20:
                    r[f'reference {t} | {g}'] = {'n': len(ks), 'species': len({ref[k]['species'] for k in ks}),
                                                 'spearman': round(spearman([float(ref[k]['value']) for k in ks], [dr[k][ti] for k in ks]), 3)}
    # difference to PlantTraitNet on the field reference, resampling species (1,000 samples): is a lead or a lag more than chance?
    rng = np.random.default_rng(0)
    base = models['PlantTraitNet multi-trait'][1]
    for name, (_, dr) in models.items():
        if name.startswith('PlantTraitNet'):
            continue
        for ti, t in enumerate(TRAITS):
            by = collections.defaultdict(list)
            for k in dr:
                if k in ref and k in base and ref[k]['trait'] == t:
                    for g in group(ref[k]):
                        by[g].append(k)
            for g, ks in by.items():
                if len(ks) < 20:
                    continue
                sp = collections.defaultdict(list)
                for n_, k in enumerate(ks):
                    sp[ref[k]['species']].append(n_)
                y = np.array([float(ref[k]['value']) for k in ks]); o = np.array([dr[k][ti] for k in ks]); q = np.array([base[k][ti] for k in ks])
                groups = [np.array(v) for v in sp.values()]
                d = []
                for _ in range(1000):
                    idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
                    d.append(spearman(y[idx], o[idx]) - spearman(y[idx], q[idx]))
                lo, hi = np.percentile(d, [2.5, 97.5])
                res[name][f'reference {t} | {g}']['minus_planttraitnet'] = [round(float(spearman(y, o) - spearman(y, q)), 3), round(float(lo), 3), round(float(hi), 3)]
                print(f'DIFF {name:22s} {t:9s} {g:34s} n={len(ks):5d} species={len(groups):5d}  {spearman(y, o) - spearman(y, q):+.3f} ({lo:+.3f} to {hi:+.3f})', flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f'even-scores{a.tag}.json').write_text(json.dumps(res, indent=1) + '\n')
    cells = sorted({c for r in res.values() for c in r}, key=lambda c: (c.split()[0] != 'validation', TRAITS.index(c.split()[1]), c))
    for c in cells:
        n = next(r[c]['n'] for r in res.values() if c in r)
        print(f'{c:62s} n={n:6d}  ' + '  '.join(f"{name}={r[c]['spearman']:.3f}" if c in r else f'{name}=-' for name, r in res.items()))


def fit(a):
    import torch
    import train as T
    DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
    D, S = a.data, a.data / 'sota-out'
    a.out.mkdir(parents=True, exist_ok=True)
    parts = set(a.arm.split('+'))
    sizes = SIZESX if 'fx' in parts else SIZES8 if 'f8' in parts else SIZES3
    use_flora = bool(parts & {'f3', 'f8', 'fx'})

    def load(name, emb_dir):
        rows = tsv(S / f'{name}.tsv')
        e = np.load(S / emb_dir / 'emb-0.npy').astype(np.float32)
        k = {key: i for i, key in enumerate((S / emb_dir / 'emb-0.keys').read_text().split('\n')[:len(e)])}
        rows = [r for r in rows if r['key'] in k]
        x = e[[k[r['key']] for r in rows]]
        loc = None
        if 'loc' in parts:
            l = np.load(S / f'loc-{name}.npy')
            lk = {key: i for i, key in enumerate((S / f'loc-{name}.keys').read_text().split('\n'))}
            loc = l[[lk[r['key']] for r in rows]]
        return rows, torch.from_numpy(x).to(DEV), None if loc is None else torch.from_numpy(loc).to(DEV)
    trn, XT, LT = load('ptn-train', 'emb-ptn-train')
    val, XV, LV = load('ptn-val', 'emb-ptn-val')
    ref, XR, LR = load('ptn-reference', 'emb-ptn-ref')
    y = np.log10(np.array([[float(r[t]) for t in TRAITS] for r in trn]).clip(1e-6))
    mu, sd = y.mean(0), y.std(0)
    yz = torch.tensor((y - mu) / sd, dtype=torch.float32, device=DEV)
    sp_names, sp_inv = np.unique([r['species'] for r in trn], return_inverse=True)
    wt = torch.from_numpy((1.0 / np.minimum(np.bincount(sp_inv), a.cap))[sp_inv].astype(np.float32)).to(DEV) if a.cap else torch.ones(len(trn), device=DEV)
    gt, gv, gr = (np.array([T.bucket(r['genus']) for r in rows]) for rows in (trn, val, ref))
    nt = len(TRAITS)
    print('arm', a.arm, 'regime', a.regime, 'training', len(trn), 'species', len(sp_names), 'val', len(val), 'reference', len(ref), flush=True)

    # flora side: our photographs with flora labels
    if use_flora or 'ours' in parts:
        size = collections.defaultdict(dict)
        for r in tsv(D / ('measure-labels-v3.tsv' if 'fx' in parts else 'measure-labels-v2.tsv' if 'f8' in parts else 'measure-labels.tsv')):
            if r['trait'] in sizes:
                size[r['taxon']][r['trait']] = float(r['log10_m'])
        allowed = collections.defaultdict(dict)
        for r in tsv(D / 'pilot-labels-v3.tsv') + (tsv(D / 'extra-labels.tsv') if 'fx' in parts else []):
            allowed[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
        cats = sorted(allowed)
        classes = {t: sorted({c for s in allowed[t].values() for c in s}) for t in cats}
        labelled = set(size) | {t for d in allowed.values() for t in d}
        emb, ids = T.load_embeddings(D / 'emb')
        row = {}
        for n, i in enumerate(ids):
            row.setdefault(int(i), n)
        rows, taxa = [], []
        for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
            if int(r['photo_id']) in row and r['taxon'] in labelled:
                rows.append(row[int(r['photo_id'])]); taxa.append(r['taxon'])
        names, inv = np.unique(np.array(taxa), return_inverse=True)
        XF = torch.from_numpy(emb[rows].astype(np.float32)).to(DEV)
        del emb
        inv_t = torch.from_numpy(inv).to(DEV)
        ys = np.array([[size[t].get(k, np.nan) for k in sizes] for t in names], np.float32)
        ys = (ys - np.nanmean(ys, 0)) / np.nanstd(ys, 0)
        ys_t, ms_t = torch.from_numpy(np.nan_to_num(ys)).to(DEV), torch.from_numpy(~np.isnan(ys)).to(DEV)
        sets = {}
        for t in cats:
            ci = {c: n for n, c in enumerate(classes[t])}
            m = np.zeros((len(names), len(classes[t])), np.float32)
            for n, s in enumerate(names):
                for c in allowed[t].get(s, ()):
                    m[n, ci[c]] = 1
            sets[t] = torch.from_numpy(m).to(DEV)
        wphoto = torch.from_numpy((1.0 / np.minimum(np.bincount(inv), 50))[inv].astype(np.float32)).to(DEV)
        gf = np.array([T.bucket(t.split()[0]) for t in taxa])
        ncat, ns = sum(len(classes[t]) for t in cats), len(sizes)
        tv = {}
        for r in trn:
            tv.setdefault(r['species'], [float(r[t]) for t in TRAITS])
        yts = np.full((len(names), nt), np.nan, np.float32)
        for n, s_ in enumerate(names):
            b = binomial(s_)
            if b in tv:
                yts[n] = (np.log10(np.clip(tv[b], 1e-6, None)) - mu) / sd
        has_try = ~np.isnan(yts).any(1)
        yts_t = torch.from_numpy(np.nan_to_num(yts)).to(DEV)
        print('flora photographs', len(rows), 'species', len(names), '| our species with a TRY value', int(has_try.sum()), 'photographs', int(has_try[inv].sum()), flush=True)

    def flora_net(ftr, seed):
        torch.manual_seed(seed)
        net = torch.nn.Sequential(torch.nn.Linear(XF.shape[1], 2048), torch.nn.GELU(), torch.nn.Dropout(0.3),
                                  torch.nn.Linear(2048, 512), torch.nn.GELU(), torch.nn.Linear(512, ns + ncat)).to(DEV)
        opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-2)
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=a.flora_steps)
        net.train()
        for _ in range(a.flora_steps):
            fb = ftr[torch.randint(len(ftr), (4096,), device=DEV)]
            o, sp, w = net(XF[fb]), inv_t[fb], wphoto[fb]
            m = ms_t[sp] * w[:, None]
            fl = (torch.nn.functional.smooth_l1_loss(o[:, :ns], ys_t[sp], reduction='none') * m).sum() / m.sum().clamp(min=1e-6)
            k = ns
            for t in cats:
                C = len(classes[t])
                s = sets[t][sp]
                has = (s.sum(1) > 0).float() * w
                mass = (torch.softmax(o[:, k:k + C], 1) * s).sum(1).clamp(min=1e-6)
                fl = fl + (-(torch.log(mass)) * has).sum() / has.sum().clamp(min=1e-6) / len(cats)
                k += C
            opt.zero_grad(); fl.backward(); opt.step(); sched.step()
        net.eval()

        def feats(q):
            with torch.no_grad():
                outs = []
                for i in range(0, len(q), 65536):
                    o = net(q[i:i + 65536])
                    out, k = [o[:, :ns]], ns
                    for t in cats:
                        out.append(torch.softmax(o[:, k:k + len(classes[t])], 1) * 3)
                        k += len(classes[t])
                    outs.append(torch.cat(out, 1))
                return torch.cat(outs)
        return feats

    def run(tr_idx, ftr_idx, te_v, te_r, seed):
        """One model: returns predictions for val rows te_v and reference rows te_r (standardised)."""
        feats = flora_net(ftr_idx, seed) if use_flora else None

        def inp(x, loc):
            cols = [x] if 'emb' in parts else []
            if feats is not None:
                cols.append(feats(x))
            if 'loc' in parts:
                cols.append(loc)
            return torch.cat(cols, 1)
        Xin = inp(XT, LT)
        torch.manual_seed(seed + 7)
        net = torch.nn.Sequential(torch.nn.Linear(Xin.shape[1], a.width), torch.nn.GELU(), torch.nn.Dropout(a.dropout),
                                  torch.nn.Linear(a.width, 512), torch.nn.GELU(), torch.nn.Linear(512, nt)).to(DEV)
        opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=a.wd)
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, a.lr, total_steps=a.steps)
        if 'ours' in parts:
            ttr = ftr_idx[torch.from_numpy(has_try[inv]).to(DEV)[ftr_idx]]
            Lz = torch.zeros(1, LT.shape[1], device=DEV) if 'loc' in parts else None     # our photographs: no location used
        net.train()
        for _ in range(a.steps):
            b = tr_idx[torch.randint(len(tr_idx), (a.batch,), device=DEV)]
            l = torch.nn.functional.smooth_l1_loss(net(Xin[b]), yz[b], reduction='none').mean(1)
            loss = (l * wt[b]).sum() / wt[b].sum()
            if 'ours' in parts:
                tb = ttr[torch.randint(len(ttr), (a.batch,), device=DEV)]
                w = wphoto[tb]
                o = net(inp(XF[tb], None if Lz is None else Lz.expand(len(tb), -1)))
                loss = loss + a.ours_weight * (torch.nn.functional.smooth_l1_loss(o, yts_t[inv_t[tb]], reduction='none').mean(1) * w).sum() / w.sum()
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        net.eval()
        with torch.no_grad():
            tv_, tr_ = torch.from_numpy(te_v).to(DEV), torch.from_numpy(te_r).to(DEV)
            return (net(inp(XV[tv_], None if LV is None else LV[tv_])).cpu().numpy(),
                    net(inp(XR[tr_], None if LR is None else LR[tr_])).cpu().numpy() if len(te_r) else np.zeros((0, nt), np.float32))

    seeds = [int(s) for s in a.seeds.split(',')]
    pv, pr = np.zeros((len(val), nt), np.float32), np.zeros((len(ref), nt), np.float32)
    everything = lambda n: torch.arange(n, device=DEV)
    if a.regime == 'all':
        ftr = everything(len(gf)) if (use_flora or 'ours' in parts) else None
        out = [run(everything(len(trn)), ftr, np.arange(len(val)), np.arange(len(ref)), s) for s in seeds]
        pv, pr = np.mean([o[0] for o in out], 0) * sd + mu, np.mean([o[1] for o in out], 0) * sd + mu
    else:
        for fold in range(5):
            held = lambda g: (g - 2 * fold) % 10 < 2
            tr = torch.from_numpy(np.flatnonzero(~held(gt))).to(DEV)
            ftr = torch.from_numpy(np.flatnonzero(~held(gf))).to(DEV) if (use_flora or 'ours' in parts) else None
            te_v, te_r = np.flatnonzero(held(gv)), np.flatnonzero(held(gr))
            out = [run(tr, ftr, te_v, te_r, 1000 * s + fold) for s in seeds]
            pv[te_v] = np.mean([o[0] for o in out], 0) * sd + mu
            pr[te_r] = np.mean([o[1] for o in out], 0) * sd + mu
            print('fold', fold, len(te_v), len(te_r), flush=True)
    np.savez(a.out / f'{a.arm}@{a.regime}{a.tag}.npz', val_keys=np.array([r['key'] for r in val]), val_pred=pv,
             ref_keys=np.array([r['key'] for r in ref]), ref_pred=pr, traits=np.array(TRAITS))
    for ti, t in enumerate(TRAITS):
        rk = [i for i, r in enumerate(ref) if r['trait'] == t]
        print('RESULT', a.arm, a.regime, t, 'val', round(spearman([float(r[t]) for r in val], pv[:, ti]), 3),
              'reference', round(spearman([float(ref[i]['value']) for i in rk], pr[rk, ti]), 3), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('lists', 'climplicit', 'fit', 'score'))
    p.add_argument('--data', type=Path)
    p.add_argument('--root', type=Path)
    p.add_argument('--models', type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--arm', default='emb')
    p.add_argument('--regime', choices=('all', 'folds'), default='all')
    p.add_argument('--steps', type=int, default=12000)
    p.add_argument('--flora-steps', type=int, default=4500)
    p.add_argument('--batch', type=int, default=1024)
    p.add_argument('--width', type=int, default=2048)
    p.add_argument('--dropout', type=float, default=0.3)
    p.add_argument('--lr', type=float, default=1e-3)
    p.add_argument('--wd', type=float, default=1e-2)
    p.add_argument('--cap', type=int, default=0, help='a species counts at most this many photographs (0: every photograph counts once)')
    p.add_argument('--ours-weight', type=float, default=1.0)
    p.add_argument('--seeds', default='0,1,2')
    p.add_argument('--tag', default='')
    p.add_argument('preds', nargs='*', help='score: NAME=predictions.npz')
    a = p.parse_args()
    {'lists': lists, 'climplicit': climplicit, 'fit': fit, 'score': score}[a.mode](a)


if __name__ == '__main__':
    main()
