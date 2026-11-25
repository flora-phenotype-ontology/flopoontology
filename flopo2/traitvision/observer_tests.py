"""Is a classifier trained on observers' labels really no better? Tests with the label on the observation.

iNaturalist observers label an observation, not a photograph; an observation here has one or two photographs
(at most two were downloaded). The first test (``regime_tests.py``, ``ceiling_obs``) gave the value to every
photograph. Here, per trait and with the same held-out genera (observations of four fifths of the genera for
training, the other fifth for the test):

  per_photo      the observer's value on every photograph (the first test)
  single         only observations with one photograph (the value then is a photograph's value)
  bag_mean       loss on the mean prediction over the photographs of the observation
  bag_max        loss on the better of the photographs (per class: the maximum over the photographs)
  with_box       per photograph, only photographs with a detected box of the organ
  flora_same     the same observations and photographs, labelled with what the floras say about the species
  flora_same_one / observer_same_one   the observations of species with one stated value: flora label / observer label
  + mlp          the same with one hidden layer
  flora_all      the classifier trained on all 1 million flora-labelled photographs (``value_arms``/``regime``)

Test: observers' values in held-out genera, all observations and those with one photograph.

    python observer_tests.py DIR      (standalone: numpy + torch)
"""
import collections
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch

import hashlib

DEV = 'cuda' if torch.cuda.is_available() else 'cpu'


def bucket(genus):
    return int(hashlib.md5(genus.encode()).hexdigest()[:8], 16) % 10

ORGAN = {'flower_colour': {'flower'}, 'habit': None, 'leaf_margin': {'leaf'}, 'leaf_arrangement': {'leaf', 'stem'},
         'leaf_complexity': {'leaf'}, 'fruit_colour': {'fruit'}, 'spines': {'thorn', 'stem'}}


def fit(x, bags, target, weight, pool, hidden, seed=0, epochs=200):
    """bags: (B, 2) photo rows (a single photograph is repeated)."""
    torch.manual_seed(seed)
    n = target.shape[1]
    net = (torch.nn.Sequential(torch.nn.Linear(x.shape[1], 512), torch.nn.GELU(), torch.nn.Dropout(0.3), torch.nn.Linear(512, n))
           if hidden else torch.nn.Linear(x.shape[1], n))
    net = net.to(DEV)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3 if hidden else 3e-3, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, opt.param_groups[0]['lr'], total_steps=epochs)
    net.train()
    for _ in range(epochs):
        logits = net(x[bags])                                  # B, 2, C
        if pool == 'max':
            logp = torch.log_softmax(logits.max(1).values, 1)
        else:
            logp = torch.log(torch.softmax(logits, 2).mean(1) + 1e-9)
        loss = -(torch.logsumexp(logp + torch.log(target + 1e-12), 1) * weight).sum() / weight.sum()
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    net.eval()
    return net


def bal(pairs):
    hit, tot = collections.Counter(), collections.Counter()
    for t, p in pairs:
        tot[t] += 1
        hit[t] += t == p
    big = [c for c in tot if tot[c] >= 5]
    return float(np.mean([hit[c] / tot[c] for c in big])) if big else float('nan')


