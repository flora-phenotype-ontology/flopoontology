"""TRY traits on the PlantTraitNet benchmark photographs, trained on TRY labels and on what the floras say, together.

One multi-task MLP on the frozen BioCLIP 2 embedding. Two sources of labels, one batch of each per step:

* TRY      the PlantTraitNet validation photographs of the training genera: Height, LeafArea, SLA, Leaf_N (log10,
           species values of TRY) and the plant functional type, as in ``sota/ptn_benchmark.py fit``;
* flora    our photographs with flora labels: sizes (plant height, leaf length, leaf width; ``measure-labels.tsv``)
           and, in the last arm, the eight categorical traits (``pilot-labels-v3.tsv``, set loss: the probability
           mass on the values the floras allow).

Arms (same folds, same test rows, same network): ``try`` (TRY labels only), ``try+sizes``, ``try+sizes+traits``.
Two-stage arms: a flora network (sizes and categorical traits, flora labels only, ``--flora-steps``) is fitted first; its
outputs for a photograph (three sizes, the probabilities of every categorical value) are then the input of the TRY
head, alone (``stack``) or next to the embedding (``stack+emb``).
Held-out genera, five folds (``train.bucket``): a test photograph is answered by the model that saw no species of
its genus, neither among the TRY photographs nor among ours. Species and genus names are labels and fold keys
only, never an input.

Writes ``<out>/<arm>.npz`` in the layout of ``ptn_benchmark.py fit`` (``ours.npz``), so that
``ptn_benchmark.py score --ours <arm>.npz ...`` scores every arm exactly as the published models are scored.

    python try_joint.py --data DIR --out DIR/try-joint [--arms try,try+sizes] [--steps 1500] [--flora-weight 1]
"""
import argparse
import collections
import csv
from pathlib import Path

import numpy as np
import torch

import train as T

TRAITS = ['Height', 'LeafArea', 'SLA', 'Leaf_N']
SIZES = ('height', 'leaf_length', 'leaf_width')
ARMS = ('try', 'try+sizes', 'try+sizes+traits')
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'


def tsv(path):
    return list(csv.DictReader(open(path, newline=''), delimiter='\t'))


