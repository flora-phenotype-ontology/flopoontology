"""Our model (frozen BioCLIP 2 + small head) on THE PlantTraitNet benchmark data, next to PlantTraitNet and the Schiller CNNs.

Which comparison is fair here: PlantTraitNet and Schiller et al. predict continuous TRY traits, so our encoder is given the same
supervision (the TRY species values of ``val.csv``, no flora text) and the same kind of head, trained on the downloaded part of
PlantTraitNet's validation split with the genus-held-out folds we use everywhere (five rotating fifths, ``train.bucket``). The published
benchmark of PlantTraitNet (sPlotOpen plots on a 1-degree grid, 300 000 uncurated photographs) is NOT reproduced: it needs 415 GB of images
and the plot data. What is compared instead, on the same photographs:

  val        ~20,600 validation photographs: Spearman and Pearson r of the prediction with the TRY species value (log10) and
             balanced accuracy for the plant functional type (Grass / Shrub / Tree ...), PlantTraitNet and Schiller as published, ours
             on held-out genera
  reference  in-situ measurements (height, leaf area, SLA, leaf N measured on the plant in the photograph): rank correlation with
             the measurement for each model; ours again on held-out genera

PlantTraitNet's target scaler is not released, so its numbers are compared by rank and Pearson r on log10, not by R2 in original units.

    python ptn_benchmark.py fit   --data DIR --emb-val DIR/sota-out/emb-ptn-val --emb-ref DIR/sota-out/emb-ptn-reference --out DIR/sota-out/ptn
    python ptn_benchmark.py score --data DIR --ours DIR/sota-out/ptn/ours.npz --ptn DIR/sota-out/ptn-val/pred.npz,DIR/sota-out/ptn-ref/pred.npz \
                                  --schiller DIR/sota-out/schiller-val/pred.npz,DIR/sota-out/schiller-ref/pred.npz --out DIR/sota-out/ptn
``fit`` is GPU (tiny); ``score`` is numpy (login node).
"""
import argparse
import collections
import json
from pathlib import Path

import numpy as np

from common import import_pilot, spearman, tsv

TRAITS = ['Height', 'LeafArea', 'SLA', 'Leaf_N']


def load_emb(folder):
    e = np.load(Path(folder) / 'emb-0.npy').astype(np.float32)
    k = (Path(folder) / 'emb-0.keys').read_text().split('\n')[:len(e)]
    return {key: i for i, key in enumerate(k)}, e


