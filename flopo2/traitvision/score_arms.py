"""Score the arms of ``value_arms.py`` on species and observations whose genus the model never saw.

    python -m flopo2.traitvision.score_arms local-corpora/trait-vision [TAG [STATEMENTS FILE FOR THE TEST LABELS]]

Reads ``varms/fold-K/base-<trait>.npz`` and ``pred-<trait>-<arm>-s<seed>.npz``. Per arm (mean over seeds, and
the spread between seeds):

* agreed species (2+ floras state one colour each, the same one): balanced accuracy, and the mean colour
  distance between the predicted and the stated colour (0 when right);
* iNaturalist observers' own colour labels: the same two numbers;
* species that have only "X to Y" statements: where the photographs fall (an end, a colour between, elsewhere),
  next to species stated "X or Y" with the same two colours. Uses the ``plain`` arm, which never saw a "to" statement.
"""
import collections
import csv
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np

from flopo2.traitvision import labels as L
from flopo2.traitvision.score_consensus import agreed, balanced


def statements(folder, tag, source='pilot-assertions-v4.tsv'):
    sup = L.ontology()
    acc = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / f'taxon-names-{tag}.tsv'), delimiter='\t')}
    per = collections.defaultdict(lambda: collections.defaultdict(set))
    for row in csv.DictReader(open(folder / source), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row['rank'] != 'species' or row['frequency'] in L.RARE or row['taxon'] not in acc or row['attr'] != 'PATO_0000014':
            continue
        for trait, cls in L.classes(row, sup):
            per[acc[row['taxon']], trait][row['source']].add(cls)
    return per


def main(folder, tag='v3', source='pilot-assertions-v4.tsv'):
    folder = Path(folder)
    space = json.loads((folder / 'colour-space.json').read_text())
    cd = space['class_dist']
    truth = agreed(statements(folder, tag, source))
    photo_taxon = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(folder / f'inat-photos-{tag}.tsv'), delimiter='\t')}
    lab = collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'colour-labels-v4.tsv'), delimiter='\t'):
        lab[r['trait']][r['taxon']] = r
    field = collections.defaultdict(list)
    for r in csv.DictReader(open(folder / f'field-test-{tag}.tsv'), delimiter='\t'):
        field[r['trait']].append((r['class'], r['taxon'], [int(x) for x in r['photos'].split('|')]))
    report = {}
    for trait in ('flower_colour', 'fruit_colour'):
        pairs = collections.defaultdict(list)            # (group, arm, seed) -> [(true, predicted)]
        where = collections.defaultdict(collections.Counter)
        for base in sorted(glob.glob(str(folder / 'varms' / 'fold-*' / f'base-{trait}.npz'))):
            fold = int(Path(base).parent.name.split('-')[-1])
            held = lambda taxon: (L_bucket(taxon.split()[0]) - 2 * fold) % 10 < 2
            b = np.load(base)
            classes = [str(c) for c in b['classes']]
            by = collections.defaultdict(list)
            for n, pid in enumerate(b['photo_ids']):
                by[photo_taxon[int(pid)]].append(n)
            frow = {int(p): n for n, p in enumerate(b['field_ids'])}
            preds = {'prompts-s0': {'prob': b['zero_shot']}}
            for f in sorted(glob.glob(str(Path(base).parent / f'pred-{trait}-*.npz'))):
                preds[Path(f).stem[len(f'pred-{trait}-'):]] = np.load(f)
            for key, z in preds.items():
                arm, seed = re.fullmatch(r'(.+)-s(\d+)', key).groups()
                prob = z['prob'].astype(np.float32)
                for taxon, rows in by.items():
                    if taxon in truth[trait] and truth[trait][taxon][0] in classes:
                        value, floras = truth[trait][taxon]
                        pairs['agreed' if floras >= 2 else 'one_flora', arm, seed].append((value, classes[int(prob[rows].mean(0).argmax())]))
                if 'field_prob' in z:
                    fp = z['field_prob'].astype(np.float32)
                    for value, taxon, photos in field[trait]:
                        rows = [frow[p] for p in photos if p in frow]
                        if rows and value in classes and held(taxon):
                            pairs['users', arm, seed].append((value, classes[int(fp[rows].mean(0).argmax())]))
                if key == 'plain-s0':                    # where do the photographs of "X to Y" species fall?
                    top = prob.argmax(1)
                    for taxon, rows in by.items():
                        r = lab[trait].get(taxon)
                        if not r:
                            continue
                        al, ends = set(filter(None, r['allowed'].split('|'))), set(filter(None, r['to_ends'].split('|')))
                        mid = set(filter(None, r['to_between'].split('|')))
                        if not al and len(ends) == 2 and '|' not in r['to_pairs']:
                            kind, two = 'to', ends
                        elif len(al) == 2 and not ends:
                            kind, two = 'or', al
                        else:
                            continue
                        if not two <= set(classes):
                            continue
                        a, c = sorted(two)
                        mid = mid or set(space['between_basic'].get(f'{a}|{c}', []))
                        share = np.bincount(top[rows], minlength=len(classes)) / len(rows)
                        s = {x: share[classes.index(x)] for x in classes}
                        w = where[kind, bool(mid)]
                        w['species'] += 1
                        w['end'] += s[a] + s[c]
                        w['minor end'] += min(s[a], s[c])
                        w['between'] += sum(s[x] for x in mid if x in s)
                        near = {x for x in classes if x not in two | mid and min(cd[a][x], cd[c][x]) <= 14}
                        w['near an end'] += sum(s[x] for x in near)
        arms = sorted({a for _, a, _ in pairs})
        out = {}
        for arm in arms:
            row = {}
            for group in ('agreed', 'one_flora', 'users'):
                seeds = sorted(s for g, a, s in pairs if g == group and a == arm)
                if not seeds:
                    continue
                acc = [balanced(pairs[group, arm, s])[0] for s in seeds]
                err = [float(np.mean([cd[t][p] for t, p in pairs[group, arm, s]])) for s in seeds]
                row[group] = {'n': len(pairs[group, arm, seeds[0]]), 'balanced': float(np.mean(acc)), 'spread': float(np.ptp(acc)),
                              'colour_error': float(np.mean(err)), 'error_spread': float(np.ptp(err))}
            out[arm] = row
        report[trait] = {'arms': out, 'to_or': {f'{k[0]}:{"with" if k[1] else "no"} colour between': dict(v) for k, v in where.items()}}
        print(f'\n{trait}: balanced accuracy (spread over seeds) / mean colour distance of the prediction from the stated colour')
        for arm in ['prompts', 'plain', 'ends', 'range'] + [a for a in arms if 'near' in a]:
            if arm not in out:
                continue
            cell = lambda g: (f"{out[arm][g]['balanced']:.3f} (±{out[arm][g]['spread'] / 2:.3f}) / {out[arm][g]['colour_error']:5.2f}"
                              if g in out[arm] else '-')
            n = lambda g: out[arm].get(g, {}).get('n', 0)
            print(f"  {arm:14s} agreed n={n('agreed'):5d}: {cell('agreed')} | one flora n={n('one_flora'):5d}: {cell('one_flora')}"
                  f" | iNat observers n={n('users'):5d}: {cell('users')}")
        for (kind, has_mid), w in sorted(where.items()):
            n = w['species']
            print(f"  species stated X {kind} Y, {'with a' if has_mid else 'no'} colour between (n={n}): photos on an end {w['end'] / n:.2f}"
                  f" (rarer end {w['minor end'] / n:.2f}), between {w['between'] / n:.2f}, another near colour {w['near an end'] / n:.2f}")
    (folder / 'varms' / 'scores.json').write_text(json.dumps(report, indent=1) + '\n')


def L_bucket(genus):
    import hashlib
    return int(hashlib.md5(genus.encode()).hexdigest()[:8], 16) % 10


if __name__ == '__main__':
    main(*sys.argv[1:])
