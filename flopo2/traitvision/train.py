"""Pilot trait heads on frozen BioCLIP 2 embeddings, trained from taxon-level flora labels.

One small head per trait. A photo is trained towards the *set* of classes the floras allow for
its taxon (so "white or pink" asks for white-or-pink, not for both), unknown traits give no
loss, and each photo is weighted by how visible the trait's organ is in it.

Evaluation uses no labels of ours:
* held-out genera (a fixed fifth of all genera, chosen by a hash of the name; ``unseen_genera`` below means these):
  does the taxon-level prediction for a genus never seen in training fall in
  the set the floras allow? Compared with zero-shot text prompts, with a head trained on
  shuffled labels, and with guessing from the plant family alone;
* iNaturalist observation fields: per-observation labels entered by iNaturalist users.

    python train.py --data DIR --out DIR/run1      (standalone: numpy + torch)
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

ORGAN = {'habit': ['plant'], 'flower_colour': ['flower'], 'fruit_colour': ['fruit'], 'leaf_complexity': ['leaf'],
         'leaf_arrangement': ['leaf', 'plant'], 'leaf_margin': ['leaf'], 'inflorescence': ['flower'],
         'spines': ['stem', 'plant', 'leaf']}
ORGANS = ['flower', 'fruit', 'leaf', 'plant', 'stem', 'other']


def bucket(text):
    return int(hashlib.md5(text.encode()).hexdigest()[:8], 16) % 10


def load_embeddings(folder):
    embs, ids = [], []
    for f in sorted(Path(folder).glob('emb-*.npy')):
        embs.append(np.load(f))
        ids.extend(int(x) for x in f.with_suffix('.ids').read_text().split())
    return np.concatenate(embs).astype(np.float32), np.array(ids)


def text_embeddings(folder):
    keys = [l.split('\t')[0] for l in (Path(folder) / 'text.tsv').read_text().splitlines()]
    return keys, np.load(Path(folder) / 'text.npy').astype(np.float32)


def organ_visibility(emb, keys, text, stats=None):
    """Score per photo of each organ group, from the text prompts (mean prompt per group).

    Each prompt has its own offset (some prompts are closer to every photo than others), so the
    similarity is standardized per organ over the training photos before it is squashed to 0..1.
    A photo then scores high for an organ when it is closer to that organ's prompts than most photos.
    """
    protos = np.stack([text[[i for i, k in enumerate(keys) if k == 'organ:' + o]].mean(0) for o in ORGANS])
    protos /= np.linalg.norm(protos, axis=1, keepdims=True)
    sim = emb @ protos.T
    stats = stats or (sim.mean(0), sim.std(0))
    return 1 / (1 + np.exp(-2 * (sim - stats[0]) / stats[1])), stats


def confusion(pred, allowed_sets, classes):
    """Rows: the single true class; columns: the predicted class."""
    m = np.zeros((len(classes), len(classes)), int)
    for p, a in zip(pred, allowed_sets):
        if len(a) == 1:
            m[next(iter(a)), p] += 1
    return m.tolist()


def balanced_accuracy(pred, allowed_sets, classes):
    """Mean over classes of: among taxa/observations whose single allowed class is c, share predicted c."""
    hit, tot = collections.Counter(), collections.Counter()
    for p, a in zip(pred, allowed_sets):
        if len(a) == 1:
            c = next(iter(a))
            tot[c] += 1
            hit[c] += p == c
    per = {classes[c]: (hit[c] / tot[c], tot[c]) for c in tot if tot[c] >= 5}
    return (float(np.mean([v[0] for v in per.values()])) if per else None), per


def in_set_accuracy(pred, allowed_sets):
    return float(np.mean([p in a for p, a in zip(pred, allowed_sets)])) if len(pred) else None


def aggregate(prob, weight, groups, pool='mean'):
    """Visibility-weighted mean probability per group (taxon or observation), or the per-class maximum."""
    out = {}
    order = np.argsort(groups, kind='stable')
    g, start = groups[order], 0
    for end in list(np.flatnonzero(g[1:] != g[:-1]) + 1) + [len(g)]:
        idx = order[start:end]
        w = weight[idx] + 1e-6
        out[g[start]] = prob[idx].max(0) if pool == 'max' else (prob[idx] * w[:, None]).sum(0) / w.sum()
        start = end
    return out


def fit(x, target, weight, n_classes, device, epochs=30, seed=0):
    """Linear head; loss = -log of the probability mass on the allowed classes."""
    torch.manual_seed(seed)
    head = torch.nn.Linear(x.shape[1], n_classes).to(device)
    opt = torch.optim.AdamW(head.parameters(), lr=2e-3, weight_decay=1e-4)
    x, target, weight = (torch.from_numpy(v).to(device) for v in (x, target, weight))
    n = len(x)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 2e-3, total_steps=epochs * (n // 4096 + 1))
    for _ in range(epochs):
        perm = torch.randperm(n, device=device)
        for i in range(0, n, 4096):
            b = perm[i:i + 4096]
            logp = torch.log_softmax(head(x[b]) * 1.0, 1)
            loss = -(torch.logsumexp(logp + torch.log(target[b] + 1e-12), 1) * weight[b]).sum() / weight[b].sum()
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
    return head


def predict(head, x, device):
    with torch.no_grad():
        return torch.softmax(head(torch.from_numpy(x).to(device)), 1).cpu().numpy()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--seeds', type=int, default=3)
    p.add_argument('--labels', default='pilot-labels.tsv')
    p.add_argument('--photos', default='inat-photos.tsv')
    p.add_argument('--field', default='field-test.tsv')
    p.add_argument('--emb', default='emb', help='embedding folder; its test photos are in <emb>-field')
    p.add_argument('--prompts', default='prompts.tsv')
    p.add_argument('--assumed', default='all', choices=['all', 'family', 'genus', 'none'],
                   help='which assumed labels to train on: all, or only those with a positive in the same family / genus')
    p.add_argument('--assumed-mass', type=float, default=0,
                   help='total weight of the assumed labels of a class, as a multiple of its stated labels (0: one weight per species)')
    p.add_argument('--fold', type=int, default=0, help='which fifth of the genera is held out (0-4)')
    p.add_argument('--dump', action='store_true',
                   help='write the predictions for every photo of the held-out genera and of the test observations')
    p.add_argument('--traits', default='', help='comma-separated traits to run (default: all)')
    p.add_argument('--pool', default='mean', choices=['mean', 'max'], help='how photos of one observation or species are combined')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    bk = lambda genus: (bucket(genus) - 2 * a.fold) % 10      # 0 test, 1 validation, rest training
    emb, ids = load_embeddings(a.data / a.emb)
    has_text = (a.data / a.emb / 'text.npy').exists()      # image-only models: no prompts, no visibility
    if has_text:
        keys, text = text_embeddings(a.data / a.emb)
    else:
        keys, text = [r['key'] for r in csv.DictReader(open(a.data / a.prompts), delimiter='\t')], None
    row_of = {int(i): n for n, i in enumerate(ids)}
    vis, vis_stats = organ_visibility(emb, keys, text) if has_text else (np.ones((len(emb), len(ORGANS)), np.float32), None)
    photo_taxon = {}
    for r in csv.DictReader(open(a.data / a.photos), delimiter='\t'):
        if int(r['photo_id']) in row_of:
            photo_taxon[int(r['photo_id'])] = r['taxon']
    labels = collections.defaultdict(dict)
    family = {}
    label_weight, assumed = {}, set()        # assumed labels (local closed world): training only, own weight
    for r in csv.DictReader(open(a.data / a.labels), delimiter='\t'):
        if a.traits and r['trait'] not in a.traits.split(','):
            continue
        if r.get('assumed') == '1' and (a.assumed == 'none' or (a.assumed == 'genus' and r['near'] != 'genus')
                                        or (a.assumed == 'family' and r['near'] == 'far')):
            continue
        labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
        label_weight[r['trait'], r['taxon']] = float(r.get('weight') or 1)
        if r.get('assumed') == '1':
            assumed.add((r['trait'], r['taxon']))
        family[r['taxon']] = r['family']
    genus_family = {t.split()[0]: f for t, f in family.items() if f}
    field = collections.defaultdict(list)      # trait -> [(observation, class, [rows], genus)]
    fpath = a.data / a.field
    femb = fids = None
    if fpath.exists() and (a.data / (a.emb + '-field')).exists():
        femb, fids = load_embeddings(a.data / (a.emb + '-field'))
        frow = {int(i): n for n, i in enumerate(fids)}
        fvis = organ_visibility(femb, keys, text, vis_stats)[0] if has_text else np.ones((len(femb), len(ORGANS)), np.float32)
        for r in csv.DictReader(open(fpath), delimiter='\t'):
            rows = [frow[int(x)] for x in r['photos'].split('|') if int(x) in frow]
            if rows:
                field[r['trait']].append((r['observation'], r['class'], rows, r['taxon'].split()[0]))
    held_ids = np.array(sorted(i for i, t in photo_taxon.items() if bk(t.split()[0]) < 2))
    held_rows = np.array([row_of[i] for i in held_ids])
    results = {'fold': a.fold, 'photos': len(ids), 'taxa_with_photos': len(set(photo_taxon.values())), 'device': device, 'traits': {}}

    for trait, lab in sorted(labels.items()):
        classes = sorted(c for c in {c for s in lab.values() for c in s} if f'zs:{trait}:{c}' in keys)
        lab = {t: s & set(classes) for t, s in lab.items() if s & set(classes)}   # rare classes are left out
        cidx = {c: i for i, c in enumerate(classes)}
        pid = [i for i, t in photo_taxon.items() if t in lab]
        if not pid:
            continue
        rows = np.array([row_of[i] for i in pid])
        taxa = np.array([photo_taxon[i] for i in pid])
        split = np.array([bk(t.split()[0]) for t in taxa])       # by genus: 0 test, 1 validation, rest training
        x = emb[rows]
        w = vis[rows][:, [ORGANS.index(o) for o in ORGAN[trait]]].max(1).astype(np.float32)
        target = np.zeros((len(pid), len(classes)), np.float32)
        for n, t in enumerate(taxa):
            for c in lab[t]:
                target[n, cidx[c]] = 1
        tr, te = split >= 2, split == 0
        # equal weight per taxon, and per class (single-valued taxa define the class frequency)
        per_taxon = collections.Counter(taxa[tr])
        is_assumed = np.array([(trait, t) in assumed for t in taxa[tr]])
        single = target[tr].sum(1) == 1
        cls_freq = np.maximum(target[tr][single & ~is_assumed].sum(0) if a.assumed_mass else target[tr][single].sum(0), 1)
        cw = (cls_freq.sum() / cls_freq / len(classes)).astype(np.float32)
        base = np.array([label_weight[trait, t] / per_taxon[t] for t in taxa[tr]], np.float32) * (target[tr] * cw).max(1)
        if a.assumed_mass and is_assumed.any():      # assumed labels of a class share a fixed multiple of its stated weight
            for c in range(len(classes)):
                m = is_assumed & (target[tr][:, c] == 1)
                stated = base[~is_assumed & (target[tr][:, c] == 1)].sum()
                if m.any() and stated > 0:
                    base[m] *= a.assumed_mass * stated / base[m].sum()
        test_taxa = sorted(t for t in set(taxa[te]) if (trait, t) not in assumed)
        allowed = [{cidx[c] for c in lab[t]} for t in test_taxa]
        out = {'classes': classes, 'train_taxa': len(per_taxon), 'test_taxa': len(test_taxa),
               'train_photos': int(tr.sum()), 'test_photos': int(te.sum()),
               'mean_visibility': float(w.mean()), 'arms': {}}

        def score(prob_test, weight_test, name, prob_field=None):
            agg = aggregate(prob_test, weight_test, taxa[te], a.pool)
            pred = [int(np.argmax(agg[t])) for t in test_taxa]
            bal, per = balanced_accuracy(pred, allowed, classes)
            res = {'heldout_genus_in_set_accuracy': in_set_accuracy(pred, allowed),
                   'heldout_genus_balanced_accuracy': bal, 'per_class': per}
            if prob_field is not None and field[trait]:
                for scope in ('all', 'unseen_genera'):
                    obs = [o for o in field[trait] if o[1] in cidx and (scope == 'all' or bk(o[3]) < 2)]
                    if not obs:
                        continue
                    fw = fvis[:, [ORGANS.index(o) for o in ORGAN[trait]]].max(1)
                    pr = []
                    for _, _, rws, _ in obs:
                        ww = fw[rws] + 1e-6
                        pr.append(int(np.argmax(prob_field[rws].max(0) if a.pool == 'max' else (prob_field[rws] * ww[:, None]).sum(0))))
                    al = [{cidx[o[1]]} for o in obs]
                    fb, fper = balanced_accuracy(pr, al, classes)
                    res[f'field_{scope}'] = {'observations': len(obs), 'accuracy': in_set_accuracy(pr, al),
                                             'balanced_accuracy': fb, 'per_class': fper,
                                             'confusion': confusion(pr, al, classes)}
            out['arms'].setdefault(name, []).append(res)

        # zero-shot text prompts
        if has_text:
            zt = np.stack([text[keys.index(f'zs:{trait}:{c}')] for c in classes])
            zs = lambda e: torch.softmax(torch.from_numpy(e @ zt.T) * 100, 1).numpy()
            score(zs(x[te]), w[te], 'zero_shot', zs(femb) if femb is not None else None)
        # family alone: most common allowed class of the family among training taxa, else the global one
        fam = collections.defaultdict(lambda: np.zeros(len(classes)))
        glob = np.zeros(len(classes))
        for t in per_taxon:
            v = np.zeros(len(classes))
            v[[cidx[c] for c in lab[t]]] = 1 / len(lab[t])
            fam[family[t]] += v
            glob += v
        pred = [int(np.argmax(fam[family[t]] if family[t] in fam else glob)) for t in test_taxa]
        bal, per = balanced_accuracy(pred, allowed, classes)
        res = {'heldout_genus_in_set_accuracy': in_set_accuracy(pred, allowed),
               'heldout_genus_balanced_accuracy': bal, 'per_class': per}
        for scope in ('all', 'unseen_genera'):       # the same guess for the observations people labelled
            obs = [o for o in field[trait] if o[1] in cidx and (scope == 'all' or bk(o[3]) < 2)]
            if obs:
                pr = [int(np.argmax(fam[genus_family[o[3]]] if genus_family.get(o[3]) in fam else glob)) for o in obs]
                al = [{cidx[o[1]]} for o in obs]
                fb, fper = balanced_accuracy(pr, al, classes)
                res[f'field_{scope}'] = {'observations': len(obs), 'accuracy': in_set_accuracy(pr, al),
                                         'balanced_accuracy': fb, 'per_class': fper}
        out['arms']['family_only'] = [res]
        for seed in range(a.seeds):
            for name, wt, shuffle in ((('flora_visibility', base * w[tr], False),) if has_text else ()) + (
                    ('flora_plain', base, False), ('shuffled_labels', base * w[tr], True)):
                tgt = target[tr]
                if shuffle:                      # give every training taxon another taxon's label set
                    names = sorted(per_taxon)
                    perm = dict(zip(names, np.random.default_rng(seed).permutation(names)))
                    tgt = np.zeros_like(tgt)
                    for n, t in enumerate(taxa[tr]):
                        for c in lab[perm[t]]:
                            tgt[n, cidx[c]] = 1
                head = fit(x[tr], tgt, wt.astype(np.float32), len(classes), device, seed=seed)
                score(predict(head, x[te], device), w[te] if name != 'flora_plain' else np.ones(te.sum(), np.float32),
                      name, predict(head, femb, device) if femb is not None else None)
                if name == 'flora_plain' and seed == 0:
                    torch.save({'state': head.state_dict(), 'classes': classes}, a.out / f'head-{trait}.pt')
                    if a.dump:
                        extra = {'zero_shot': zs(emb[held_rows]).astype(np.float16)} if has_text else {}
                        if femb is not None:
                            extra.update(field_ids=fids, field_prob=predict(head, femb, device).astype(np.float16))
                        np.savez(a.out / f'pred-{trait}.npz', classes=np.array(classes), photo_ids=held_ids,
                                 prob=predict(head, emb[held_rows], device).astype(np.float16), **extra)
        results['traits'][trait] = out
        for metric in ('heldout_genus_balanced_accuracy', 'field_unseen_genera'):
            get = lambda r: r.get(metric) if metric.startswith('heldout') else (r.get(metric) or {}).get('balanced_accuracy')
            summary = {k: round(float(np.mean([get(r) or 0 for r in v])), 3) for k, v in out['arms'].items()}
            print(trait, metric, out['train_taxa'], out['test_taxa'], f'vis={w.mean():.2f}', summary, flush=True)
    (a.out / 'results.json').write_text(json.dumps(results, indent=1, default=float) + '\n')


if __name__ == '__main__':
    main()
