"""Score any frozen image encoder on OUR tests, exactly as ``allphotos_train.py`` scores BioCLIP 2.

Same protocol: flora labels (``pilot-labels-v3.tsv``) as the only training signal, one bag per species (8 photographs drawn per step),
two-layer perceptron, loss on the mean prediction of the bag, class weights, five rotating held-out-genus folds
(``train.bucket``), balanced accuracy (mean recall over classes with 5+ cases, ``regime_tests.bal``) on

* agreed species (``agreed-v3.tsv``, 2+ floras state the same single value), photographs pooled per species;
* observers' labels (``field-test-v3.tsv``), all photographs of the observation pooled.

Difference to ``allphotos_train.py``: training and test photographs are restricted to the photographs listed in the SOTA manifest
(``sota-photos.tsv``: at most 8 photographs per species, role ``train``; every photograph of the labelled observations, role ``field``),
so that every encoder, BioCLIP 2 included, sees exactly the same pixels and the same number of them. The BioCLIP 2 row of this script is
therefore the reference for the others, not the 1-million-photograph number of the paper. With ``--feature-name`` an encoder is a folder
``DIR/sota-out/<name>`` in the layout of ``embed.py`` (emb-*.npy / emb-*.ids, photo ids), or ``bioclip2`` (the existing ``emb`` +
``emb-field``).

    python probe_any.py --data DIR --names bioclip2,planttraitnet,... [--seeds 0,1,2] --out DIR/sota-out/probe
    python probe_any.py --data DIR --names planttraitnet-pred,schiller-pred --head linear --standardize --out ...   (predicted traits only)
GPU job: tools/orix/traitvision_sota_probe.sbatch.
"""
import argparse
import collections
import json
from pathlib import Path

import numpy as np
import torch

from common import import_pilot, tsv

T, R = import_pilot()
DEV = R.DEV


