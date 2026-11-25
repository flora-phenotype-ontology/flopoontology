"""Which photograph shows flowers, which fruits: learned from iNaturalist's phenology annotations.

The detector finds the reproductive structure but cannot tell fruit from flower. iNaturalist observations
carry phenology annotations (flowering, fruiting, budding) made by observers and identifiers: a label on the
observation, like every iNaturalist label. A head on the frozen photo embeddings is trained with one bag per
observation: the observation is "fruiting" when its strongest photograph is (maximum over the bag), so the
head learns per photograph without any label per photograph.

Annotated observations only (an observation without annotation says nothing). Every genus is held out in one
of five runs, and every photograph gets its score from the run that did not see its genus.

    python phenology_head.py --data DIR      (standalone: numpy + torch; needs train.py)

Writes ``phenology-scores.npz`` (ids, prob [flowering, fruiting, budding], and the same for the photographs of
observations with an observer's trait label: field_ids, field_prob) and prints, per value, the area under the
curve for held-out observations.
"""
import argparse
import collections
import csv
from pathlib import Path

import numpy as np
import torch

import train as T

VALUES = ('flowering', 'fruiting', 'budding')
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
CAP = 12


def auc(score, truth):
    order = np.argsort(score)
    rank = np.empty(len(score))
    rank[order] = np.arange(1, len(score) + 1)
    pos = truth.sum()
    neg = len(truth) - pos
    return float((rank[truth > 0].sum() - pos * (pos + 1) / 2) / (pos * neg)) if pos and neg else float('nan')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--epochs', type=int, default=20)
    a = p.parse_args()
    D = a.data
    emb, ids = T.load_embeddings(D / 'emb')
    row = {}
    for n, i in enumerate(ids):
        row.setdefault(int(i), n)
    x = torch.from_numpy(emb).to(DEV)
    pheno = {}
    for r in csv.DictReader(open(D / 'phenology-v3.tsv'), delimiter='\t'):
        if r['values'] and r['values'] != 'gone':
            pheno[r['observation_uuid']] = set(r['values'].split('|'))
    bags = collections.defaultdict(list)
    genus_of = {}
    photo_genus = np.empty(len(ids), object)
    for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
        i = int(r['photo_id'])
        if i in row:
            photo_genus[row[i]] = r['taxon'].split()[0]
            if r['observation_uuid'] in pheno:
                bags[r['observation_uuid']].append((int(r['position']), row[i]))
                genus_of[r['observation_uuid']] = r['taxon'].split()[0]
    obs = sorted(bags)
    idx = torch.zeros((len(obs), CAP), dtype=torch.long)
    mask = torch.zeros((len(obs), CAP), dtype=torch.bool)
    for n, o in enumerate(obs):
        rows = [q for _, q in sorted(bags[o])][:CAP]
        idx[n, :len(rows)] = torch.tensor(rows)
        mask[n, :len(rows)] = True
    y = np.array([[v in pheno[o] for v in VALUES] for o in obs], np.float32)
    bucket = np.array([T.bucket(genus_of[o]) for o in obs])
    pb = np.array([T.bucket(g) if g else 0 for g in photo_genus])
    print('annotated observations', len(obs), dict(zip(VALUES, y.sum(0).astype(int).tolist())), flush=True)
    idx, mask, yt = idx.to(DEV), mask.to(DEV), torch.from_numpy(y).to(DEV)
    prob = np.zeros((len(ids), len(VALUES)), np.float16)
    # the photographs of observations with an observer's trait label
    femb, fids = T.load_embeddings(D / 'emb-field')
    fgenus = {}
    obs_taxon = {r['observation']: r['taxon'] for r in csv.DictReader(open(D / 'field-test-v3.tsv'), delimiter='\t')}
    for r in csv.DictReader(open(D / 'field-obs-photos.tsv'), delimiter='\t'):
        if r['observation'] in obs_taxon:
            fgenus[int(r['photo_id'])] = obs_taxon[r['observation']].split()[0]
    fb = np.array([T.bucket(fgenus[int(i)]) if int(i) in fgenus else 0 for i in fids])
    fx = torch.from_numpy(femb).to(DEV)
    fprob = np.zeros((len(fids), len(VALUES)), np.float16)
    held_score = np.zeros_like(y)
    for fold in range(5):
        tr = torch.from_numpy(np.flatnonzero((bucket - 2 * fold) % 10 >= 2)).to(DEV)
        te = np.flatnonzero((bucket - 2 * fold) % 10 < 2)
        torch.manual_seed(fold)
        net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 1024), torch.nn.GELU(), torch.nn.Dropout(0.2),
                                  torch.nn.Linear(1024, len(VALUES))).to(DEV)
        opt = torch.optim.AdamW(net.parameters(), lr=5e-4, weight_decay=1e-4)
        pos = yt[tr].mean(0)
        pw = ((1 - pos) / pos).clamp(max=20)
        steps = a.epochs * (len(tr) // 1024 + 1)
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=steps)

        def bag_logit(b):
            z = net(x[idx[b]]).masked_fill(~mask[b][:, :, None], -1e4)
            return z.max(1).values
        net.train()
        for _ in range(a.epochs):
            perm = tr[torch.randperm(len(tr), device=DEV)]
            for i in range(0, len(perm), 1024):
                b = perm[i:i + 1024]
                loss = torch.nn.functional.binary_cross_entropy_with_logits(bag_logit(b), yt[b], pos_weight=pw)
                opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        net.eval()
        with torch.no_grad():
            tet = torch.from_numpy(te).to(DEV)
            held_score[te] = torch.cat([torch.sigmoid(bag_logit(tet[i:i + 8192])) for i in range(0, len(tet), 8192)]).cpu().numpy()
            sel = np.flatnonzero((pb - 2 * fold) % 10 < 2)
            st = torch.from_numpy(sel).to(DEV)
            prob[sel] = torch.cat([torch.sigmoid(net(x[st[i:i + 65536]])) for i in range(0, len(st), 65536)]).cpu().numpy()
            fsel = np.flatnonzero((fb - 2 * fold) % 10 < 2)
            fprob[fsel] = torch.sigmoid(net(fx[torch.from_numpy(fsel).to(DEV)])).cpu().numpy()
        print('fold', fold, {v: round(auc(held_score[te, k], y[te, k]), 3) for k, v in enumerate(VALUES)}, flush=True)
    print('RESULT held-out observations, area under the curve:', {v: round(auc(held_score[:, k], y[:, k]), 3) for k, v in enumerate(VALUES)})
    only = lambda v, w: (y[:, VALUES.index(v)] == 1) & (y[:, VALUES.index(w)] == 0)
    fl, fr = only('flowering', 'fruiting'), only('fruiting', 'flowering')
    for k, v in enumerate(VALUES[:2]):
        print(f'RESULT {v} score above 0.5 in an observation annotated flowering only: {(held_score[fl, k] > 0.5).mean():.2f}, '
              f'fruiting only: {(held_score[fr, k] > 0.5).mean():.2f}')
    np.savez(D / 'phenology-scores.npz', ids=ids, prob=prob, field_ids=fids, field_prob=fprob, values=np.array(VALUES))


if __name__ == '__main__':
    main()
