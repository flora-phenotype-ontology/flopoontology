"""Species identification of never-seen genera from predicted traits and the flora table (first baseline).

    python -m flopo2.traitvision.identify local-corpora/trait-vision [TAG]

For each of the five runs, the candidates are all species of the held-out genera that have photographs and
at least MIN_TRAITS described pilot traits. An observation is scored against every candidate c by
sum over traits of log sum_v p(v | photos) * p(v | c) / p(v), where p(v | c) is uniform over the values the
floras allow for c (a trait the floras do not describe for c counts as neutral). Reported: how often the
true species is first / in the first 5 / first 10, among all candidates and among those of its family, next
to chance and to the same score computed from the true species' own flora values ("perfect traits").
"""
import collections
import csv
import glob
import hashlib
import sys
from pathlib import Path

import numpy as np

MIN_TRAITS, SAMPLE = 4, 3000


def main(folder, tag='v3'):
    folder = Path(folder)
    rng = np.random.default_rng(0)
    labels, family = collections.defaultdict(dict), {}
    for r in csv.DictReader(open(folder / f'pilot-labels-{tag}.tsv'), delimiter='\t'):
        labels[r['taxon']][r['trait']] = set(r['allowed'].split('|'))
        family[r['taxon']] = r['family']
    photo = {}
    for r in csv.DictReader(open(folder / f'inat-photos-{tag}.tsv'), delimiter='\t'):
        photo[int(r['photo_id'])] = (r['taxon'], r['observation_uuid'])
    tot = collections.Counter()
    for fold in range(5):
        preds = {Path(f).stem[5:]: np.load(f) for f in sorted(glob.glob(str(folder / 'folds' / f'run-fold-{fold}' / 'pred-*.npz')))}
        ids = next(iter(preds.values()))['photo_ids']
        cands = sorted({photo[int(p)][0] for p in ids} & {t for t, d in labels.items() if len(d) >= MIN_TRAITS})
        cidx = {t: n for n, t in enumerate(cands)}
        fam = np.array([family[t] for t in cands])
        obs = collections.defaultdict(list)
        for n, p in enumerate(ids):
            t, o = photo[int(p)]
            if t in cidx:
                obs[o, t].append(n)
        keys = list(obs)
        keys = [keys[i] for i in rng.choice(len(keys), min(SAMPLE, len(keys)), replace=False)]
        true = np.array([cidx[t] for _, t in keys])
        score = np.zeros((len(keys), len(cands)), np.float32)
        perfect = np.zeros((len(keys), len(cands)), np.float32)
        for trait, z in preds.items():
            classes = [str(c) for c in z['classes']]
            m = np.zeros((len(cands), len(classes)), np.float32)
            described = np.zeros(len(cands), bool)
            for t, n in cidx.items():
                s = [classes.index(c) for c in labels[t].get(trait, ()) if c in classes]
                if s:
                    m[n, s] = 1 / len(s)
                    described[n] = True
            prior = m[described].mean(0) + 1e-6
            ratio = np.where(described[:, None], m / prior, 1.0).astype(np.float32)
            prob = z['prob'].astype(np.float32)
            p = np.stack([prob[obs[k]].mean(0) for k in keys])
            score += np.log(p @ ratio.T + 1e-6)
            own = np.where(described[true][:, None], m[true], prior / prior.sum())     # the true species' flora values as "prediction"
            perfect += np.log(own @ ratio.T + 1e-6)
        for name, s in (('model', score), ('perfect traits', perfect)):
            st = s[np.arange(len(keys)), true][:, None]
            for scope, mask in (('all', np.ones_like(s, bool)), ('family', fam[None, :] == fam[true][:, None])):
                rank = 1 + ((s > st) & mask).sum(1) + 0.5 * (((s == st) & mask).sum(1) - 1)
                n = mask.sum(1)
                for k in (1, 5, 10):
                    tot[name, scope, f'top{k}'] += float((rank <= k).sum())
                    tot['chance', scope, f'top{k}'] += float(np.minimum(k / n, 1).sum())
                tot[name, scope, 'n'] += len(keys)
                tot['chance', scope, 'n'] += len(keys)
                tot['candidates', scope, 'sum'] += float(n.sum())
        tot['obs'] += len(keys)
        print('fold', fold, 'candidates', len(cands), 'observations', len(keys), flush=True)
    for scope in ('all', 'family'):
        print(f"candidates per observation ({scope}): {tot['candidates', scope, 'sum'] / 2 / tot['obs']:.0f}")
        for name in ('chance', 'model', 'perfect traits'):
            n = tot[name, scope, 'n']
            print(f"  {name:15s} first {tot[name, scope, 'top1'] / n:.3f}  in first 5 {tot[name, scope, 'top5'] / n:.3f}  in first 10 {tot[name, scope, 'top10'] / n:.3f}")


if __name__ == '__main__':
    main(*sys.argv[1:])
