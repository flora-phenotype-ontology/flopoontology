"""Gene families of sequenced plants against the trait catalogue.

    python -m flopo2.traitvision.genes matrix    # applications/genes/families.npz, gene-species.tsv

Input: ``applications/genes/proteomes-used.tsv`` (UniProt proteomes of vascular plants, BUSCO completeness >= 80%, one per
species) and ``prot/<proteome>.tsv.gz`` (accession, Pfam, PANTHER of every protein; UniProt REST, ``fetch.sh``).
``matrix`` counts the proteins per Pfam family, PANTHER family and PANTHER subfamily in each proteome and joins the species to
the trait table (``species-traits.tsv`` of ``macro.py table``) and to flower colour. A species without a flora value takes
the value of its genus when at least three species of the genus have one and 90% of them agree (column ``<trait>_src``:
species / genus). The tree tip is that of the species, else of a congener.
"""
import collections, csv, gzip, json, re, sys
from pathlib import Path
import numpy as np

A = Path('local-corpora/trait-vision/applications')
G = A / 'genes'
BIN = ['woody', 'annual', 'hairy', 'spiny', 'fleshy_fruit', 'climber', 'succulent', 'compound', 'toothed', 'blue_purple', 'yellow', 'white', 'red_orange', 'nfix', 'c4']
NUM = ['height', 'leaf_area', 'petal_length', 'fruit_length', 'seed_length', 'n_flowers', 'n_stamens']


def matrix():
    prot = list(csv.DictReader(open(G / 'proteomes-used.tsv'), delimiter='\t'))
    prot = [p for p in prot if (G / 'prot' / f"{p['Proteome Id']}.tsv.gz").exists()]
    counts, fams = [], collections.Counter()
    for p in prot:
        c = collections.Counter()
        with gzip.open(G / 'prot' / f"{p['Proteome Id']}.tsv.gz", 'rt') as f:
            next(f)
            for line in f:
                x = line.rstrip('\n').split('\t')
                ids = set(x[1].split(';')) | set(x[2].split(';')) if len(x) > 2 else set()
                for i in ids - {''}:
                    c[i] += 1
                c['_proteins'] += 1
        counts.append(c)
    ok = [c['_proteins'] >= 5000 for c in counts]      # retired proteomes come back empty
    prot = [p for p, o in zip(prot, ok) if o]; counts = [c for c, o in zip(counts, ok) if o]
    for c in counts:
        fams.update(c.keys())
    keep = sorted(f for f, n in fams.items() if n >= 5 and f != '_proteins')
    M = np.array([[c.get(f, 0) for f in keep] for c in counts], dtype=np.int32)
    # traits
    rows = {r['taxon']: r for r in csv.DictReader(open(A / 'species-traits.tsv'), delimiter='\t')}
    lab = collections.defaultdict(dict)
    for r in csv.DictReader(open(A.parent / 'labels-v5.tsv'), delimiter='\t'):
        lab[r['trait']][r['taxon']] = set(r['allowed'].split('|'))

    gs = {r['work_ID']: r['work_species'] for r in json.load(open(A.parent / 'external/gift/species.json'))}
    gift = {'nfix': {gs[r['work_ID']]: float(r['trait_value'] == 'yes') for r in json.load(open(A.parent / 'external/gift/trait-4.5.1.json'))},
            'c4': {gs[r['work_ID']]: float(r['trait_value'] == 'C4') for r in json.load(open(A.parent / 'external/gift/trait-4.2.1.json'))}}

    def value(t, k):
        if k in gift:                      # positive controls: values of GIFT, not of our floras
            return gift[k].get(t)
        r = rows.get(t)
        if k in NUM:
            return None if r is None or r[k] == 'NA' else float(r[k])
        if k == 'woody':
            return None if r is None or r['growth'] not in ('woody', 'herb') else float(r['growth'] == 'woody')
        if k in ('annual', 'hairy', 'spiny', 'fleshy_fruit', 'climber', 'succulent'):
            return None if r is None or r[k] == 'NA' else float(r[k])
        if k == 'compound':
            v = lab['leaf_complexity'].get(t); return None if not v else 1.0 if 'simple' not in v else 0.0 if v == {'simple'} else None
        if k == 'toothed':
            v = lab['leaf_margin'].get(t); return None if not v else 0.0 if v == {'entire'} else 1.0 if 'entire' not in v else None
        v = lab['flower_colour'].get(t)
        if not v:
            return None
        want = {'blue_purple': {'blue', 'purple'}, 'yellow': {'yellow'}, 'white': {'white'}, 'red_orange': {'red', 'orange'}}[k]
        return float(bool(v & want))
    by_genus = collections.defaultdict(list)
    for t in set(rows) | {t for d in lab.values() for t in d} | set(gift['nfix']) | set(gift['c4']):
        by_genus[t.split()[0]].append(t)
    tips = set(re.findall(r'[(,]([A-Z][a-z-]+_[a-z-]+):', open(A / 'phylo' / 'v0.1' / 'ALLMB.tre').read()))
    tip_genus = {}
    for t in sorted(tips):
        tip_genus.setdefault(t.split('_')[0], t)
    used = set()
    with open(G / 'gene-species.tsv', 'w') as f:
        f.write('proteome\tspecies\ttip\tproteins\tbusco\t' + '\t'.join(f'{k}\t{k}_src' for k in BIN + NUM) + '\n')
        for p, c in zip(prot, counts):
            sp = p['sp']; g = sp.split()[0]
            tip = sp.replace(' ', '_')
            if tip not in tips or tip in used:
                tip = tip_genus.get(g, 'NA') if tip_genus.get(g) not in used else 'NA'
            used.add(tip)
            out = []
            for k in BIN + NUM:
                v = value(sp, k); src = 'species'
                if v is None:
                    vs = [x for x in (value(t, k) for t in by_genus.get(g, ())) if x is not None]
                    src = 'genus'
                    if len(vs) >= 3 and k in NUM:
                        v = float(np.median(vs))
                    elif len(vs) >= 3 and (np.mean(vs) >= 0.9 or np.mean(vs) <= 0.1):
                        v = float(round(np.mean(vs)))
                out += ['NA' if v is None else f'{v:g}', 'NA' if v is None else src]
            f.write('\t'.join([p['Proteome Id'], sp, tip, str(c['_proteins']), p['busco']] + out) + '\n')
    np.savez_compressed(G / 'families.npz', M=M, families=np.array(keep), proteomes=np.array([p['Proteome Id'] for p in prot]))
    with open(G / 'families.tsv', 'w') as f:
        f.write('proteome\t' + '\t'.join(keep) + '\n')
        for p, row in zip(prot, M):
            f.write(p['Proteome Id'] + '\t' + '\t'.join(map(str, row)) + '\n')
    print('proteomes', len(prot), 'families', len(keep))


if __name__ == '__main__':
    {'matrix': matrix}[sys.argv[1]]()
