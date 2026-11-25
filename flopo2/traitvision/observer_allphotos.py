"""Observers' labels with ALL photographs of the observation, and the organ taken into account at both ends.

An iNaturalist label belongs to the observation; the photograph that shows the fruit may be the fourth. Here a
head is trained on observers' labels (held-out genera, 5 folds, 3 seeds) with one bag per observation, and the
photographs in the bag are

* ``first two``        the first two photographs (all we had before);
* ``all``              every photograph of the observation;
* ``organ, else all``  the photographs in which the organ of the trait was detected; all of them when none was.

The same three choices are made at test time, so the table is training choice x test choice.

    python observer_allphotos.py DIR        (standalone: numpy + torch)
"""
import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch

DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
ORGAN = {'flower_colour': {'flower'}, 'habit': None, 'leaf_margin': {'leaf'}, 'leaf_arrangement': {'leaf', 'stem'},
         'leaf_complexity': {'leaf'}, 'fruit_colour': {'fruit'}, 'spines': {'thorn', 'stem'}}
SETS = ('first two', 'all', 'organ, else all')
CAP = 12


def bucket(genus):
    return int(hashlib.md5(genus.encode()).hexdigest()[:8], 16) % 10


def pad(bags):
    idx = torch.zeros((len(bags), CAP), dtype=torch.long)
    mask = torch.zeros((len(bags), CAP))
    for n, b in enumerate(bags):
        b = b[:CAP]
        idx[n, :len(b)] = torch.tensor(b)
        mask[n, :len(b)] = 1
    return idx.to(DEV), mask.to(DEV)


def pooled(net, x, idx, mask):
    p = torch.softmax(net(x[idx]), 2) * mask[:, :, None]
    return p.sum(1) / mask.sum(1, keepdim=True)


def fit(x, idx, mask, target, weight, hidden, seed, epochs=200):
    torch.manual_seed(seed)
    n = target.shape[1]
    net = (torch.nn.Sequential(torch.nn.Linear(x.shape[1], 512), torch.nn.GELU(), torch.nn.Dropout(0.3), torch.nn.Linear(512, n))
           if hidden else torch.nn.Linear(x.shape[1], n)).to(DEV)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3 if hidden else 3e-3, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, opt.param_groups[0]['lr'], total_steps=epochs)
    net.train()
    for _ in range(epochs):
        loss = -((torch.log(pooled(net, x, idx, mask) + 1e-9) * target).sum(1) * weight).sum() / weight.sum()
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    return net.eval()


def bal(pairs):
    hit, tot = collections.Counter(), collections.Counter()
    for t, p in pairs:
        tot[t] += 1
        hit[t] += t == p
    big = [c for c in tot if tot[c] >= 5]
    return float(np.mean([hit[c] / tot[c] for c in big])) if big else float('nan')


def first(folder, *names):
    return next(folder / n for n in names if (folder / n).exists())


def main(folder):
    folder = Path(folder)
    embs, ids = [], []
    for f in sorted((folder / 'emb-field').glob('emb-*.npy')):
        embs.append(np.load(f).astype(np.float32))
        ids += [int(i) for i in f.with_suffix('.ids').read_text().split()]
    emb = torch.from_numpy(np.concatenate(embs)).to(DEV)
    row = {}
    for n, i in enumerate(ids):
        row.setdefault(i, n)
    boxes = collections.defaultdict(set)
    for f in (first(folder, 'field-boxes.tsv', 'crops-field/boxes-0.tsv'), first(folder, 'field-boxes-rest.tsv', 'crops-field/boxes-rest.tsv')):
        for r in csv.DictReader(open(f), delimiter='\t'):
            boxes[r['organ']].add(int(r['photo_id']))
    photos = collections.defaultdict(list)
    for r in csv.DictReader(open(folder / 'field-obs-photos.tsv'), delimiter='\t'):
        if int(r['photo_id']) in row:
            photos[r['observation']].append((int(r['position']), int(r['photo_id'])))
    obs = collections.defaultdict(list)
    for r in csv.DictReader(open(folder / 'field-test-v3.tsv'), delimiter='\t'):
        ph = [p for _, p in sorted(photos.get(r['observation'], []))]
        if ph:
            obs[r['trait']].append((r['class'], r['taxon'], ph))
    report = {}
    for trait in ORGAN:
        count = collections.Counter(o[0] for o in obs[trait])
        classes = sorted(c for c, n in count.items() if n >= 10)
        cidx = {c: i for i, c in enumerate(classes)}
        O = [o for o in obs[trait] if o[0] in cidx]
        organ = lambda p: ORGAN[trait] is not None and any(p in boxes[g] for g in ORGAN[trait])

        def choose(o, how):
            if how == 'first two':
                return o[2][:2]
            if how == 'organ, else all':
                return [p for p in o[2] if organ(p)] or o[2]
            return o[2]
        late = lambda o: len(o[2]) >= 3 and (ORGAN[trait] is None or (any(organ(p) for p in o[2]) and not all(organ(p) for p in o[2])))
        res = collections.defaultdict(list)
        for fold in range(5):
            held = lambda o: (bucket(o[1].split()[0]) - 2 * fold) % 10 < 2
            tr, te = [o for o in O if not held(o)], [o for o in O if held(o)]
            if len(tr) < 100:
                continue
            tg = np.zeros((len(tr), len(classes)), np.float32)
            tg[np.arange(len(tr)), [cidx[o[0]] for o in tr]] = 1
            freq = np.maximum(tg.sum(0), 1)
            w = torch.from_numpy((tg * (freq.sum() / freq / len(classes))).max(1)).to(DEV)
            tests = {how: pad([[row[p] for p in choose(o, how)] for o in te]) for how in SETS}
            for hidden in (False, True):
                for how in SETS:
                    idx, mask = pad([[row[p] for p in choose(o, how)] for o in tr])
                    for seed in range(3):
                        net = fit(emb, idx, mask, torch.from_numpy(tg).to(DEV), w, hidden, seed)
                        with torch.no_grad():
                            for th, (ti, tm) in tests.items():
                                pred = pooled(net, emb, ti, tm).argmax(1).cpu().numpy()
                                for o, p in zip(te, pred):
                                    key = ('mlp' if hidden else 'linear', how, th, seed)
                                    res[key + ('all',)].append((o[0], classes[p]))
                                    if late(o):
                                        res[key + ('late',)].append((o[0], classes[p]))
        n_all = len(res['linear', 'all', 'all', 0, 'all'])
        n_late = len(res['linear', 'all', 'all', 0, 'late'])
        print(f'\n{trait}: {len(O)} observations, classes {len(classes)}; tested {n_all}; 3+ photographs with the organ in some only {n_late}')
        out = {}
        for head in ('linear', 'mlp'):
            for group in ('all', 'late'):
                print(f'  {head}, {"all tested observations" if group == "all" else "organ in some photographs only"}'
                      f'      test on: ' + ' | '.join(SETS))
                for how in SETS:
                    cells = [float(np.mean([bal(res[head, how, th, s, group]) for s in range(3)])) for th in SETS]
                    out[f'{head}|{group}|{how}'] = dict(zip(SETS, cells))
                    print(f'    trained on {how:16s} ' + '   '.join(f'{c:.3f}' for c in cells))
        report[trait] = {'n': n_all, 'n_late': n_late, 'scores': out}
    (folder / 'observer-allphotos.json').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main(sys.argv[1])
