"""Baseline 2: every photograph, flora + observers' labels, sizes from the floras, and species identification.

Categorical traits (the eight pilot traits): MLP head with bags, one bag per species (flora label, a set of
allowed values) and one per labelled observation (observer's value; together they weigh 0.3 of the species
bags); photographs with a box of the trait's organ, else all, for the leaf traits and spines. Class weights
are capped at CAP times the mean (uncapped, a value with one or two single-valued species got a weight of
several hundred and pulled every species that allows it).

Sizes (``labels``: plant height, leaf, fruit, seed, petal and flower sizes stated by the floras, log10 m):
one regression MLP, a species counts once.

Everything is fitted five times over held-out genera; each photograph is predicted by the model that saw no
species of its genus. The species name is a training label only, never an input.

Species identification of unseen genera: the candidates are the species of the held-out genera with
photographs and at least MIN_TRAITS described categorical traits. An observation (all its photographs) is
scored against a candidate by the sum over traits of the log likelihood ratio: for a categorical trait
sum_v p(v | photos) p(v | c) / p(v); for a size the normal density of the predicted value around the
candidate's flora value against the mean density over candidates (spread: the model's own error on the other
folds). A trait the floras do not give for a candidate is neutral.

    python3 -m flopo2.traitvision.baseline_v2 labels local-corpora/trait-vision
    python baseline_v2.py fit --data DIR --out DIR/baseline-v2            (needs train.py, regime_tests.py)
"""
import argparse
import collections
import csv
import json
import math
import statistics
import sys
from pathlib import Path

RULES = {('whole plant', 'height'): ('height', 'high'), ('stem', 'height'): ('height', 'high'),
         ('leaf lamina', 'length'): ('leaf_length', 'mid'), ('leaf', 'length'): ('leaf_length', 'mid'),
         ('leaf lamina', 'width'): ('leaf_width', 'mid'), ('leaf', 'width'): ('leaf_width', 'mid'),
         ('fruit', 'length'): ('fruit_length', 'mid'), ('fruit', 'width'): ('fruit_width', 'mid'), ('fruit', 'diameter'): ('fruit_width', 'mid'),
         ('seed', 'length'): ('seed_length', 'mid'), ('seed', 'diameter'): ('seed_length', 'mid'),
         ('petal', 'length'): ('petal_length', 'mid'), ('corolla', 'length'): ('petal_length', 'mid'),
         ('flower', 'diameter'): ('flower_diameter', 'mid'), ('corolla', 'diameter'): ('flower_diameter', 'mid')}
SIZES = ('height', 'leaf_length', 'leaf_width', 'fruit_length', 'fruit_width', 'seed_length', 'petal_length', 'flower_diameter')
PILOT = {'flower_colour', 'fruit_colour', 'habit', 'inflorescence', 'leaf_arrangement', 'leaf_complexity', 'leaf_margin', 'spines'}
# values next to each other on their scale (pattern 17 of docs/odp for shapes and arrangement, the colour space for
# colours, the ordered scales otherwise): used only by the arm ``adjacent``
NEIGHBOURS = {
    'leaf_shape': [('linear', 'lanceolate'), ('linear', 'oblong'), ('lanceolate', 'elliptic'), ('lanceolate', 'ovate'), ('elliptic', 'ovate'),
                   ('elliptic', 'obovate'), ('elliptic', 'oblong'), ('elliptic', 'round'), ('ovate', 'cordate'), ('ovate', 'round')],
    'leaf_arrangement': [('opposite', 'whorled')],
    'flower_colour': [('red', 'pink'), ('red', 'orange'), ('red', 'purple'), ('red', 'brown'), ('orange', 'yellow'), ('orange', 'brown'), ('pink', 'purple'),
                      ('pink', 'white'), ('purple', 'blue')],
    'leaf_apex': [('acute', 'acuminate'), ('acute', 'obtuse'), ('acute', 'mucronate'), ('obtuse', 'emarginate')],
    'leaf_base': [('cuneate', 'rounded'), ('rounded', 'cordate'), ('rounded', 'truncate'), ('truncate', 'cordate')],
    'habit': [('shrub', 'tree'), ('herb', 'shrub')],
    'life_span': [('annual', 'biennial'), ('biennial', 'perennial')],
    'fruit_shape': [('globose', 'ovoid'), ('ovoid', 'elongate')],
    'leaf_texture': [('papery', 'membranous'), ('papery', 'coriaceous')],
    'posture': [('erect', 'ascending'), ('ascending', 'prostrate')],
    'leaf_margin': [('toothed', 'lobed')],
}
NEIGHBOURS['fruit_colour'] = NEIGHBOURS['flower_colour'] + [('purple', 'black'), ('brown', 'black')]
EXTRA_SIZES = ('leaflet_length', 'leaflet_width')
COUNTS = ('n_flowers', 'n_stamens', 'n_petals', 'n_sepals', 'n_leaflets', 'n_seeds', 'n_ray_flowers', 'n_veins', 'n_styles', 'n_carpels')
ORGAN_SET = {'leaf_margin', 'leaf_complexity', 'leaf_arrangement', 'spines'}
ALPHA, CAP, MIN_TRAITS, SAMPLE = 0.3, 10.0, 4, 3000
# traits read from a region of the photograph instead of the whole: folder with the region embeddings
# (boxes-train.tsv, boxes-field.tsv, emb-train, emb-field), and the PhenoVision stage and score that a photograph
# needs for its boxes to count (None: every box counts). A photograph without a region keeps its whole embedding.
REGION = {'fruit_colour': ('fruit-region', 'fruiting', 0.6)}