def fit(a):
    import torch
    T, R = import_pilot()
    dev = R.DEV
    val = tsv(a.data / 'ptn-val.tsv')
    ref = tsv(a.data / 'ptn-reference.tsv')
    vrow, vemb = load_emb(a.emb_val)
    rrow, remb = load_emb(a.emb_ref)
    val = [r for r in val if r['key'] in vrow]
    ref = [r for r in ref if r['key'] in rrow]
    pfts = sorted({r['pft'] for r in val})
    y = np.log10(np.array([[float(r[t]) for t in TRAITS] for r in val]).clip(1e-6))
    mu, sd = y.mean(0), y.std(0)
    yz = torch.tensor((y - mu) / sd, dtype=torch.float32, device=dev)
    pf = torch.tensor([pfts.index(r['pft']) for r in val], device=dev)
    cw = torch.tensor(len(pf) / (len(pfts) * np.maximum(np.bincount(pf.cpu().numpy(), minlength=len(pfts)), 1)), dtype=torch.float32, device=dev)
    X = torch.from_numpy(vemb[[vrow[r['key']] for r in val]]).to(dev)
    XR = torch.from_numpy(remb[[rrow[r['key']] for r in ref]]).to(dev)
    gv = np.array([T.bucket(r['genus']) for r in val])
    gr = np.array([T.bucket(r['genus']) for r in ref])
    pred_val = np.zeros((len(val), len(TRAITS)), np.float32)
    pft_val = np.zeros((len(val), len(pfts)), np.float32)
    pred_ref = np.zeros((len(ref), len(TRAITS)), np.float32)
    for fold in range(5):
        tr = torch.from_numpy(np.flatnonzero((gv - 2 * fold) % 10 >= 2)).to(dev)
        te_v = np.flatnonzero((gv - 2 * fold) % 10 < 2)
        te_r = np.flatnonzero((gr - 2 * fold) % 10 < 2)
        torch.manual_seed(fold)
        net = torch.nn.Sequential(torch.nn.Linear(X.shape[1], 1024), torch.nn.GELU(), torch.nn.Dropout(0.2),
                                  torch.nn.Linear(1024, len(TRAITS) + len(pfts))).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=5e-4, weight_decay=1e-4)
        epochs, bs = a.epochs, 512
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=epochs * (len(tr) // bs + 1))
        net.train()
        for _ in range(epochs):
            perm = tr[torch.randperm(len(tr), device=dev)]
            for i in range(0, len(perm), bs):
                b = perm[i:i + bs]
                o = net(X[b])
                loss = torch.nn.functional.mse_loss(o[:, :len(TRAITS)], yz[b]) + \
                    torch.nn.functional.cross_entropy(o[:, len(TRAITS):], pf[b], weight=cw)
                opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        net.eval()
        with torch.no_grad():
            o = net(X[torch.from_numpy(te_v).to(dev)]).cpu().numpy()
            pred_val[te_v] = o[:, :len(TRAITS)] * sd + mu
            pft_val[te_v] = torch.softmax(torch.from_numpy(o[:, len(TRAITS):]), 1).numpy()
            if len(te_r):
                o = net(XR[torch.from_numpy(te_r).to(dev)]).cpu().numpy()
                pred_ref[te_r] = o[:, :len(TRAITS)] * sd + mu
        print('fold', fold, 'val', len(te_v), 'reference', len(te_r), flush=True)
    np.savez(a.out / 'ours.npz', val_keys=np.array([r['key'] for r in val]), val_pred=pred_val, val_pft=pft_val,
             pfts=np.array(pfts), ref_keys=np.array([r['key'] for r in ref]), ref_pred=pred_ref, traits=np.array(TRAITS))


def corr(x, y):
    return float(np.corrcoef(x, y)[0, 1]) if len(x) > 2 else float('nan')


def score(a):
    val = {r['key']: r for r in tsv(a.data / 'ptn-val.tsv')}
    ref = {r['key']: r for r in tsv(a.data / 'ptn-reference.tsv')}
    ours = np.load(a.ours)
    models = {'ours (BioCLIP 2 + head)': {'val': dict(zip(ours['val_keys'], ours['val_pred'])),
                                          'ref': dict(zip(ours['ref_keys'], ours['ref_pred']))}}

    def collect(paths, name_for):
        out = {}
        for part, f in zip(('val', 'ref'), paths.split(',')):
            z = np.load(f)
            for name, cols in name_for(z).items():
                out.setdefault(name, {'val': {}, 'ref': {}})[part].update(dict(zip(z['ids'], cols)))
        return out
    if a.ptn:
        def ptn_cols(z):
            ok = z['has_geo']
            d = {'PlantTraitNet multi-trait (3 seeds)': np.mean([z[f'multitrait_seed{s}_mu'] for s in (0, 100, 200)], 0)}
            single = [z[f'singletrait_{k}_seed0_mu'][:, 0] for k in ('plantheight', 'LA', 'sla', 'LN')]
            d['PlantTraitNet single-trait (seed 0)'] = np.stack(single, 1)
            return d
        models.update(collect(a.ptn, ptn_cols))
    if a.schiller:
        order = {'Height': 'gh', 'LeafArea': 'la', 'SLA': 'sla', 'Leaf_N': 'lnc'}
        models.update(collect(a.schiller, lambda z: {'Schiller et al. 2021 (ensemble)': np.stack([z[f'ens_{order[t]}'] for t in TRAITS], 1)}))
    sp_val = {}
    for r_ in val.values():
        sp_val.setdefault(r_['species'], {t: float(r_[t]) for t in TRAITS})
    res = {}
    for name, d in models.items():
        r = res[name] = {}
        for ti, t in enumerate(TRAITS):
            keys = [k for k in d['val'] if k in val]
            if keys:
                truth = np.log10(np.array([float(val[k][t]) for k in keys]).clip(1e-6))
                pred = np.array([d['val'][k][ti] for k in keys])
                r[f'val_{t}'] = {'n': len(keys), 'spearman': spearman(truth, pred), 'pearson_log10': corr(truth, pred)}
                sp = collections.defaultdict(list)
                for k, p_ in zip(keys, pred):
                    sp[val[k]['species']].append(p_)
                names = sorted(sp)
                tsp = np.log10(np.array([sp_val[n_][t] for n_ in names]).clip(1e-6))
                r[f'val_{t}']['spearman_species_mean'] = spearman(tsp, [np.mean(sp[n_]) for n_ in names])
            rk = [k for k in d['ref'] if k in ref and ref[k]['trait'] == t]
            if rk:
                truth = np.log10(np.array([float(ref[k]['value']) for k in rk]).clip(1e-6))
                pred = np.array([d['ref'][k][ti] for k in rk])
                r[f'reference_{t}'] = {'n': len(rk), 'spearman': spearman(truth, pred), 'pearson_log10': corr(truth, pred)}
    pft_true = [val[k]['pft'] for k in ours['val_keys']]
    pfts = list(ours['pfts'])
    pred = [pfts[int(i)] for i in ours['val_pft'].argmax(1)]
    hit, tot = collections.Counter(), collections.Counter()
    for t_, p_ in zip(pft_true, pred):
        tot[t_] += 1
        hit[t_] += t_ == p_
    res['ours (BioCLIP 2 + head)']['val_PFT_balanced_accuracy'] = float(np.mean([hit[c] / tot[c] for c in tot if tot[c] >= 5]))
    print(json.dumps(res, indent=1))
    (a.out / 'ptn-scores.json').write_text(json.dumps(res, indent=1) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['fit', 'score'])
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--emb-val', type=Path)
    p.add_argument('--emb-ref', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--epochs', type=int, default=30)
    p.add_argument('--ours', type=Path)
    p.add_argument('--ptn')
    p.add_argument('--schiller')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    fit(a) if a.mode == 'fit' else score(a)


if __name__ == '__main__':
    main()