def load_keyed(folder):
    e = np.load(Path(folder) / 'emb-0.npy').astype(np.float32)
    k = (Path(folder) / 'emb-0.keys').read_text().split('\n')[:len(e)]
    return {key: i for i, key in enumerate(k)}, e


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--arms', default=','.join(ARMS))
    p.add_argument('--steps', type=int, default=1500)
    p.add_argument('--seeds', default='0,1,2')
    p.add_argument('--flora-weight', type=float, default=1.0)
    p.add_argument('--width', type=int, default=2048)
    p.add_argument('--flora-steps', type=int, default=4500)
    p.add_argument('--try-species', type=Path, help='TSV species, Height, LeafArea, SLA, Leaf_N: TRY species values put on OUR photographs of these species (training genera only)')
    p.add_argument('--tag', default='')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    D = a.data
    S = D / 'sota-out'

    # TRY side: exactly the rows of ptn_benchmark.py fit
    val, ref = tsv(S / 'ptn-val.tsv'), tsv(S / 'ptn-reference.tsv')
    vrow, vemb = load_keyed(S / 'emb-ptn-val')
    rrow, remb = load_keyed(S / 'emb-ptn-ref')
    val = [r for r in val if r['key'] in vrow]
    ref = [r for r in ref if r['key'] in rrow]
    pfts = sorted({r['pft'] for r in val})
    y = np.log10(np.array([[float(r[t]) for t in TRAITS] for r in val]).clip(1e-6))
    mu, sd = y.mean(0), y.std(0)
    yz = torch.tensor((y - mu) / sd, dtype=torch.float32, device=DEV)
    pf = torch.tensor([pfts.index(r['pft']) for r in val], device=DEV)
    cw = torch.tensor(len(pf) / (len(pfts) * np.maximum(np.bincount(pf.cpu().numpy(), minlength=len(pfts)), 1)), dtype=torch.float32, device=DEV)
    X = torch.from_numpy(vemb[[vrow[r['key']] for r in val]]).to(DEV)
    XR = torch.from_numpy(remb[[rrow[r['key']] for r in ref]]).to(DEV)
    gv = np.array([T.bucket(r['genus']) for r in val])
    gr = np.array([T.bucket(r['genus']) for r in ref])
    nt, npf = len(TRAITS), len(pfts)

    # flora side
    size = collections.defaultdict(dict)
    for r in tsv(D / 'measure-labels.tsv'):
        size[r['taxon']][r['trait']] = float(r['log10_m'])
    allowed = collections.defaultdict(dict)
    for r in tsv(D / 'pilot-labels-v3.tsv'):
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
    ys = np.array([[size[t].get(k, np.nan) for k in SIZES] for t in names], np.float32)
    ys = (ys - np.nanmean(ys, 0)) / np.nanstd(ys, 0)
    ys_t = torch.from_numpy(np.nan_to_num(ys)).to(DEV)                  # per species
    ms_t = torch.from_numpy(~np.isnan(ys)).to(DEV)
    sets = {}                                                           # per trait: species x classes, 1 where allowed (all 0: no label)
    for t in cats:
        ci = {c: n for n, c in enumerate(classes[t])}
        m = np.zeros((len(names), len(classes[t])), np.float32)
        for n, s in enumerate(names):
            for c in allowed[t].get(s, ()):
                m[n, ci[c]] = 1
        sets[t] = torch.from_numpy(m).to(DEV)
    yts = np.full((len(names), nt), np.nan, np.float32)
    if a.try_species:
        tv = {r['species']: [float(r[t]) for t in TRAITS] for r in tsv(a.try_species)}
        for n, s_ in enumerate(names):
            if s_ in tv:
                yts[n] = (np.log10(np.clip(tv[s_], 1e-6, None)) - mu) / sd
    has_try = ~np.isnan(yts).any(1)
    yts_t = torch.from_numpy(np.nan_to_num(yts)).to(DEV)
    wphoto = torch.from_numpy((1.0 / np.minimum(np.bincount(inv), 50))[inv].astype(np.float32)).to(DEV)   # a species counts once (up to 50 photographs)
    gf = np.array([T.bucket(t.split()[0]) for t in taxa])
    ncat = sum(len(classes[t]) for t in cats)
    print('our species with a TRY value', int(has_try.sum()), 'photographs', int(has_try[inv].sum()), flush=True)
    print('TRY photographs', len(val), 'reference rows', len(ref), '| flora photographs', len(rows), 'species', len(names),
          'with sizes', int(ms_t.any(1).sum()), 'categorical traits', {t: int((sets[t].sum(1) > 0).sum()) for t in cats}, flush=True)

    def flora_loss(o, sp, w, use_sizes, use_cats):
        fl = 0.0
        if use_sizes:
            m = ms_t[sp] * w[:, None]
            fl = fl + (torch.nn.functional.smooth_l1_loss(o[:, :3], ys_t[sp], reduction='none') * m).sum() / m.sum().clamp(min=1e-6)
        if use_cats:
            k = 3
            for t in cats:
                C = len(classes[t])
                s = sets[t][sp]
                has = (s.sum(1) > 0).float() * w
                mass = (torch.softmax(o[:, k:k + C], 1) * s).sum(1).clamp(min=1e-6)
                fl = fl + (-(torch.log(mass)) * has).sum() / has.sum().clamp(min=1e-6) / len(cats)
                k += C
        return fl

    seeds = [int(s) for s in a.seeds.split(',')]
    for arm in a.arms.split(','):
        pred_val = np.zeros((len(val), nt), np.float32)
        pft_val = np.zeros((len(val), npf), np.float32)
        pred_ref = np.zeros((len(ref), nt), np.float32)
        for fold in range(5):
            tr = torch.from_numpy(np.flatnonzero((gv - 2 * fold) % 10 >= 2)).to(DEV)
            ftr = torch.from_numpy(np.flatnonzero((gf - 2 * fold) % 10 >= 2)).to(DEV)
            ttr = torch.from_numpy(np.flatnonzero(((gf - 2 * fold) % 10 >= 2) & has_try[inv])).to(DEV)
            te_v = np.flatnonzero((gv - 2 * fold) % 10 < 2)
            te_r = np.flatnonzero((gr - 2 * fold) % 10 < 2)
            ov, orf = [], []
            for seed in seeds:
                torch.manual_seed(1000 * seed + fold)
                Xin, XRin = X, XR
                inp = lambda q: q
                if arm.startswith('stack'):
                    fnet = torch.nn.Sequential(torch.nn.Linear(X.shape[1], a.width), torch.nn.GELU(), torch.nn.Dropout(0.3),
                                               torch.nn.Linear(a.width, 512), torch.nn.GELU(), torch.nn.Linear(512, len(SIZES) + ncat)).to(DEV)
                    fopt = torch.optim.AdamW(fnet.parameters(), lr=1e-3, weight_decay=1e-2)
                    fsched = torch.optim.lr_scheduler.OneCycleLR(fopt, 1e-3, total_steps=a.flora_steps)
                    fnet.train()
                    for _ in range(a.flora_steps):
                        fb = ftr[torch.randint(len(ftr), (4096,), device=DEV)]
                        fl = flora_loss(fnet(XF[fb]), inv_t[fb], wphoto[fb], True, True)
                        fopt.zero_grad(); fl.backward(); fopt.step(); fsched.step()
                    fnet.eval()

                    def feats(q):
                        with torch.no_grad():
                            o = fnet(q)
                            out, k = [o[:, :3]], 3
                            for t in cats:
                                out.append(torch.softmax(o[:, k:k + len(classes[t])], 1) * 3)
                                k += len(classes[t])
                            return torch.cat(out, 1)
                    FV, FR = feats(X), feats(XR)
                    Xin, XRin = (torch.cat([X, FV], 1), torch.cat([XR, FR], 1)) if arm == 'stack+emb' else (FV, FR)
                    inp = (lambda q: torch.cat([q, feats(q)], 1)) if arm == 'stack+emb' else feats
                use_sizes = use_cats = False if arm.startswith('stack') else None
                use_sizes, use_cats = ('sizes' in arm, 'traits' in arm) if use_sizes is None else (False, False)
                trunk = torch.nn.Sequential(torch.nn.Linear(Xin.shape[1], a.width), torch.nn.GELU(), torch.nn.Dropout(0.2)).to(DEV)
                h_try = torch.nn.Linear(a.width, nt + npf).to(DEV)
                h_flora = torch.nn.Linear(a.width, len(SIZES) + ncat).to(DEV)
                params = [*trunk.parameters(), *h_try.parameters(), *h_flora.parameters()]
                opt = torch.optim.AdamW(params, lr=5e-4, weight_decay=1e-4)
                sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=a.steps)
                trunk.train()
                for _ in range(a.steps):
                    b = tr[torch.randint(len(tr), (512,), device=DEV)]
                    o = h_try(trunk(Xin[b]))
                    loss = torch.nn.functional.mse_loss(o[:, :nt], yz[b]) + torch.nn.functional.cross_entropy(o[:, nt:], pf[b], weight=cw)
                    if a.try_species:
                        tb = ttr[torch.randint(len(ttr), (2048,), device=DEV)]
                        w = wphoto[tb]
                        o = h_try(trunk(inp(XF[tb])))
                        loss = loss + (((o[:, :nt] - yts_t[inv_t[tb]]) ** 2).mean(1) * w).sum() / w.sum()
                    if use_sizes or use_cats:
                        fb = ftr[torch.randint(len(ftr), (4096,), device=DEV)]
                        fl = flora_loss(h_flora(trunk(XF[fb])), inv_t[fb], wphoto[fb], use_sizes, use_cats)
                        loss = loss + a.flora_weight * fl
                    opt.zero_grad(); loss.backward(); opt.step(); sched.step()
                trunk.eval()
                with torch.no_grad():
                    ov.append(h_try(trunk(Xin[torch.from_numpy(te_v).to(DEV)])).cpu().numpy())
                    if len(te_r):
                        orf.append(h_try(trunk(XRin[torch.from_numpy(te_r).to(DEV)])).cpu().numpy())
            o = np.mean(ov, 0)
            pred_val[te_v] = o[:, :nt] * sd + mu
            pft_val[te_v] = torch.softmax(torch.from_numpy(o[:, nt:]), 1).numpy()
            if len(te_r):
                pred_ref[te_r] = np.mean(orf, 0)[:, :nt] * sd + mu
            print(arm, 'fold', fold, 'val', len(te_v), 'reference', len(te_r), flush=True)
        np.savez(a.out / f'{arm}{a.tag}.npz', val_keys=np.array([r['key'] for r in val]), val_pred=pred_val, val_pft=pft_val,
                 pfts=np.array(pfts), ref_keys=np.array([r['key'] for r in ref]), ref_pred=pred_ref, traits=np.array(TRAITS))


if __name__ == '__main__':
    main()