def main(folder):
    folder = Path(folder)
    emb = torch.from_numpy(np.load(folder / 'emb-field' / 'emb-0.npy').astype(np.float32)).to(DEV)
    row = {int(i): n for n, i in enumerate((folder / 'emb-field' / 'emb-0.ids').read_text().split())}
    boxes = collections.defaultdict(set)
    for r in csv.DictReader(open(folder / ('field-boxes.tsv' if (folder / 'field-boxes.tsv').exists() else 'crops-field/boxes-0.tsv')), delimiter='\t'):
        boxes[r['organ']].add(int(r['photo_id']))
    flora = collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'pilot-labels-v3.tsv'), delimiter='\t'):
        flora[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    big = {}
    for f in sorted((folder / 'regime').glob('*.json')):
        if 'combo' not in f.name:
            for t, a in json.loads(f.read_text())['scores'].items():
                if 'observers' in a.get('base', {}):
                    big[t] = a['base']['observers']['balanced']
    obs = collections.defaultdict(list)
    for r in csv.DictReader(open(folder / 'field-test-v3.tsv'), delimiter='\t'):
        ph = [int(x) for x in r['photos'].split('|') if int(x) in row]
        if ph:
            obs[r['trait']].append((r['class'], r['taxon'], ph))
    report = {}
    for trait in ('flower_colour', 'habit', 'leaf_arrangement', 'leaf_margin', 'leaf_complexity'):
        classes = sorted({o[0] for o in obs[trait]} & {c for s in flora[trait].values() for c in s})
        cidx = {c: i for i, c in enumerate(classes)}
        O = [o for o in obs[trait] if o[0] in cidx]
        res = collections.defaultdict(list)
        for fold in range(5):
            held = lambda o: (bucket(o[1].split()[0]) - 2 * fold) % 10 < 2
            tr, te = [o for o in O if not held(o)], [o for o in O if held(o)]

            def train(name, items, label, pool='mean', hidden=False, per_photo=False):
                bags, tg = [], []
                for o in items:
                    t = np.zeros(len(classes), np.float32)
                    for c in label(o):
                        if c in cidx:
                            t[cidx[c]] = 1
                    if not t.any():
                        continue
                    rows = [row[p] for p in o[2]]
                    for b in ([[r, r] for r in rows] if per_photo else [[rows[0], rows[-1]]]):
                        bags.append(b); tg.append(t / (len(rows) if per_photo else 1) + 0)
                if len(bags) < 100:
                    return
                tg = np.array(tg)
                hard = (tg > 0).astype(np.float32)
                freq = np.maximum(hard[hard.sum(1) == 1].sum(0), 1)
                w = (hard * (freq.sum() / freq / len(classes))).max(1) * tg.max(1)       # per_photo: each observation counts once
                net = fit(emb, torch.tensor(bags, device=DEV), torch.from_numpy(hard).to(DEV), torch.from_numpy(w.astype(np.float32)).to(DEV), pool, hidden)
                with torch.no_grad():
                    p = torch.softmax(net(emb), 1).cpu()
                for o in te:
                    pred = classes[int(p[[row[x] for x in o[2]]].mean(0).argmax())]
                    res[name, 'all'].append((o[0], pred))
                    if len(o[2]) == 1:
                        res[name, 'one photo'].append((o[0], pred))
                res[name, 'n'].append(len(bags))

            own = lambda o: [o[0]]
            fl = lambda o: flora[trait].get(o[1], ())
            for hidden in (False, True):
                s = ' + mlp' if hidden else ''
                train('per_photo' + s, tr, own, per_photo=True, hidden=hidden)
                train('single' + s, [o for o in tr if len(o[2]) == 1], own, hidden=hidden)
                train('bag_mean' + s, tr, own, hidden=hidden)
                train('bag_max' + s, tr, own, pool='max', hidden=hidden)
                if ORGAN[trait]:
                    wb = [(o[0], o[1], [p for p in o[2] if any(p in boxes[g] for g in ORGAN[trait])]) for o in tr]
                    train('with_box' + s, [o for o in wb if o[2]], own, per_photo=True, hidden=hidden)
                train('flora_same' + s, tr, fl, per_photo=True, hidden=hidden)
                one = lambda o: fl(o) if len(set(fl(o)) & set(classes)) == 1 else ()
                train('flora_same_one' + s, tr, one, per_photo=True, hidden=hidden)       # species with one stated value
                train('observer_same_one' + s, [o for o in tr if one(o)], own, per_photo=True, hidden=hidden)
        print(f'\n{trait}: {len(O)} observations with a value; test = held-out genera '
              f'(all n={len(res[next(iter(res))[0], "all"])}, one photo n={len(res[next(iter(res))[0], "one photo"])})')
        out = {}
        for name in dict.fromkeys(k[0] for k in res):
            out[name] = {'all': bal(res[name, 'all']), 'one_photo': bal(res[name, 'one photo']), 'train_items': int(np.mean(res[name, 'n']))}
            print(f"  {name:20s} trained on {out[name]['train_items']:6d}   all {out[name]['all']:.3f}   one photo {out[name]['one_photo']:.3f}")
        print(f"  {'flora_all (1M photos)':20s} {'':19s} all {big.get(trait, float('nan')):.3f}")
        report[trait] = out
    (folder / 'observer-tests.json').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main(sys.argv[1])