def labels(folder):
    folder = Path(folder)
    vals, srcs = collections.defaultdict(list), collections.defaultdict(set)
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
        if v and 1e-4 <= v <= (130 if rule[0] == 'height' else 6):
            vals[r['taxon'], rule[0]].append(math.log10(v))
            srcs[r['taxon'], rule[0]].add(r['source'])
    with open(folder / 'measure-labels-v2.tsv', 'w') as f:
        f.write('taxon\ttrait\tlog10_m\tstatements\tsources\n')
        for (t, k), v in sorted(vals.items()):
            f.write(f'{t}\t{k}\t{statistics.median(v):.4f}\t{len(v)}\t{len(srcs[t, k])}\n')
    print({k: sum(1 for key in vals if key[1] == k) for k in SIZES})


def fit(a):
    import numpy as np
    import torch
    import regime_tests as R
    import train as T
    DEV = R.DEV
    D = a.data
    a.out.mkdir(parents=True, exist_ok=True)
    emb, ids = T.load_embeddings(D / a.emb)
    keys, _ = T.text_embeddings(D / 'emb')
    row_of = {}
    for n, i in enumerate(ids):
        row_of.setdefault(int(i), n)
    pid, taxa, obs_of = [], [], []
    for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
        if int(r['photo_id']) in row_of:
            pid.append(int(r['photo_id'])); taxa.append(r['taxon']); obs_of.append(r['observation_uuid'])
    pid, taxa = np.array(pid), np.array(taxa)
    N = len(pid)
    x = torch.from_numpy(emb[[row_of[i] for i in pid]]).to(DEV)
    del emb
    gb = np.array([T.bucket(t.split()[0]) for t in taxa])
    femb, fids = T.load_embeddings(D / (a.emb + '-field'))
    frow = {}
    for n, i in enumerate(fids):
        frow.setdefault(int(i), n)
    xa = torch.cat([x, torch.from_numpy(femb).to(DEV)])        # observers' photographs follow at offset N
    F = len(femb)
    pidx = {int(i): n for n, i in enumerate(pid)}
    regions = {}                                               # trait -> (photo -> rows, field photo -> rows, first row, end row)
    for trait, (folder, stage, thr) in REGION.items():
        if trait not in a.regions.split(','):
            continue
        ok = None
        if stage:
            z = np.load(D / 'sota-out' / 'phenovision' / 'phenovision-as-pheno.npz')
            k = list(z['values']).index(stage)
            ok = {int(i) for i_, p_ in ((z['ids'], z['prob']), (z['field_ids'], z['field_prob'])) for i, v in zip(i_, p_[:, k]) if v >= thr}
        lo = base = xa.shape[0]
        tre, fre, parts = {}, {}, []
        for name, dest, known in (('train', tre, pidx), ('field', fre, frow)):
            e, cid = T.load_embeddings(D / folder / f'emb-{name}')
            crow = {int(c): n for n, c in enumerate(cid)}
            keep = []
            for r in csv.DictReader(open(D / folder / f'boxes-{name}.tsv'), delimiter='\t'):
                q, c = int(r['photo_id']), int(r['crop_id'])
                if q in known and c in crow and (ok is None or q in ok):
                    dest.setdefault(q, []).append(base + len(keep)); keep.append(crow[c])
            parts.append(e[keep]); base += len(keep)
        xa = torch.cat([xa, torch.from_numpy(np.concatenate(parts)).to(DEV)])
        regions[trait] = (tre, fre, lo, base)
        print('regions', trait, 'photographs', len(tre), 'observers photographs', len(fre), 'regions', base - lo, flush=True)
    labels_, family = collections.defaultdict(dict), {}
    extra = (D / 'extra-labels.tsv').exists()                  # labels_extra.py: leaf texture, life span, persistence, shape
    v5 = (D / 'labels-v5.tsv').exists() and not a.labels_v3     # labels_extra.py on the re-extracted statements: all traits
    for f in ['labels-v5.tsv'] if v5 else ['pilot-labels-v3.tsv'] + (['extra-labels.tsv'] if extra else []):
        for r in csv.DictReader(open(D / f), delimiter='\t'):
            labels_[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
            family.setdefault(r['taxon'], r['family'])
    pilot = {t: d for t, d in labels_.items() if t in PILOT}  # the candidates of the identification: always by the standard labels
    if a.labels:                                               # a variant of the labels (labels_extra.py): training and the candidates' values
        labels_ = collections.defaultdict(dict)
        for r in csv.DictReader(open(D / a.labels), delimiter='\t'):
            labels_[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
            family.setdefault(r['taxon'], r['family'])
    agreed = collections.defaultdict(dict)
    for f in ['agreed-v5.tsv'] if v5 else ['agreed-v3.tsv'] + (['agreed-extra.tsv'] if extra else []):
        for r in csv.DictReader(open(D / f), delimiter='\t'):
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
            field[r['trait']].append((r['class'], r['taxon'].split()[0], ph, r['taxon'], r['observation']))
    onames, oinv = np.unique(np.array(obs_of), return_inverse=True)       # observation of every photograph
    report = {'traits': {}, 'sizes': {}}
    cat = {}                                                   # trait -> (classes, prob (N, C) float16, chosen (N,) bool)
    traits = [t for t in sorted(labels_) if not a.traits or t in a.traits.split(',')]
    old = json.loads((a.reuse / 'baseline-v2.json').read_text()) if a.reuse else {}
    for trait in traits:
        if a.reuse and trait not in regions and (a.reuse / f'pred-{trait}.npz').exists():
            z = np.load(a.reuse / f'pred-{trait}.npz')
            assert (z['photo_ids'] == pid).all()
            cat[trait] = ([str(c) for c in z['classes']], z['prob'], z['chosen'])
            report['traits'][trait] = old['traits'][trait]
            if a.reuse != a.out:
                np.savez(a.out / f'pred-{trait}.npz', **{k: z[k] for k in z.files})
            print('reused', trait, flush=True)
            continue
        reg = regions.get(trait)
        lab = labels_[trait]
        classes = sorted(c for c in {c for s in lab.values() for c in s} if a.all_classes or trait not in PILOT or f'zs:{trait}:{c}' in keys)
        cidx = {c: i for i, c in enumerate(classes)}
        C = len(classes)
        lab = {t: s & set(classes) for t, s in lab.items() if s & set(classes)}
        boxes = (R.ORGAN_BOX.get(trait) or set()) if trait in ORGAN_SET else set()
        has = (lambda i: i in reg[0] or i in reg[1]) if reg else (lambda i: any(i in organ[o] for o in boxes))
        boxes = boxes or bool(reg)
        has_box = np.array([has(int(i)) for i in pid]) if boxes else np.ones(N, bool)
        rows_f = lambda q: (reg[1].get(q) if reg else None) or [N + frow[q]]
        if reg:                                                # (photograph, region row) pairs, to pool the regions' answers
            tn = np.array([pidx[q] for q, rr in reg[0].items() for _ in rr]); trr = np.array([j - reg[2] for rr in reg[0].values() for j in rr])
            fn = np.array([frow[q] for q, rr in reg[1].items() for _ in rr]); frr = np.array([j - reg[2] for rr in reg[1].values() for j in rr])

            def swap(p, at, rows, pr):                         # a photograph with regions answers with their mean
                at, rows = torch.from_numpy(at).to(DEV), torch.from_numpy(rows).to(DEV)
                s = torch.zeros_like(p).index_add_(0, at, pr[rows].to(p.dtype))
                c = torch.zeros(len(p), 1, device=DEV, dtype=p.dtype).index_add_(0, at, torch.ones(len(at), 1, device=DEV, dtype=p.dtype))
                return torch.where(c > 0, s / c.clamp(min=1), p)
        names, inv = np.unique(taxa, return_inverse=True)
        any_box = np.zeros(len(names), bool)
        np.logical_or.at(any_box, inv, has_box)
        mask = has_box | ~any_box[inv]                         # training and species pooling: organ, else all
        oany = np.zeros(len(onames), bool)
        np.logical_or.at(oany, oinv, has_box)
        chosen = has_box | ~oany[oinv]                         # observation pooling
        labelled = np.array([t in lab for t in taxa])
        tset = {t: np.array([1.0 if c in lab[t] else 0 for c in classes], np.float32) for t in names if t in lab}
        bset = tset                                            # the allowed values as stated: for the class weights
        if a.arm == 'one-value':                               # ignore that a flora gives alternatives: one of them, at random
            pick = np.random.default_rng(a.seed)
            tset = {t: np.eye(C, dtype=np.float32)[pick.choice(np.flatnonzero(v))] for t, v in sorted(tset.items())}
            bset = tset
        elif a.arm == 'adjacent':                              # a neighbouring value on the scale counts a little
            nb = np.zeros((C, C), np.float32)
            for u, v in NEIGHBOURS.get(trait, ()):
                if u in cidx and v in cidx:
                    nb[cidx[u], cidx[v]] = nb[cidx[v], cidx[u]] = 1
            tset = {t: np.maximum(v, 0.3 * np.minimum(v @ nb, 1)) for t, v in tset.items()}
        obs = [o for o in field[trait] if o[0] in cidx]
        frows = []                                             # observers' observations of held-out genera: what the head says
        choose = lambda ph: ([q for q in ph if has(q)] or ph) if boxes else ph
        prob = np.zeros((N, C), np.float16)
        pairs = collections.defaultdict(list)
        for fold in range(5):
            bk = (gb - 2 * fold) % 10
            tr, held = bk >= 2, bk < 2
            is_held = lambda o: (T.bucket(o[1]) - 2 * fold) % 10 < 2
            fobs, tobs = [o for o in obs if is_held(o)], [o for o in obs if not is_held(o)]
            use = tr & mask & labelled
            sp, sinv = np.unique(taxa[use], return_inverse=True)
            idx = np.flatnonzero(use)
            order = np.argsort(sinv, kind='stable')
            start = np.r_[0, np.flatnonzero(np.diff(sinv[order])) + 1, len(order)]
            groups = [idx[order[start[k]:start[k + 1]]] for k in range(len(sp))]
            if reg:
                groups = [np.array([j for n in g for j in (reg[0].get(int(pid[n])) or [n])]) for g in groups]
            m = int(min(max(len(g) for g in groups), 64))
            member = np.stack([np.resize(g, m) for g in groups])
            hard = np.stack([tset[t] for t in sp])
            cap = 1e9 if a.arm == 'no-cap' else CAP
            cw = lambda h: np.minimum((lambda f: f.sum() / f / C)(np.maximum(h[h.sum(1) == 1].sum(0), 1)), cap)
            hb = np.stack([bset[t] for t in sp])
            spw = (hb * cw(hb)).max(1).astype(np.float32)
            mem, tg, w = member, hard, spw
            if len(tobs) >= 100 and a.arm != 'no-observers':
                omember = np.stack([np.resize([j for q in choose(o[2]) for j in rows_f(q)], m) for o in tobs])
                ohard = np.zeros((len(tobs), C), np.float32)
                ohard[np.arange(len(tobs)), [cidx[o[0]] for o in tobs]] = 1
                ow = (ohard * cw(ohard)).max(1).astype(np.float32)
                mem, tg = np.concatenate([member, omember]), np.concatenate([hard, ohard])
                w = np.concatenate([spw, ow * (ALPHA * spw.sum() / ow.sum())])
            tt = torch.from_numpy(tg).to(DEV)
            if a.arm == 'photo':                               # no bags: every photograph carries its species' label alone
                items = np.concatenate(groups)
                owner = np.repeat(np.arange(len(groups)), [len(g) for g in groups])
                pw_ = (spw / np.array([len(g) for g in groups]))[owner].astype(np.float32)
                head = R.fit(xa[torch.from_numpy(items).to(DEV)], torch.from_numpy(hard[owner]).to(DEV), torch.from_numpy(pw_).to(DEV), 'mlp', 'set', seed=a.seed)
            else:
                head = R.fit(xa, tt, None, 'mlp', 'set', seed=a.seed, bags=(tt, torch.from_numpy(w).to(DEV), torch.from_numpy(mem).to(DEV)))
            ph = R.prob(head, x[torch.from_numpy(np.flatnonzero(held)).to(DEV)])
            pf = R.prob(head, xa[N:N + F])
            if reg:
                pr = R.prob(head, xa[reg[2]:reg[3]])
                at = np.full(N, -1); at[np.flatnonzero(held)] = np.arange(int(held.sum()))
                ph = swap(ph, at[tn[held[tn]]], trr[held[tn]], pr)
                pf = swap(pf, fn, frr, pr)
            prob[held] = ph.cpu().numpy()
            sel = (mask & labelled)[held]
            g = R.group_mean(ph[torch.from_numpy(sel).to(DEV)], taxa[held][sel])
            pairs['agreed'] += [(agreed[trait][t], classes[int(np.argmax(v))]) for t, v in g.items() if agreed[trait].get(t) in cidx]
            for v, _, photos, taxon_, obs_ in fobs:
                pm = pf[[frow[q] for q in choose(photos)]].mean(0)
                pairs['observers'].append((v, classes[int(pm.argmax())]))
                frows.append((obs_, taxon_, v, pm.cpu().numpy()))
            print(trait, 'fold', fold, 'species bags', len(sp), 'observation bags', len(tobs) if len(tobs) >= 100 else 0, flush=True)
        sc = {t: R.bal(pairs[t]) for t in ('agreed', 'observers')}
        report['traits'][trait] = {'agreed': sc['agreed'], 'n_agreed': len(pairs['agreed']), 'observers': sc['observers'], 'n_observers': len(pairs['observers'])}
        print(f"RESULT {trait:17s} agreed (n={len(pairs['agreed'])}) {(sc['agreed'] if sc['agreed'] is not None else float('nan')):.3f}   observers (n={len(pairs['observers'])}) "
              + ('  -' if sc['observers'] is None else f"{sc['observers']:.3f}"), flush=True)
        cat[trait] = (classes, prob, chosen)
        np.savez(a.out / f'pred-{trait}.npz', photo_ids=pid, prob=prob, classes=np.array(classes), chosen=chosen)
        if frows:
            np.savez(a.out / f'field-pred-{trait}.npz', observation=np.array([r[0] for r in frows]), taxon=np.array([r[1] for r in frows]),
                     value=np.array([r[2] for r in frows]), prob=np.stack([r[3] for r in frows]).astype(np.float32), classes=np.array(classes))
        (a.out / 'baseline-v2.json').write_text(json.dumps(report, indent=1) + '\n')

    # ---- sizes
    size = collections.defaultdict(dict)
    v3 = (D / 'measure-labels-v3.tsv').exists() and not a.sizes_v2      # labels_extra.py: accepted names, leaflets, counts
    SIZES = globals()['SIZES'] + (EXTRA_SIZES + COUNTS if v3 else ())
    slo, shi = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in csv.DictReader(open(D / ('measure-labels-v3.tsv' if v3 else 'measure-labels-v2.tsv')), delimiter='\t'):
        size[r['taxon']][r['trait']] = float(r['log10_m'])
        slo[r['taxon']][r['trait']] = float(r.get('low') or r['log10_m'])       # the range the floras state
        shi[r['taxon']][r['trait']] = float(r.get('high') or r['log10_m'])
    names, inv = np.unique(taxa, return_inverse=True)
    y = np.array([[size.get(t, {}).get(k, np.nan) for k in SIZES] for t in names], np.float32)
    mu, sd = np.nanmean(y, 0), np.nanstd(y, 0)
    yz = (y - mu) / sd
    yt = torch.from_numpy(np.nan_to_num(yz)[inv]).to(DEV)
    zr = lambda d: torch.from_numpy(np.nan_to_num((np.array([[d.get(t, {}).get(k, np.nan) for k in SIZES] for t in names], np.float32) - mu) / sd)[inv]).to(DEV)
    ylo, yhi = (zr(slo), zr(shi)) if a.ranges in ('train', 'both') else (None, None)
    mt = torch.from_numpy(~np.isnan(yz)[inv]).to(DEV)
    wt = torch.from_numpy((1.0 / np.minimum(np.bincount(inv), 50))[inv].astype(np.float32)).to(DEV)
    has_any = (~np.isnan(y)).any(1)[inv]
    spred = np.zeros((N, len(SIZES)), np.float32)
    for fold in range(5):
        tr = torch.from_numpy(np.flatnonzero(((gb - 2 * fold) % 10 >= 2) & has_any)).to(DEV)
        torch.manual_seed(a.seed)
        net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 2048), torch.nn.GELU(), torch.nn.Dropout(0.3),
                                  torch.nn.Linear(2048, 512), torch.nn.GELU(), torch.nn.Linear(512, len(SIZES))).to(DEV)
        opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-2)
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=15 * (len(tr) // 4096 + 1))
        net.train()
        for _ in range(15):
            perm = tr[torch.randperm(len(tr), device=DEV)]
            for i in range(0, len(perm), 4096):
                b = perm[i:i + 4096]
                wm = mt[b] * wt[b][:, None]
                out = net(x[b])
                err = torch.nn.functional.smooth_l1_loss(out, yt[b], reduction='none')
                if ylo is not None:                            # no error inside the stated range; a light pull to its middle
                    gap = torch.relu(ylo[b] - out) + torch.relu(out - yhi[b])
                    err = torch.nn.functional.smooth_l1_loss(gap, torch.zeros_like(gap), reduction='none') + 0.1 * err
                loss = (err * wm).sum() / wm.sum()
                opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        net.eval()
        with torch.no_grad():
            te = torch.from_numpy(np.flatnonzero((gb - 2 * fold) % 10 < 2)).to(DEV)
            spred[te.cpu().numpy()] = torch.cat([net(x[te[i:i + 65536]]) for i in range(0, len(te), 65536)]).cpu().numpy() * sd + mu
        print('sizes fold', fold, flush=True)
    sp_mean = np.zeros((len(names), len(SIZES))); np.add.at(sp_mean, inv, spred); sp_mean /= np.bincount(inv)[:, None]
    rank = lambda v: np.argsort(np.argsort(v))
    for n, k in enumerate(SIZES):
        ok = ~np.isnan(y[:, n])
        rho = float(np.corrcoef(rank(sp_mean[ok, n]), rank(y[ok, n]))[0, 1])
        report['sizes'][k] = {'species': int(ok.sum()), 'spearman_held_out': rho, 'rmse_log10': float(np.sqrt(((sp_mean[ok, n] - y[ok, n]) ** 2).mean()))}
        print(f'RESULT size {k:16s} species {int(ok.sum()):6d}  Spearman on unseen genera {rho:.3f}', flush=True)
    np.savez(a.out / 'pred-sizes.npz', photo_ids=pid, pred=spred.astype(np.float16), sizes=np.array(SIZES))

    # ---- species identification of unseen genera
    rng = np.random.default_rng(0)
    alltraits = {t for d in labels_.values() for t in d}
    ntr = collections.Counter(t for d in pilot.values() for t in d)        # candidates: by the eight pilot traits, as before
    # observation-level size prediction and its error per fold (for the spread: the other folds)
    osize = np.zeros((len(onames), len(SIZES))); np.add.at(osize, oinv, spred); osize /= np.bincount(oinv)[:, None]
    otax = np.empty(len(onames), object); otax[oinv] = taxa
    ofold = np.array([next(f for f in range(5) if (T.bucket(t.split()[0]) - 2 * f) % 10 < 2) for t in otax])
    oy = np.array([[size.get(t, {}).get(k, np.nan) for k in SIZES] for t in otax])
    VARIANTS = {'categorical': (True, ()), 'categorical + height and leaf size': (True, SIZES[:3]),
                'categorical + all sizes': (True, tuple(k for k in SIZES if k not in COUNTS)), 'sizes only': (False, tuple(k for k in SIZES if k not in COUNTS))}
    if v3:
        VARIANTS['categorical + all sizes + counts'] = (True, SIZES)
    tot = collections.Counter()
    store = {}
    oreg, sreg = {}, {}
    if a.geo:                                                  # botanical country of the observation; countries each species is recorded from
        oreg = {r['observation']: r['region'] for r in csv.DictReader(open(a.geo / 'obs-regions.tsv'), delimiter='\t')}
        sreg = {r['taxon']: set(r['regions'].split('|')) for r in csv.DictReader(open(a.geo / 'species-regions.tsv'), delimiter='\t')}
        VARIANTS['region only'] = (False, ('_region',))
        VARIANTS['categorical + all sizes + counts + region'] = (True, SIZES + ('_region',))
    for fold in range(5):
        sigma = np.sqrt(np.nanmean((osize[ofold != fold] - oy[ofold != fold]) ** 2, 0))
        hobs = np.flatnonzero(ofold == fold)
        cands = sorted({t for t in set(otax[hobs]) if ntr[t] >= MIN_TRAITS})
        cix = {t: n for n, t in enumerate(cands)}
        fam = np.array([family[t] for t in cands])
        hobs = hobs[[otax[o] in cix for o in hobs]]
        hobs = hobs[rng.choice(len(hobs), min(SAMPLE, len(hobs)), replace=False)]
        true = np.array([cix[otax[o]] for o in hobs])
        opos = {int(o): n for n, o in enumerate(hobs)}
        prow = np.flatnonzero(np.isin(oinv, hobs))
        ppos = torch.from_numpy(np.array([opos[int(o)] for o in oinv[prow]])).to(DEV)
        parts, perfect = {}, {}
        store[fold] = {'P': {}, 'M': {}, 'D': {}, 'S': {}, 'true': None, 'fam': None}
        for trait, (classes, prob, chosen) in cat.items():
            m = np.zeros((len(cands), len(classes)), np.float32)
            described = np.zeros(len(cands), bool)
            for t, n in cix.items():
                s = [classes.index(c) for c in labels_[trait].get(t, ()) if c in classes]
                if s:
                    m[n, s] = 1 / len(s); described[n] = True
            prior = m[described].mean(0) + 1e-6
            if a.rule == 'wmc':                                # weighted model count: P(value in the candidate's set | photographs)
                ind = (m > 0).astype(np.float32)               # over P(value in the set) among the candidates
                pc = prior / prior.sum()
                ratio = torch.from_numpy(np.where(described[:, None], ind / np.maximum(ind @ pc, 1e-6)[:, None], 1.0).astype(np.float32)).to(DEV)
            else:
                ratio = torch.from_numpy(np.where(described[:, None], m / prior, 1.0).astype(np.float32)).to(DEV)
            wsel = torch.from_numpy(chosen[prow].astype(np.float32)).to(DEV)[:, None]
            pp = torch.from_numpy(prob[prow].astype(np.float32)).to(DEV) * wsel
            p = torch.zeros(len(hobs), len(classes), device=DEV).index_add_(0, ppos, pp) / torch.zeros(len(hobs), 1, device=DEV).index_add_(0, ppos, wsel).clamp(min=1)
            if a.temp != 1:                                    # sharpen (> 1) or flatten (< 1) the model's answer
                p = p.clamp(min=1e-6) ** a.temp
                p = p / p.sum(1, keepdim=True)
            parts[trait] = torch.log(p @ ratio.T + 1e-6)
            store[fold]['P'][trait], store[fold]['M'][trait], store[fold]['D'][trait] = p, torch.from_numpy(m).to(DEV), torch.from_numpy(described).to(DEV)
            own = torch.from_numpy(np.where(described[true][:, None], m[true], prior / prior.sum()).astype(np.float32)).to(DEV)
            perfect[trait] = torch.log(own @ ratio.T + 1e-6)
        cy = np.array([[size.get(t, {}).get(k, np.nan) for k in SIZES] for t in cands])
        clo = np.array([[slo.get(t, {}).get(k, np.nan) for k in SIZES] for t in cands])
        chi = np.array([[shi.get(t, {}).get(k, np.nan) for k in SIZES] for t in cands])
        for n, k in enumerate(SIZES):
            desc = ~np.isnan(cy[:, n])
            if desc.sum() < 2:
                continue
            c = torch.from_numpy(np.nan_to_num(cy[:, n])).to(DEV)[None, :]
            dm = torch.from_numpy(desc).to(DEV)[None, :]

            lo_ = torch.from_numpy(np.where(desc, np.minimum(clo[:, n], cy[:, n] - 0.02), -1.0)).to(DEV)[None, :]      # at least 0.04 wide
            hi_ = torch.from_numpy(np.where(desc, np.maximum(chi[:, n], cy[:, n] + 0.02), 1.0)).to(DEV)[None, :]

            def ll(pred, s, c=c, dm=dm, desc=desc, lo_=lo_, hi_=hi_):
                xx = pred if torch.is_tensor(pred) else torch.from_numpy(pred).to(DEV)
                if a.ranges in ('ident', 'both'):              # the candidate's range as stated, blurred by the model's error
                    cdf = lambda v: 0.5 * (1 + torch.erf((v - xx[:, None]) / (s * 2 ** 0.5)))
                    d = torch.log((cdf(hi_) - cdf(lo_)).clamp(min=1e-12) / (hi_ - lo_))
                else:
                    d = -0.5 * ((xx[:, None] - c) / s) ** 2
                marg = torch.logsumexp(d.masked_fill(~dm, -1e9), 1, keepdim=True) - math.log(int(desc.sum()))
                return torch.where(dm, d - marg, torch.zeros_like(d)).float()
            parts[k] = ll(osize[hobs, n], float(sigma[n]))
            store[fold]['S'][k] = (torch.from_numpy(osize[hobs, n]).to(DEV), float(sigma[n]), ll)
            own = np.where(desc[true], cy[true, n], np.nan)
            pf = ll(np.nan_to_num(own), 0.05)
            perfect[k] = torch.where(torch.from_numpy(~np.isnan(own)).to(DEV)[:, None], pf, torch.zeros_like(pf))
        famt = torch.from_numpy(np.unique(fam, return_inverse=True)[1]).to(DEV)
        truet = torch.from_numpy(true).to(DEV)
        store[fold]['X'] = {}
        if a.geo:                                              # a candidate not recorded from the observation's country counts 0.02
            inreg = np.array([[(oreg.get(str(onames[o])) is None) or (t not in sreg) or (oreg[str(onames[o])] in sreg[t]) for t in cands] for o in hobs])
            parts['_region'] = perfect['_region'] = store[fold]['X']['_region'] = torch.from_numpy(np.where(inreg, 0.0, math.log(0.02)).astype(np.float32)).to(DEV)
            tot['region cands'] += float(inreg.sum()); tot['region true'] += float(inreg[np.arange(len(hobs)), true].sum())
        store[fold]['true'], store[fold]['fam'] = truet, famt
        for vname, (use_cat, sizes) in VARIANTS.items():
            for kind, src in (('model', parts), ('flora values read exactly', perfect)):
                ks = [t for t in cat if use_cat] + [k for k in sizes if k in src]
                s = sum(src[k] for k in ks)
                st = s[torch.arange(len(hobs)), truet][:, None]
                for scope, mask in (('all', torch.ones_like(s, dtype=torch.bool)), ('family', famt[None, :] == famt[truet][:, None])):
                    rk = 1 + ((s > st) & mask).sum(1) + 0.5 * (((s == st) & mask).sum(1) - 1)
                    for kk in (1, 5, 10):
                        tot[vname, kind, scope, f'top{kk}'] += float((rk <= kk).sum())
                        if vname == 'categorical' and kind == 'model':
                            tot['chance', scope, f'top{kk}'] += float(torch.clamp(kk / mask.sum(1), max=1).sum())
                    if vname == 'categorical' and kind == 'model':
                        tot['cands', scope] += float(mask.sum(1).sum())
        tot['obs'] += len(hobs)
        print('identification fold', fold, 'candidates', len(cands), 'observations', len(hobs), flush=True)
    n = tot['obs']
    ident = {}
    for scope in ('all', 'family'):
        ident[scope] = {'candidates_per_observation': tot['cands', scope] / n, 'chance': {f'top{k}': tot['chance', scope, f'top{k}'] / n for k in (1, 5, 10)}}
        print(f"RESULT identification ({scope}): {tot['cands', scope] / n:.0f} candidates per observation; chance first {tot['chance', scope, 'top1'] / n:.4f}")
        for vname in VARIANTS:
            for kind in ('model', 'flora values read exactly'):
                r = {f'top{k}': tot[vname, kind, scope, f'top{k}'] / n for k in (1, 5, 10)}
                ident[scope][f'{vname} | {kind}'] = r
                print(f"RESULT   {vname:36s} {kind:26s} first {r['top1']:.3f}  in first 5 {r['top5']:.3f}  in first 10 {r['top10']:.3f}", flush=True)
    report['identification'] = ident
    if a.geo:
        ident['region'] = {'candidates_in_region_per_observation': tot['region cands'] / n, 'true_species_in_region': tot['region true'] / n}
        print(f"RESULT region: {tot['region cands'] / n:.0f} candidates recorded from the observation's country; the true species among them {tot['region true'] / n:.3f}", flush=True)
    if a.learn:
        report['identification_learned'] = learn_identification(store, cat, labels_, [k for k in SIZES], COUNTS)
    (a.out / 'baseline-v2.json').write_text(json.dumps(report, indent=1) + '\n')


def learn_identification(store, cat, labels_, sizes, counts, steps=200):
    """Identification with a model per trait, learned on the observations of the other folds (other genera; their
    predictions come from heads that never saw them): a weight per trait and per size, the width of each size's error,
    and (second variant) per trait a table of how well each flora value goes with each predicted value. Starts at the
    fixed rule; the loss is the cross-entropy of the true species among the candidates."""
    import numpy as np
    import torch
    DEV = next(iter(store[0]['P'].values())).device
    prior = {}
    for trait, (classes, _, _) in cat.items():
        v = np.full(len(classes), 1e-3)
        for s in labels_[trait].values():
            ok = [classes.index(c) for c in s if c in classes]
            for i in ok:
                v[i] += 1 / len(ok)
        prior[trait] = torch.from_numpy((v / v.sum()).astype(np.float32)).to(DEV)

    def score(th, st, feats):
        s = 0
        for trait in cat:
            if trait not in feats:
                continue
            A = torch.exp(th['A'][trait]) if 'A' in th else torch.diag(1 / prior[trait])
            R = torch.where(st['D'][trait][:, None], st['M'][trait] @ A, torch.ones_like(st['M'][trait]))
            s = s + torch.exp(th['w'][trait]) * torch.log(st['P'][trait] @ R.T + 1e-6)
        for k, (pred, sigma, ll) in st['S'].items():
            if k in feats:
                s = s + torch.exp(th['w'][k]) * ll(pred, sigma * torch.exp(th['s'][k]))
        for k, m in st['X'].items():
            if k in feats:
                s = s + torch.exp(th['w'][k]) * m
        return s

    out = {}
    sets = {'categorical': list(cat), 'categorical + all sizes + counts': list(cat) + list(sizes)}
    if store[0]['X']:
        sets['categorical + all sizes + counts + region'] = list(cat) + list(sizes) + list(store[0]['X'])
    for vname, feats in sets.items():
        for mode in ('fixed rule', 'weights', 'weights + value table'):
            tot, wsum = collections.Counter(), collections.Counter()
            for fold in store:
                th = {'w': {k: torch.zeros((), device=DEV, requires_grad=True) for k in feats},
                      's': {k: torch.zeros((), device=DEV, requires_grad=True) for k in sizes}}
                if mode == 'weights + value table':
                    th['A'] = {t: torch.log(torch.diag(1 / prior[t]) + 1e-3).requires_grad_(True) for t in cat}
                params = [v for d in th.values() for v in d.values()]
                if mode != 'fixed rule':
                    opt = torch.optim.Adam(params, lr=0.03)
                    for _ in range(steps):
                        loss = sum(torch.nn.functional.cross_entropy(score(th, st, feats), st['true']) for g, st in store.items() if g != fold)
                        opt.zero_grad(); loss.backward(); opt.step()
                with torch.no_grad():
                    st = store[fold]
                    s = score(th, st, feats)
                    sv = s[torch.arange(len(s)), st['true']][:, None]
                    for scope, mask in (('all', torch.ones_like(s, dtype=torch.bool)), ('family', st['fam'][None, :] == st['fam'][st['true']][:, None])):
                        rk = 1 + ((s > sv) & mask).sum(1) + 0.5 * (((s == sv) & mask).sum(1) - 1)
                        for kk in (1, 5, 10):
                            tot[scope, kk] += float((rk <= kk).sum())
                    tot['obs'] += len(s)
                    for k in feats:
                        wsum[k] += float(torch.exp(th['w'][k])) / len(store)
            for scope in ('all', 'family'):
                r = {f'top{k}': tot[scope, k] / tot['obs'] for k in (1, 5, 10)}
                out[f'{vname} | {mode} | {scope}'] = r
                print(f"RESULT learned {vname:34s} {mode:22s} {scope:7s} first {r['top1']:.3f}  in first 5 {r['top5']:.3f}  in first 10 {r['top10']:.3f}", flush=True)
            if mode == 'weights':
                out[f'{vname} | weights'] = dict(wsum)
                print('RESULT weights', vname, ' '.join(f'{k}={v:.2f}' for k, v in sorted(wsum.items(), key=lambda kv: -kv[1])), flush=True)
    return out


def main():
    if sys.argv[1] == 'labels':
        return labels(sys.argv[2])
    p = argparse.ArgumentParser()
    p.add_argument('mode')
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--traits', default='')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--arm', default='full', choices=('full', 'one-value', 'adjacent', 'no-observers', 'no-cap', 'photo'),
                   help='ablations of the training signal for the categorical traits')
    p.add_argument('--all-classes', action='store_true', help='keep classes of the eight original traits that have no text prompt (fine classes)')
    p.add_argument('--geo', type=Path, help='folder with obs-regions.tsv and species-regions.tsv: the species recorded from the country of the observation')
    p.add_argument('--emb', default='emb', help='folder of the image embeddings (emb: BioCLIP 2; emb-dinov2, emb-siglip2: models trained without taxon names)')
    p.add_argument('--labels', default='', help='a variant of labels-v5.tsv (file name under --data) for training and the candidates')
    p.add_argument('--ranges', default='', choices=('', 'train', 'ident', 'both'), help='sizes as the ranges the floras state, not their middle')
    p.add_argument('--learn', action='store_true', help='identification: also with weights per trait learned on the other folds')
    p.add_argument('--rule', default='ratio', choices=('ratio', 'wmc'), help='identification: how a candidate set of values is scored')
    p.add_argument('--temp', type=float, default=1.0, help='identification: exponent on the predicted probabilities')
    p.add_argument('--labels-v3', action='store_true', help='pilot-labels-v3.tsv and extra-labels.tsv instead of labels-v5.tsv')
    p.add_argument('--sizes-v2', action='store_true', help='the eight sizes of measure-labels-v2.tsv only')
    p.add_argument('--regions', default=','.join(REGION), help='traits read from regions (comma-separated; empty: none)')
    p.add_argument('--reuse', type=Path, help='folder of an earlier run: its predictions are taken for traits without regions')
    fit(p.parse_args())


if __name__ == '__main__':
    main()