def features(D, name, ids_wanted):
    """float32 matrix of the wanted photo ids (rows in the order of the returned id list). ``a+b`` joins two encoders."""
    if '+' in name:
        parts = [features(D, n, ids_wanted) for n in name.split('+')]
        common = set(parts[0][1]).intersection(*(q[1] for q in parts[1:]))
        keep = [i for i in parts[0][1] if i in common]
        out = []
        for e, i in parts:
            r = {v: n for n, v in enumerate(i)}
            out.append(e[[r[v] for v in keep]])
        return np.concatenate(out, 1), keep
    if name == 'bioclip2':
        folders = [D / 'emb', D / 'emb-field']
    elif (D / 'sota-out' / name).exists():
        folders = [D / 'sota-out' / name]
    else:                                                  # the pilot's baseline encoders: emb-<name>, emb-<name>-field
        folders = [D / f'emb-{name}', D / f'emb-{name}-field']
    embs, ids = [], []
    for f in folders:
        e, i = T.load_embeddings(f)
        embs.append(e)
        ids.append(i)
    emb, ids = np.concatenate(embs), np.concatenate(ids)
    row = {}
    for n, i in enumerate(ids):
        row.setdefault(int(i), n)
    keep = [i for i in ids_wanted if i in row]
    return emb[[row[i] for i in keep]].astype(np.float32), keep


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--names', default='bioclip2')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--manifest', default='sota-photos.tsv')
    p.add_argument('--seeds', default='0')
    p.add_argument('--traits', default='')
    p.add_argument('--folds', default='0,1,2,3,4')
    p.add_argument('--head', default='mlp', choices=['mlp', 'linear'], help='linear for low-dimensional inputs such as predicted traits')
    p.add_argument('--standardize', action='store_true', help='z-score every feature column (predicted trait values)')
    p.add_argument('--ids-from', default='', help='keep only the photographs that this encoder has too (same photographs for every row)')
    p.add_argument('--require-geo', action='store_true', help='keep only photographs with a location (PlantTraitNet embeddings)')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    D = a.data
    man = tsv(D / a.manifest)
    train_ids = [int(r['photo_id']) for r in man if 'train' in r['role'].split(',')]
    field_ids = [int(r['photo_id']) for r in man if 'field' in r['role'].split(',')]
    taxon_of = {int(r['photo_id']): r['taxon'] for r in man}
    obs_photos = collections.defaultdict(list)
    for r in man:
        if 'field' in r['role'].split(','):
            obs_photos[r['observation']].append(int(r['photo_id']))
    keys, _ = T.text_embeddings(D / 'emb')
    labels = collections.defaultdict(dict)
    for r in tsv(D / 'pilot-labels-v3.tsv'):
        labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    agreed = collections.defaultdict(dict)
    for r in tsv(D / 'agreed-v3.tsv'):
        if int(r['floras']) >= 2:
            agreed[r['trait']][r['taxon']] = r['value']
    field = collections.defaultdict(list)
    for r in tsv(D / 'field-test-v3.tsv'):
        field[r['trait']].append((r['class'], r['taxon'].split()[0], r['observation']))
    want = [t for t in sorted(labels) if not a.traits or t in a.traits.split(',')]
    result = {}
    for name in a.names.split(','):
        X, got = features(D, name, train_ids + field_ids)
        if a.ids_from:
            have = set(features(D, a.ids_from, train_ids + field_ids)[1])
            sel = [n for n, i in enumerate(got) if i in have]
            X, got = X[sel], [got[n] for n in sel]
        if a.require_geo:
            geo = {int(r['photo_id']) for r in man if r['latitude'] and r['longitude']}
            sel = [n for n, i in enumerate(got) if i in geo]
            X, got = X[sel], [got[n] for n in sel]
        if a.standardize:
            X = (X - X.mean(0)) / (X.std(0) + 1e-6)
        row = {i: n for n, i in enumerate(got)}
        x = torch.from_numpy(X.astype(np.float32)).to(DEV)
        tr_set = set(train_ids)
        pid = np.array([i for i in got if i in tr_set])
        taxa = np.array([taxon_of[i] for i in pid])
        gb = np.array([T.bucket(t.split()[0]) for t in taxa])
        print(name, 'dim', X.shape[1], 'train photos', len(pid), 'field photos', len(got) - len(pid), flush=True)
        for seed in (int(s) for s in a.seeds.split(',')):
            per_trait = {}
            for trait in want:
                lab = labels[trait]
                classes = sorted(c for c in {c for s in lab.values() for c in s} if f'zs:{trait}:{c}' in keys)
                cidx = {c: i for i, c in enumerate(classes)}
                C = len(classes)
                lab = {t: s & set(classes) for t, s in lab.items() if s & set(classes)}
                inlab = np.array([t in lab for t in taxa])
                P_, taxa_t, gb_t = pid[inlab], taxa[inlab], gb[inlab]
                names, inv = np.unique(taxa_t, return_inverse=True)
                tset = {t: np.array([1.0 if c in lab[t] else 0 for c in classes], np.float32) for t in names}
                xi = torch.from_numpy(np.array([row[i] for i in P_])).to(DEV)
                xt = x[xi]
                obs = [(v, g, o) for v, g, o in field[trait] if v in cidx and any(q in row for q in obs_photos.get(o, []))]
                pairs = {'agreed': [], 'observers': []}
                for fold in (int(f) for f in a.folds.split(',')):
                    bk = (gb_t - 2 * fold) % 10
                    use, held = bk >= 2, bk < 2
                    sp, sinv = np.unique(taxa_t[use], return_inverse=True)
                    idx = np.flatnonzero(use)
                    order = np.argsort(sinv, kind='stable')
                    start = np.r_[0, np.flatnonzero(np.diff(sinv[order])) + 1, len(order)]
                    m = int(min(np.bincount(sinv).max(), 64))
                    member = np.stack([np.resize(idx[order[start[k]:start[k + 1]]], m) for k in range(len(sp))])
                    hard = np.stack([tset[t] for t in sp])
                    freq = np.maximum(hard[hard.sum(1) == 1].sum(0), 1)
                    spw = torch.from_numpy((hard * (freq.sum() / freq / C)).max(1).astype(np.float32)).to(DEV)
                    spt = torch.from_numpy(hard).to(DEV)
                    head = R.fit(xt, spt, None, a.head, 'set', seed=seed, bags=(spt, spw, torch.from_numpy(member).to(DEV)))
                    ph = R.prob(head, xt)
                    g = R.group_mean(ph[torch.from_numpy(held).to(DEV)], taxa_t[held])
                    pairs['agreed'] += [(agreed[trait][t], classes[int(np.argmax(v))]) for t, v in g.items()
                                        if agreed[trait].get(t) in cidx]
                    for v, genus, o in obs:
                        if (T.bucket(genus) - 2 * fold) % 10 < 2:
                            rr = [row[q] for q in obs_photos[o] if q in row]
                            pf = R.prob(head, x[torch.tensor(rr, device=DEV)])
                            pairs['observers'].append((v, classes[int(pf.mean(0).argmax())]))
                per_trait[trait] = {'agreed': R.bal(pairs['agreed']), 'n_agreed': len(pairs['agreed']),
                                    'observers': R.bal(pairs['observers']), 'n_observers': len(pairs['observers'])}
                print(name, 'seed', seed, trait, per_trait[trait], flush=True)
            mean = lambda k: float(np.mean([v[k] for v in per_trait.values() if v[k] is not None]))
            per_trait['mean'] = {'agreed': mean('agreed'), 'observers': mean('observers')}
            result[f'{name}|seed{seed}'] = per_trait
            print(name, 'seed', seed, 'MEAN', per_trait['mean'], flush=True)
            (a.out / 'probe.json').write_text(json.dumps(result, indent=1) + '\n')


if __name__ == '__main__':
    main()
