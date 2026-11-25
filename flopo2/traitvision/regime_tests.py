"""Small tests of the training regime with weak flora labels (frozen embeddings; standalone, runs on ORIX).

Every arm changes one thing against ``base`` (the regime used so far: one linear head per trait, every photo
of a species takes the set of values the floras allow for it, loss = -log of the probability mass on that
set, equal weight per species and per class). Same five rotations of held-out genera for every arm.

Where the ceiling is
  ceiling_obs   trained on the values observers entered for single observations (training genera only)
  lc10, lc30    base with 10% / 30% of the training species
  agreed_only   only species on which two or more floras agree
Which photos carry the label
  organ_photos  only photos with a detected box of the trait's organ;  same_n: as many photos, at random
  self_select   second round on the half of each species' photos that agree best with the label
  self_weight   second round, photos weighted by that agreement
  bag           loss on the mean prediction over 8 photos of one species, not on single photos
Which labels to trust
  single_only   only species with one stated value
  vote          target = share of floras stating each value (cross-entropy), not the union set
  gce           robust loss on the set mass (generalised cross-entropy, q = 0.7)
  boot          second round, target mixed with the model's own prediction for the species
Which model
  mlp           one hidden layer;  multitask: one hidden layer shared by all traits
  genus_w       equal weight per genus;  no_cw: no class weights
At test time (no new training)
  pool_log, pool_top3   species prediction = mean log probability / mean of the 3 most confident photos

Scores: balanced accuracy on species where 2+ floras agree and on observers' labels, both in held-out genera.

    python regime_tests.py --data DIR --out DIR/regime [--traits a,b]
"""
import argparse
import collections
import csv
import json
import time
from pathlib import Path

import numpy as np
import torch

import train as T

ORGAN_BOX = {'flower_colour': {'flower'}, 'inflorescence': {'flower'}, 'fruit_colour': {'fruit'}, 'leaf_complexity': {'leaf'},
             'leaf_margin': {'leaf'}, 'leaf_arrangement': {'leaf', 'stem'}, 'spines': {'thorn', 'stem'}, 'habit': set()}
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
TAG = ''


def make_head(dim, n, kind):
    if kind == 'mlp':
        return torch.nn.Sequential(torch.nn.Linear(dim, 1024), torch.nn.GELU(), torch.nn.Dropout(0.2), torch.nn.Linear(1024, n)).to(DEV)
    return torch.nn.Linear(dim, n).to(DEV)


def loss_of(logp, target, weight, kind):
    if kind == 'ce':                                          # target is a distribution
        per = -(target * logp).sum(1)
    else:
        mass = torch.logsumexp(logp + torch.log(target + 1e-12), 1)
        per = (1 - torch.exp(0.7 * mass)) / 0.7 if kind == 'gce' else -mass
    return (per * weight).sum() / weight.sum()


