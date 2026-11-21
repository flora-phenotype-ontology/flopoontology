"""Score the rotating held-out-genus runs against labels that two or more floras agree on.

    python -m flopo2.traitvision.score_consensus local-corpora/trait-vision [TAG]

Reads ``folds/run-fold-K/pred-<trait>.npz`` (written by ``train.py --fold K --dump``): every genus is held out
in exactly one of the five runs, so every species and every labelled observation is scored by a model that
never saw its genus.

* agreed species: 2+ floras state one value each, and the same one;
* one-flora species: a single flora states a single value;
* iNaturalist observations: the value an observer entered; next to it, how often simply looking up the
  flora of the observed species gives that value.
"""
import collections
import csv
import glob
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from flopo2.traitvision import labels as L


def bucket(genus):
    return int(hashlib.md5(genus.encode()).hexdigest()[:8], 16) % 10


def statements(folder, tag='v3'):
    """(taxon, trait) -> flora -> set of values, on accepted names."""
    sup = L.ontology()
    acc = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / f'taxon-names-{tag}.tsv'), delimiter='\t')}
    per = collections.defaultdict(lambda: collections.defaultdict(set))
    for row in csv.DictReader(open(folder / 'pilot-assertions.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row['rank'] != 'species' or row['frequency'] in L.RARE or row['taxon'] not in acc:
            continue
        for trait, cls in L.classes(row, sup):
            per[acc[row['taxon']], trait][row['source']].add(cls)
    return per


def agreed(per):
    """trait -> {taxon: (value, number of floras)} for single-valued statements; 2+ floras = agreed."""
    out = collections.defaultdict(dict)
    for (taxon, trait), v in per.items():
        sets = list(v.values())
        if all(len(s) == 1 for s in sets) and len({next(iter(s)) for s in sets}) == 1:
            out[trait][taxon] = (next(iter(sets[0])), len(sets))
    return out


def balanced(pairs):
    """pairs: (true, predicted). Mean recall over classes with 5+ cases; also n."""
    hit, tot = collections.Counter(), collections.Counter()
    for t, p in pairs:
        tot[t] += 1
        hit[t] += t == p
    big = [c for c in tot if tot[c] >= 5]
    return (float(np.mean([hit[c] / tot[c] for c in big])) if big else float('nan')), sum(tot[c] for c in big)


def main(folder, tag='v3'):
    folder = Path(folder)
    per = statements(folder, tag)
    truth = agreed(per)
    photo_taxon = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(folder / f'inat-photos-{tag}.tsv'), delimiter='\t')}
    labels, family = collections.defaultdict(dict), {}
    for r in csv.DictReader(open(folder / f'pilot-labels-{tag}.tsv'), delimiter='\t'):
        labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
        family[r['taxon']] = r['family']
    field = collections.defaultdict(list)
    for r in csv.DictReader(open(folder / f'field-test-{tag}.tsv'), delimiter='\t'):
        field[r['trait']].append((r['class'], r['taxon'], [int(x) for x in r['photos'].split('|')]))
    report = {}
    for trait in sorted(truth):
        res = collections.defaultdict(list)
        for f in sorted(glob.glob(str(folder / 'folds' / 'run-fold-*' / f'pred-{trait}.npz'))):
            fold = int(Path(f).parent.name.split('-')[-1])
            held = lambda taxon: (bucket(taxon.split()[0]) - 2 * fold) % 10 < 2
            z = np.load(f)
            classes = [str(c) for c in z['classes']]
            fam, glob_ = collections.defaultdict(lambda: np.zeros(len(classes))), np.zeros(len(classes))
            for t, s in labels[trait].items():           # family guess from the training genera of this run
                s = [c for c in s if c in classes]
                if s and not held(t):
                    for c in s:
                        fam[family[t]][classes.index(c)] += 1 / len(s)
                        glob_[classes.index(c)] += 1 / len(s)
            by = collections.defaultdict(list)
            for n, pid in enumerate(z['photo_ids']):
                by[photo_taxon[int(pid)]].append(n)
            for taxon, rows in by.items():
                if taxon not in truth[trait] or truth[trait][taxon][0] not in classes:
                    continue
                value, floras = truth[trait][taxon]
                group = 'agreed' if floras >= 2 else 'one_flora'
                res[group, 'model'].append((value, classes[int(z['prob'][rows].astype(np.float32).mean(0).argmax())]))
                if 'zero_shot' in z:
                    res[group, 'prompts'].append((value, classes[int(z['zero_shot'][rows].astype(np.float32).mean(0).argmax())]))
                g = fam[family.get(taxon)] if family.get(taxon) in fam else glob_
                res[group, 'family'].append((value, classes[int(g.argmax())]))
                if group == 'agreed':
                    res['agreed_photo', 'model'] += [(value, classes[int(k)]) for k in z['prob'][rows].argmax(1)]
            if 'field_ids' in z:
                frow = {int(p): n for n, p in enumerate(z['field_ids'])}
                for value, taxon, photos in field[trait]:
                    rows = [frow[p] for p in photos if p in frow]
                    if not rows or value not in classes or not held(taxon):
                        continue
                    pred = classes[int(z['field_prob'][rows].astype(np.float32).mean(0).argmax())]
                    res['users', 'model'].append((value, pred))
                    s = labels[trait].get(taxon)
                    if s and len(s) == 1:
                        res['users_single', 'flora_lookup'].append((value, next(iter(s))))
                        res['users_single', 'model'].append((value, pred))
        report[trait] = {f'{a}:{b}': balanced(v) for (a, b), v in res.items()}
        r = report[trait]
        g = lambda k: f"{r[k][0]:.2f}" if k in r else '  - '
        print(f"{trait:17s} agreed species n={r.get('agreed:model', (0, 0))[1]:5d}: model {g('agreed:model')} prompts {g('agreed:prompts')} family {g('agreed:family')}"
              f" | per photo n={r.get('agreed_photo:model', (0, 0))[1]:6d}: {g('agreed_photo:model')}"
              f" | one flora n={r.get('one_flora:model', (0, 0))[1]:5d}: model {g('one_flora:model')}"
              f" | iNat users n={r.get('users:model', (0, 0))[1]:5d}: model {g('users:model')}; where flora has one value n={r.get('users_single:model', (0, 0))[1]:4d}: model {g('users_single:model')} flora lookup {g('users_single:flora_lookup')}")
    (folder / 'folds' / 'consensus-scores.json').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    main(*sys.argv[1:])
