"""PhenoVision against our phenology head, on the same iNaturalist observations and the same photographs.

Test: observations with an iNaturalist phenology annotation (``phenology-v3.tsv``: flowering, fruiting, budding, none; made
by observers and identifiers, not by us). Each observation is a bag of up to 12 photographs; its score is the maximum over the
photographs. Two scorers:

* PhenoVision (flower, fruit; ``scores.npz`` of run_phenovision.py), as published, no training on our side. Caveat: it was
  trained on 1.5 million iNaturalist photographs (its own genus-stratified split), so some of our photographs may be in its
  training data; our head is scored only on genera it did not see.
* our head: two-layer perceptron on frozen BioCLIP 2 embeddings, trained on the annotated observations of the other four fifths of
  the genera (same code path as ``phenology_head.py``: bag maximum, 5 genus folds from ``train.bucket``).

Reports the area under the ROC curve per value and, for PhenoVision, accuracy / sensitivity / specificity at its published
thresholds (flower 0.48, fruit 0.60). Also writes ``phenovision-as-pheno.npz`` in the format of ``phenology-scores.npz`` so that
``allphotos_train.py --pheno`` can use PhenoVision to choose the fruit photographs of the fruit-colour test.

    python score_phenology.py --data DIR --scores DIR/sota-out/phenovision/scores.npz --out DIR/sota-out/phenovision
(GPU job: the head is trained on the GPU; tools/orix/traitvision_sota_phenovision.sbatch)
"""
import argparse
import collections
import json
from pathlib import Path

import numpy as np
import torch

from common import auc, import_pilot, tsv

T, R = import_pilot()
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
VALUES = ('flowering', 'fruiting', 'budding')
CAP = 12


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--scores', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--manifest', default='sota-photos.tsv')
    p.add_argument('--epochs', type=int, default=20)
    a = p.parse_args()
    D = a.data
    pv = np.load(a.scores)
    lab = list(pv['phenovision_labels'])
    prow = {int(i): n for n, i in enumerate(pv['ids'])}
    pprob = pv['phenovision_prob']
    flower_k, fruit_k = lab.index('flower'), lab.index('fruit')
    pheno = {r['observation_uuid']: set(r['values'].split('|')) for r in tsv(D / 'phenology-v3.tsv')
             if r['values'] and r['values'] != 'gone'}
    emb, ids = T.load_embeddings(D / 'emb')
    erow = {}
    for n, i in enumerate(ids):
        erow.setdefault(int(i), n)
    bags, genus = collections.defaultdict(list), {}
    for r in tsv(D / a.manifest):
        i = int(r['photo_id'])
        if r['observation'] in pheno and 'pheno' in r['role'].split(',') and i in erow and i in prow:
            bags[r['observation']].append(i)
            genus[r['observation']] = r['taxon'].split()[0]
    obs = sorted(bags)
    y = np.array([[v in pheno[o] for v in VALUES] for o in obs], np.float32)
    bucket = np.array([T.bucket(genus[o]) for o in obs])
    print('annotated observations with embeddings and PhenoVision scores:', len(obs), flush=True)
    # PhenoVision: maximum over the bag
    pv_score = np.array([[max(pprob[prow[i], k] for i in bags[o][:CAP]) for k in (flower_k, fruit_k)] for o in obs])
    # our head
    x = torch.from_numpy(emb).to(DEV)
    idx = torch.zeros((len(obs), CAP), dtype=torch.long)
    mask = torch.zeros((len(obs), CAP), dtype=torch.bool)
    for n, o in enumerate(obs):
        rows = [erow[i] for i in bags[o][:CAP]]
        idx[n, :len(rows)] = torch.tensor(rows)
        mask[n, :len(rows)] = True
    idx, mask, yt = idx.to(DEV), mask.to(DEV), torch.from_numpy(y).to(DEV)
    ours = np.zeros_like(y)
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
            return net(x[idx[b]]).masked_fill(~mask[b][:, :, None], -1e4).max(1).values
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
            ours[te] = torch.cat([torch.sigmoid(bag_logit(tet[i:i + 8192])) for i in range(0, len(tet), 8192)]).cpu().numpy()
        print('fold', fold, flush=True)
    res = {'n_observations': len(obs), 'n_positive': dict(zip(VALUES, y.sum(0).astype(int).tolist()))}
    for name, k in (('flowering', 0), ('fruiting', 1)):
        col = 0 if name == 'flowering' else 1
        res[name] = {'auc_phenovision': auc(pv_score[:, col], y[:, k]), 'auc_ours_biocl2_mlp': auc(ours[:, k], y[:, k])}
        th = 0.48 if name == 'flowering' else 0.60
        pred = pv_score[:, col] >= th
        sens = float((pred & (y[:, k] > 0)).sum() / max((y[:, k] > 0).sum(), 1))
        spec = float((~pred & (y[:, k] == 0)).sum() / max((y[:, k] == 0).sum(), 1))
        res[name].update(phenovision_threshold=th, sensitivity=sens, specificity=spec, balanced_accuracy=(sens + spec) / 2)
        th_o = 0.5
        pred_o = ours[:, k] >= th_o
        so = float((pred_o & (y[:, k] > 0)).sum() / max((y[:, k] > 0).sum(), 1))
        sp = float((~pred_o & (y[:, k] == 0)).sum() / max((y[:, k] == 0).sum(), 1))
        res[name].update(ours_threshold=th_o, ours_sensitivity=so, ours_specificity=sp, ours_balanced_accuracy=(so + sp) / 2)
    only = lambda v, w: (y[:, VALUES.index(v)] == 1) & (y[:, VALUES.index(w)] == 0)
    fl, fr = only('flowering', 'fruiting'), only('fruiting', 'flowering')
    res['flower_vs_fruit_only'] = {  # does the fruit score separate fruit-only from flower-only observations?
        'n_flower_only': int(fl.sum()), 'n_fruit_only': int(fr.sum()),
        'auc_fruit_score_phenovision': auc(np.r_[pv_score[fl, 1], pv_score[fr, 1]], np.r_[np.zeros(fl.sum()), np.ones(fr.sum())]),
        'auc_fruit_score_ours': auc(np.r_[ours[fl, 1], ours[fr, 1]], np.r_[np.zeros(fl.sum()), np.ones(fr.sum())])}
    print(json.dumps(res, indent=1))
    (a.out / 'phenology-compare.json').write_text(json.dumps(res, indent=1) + '\n')
    # PhenoVision in the format of phenology-scores.npz (all scored photographs; budding column zero)
    from_manifest = {int(r['photo_id']): r['role'] for r in tsv(D / a.manifest)}
    allp = np.array([i for i in pv['ids']])
    isfield = np.array(['field' in from_manifest.get(int(i), '').split(',') for i in allp])
    prob3 = np.zeros((len(allp), 3), np.float16)
    prob3[:, 0], prob3[:, 1] = pprob[:, flower_k], pprob[:, fruit_k]
    np.savez(a.out / 'phenovision-as-pheno.npz', values=np.array(VALUES), ids=allp[~isfield], prob=prob3[~isfield],
             field_ids=allp[isfield], field_prob=prob3[isfield])


if __name__ == '__main__':
    main()
