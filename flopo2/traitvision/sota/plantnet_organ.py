"""Pl@ntNet-300K (Garcin et al. 2021, CC BY 4.0): a public benchmark whose images carry the plant organ shown (flower, fruit, leaf, bark,
habit, ...), entered by Pl@ntNet users. Two uses:

``lists``  (login node, CPU) read the zip's metadata and write ``plantnet-list.tsv`` (key, path = member of the zip) and
           ``plantnet-meta.tsv`` (key, split, organ, species)
``fit``    (GPU) train an organ head on the frozen BioCLIP 2 embeddings of the train split, report accuracy / balanced accuracy on the test
           split, then apply the head to OUR photographs (all photographs with BioCLIP 2 embeddings) and score it against iNaturalist's
           phenology annotations in the same way as ``score_phenology.py`` (observation score = maximum over its photographs): area under
           the curve for "flowering" and "fruiting" using the organ probabilities flower and fruit. Writes
           ``organ-probs.npz`` and ``organ-as-pheno.npz`` (the format of ``phenology-scores.npz``; use it with ``allphotos_train.py --pheno``
           ``--thr 0.5`` to choose fruit photographs for the fruit-colour test).

This is the "their benchmark" direction for the fruit-versus-flower question: no model is trained on our labels, the organ labels come from
Pl@ntNet users, and the held-out test is Pl@ntNet's own test split.

    python plantnet_organ.py lists --zip DIR/sota-benchmarks/plantnet-300k/plantnet_300K.zip --out DIR/sota-out
    python plantnet_organ.py fit --data DIR --emb DIR/sota-out/emb-plantnet --out DIR/sota-out/plantnet-organ
"""
import argparse
import collections
import json
import re
import zipfile
from pathlib import Path

import numpy as np

from common import auc, import_pilot, tsv


def lists(a):
    z = zipfile.ZipFile(a.zip)
    names = z.namelist()
    meta_name = next(n for n in names if n.endswith('metadata.json'))
    meta = json.loads(z.read(meta_name))
    members = {Path(n).stem: n for n in names if re.search(r'\.(jpg|jpeg|png)$', n, re.I)}
    a.out.mkdir(parents=True, exist_ok=True)
    first = next(iter(meta.items()))
    print('metadata example', first)
    n = 0
    with open(a.out / 'plantnet-list.tsv', 'w') as fl, open(a.out / 'plantnet-meta.tsv', 'w') as fm:
        fl.write('key\tpath\n')
        fm.write('key\tsplit\torgan\tspecies\n')
        for key, m in meta.items():
            if key in members:
                fl.write(f'{key}\t{members[key]}\n')
                fm.write(f"{key}\t{m.get('split', '')}\t{m.get('organ', '')}\t{m.get('species_id', m.get('class', ''))}\n")
                n += 1
    print('images listed', n, 'of', len(meta), 'metadata entries,', len(members), 'files')


