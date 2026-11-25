"""Our image model on the PlantTraits2024 benchmark (Kaggle, FGVC11): six plant traits from a citizen-science photograph.

Targets X4 (wood density), X11 (specific leaf area), X18 (height), X26 (seed mass), X50 (leaf nitrogen per area),
X3112 (leaf area): species means from TRY attached to iNaturalist photographs, with 163 climate, soil and
satellite columns per photograph. The competition measure is R2 averaged over the six traits.

The test labels are not public, so the score here is five-fold cross-validation on the training set (the data
carry no species name, so the folds are random over photographs, as in the competition's own split). As in the
winning solutions, rows with a target outside the 0.1-98th percentile are dropped and the head is fitted on
log10 of the targets (X4 as given); R2 is reported on that scale. Arms: frozen BioCLIP 2 embedding, the
tabular columns alone, and both together; one small MLP for the six targets.

    python planttraits2024.py lists --root DIR/planttraits2024 --out DIR/sota-out
    python planttraits2024.py fit --root DIR/planttraits2024 --emb DIR/sota-out/emb-pt2024 --emb-test DIR/sota-out/emb-pt2024-test --out DIR/sota-out/pt2024

``fit`` also writes ``submission.csv`` (both-arm model fitted on all training rows) for the Kaggle leaderboard.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch

TARGETS = ('X4', 'X11', 'X18', 'X50', 'X26', 'X3112')          # the order of the sample submission
LOG = {'X11', 'X18', 'X50', 'X26', 'X3112'}
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'


def lists(a):
    for part in ('train', 'test'):
        ids = [r['id'] for r in csv.DictReader(open(a.root / f'{part}.csv'))]
        name = 'pt2024-list.tsv' if part == 'train' else 'pt2024-test-list.tsv'
        (a.out / name).write_text('key\tpath\n' + ''.join(f'{i}\t{part}_images/{i}.jpeg\n' for i in ids))
        print(part, len(ids))


def table(path, keys):
    rows = {r['id']: r for r in csv.DictReader(open(path))}
    cols = [c for c in next(iter(rows.values())) if c != 'id' and not c.startswith('X')]
    return rows, cols, np.array([[float(rows[k][c] or 'nan') for c in cols] for k in keys], np.float32)


def fit_mlp(x, y, xs, seed, epochs=40):
    """x, y: training tensors (y standardised); xs: list of tensors to predict. Returns their predictions."""
    torch.manual_seed(seed)
    net = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 2048), torch.nn.GELU(), torch.nn.Dropout(0.3),
                              torch.nn.Linear(2048, 512), torch.nn.GELU(), torch.nn.Linear(512, y.shape[1])).to(DEV)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-2)
    steps = epochs * (len(x) // 512 + 1)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=steps)
    net.train()
    for _ in range(epochs):
        perm = torch.randperm(len(x), device=DEV)
        for i in range(0, len(perm), 512):
            b = perm[i:i + 512]
            loss = torch.nn.functional.smooth_l1_loss(net(x[b]), y[b])
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    net.eval()
    with torch.no_grad():
        return [net(q).cpu().numpy() for q in xs]


def fit_species(x, y, cls, table, xs, seed, epochs=40):
    """The idea of the competition's winner on a frozen embedding: next to the regression head, a head that names the
    pseudo-species (photographs with the same six values) and answers with the probability-weighted mean of the
    species' values. Returns, per tensor in xs, (regression, species) predictions."""
    torch.manual_seed(seed)
    trunk = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 2048), torch.nn.GELU(), torch.nn.Dropout(0.3)).to(DEV)
    reg = torch.nn.Sequential(torch.nn.Linear(2048, 512), torch.nn.GELU(), torch.nn.Linear(512, y.shape[1])).to(DEV)
    clf = torch.nn.Linear(2048, len(table)).to(DEV)
    params = [*trunk.parameters(), *reg.parameters(), *clf.parameters()]
    opt = torch.optim.AdamW(params, lr=1e-3, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=epochs * (len(x) // 512 + 1))
    for m in (trunk, reg, clf):
        m.train()
    for _ in range(epochs):
        perm = torch.randperm(len(x), device=DEV)
        for i in range(0, len(perm), 512):
            b = perm[i:i + 512]
            h = trunk(x[b])
            loss = torch.nn.functional.smooth_l1_loss(reg(h), y[b]) + torch.nn.functional.cross_entropy(clf(h), cls[b], label_smoothing=0.1)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    for m in (trunk, reg, clf):
        m.eval()
    with torch.no_grad():
        return [(reg(trunk(q)).cpu().numpy(), (torch.softmax(clf(trunk(q)), 1) @ table).cpu().numpy()) for q in xs]


def r2(truth, pred):
    return [float(1 - ((truth[:, k] - pred[:, k]) ** 2).sum() / ((truth[:, k] - truth[:, k].mean()) ** 2).sum()) for k in range(truth.shape[1])]


def fit(a):
    a.out.mkdir(parents=True, exist_ok=True)
    keys = [k for k in (a.emb / 'emb-0.keys').read_text().split('\n') if k]
    emb = np.load(a.emb / 'emb-0.npy').astype(np.float32)
    rows, cols, tab = table(a.root / 'train.csv', keys)
    y = np.array([[float(rows[k][f'{t}_mean']) for t in TARGETS] for k in keys])
    lo, hi = np.percentile(y, 0.1, 0), np.percentile(y, 98, 0)
    keep = ((y >= lo) & (y <= hi)).all(1) & (y[:, [t in LOG for t in TARGETS]] > 0).all(1)
    emb, tab, y = emb[keep], tab[keep], y[keep]
    for k, t in enumerate(TARGETS):
        if t in LOG:
            y[:, k] = np.log10(y[:, k])
    mu_t, sd_t = np.nanmean(tab, 0), np.nanstd(tab, 0) + 1e-6
    tabz = np.nan_to_num((tab - mu_t) / sd_t)
    arms = {'image (BioCLIP 2)': emb, 'climate and soil columns': tabz, 'image + columns': np.concatenate([emb, tabz], 1)}
    print('photographs', len(keys), 'kept', int(keep.sum()), 'columns', len(cols), flush=True)
    fold = np.random.default_rng(0).integers(0, 5, len(y))
    report = {'n': int(keep.sum()), 'targets': TARGETS, 'arms': {}}
    for name, x in arms.items():
        pred = np.zeros_like(y)
        xt = torch.from_numpy(x).to(DEV)
        for f in range(5):
            tr, te = fold != f, fold == f
            m, s = y[tr].mean(0), y[tr].std(0)
            yt = torch.from_numpy(((y[tr] - m) / s).astype(np.float32)).to(DEV)
            p = np.mean([fit_mlp(xt[torch.from_numpy(tr).to(DEV)], yt, [xt[torch.from_numpy(te).to(DEV)]], seed)[0] for seed in range(3)], 0)
            pred[te] = p * s + m
        r = r2(y, pred)
        report['arms'][name] = {'r2': dict(zip(TARGETS, r)), 'mean_r2': float(np.mean(r))}
        print(f'RESULT {name:26s} mean R2 {np.mean(r):.3f}   ' + '  '.join(f'{t} {v:.3f}' for t, v in zip(TARGETS, r)), flush=True)
    # the winner's species head, on image + columns; R2 also on the raw scale (what Kaggle scores)
    raw = lambda v: np.stack([10 ** v[:, k] if t in LOG else v[:, k] for k, t in enumerate(TARGETS)], 1)
    xt = torch.from_numpy(arms['image + columns']).to(DEV)
    pr, ps = np.zeros_like(y), np.zeros_like(y)
    for f in range(5):
        tr, te = fold != f, fold == f
        m, s = y[tr].mean(0), y[tr].std(0)
        uniq, cls = np.unique(y[tr], axis=0, return_inverse=True)
        tab_t = torch.from_numpy(((uniq - m) / s).astype(np.float32)).to(DEV)
        yt = torch.from_numpy(((y[tr] - m) / s).astype(np.float32)).to(DEV)
        out = [fit_species(xt[torch.from_numpy(tr).to(DEV)], yt, torch.from_numpy(cls.ravel()).to(DEV), tab_t, [xt[torch.from_numpy(te).to(DEV)]], seed)[0] for seed in range(3)]
        pr[te] = np.mean([o[0] for o in out], 0) * s + m
        ps[te] = np.mean([o[1] for o in out], 0) * s + m
        print('fold', f, 'pseudo-species', len(uniq), flush=True)
    for name, pred in (('with species head: regression', pr), ('with species head: species', ps), ('with species head: both', (pr + ps) / 2)):
        r, rr = r2(y, pred), r2(raw(y), raw(pred))
        report['arms'][name] = {'r2': dict(zip(TARGETS, r)), 'mean_r2': float(np.mean(r)), 'mean_r2_raw': float(np.mean(rr))}
        print(f'RESULT {name:30s} mean R2 {np.mean(r):.3f} (raw scale {np.mean(rr):.3f})   ' + '  '.join(f'{t} {v:.3f}' for t, v in zip(TARGETS, r)), flush=True)
    (a.out / 'pt2024.json').write_text(json.dumps(report, indent=1) + '\n')
    if a.emb_test and (a.emb_test / 'emb-0.npy').exists():
        tk = [k for k in (a.emb_test / 'emb-0.keys').read_text().split('\n') if k]
        te_emb = np.load(a.emb_test / 'emb-0.npy').astype(np.float32)
        _, _, ttab = table(a.root / 'test.csv', tk)
        xte = torch.from_numpy(np.concatenate([te_emb, np.nan_to_num((ttab - mu_t) / sd_t)], 1)).to(DEV)
        m, s = y.mean(0), y.std(0)
        xt = torch.from_numpy(arms['image + columns']).to(DEV)
        yt = torch.from_numpy(((y - m) / s).astype(np.float32)).to(DEV)
        uniq, cls = np.unique(y, axis=0, return_inverse=True)
        tab_t = torch.from_numpy(((uniq - m) / s).astype(np.float32)).to(DEV)
        out = [fit_species(xt, yt, torch.from_numpy(cls.ravel()).to(DEV), tab_t, [xte], seed)[0] for seed in range(5)]
        p = np.mean([(o[0] + o[1]) / 2 for o in out], 0) * s + m
        for k, t in enumerate(TARGETS):
            if t in LOG:
                p[:, k] = 10 ** p[:, k]
        got = dict(zip(tk, p))
        med = np.median(p, 0)
        with open(a.out / 'submission.csv', 'w') as f:
            f.write('id,' + ','.join(TARGETS) + '\n')
            for r in csv.DictReader(open(a.root / 'test.csv')):
                f.write(r['id'] + ',' + ','.join(f'{v:.6g}' for v in got.get(r['id'], med)) + '\n')
        print('submission rows', len(tk), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('lists', 'fit'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--emb', type=Path)
    p.add_argument('--emb-test', type=Path)
    a = p.parse_args()
    lists(a) if a.mode == 'lists' else fit(a)


if __name__ == '__main__':
    main()