def fit(x, target, weight, kind='linear', loss='set', epochs=30, seed=0, bags=None):
    """x, target, weight: tensors on the device. bags: list of index tensors per species (bag loss)."""
    torch.manual_seed(seed)
    head = make_head(x.shape[1], target.shape[1], kind)
    opt = torch.optim.AdamW(head.parameters(), lr=2e-3 if kind == 'linear' else 5e-4, weight_decay=1e-4)
    n = len(x)
    if bags is not None:
        sp_target, sp_weight, member = bags                 # per species: target, weight, padded index matrix (S, M)
        steps = epochs * (len(member) * member.shape[1] // 8 // 512 + 1)
    else:
        steps = epochs * (n // 4096 + 1)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, opt.param_groups[0]['lr'], total_steps=steps)
    head.train()
    for _ in range(epochs):
        if bags is not None:
            m = member.shape[1]
            for _rep in range(max(m // 8, 1)):
                pick = member.gather(1, torch.randint(0, m, (len(member), 8), device=DEV))      # 8 photos per species
                order = torch.randperm(len(member), device=DEV)
                for i in range(0, len(order), 512):
                    b = order[i:i + 512]
                    p = torch.softmax(head(x[pick[b]]), 2).mean(1)
                    l = loss_of(torch.log(p + 1e-12), sp_target[b], sp_weight[b], loss)
                    opt.zero_grad(); l.backward(); opt.step()
                    if sched.last_epoch < steps - 1:
                        sched.step()
        else:
            perm = torch.randperm(n, device=DEV)
            for i in range(0, n, 4096):
                b = perm[i:i + 4096]
                l = loss_of(torch.log_softmax(head(x[b]), 1), target[b], weight[b], loss)
                opt.zero_grad(); l.backward(); opt.step(); sched.step()
    head.eval()
    return head


def prob(head, x):
    with torch.no_grad():
        return torch.cat([torch.softmax(head(x[i:i + 65536]), 1) for i in range(0, len(x), 65536)])


def group_mean(p, groups, how='mean'):
    """p: tensor (N, C); groups: numpy array of names. -> {name: numpy (C,)}"""
    names, inv = np.unique(groups, return_inverse=True)
    inv_t = torch.from_numpy(inv).to(p.device)
    if how == 'top3':
        out = {}
        conf = p.max(1).values.cpu().numpy()
        pc = p.cpu().numpy()
        order = np.lexsort((-conf, inv))
        start = np.r_[0, np.flatnonzero(np.diff(inv[order])) + 1, len(order)]
        for k, name in enumerate(names):
            out[name] = pc[order[start[k]:start[k] + 3]].mean(0)
        return out
    v = torch.log(p + 1e-6) if how == 'log' else p
    s = torch.zeros(len(names), p.shape[1], device=p.device).index_add_(0, inv_t, v)
    return dict(zip(names, s.cpu().numpy()))


def bal(pairs):
    hit, tot = collections.Counter(), collections.Counter()
    for t, q in pairs:
        tot[t] += 1
        hit[t] += t == q
    big = [c for c in tot if tot[c] >= 5]
    return float(np.mean([hit[c] / tot[c] for c in big])) if big else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--traits', default='')
    p.add_argument('--arms', default='')
    p.add_argument('--folds', default='0,1,2,3,4')
    p.add_argument('--seed', type=int, default=0)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    global TAG
    TAG = f'combo-s{a.seed}' if a.arms else ''
    D = a.data
    emb, ids = T.load_embeddings(D / 'emb')
    keys, _ = T.text_embeddings(D / 'emb')
    row_of = {int(i): n for n, i in enumerate(ids)}
    photo_taxon = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(D / 'inat-photos-v3.tsv'), delimiter='\t')
                   if int(r['photo_id']) in row_of}
    femb, fids = T.load_embeddings(D / 'emb-field')
    frow = {int(i): n for n, i in enumerate(fids)}
    femb_t = torch.from_numpy(femb).to(DEV)
    labels = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'pilot-labels-v3.tsv'), delimiter='\t'):
        labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    votes = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in csv.DictReader(open(D / 'flora-statements-v3.tsv'), delimiter='\t'):
        for v in r['values'].split('|'):
            votes[r['trait']][r['taxon']][v] += 1
    agreed = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'agreed-v3.tsv'), delimiter='\t'):
        if int(r['floras']) >= 2:
            agreed[r['trait']][r['taxon']] = r['value']
    field = collections.defaultdict(list)
    for r in csv.DictReader(open(D / 'field-test-v3.tsv'), delimiter='\t'):
        rows = [frow[int(x)] for x in r['photos'].split('|') if int(x) in frow]
        if rows:
            field[r['trait']].append((r['class'], r['taxon'].split()[0], rows))
    organ_photos = collections.defaultdict(set)
    for f in sorted((D / 'crops-v3').glob('boxes-*.tsv')):
        for r in csv.DictReader(open(f), delimiter='\t'):
            organ_photos[r['organ']].add(int(r['photo_id']))
    want = [t for t in sorted(labels) if not a.traits or t in a.traits.split(',')]
    only = set(a.arms.split(',')) if a.arms else None
    folds = [int(f) for f in a.folds.split(',')]
    pairs = collections.defaultdict(list)                     # (trait, arm, test) -> [(true, predicted)]
    info = collections.defaultdict(dict)
    keep_for_multitask = {}

    for trait in want:
        lab = labels[trait]
        classes = sorted(c for c in {c for s in lab.values() for c in s} if f'zs:{trait}:{c}' in keys)
        cidx = {c: i for i, c in enumerate(classes)}
        lab = {t: s & set(classes) for t, s in lab.items() if s & set(classes)}
        pid = np.array([i for i, t in photo_taxon.items() if t in lab])
        rows = np.array([row_of[i] for i in pid])
        taxa = np.array([photo_taxon[i] for i in pid])
        genus = np.array([t.split()[0] for t in taxa])
        gb = np.array([T.bucket(g) for g in genus])
        x = torch.from_numpy(emb[rows]).to(DEV)
        C = len(classes)
        tcache = {}
        for t in set(taxa):
            s = np.zeros(C, np.float32)
            s[[cidx[c] for c in lab[t]]] = 1
            v = np.array([votes[trait][t].get(c, 0) for c in classes], np.float32)
            tcache[t] = (s, v / v.sum() if v.sum() else s / s.sum())
        target = np.stack([tcache[t][0] for t in taxa])
        vote = np.stack([tcache[t][1] for t in taxa])
        has_box = np.array([any(int(i) in organ_photos[o] for o in ORGAN_BOX[trait]) for i in pid]) if ORGAN_BOX[trait] else None
        obs = [(v, g, r) for v, g, r in field[trait] if v in cidx]
        keep_for_multitask[trait] = (classes, pid, target)
        info[trait] = {'classes': classes, 'species': len(set(taxa)), 'photos': len(pid), 'observations': len(obs),
                       'agreed_species_with_photos': len(set(taxa) & set(agreed[trait]))}
        print(trait, info[trait], flush=True)

        for fold in folds:
            bk = (gb - 2 * fold) % 10
            tr_all, held = bk >= 2, bk < 2
            x_held, taxa_held = x[torch.from_numpy(held).to(DEV)], taxa[held]
            test_species = sorted(set(taxa_held) & set(agreed[trait]))
            fobs = [o for o in obs if (T.bucket(o[1]) - 2 * fold) % 10 < 2]

            def weights(use, tgt, class_w=True, by_genus=False):
                per = collections.Counter((genus if by_genus else taxa)[use])
                names = (genus if by_genus else taxa)[use]
                w = np.array([1 / per[n] for n in names], np.float32)
                h = tgt[use]
                if class_w:
                    freq = np.maximum(h[h.sum(1) == 1].sum(0), 1)
                    w = w * (h * (freq.sum() / freq / C)).max(1)
                return w

            def score(head, arm, hows=(('mean', ''),)):
                ph = prob(head, x_held)
                for how, suffix in hows:
                    g = group_mean(ph, taxa_held, how)
                    pairs[trait, arm + suffix, 'agreed'] += [(agreed[trait][t], classes[int(np.argmax(g[t]))]) for t in test_species
                                                             if agreed[trait][t] in cidx]
                if fobs:
                    pf = prob(head, femb_t)
                    for v, _, r in fobs:
                        pairs[trait, arm, 'observers'].append((v, classes[int(pf[r].mean(0).argmax())]))

            def run(arm, use=None, tgt=None, loss='set', kind='linear', class_w=True, by_genus=False, extra_w=None, bag=False, hows=(('mean', ''),)):
                if only and arm not in only and arm != 'base':
                    return None
                use = tr_all if use is None else use
                tgt = target if tgt is None else tgt
                if use.sum() < 200:
                    return None
                w = weights(use, target if loss == 'ce' else tgt, class_w, by_genus)
                if extra_w is not None:
                    w = w * extra_w[use]
                ut = torch.from_numpy(use).to(DEV)
                t0 = time.time()
                if bag:
                    names, inv = np.unique(taxa[use], return_inverse=True)
                    idx = np.flatnonzero(use)
                    m = int(min(np.bincount(inv).max(), 64))
                    member = np.zeros((len(names), m), np.int64)
                    order = np.argsort(inv, kind='stable')
                    start = np.r_[0, np.flatnonzero(np.diff(inv[order])) + 1, len(order)]
                    for k in range(len(names)):
                        own = idx[order[start[k]:start[k + 1]]]
                        member[k] = np.resize(own, m)
                    first = idx[order[start[:-1]]]
                    spt = torch.from_numpy(tgt[first]).to(DEV)
                    hard = target[first]
                    freq = np.maximum(hard[hard.sum(1) == 1].sum(0), 1)
                    spw = torch.from_numpy((hard * (freq.sum() / freq / C)).max(1).astype(np.float32)).to(DEV)
                    head = fit(x, spt, None, kind, loss, seed=a.seed, bags=(spt, spw, torch.from_numpy(member).to(DEV)))
                else:
                    head = fit(x[ut], torch.from_numpy(tgt[use]).to(DEV), torch.from_numpy(w.astype(np.float32)).to(DEV), kind, loss, seed=a.seed)
                score(head, arm, hows)
                print(trait, 'fold', fold, arm, 'photos', int(use.sum()), f'{time.time() - t0:.0f}s', flush=True)
                return head

            base = run('base', hows=(('mean', ''), ('log', '+pool_log'), ('top3', '+pool_top3')))
            rng = np.random.default_rng(fold)
            species = np.array(sorted(set(taxa[tr_all])))
            for frac, name in ((0.1, 'lc10'), (0.3, 'lc30')):
                keep = set(rng.choice(species, int(len(species) * frac), replace=False))
                run(name, tr_all & np.array([t in keep for t in taxa]))
            run('agreed_only', tr_all & np.array([t in agreed[trait] for t in taxa]))
            run('single_only', tr_all & (target.sum(1) == 1))
            run('vote', tgt=vote, loss='ce')
            run('gce', loss='gce')
            run('mlp', kind='mlp')
            run('genus_w', by_genus=True)
            run('no_cw', class_w=False)
            run('bag', bag=True)
            run('mlp+bag', kind='mlp', bag=True)                      # the changes that helped alone, together
            run('mlp+vote', kind='mlp', tgt=vote, loss='ce')
            run('mlp+bag+vote', kind='mlp', bag=True, tgt=vote, loss='ce')
            if only and not only & {'organ_photos', 'same_n', 'self_select', 'self_weight', 'boot', 'ceiling_obs'}:
                continue
            if has_box is not None:
                sel = tr_all & has_box
                run('organ_photos', sel)
                run('same_n', tr_all & (rng.random(len(taxa)) < sel.sum() / max(tr_all.sum(), 1)))
            # second rounds, from the base model's view of the training photos
            pt = prob(base, x)
            mass = (pt * torch.from_numpy(target).to(DEV)).sum(1).cpu().numpy()
            names, inv = np.unique(taxa, return_inverse=True)
            med = np.array([np.median(mass[inv == k]) for k in range(len(names))]) if len(names) < 3000 else None
            if med is None:                                    # median per species without a Python loop over photos
                order = np.lexsort((mass, inv))
                start = np.r_[0, np.flatnonzero(np.diff(inv[order])) + 1, len(order)]
                med = np.array([mass[order[(start[k] + start[k + 1] - 1) // 2]] for k in range(len(names))])
            run('self_select', tr_all & (mass >= med[inv]))
            run('self_weight', extra_w=(mass + 0.05).astype(np.float32))
            sp = group_mean(pt, taxa)
            cnt = np.bincount(inv)
            mix = np.stack([0.7 * tcache[t][0] / tcache[t][0].sum() + 0.3 * sp[t] / cnt[k] for k, t in enumerate(names)]).astype(np.float32)
            run('boot', tgt=mix[inv], loss='ce')
            # ceiling: observers' photo-level labels of the training genera
            tro = [o for o in obs if (T.bucket(o[1]) - 2 * fold) % 10 >= 2]
            if len(tro) >= 300 and fobs and (not only or 'ceiling_obs' in only):
                xr = torch.cat([femb_t[r] for _, _, r in tro])
                yt = np.zeros((len(xr), C), np.float32)
                k = 0
                wt = np.zeros(len(xr), np.float32)
                freq = collections.Counter(v for v, _, _ in tro)
                for v, _, r in tro:
                    yt[k:k + len(r), cidx[v]] = 1
                    wt[k:k + len(r)] = 1 / len(r) / freq[v]
                    k += len(r)
                head = fit(xr, torch.from_numpy(yt).to(DEV), torch.from_numpy(wt).to(DEV), epochs=60)
                score(head, 'ceiling_obs')
        del x
        report(pairs, info, a.out)

    # one hidden layer shared by all traits
    if len(want) > 1 and (not only or 'multitask' in only) and not (only and 'multitask' not in only):
        allp = np.array(sorted({int(i) for _, pid, _ in keep_for_multitask.values() for i in pid}))
        pos = {int(i): n for n, i in enumerate(allp)}
        x = torch.from_numpy(emb[[row_of[int(i)] for i in allp]]).to(DEV)
        taxa = np.array([photo_taxon[int(i)] for i in allp])
        gb = np.array([T.bucket(t.split()[0]) for t in taxa])
        tg, mk = {}, {}
        for trait, (classes, pid, target) in keep_for_multitask.items():
            t = np.zeros((len(allp), len(classes)), np.float32)
            m = np.zeros(len(allp), bool)
            r = np.array([pos[int(i)] for i in pid])
            t[r], m[r] = target, True
            tg[trait], mk[trait] = t, m
        for fold in folds:
            bk = (gb - 2 * fold) % 10
            tr, held = bk >= 2, bk < 2
            torch.manual_seed(0)
            trunk = torch.nn.Sequential(torch.nn.Linear(x.shape[1], 1024), torch.nn.GELU(), torch.nn.Dropout(0.2)).to(DEV)
            heads = torch.nn.ModuleDict({t: torch.nn.Linear(1024, tg[t].shape[1]) for t in tg}).to(DEV)
            opt = torch.optim.AdamW(list(trunk.parameters()) + list(heads.parameters()), lr=5e-4, weight_decay=1e-4)
            idx = torch.from_numpy(np.flatnonzero(tr)).to(DEV)
            per = collections.Counter(taxa[tr])
            w, T_, M_ = {}, {}, {}
            for t in tg:
                h = tg[t]
                freq = np.maximum(h[tr & mk[t] & (h.sum(1) == 1)].sum(0), 1)
                ww = np.array([1 / per.get(n, 1) for n in taxa], np.float32) * (h * (freq.sum() / freq / h.shape[1])).max(1)
                w[t], T_[t], M_[t] = torch.from_numpy(ww).to(DEV), torch.from_numpy(h).to(DEV), torch.from_numpy(mk[t]).to(DEV)
            epochs = 30
            sched = torch.optim.lr_scheduler.OneCycleLR(opt, 5e-4, total_steps=epochs * (len(idx) // 4096 + 1))
            for _ in range(epochs):
                perm = idx[torch.randperm(len(idx), device=DEV)]
                for i in range(0, len(perm), 4096):
                    b = perm[i:i + 4096]
                    z = trunk(x[b])
                    l = 0
                    for t in tg:
                        m = M_[t][b]
                        if m.any():
                            l = l + loss_of(torch.log_softmax(heads[t](z[m]), 1), T_[t][b][m], w[t][b][m], 'set')
                    opt.zero_grad(); l.backward(); opt.step(); sched.step()
            trunk.eval()
            with torch.no_grad():
                for trait, (classes, pid, _) in keep_for_multitask.items():
                    hm = held & mk[trait]
                    ph = torch.cat([torch.softmax(heads[trait](trunk(x[torch.from_numpy(np.flatnonzero(hm)[i:i + 65536]).to(DEV)])), 1)
                                    for i in range(0, int(hm.sum()), 65536)])
                    g = group_mean(ph, taxa[hm])
                    cset = set(classes)
                    pairs[trait, 'multitask', 'agreed'] += [(agreed[trait][t], classes[int(np.argmax(g[t]))]) for t in g
                                                            if t in agreed[trait] and agreed[trait][t] in cset]
                    pf = torch.softmax(heads[trait](trunk(femb_t)), 1)
                    for v, gname, r in field[trait]:
                        if v in cset and (T.bucket(gname) - 2 * fold) % 10 < 2:
                            pairs[trait, 'multitask', 'observers'].append((v, classes[int(pf[r].mean(0).argmax())]))
            print('multitask fold', fold, flush=True)
        report(pairs, info, a.out)


def report(pairs, info, out):
    res = collections.defaultdict(dict)
    for (trait, arm, test), v in pairs.items():
        res[trait].setdefault(arm, {})[test] = {'balanced': bal(v), 'n': len(v)}
    tag = '-'.join(sorted(res))[:60] + (f'-{TAG}' if TAG else '')
    (out / f'regime-{tag}.json').write_text(json.dumps({'info': info, 'scores': res}, indent=1) + '\n')
    for trait, arms in res.items():
        b = arms.get('base', {})
        print(f'== {trait}')
        for arm, s in arms.items():
            cell = lambda k: (f"{s[k]['balanced']:.3f} ({s[k]['balanced'] - b[k]['balanced']:+.3f})" if k in s and s[k]['balanced'] is not None
                              and k in b and b[k]['balanced'] is not None else '  -  ')
            print(f"   {arm:16s} agreed species {cell('agreed'):16s} observers {cell('observers')}", flush=True)


if __name__ == '__main__':
    main()