def fit(a):
    import torch
    T, R = import_pilot()
    dev = R.DEV
    meta = {r['key']: r for r in tsv(a.meta or a.emb.parent / 'plantnet-meta.tsv')}
    e = np.load(a.emb / 'emb-0.npy').astype(np.float32)
    keys = (a.emb / 'emb-0.keys').read_text().split('\n')[:len(e)]
    count = collections.Counter(meta[k]['organ'] for k in keys if k in meta and meta[k]['organ'])
    organs = sorted(o for o, n in count.items() if n >= 200)       # drops 'branch' (37), 'scan' (2), 'none' (1)
    oi = {o: i for i, o in enumerate(organs)}
    sel = [n for n, k in enumerate(keys) if k in meta and meta[k]['organ'] in oi]
    X = torch.from_numpy(e[sel]).to(dev)
    y = torch.tensor([oi[meta[keys[n]]['organ']] for n in sel], device=dev)
    split = np.array([meta[keys[n]]['split'] for n in sel])
    tr = torch.from_numpy(np.flatnonzero(split == 'train')).to(dev)
    cnt = np.bincount(y[tr].cpu().numpy(), minlength=len(organs))
    cw = torch.tensor(len(tr) / (len(organs) * np.maximum(cnt, 1)), dtype=torch.float32, device=dev)
    torch.manual_seed(0)
    net = torch.nn.Sequential(torch.nn.Linear(X.shape[1], 1024), torch.nn.GELU(), torch.nn.Dropout(0.2),
                              torch.nn.Linear(1024, len(organs))).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=5e-4, weight_decay=1e-4)
    bs, epochs = 1024, a.epochs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=epochs * (len(tr) // bs + 1))
    net.train()
    for _ in range(epochs):
        perm = tr[torch.randperm(len(tr), device=dev)]
        for i in range(0, len(perm), bs):
            b = perm[i:i + bs]
            loss = torch.nn.functional.cross_entropy(net(X[b]), y[b], weight=cw)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    net.eval()
    res = {'organs': organs, 'train_counts': dict(zip(organs, cnt.tolist()))}
    with torch.no_grad():
        for part in ('val', 'test'):
            idx = torch.from_numpy(np.flatnonzero(split == part)).to(dev)
            pred = torch.cat([net(X[idx[i:i + 65536]]).argmax(1) for i in range(0, len(idx), 65536)])
            t = y[idx]
            rec = [float((pred[t == c] == c).float().mean()) for c in range(len(organs)) if (t == c).any()]
            res[part] = {'n': len(idx), 'accuracy': float((pred == t).float().mean()), 'balanced_accuracy': float(np.mean(rec)),
                         'recall': {organs[c]: float((pred[t == c] == c).float().mean()) for c in range(len(organs)) if (t == c).any()}}
    print(json.dumps(res, indent=1), flush=True)
    # apply to our photographs
    D = a.data
    emb, ids = T.load_embeddings(D / 'emb')
    femb, fids = T.load_embeddings(D / 'emb-field')
    allx = torch.from_numpy(np.concatenate([emb, femb])).to(dev)
    allids = np.concatenate([ids, fids])
    with torch.no_grad():
        prob = torch.cat([torch.softmax(net(allx[i:i + 65536]), 1) for i in range(0, len(allx), 65536)]).cpu().numpy()
    np.savez(a.out / 'organ-probs.npz', ids=allids, prob=prob.astype(np.float16), organs=np.array(organs))
    fl, fr = organs.index('flower'), organs.index('fruit')
    isfield = np.arange(len(allids)) >= len(ids)
    p3 = np.zeros((len(allids), 3), np.float16)
    p3[:, 0], p3[:, 1] = prob[:, fl], prob[:, fr]
    np.savez(a.out / 'organ-as-pheno.npz', values=np.array(['flowering', 'fruiting', 'budding']), ids=allids[~isfield], prob=p3[~isfield],
             field_ids=allids[isfield], field_prob=p3[isfield])
    # against iNaturalist phenology annotations (bag maximum, up to 12 photographs, as in phenology_head.py)
    pheno = {r['observation_uuid']: set(r['values'].split('|')) for r in tsv(D / 'phenology-v3.tsv') if r['values'] and r['values'] != 'gone'}
    row = {int(i): n for n, i in enumerate(allids)}
    bags = collections.defaultdict(list)
    for r in tsv(D / 'sota-photos.tsv'):
        if r['observation'] in pheno and 'pheno' in r['role'].split(',') and int(r['photo_id']) in row:
            bags[r['observation']].append(row[int(r['photo_id'])])
    obs = sorted(bags)
    yv = np.array([['flowering' in pheno[o], 'fruiting' in pheno[o]] for o in obs], float)
    sc = np.array([[prob[bags[o][:12], fl].max(), prob[bags[o][:12], fr].max()] for o in obs])
    res['inat_phenology'] = {'n_observations': len(obs), 'auc_flowering_from_flower_prob': auc(sc[:, 0], yv[:, 0]),
                             'auc_fruiting_from_fruit_prob': auc(sc[:, 1], yv[:, 1])}
    print(json.dumps(res['inat_phenology'], indent=1))
    (a.out / 'plantnet-organ.json').write_text(json.dumps(res, indent=1) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['lists', 'fit'])
    p.add_argument('--zip', type=Path)
    p.add_argument('--data', type=Path)
    p.add_argument('--emb', type=Path)
    p.add_argument('--meta', type=Path, help='plantnet-meta.tsv (default: next to the embedding folder)')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--epochs', type=int, default=15)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    lists(a) if a.mode == 'lists' else fit(a)


if __name__ == '__main__':
    main()
