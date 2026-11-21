"""Assumed-absent labels under a local closed-world assumption (spines, compound leaves).

Floras report some traits only when present: spines are mentioned when a plant has them, leaflets
when the leaf is compound. For these traits, and only these, a description that is *complete
enough* is read as closed: what it does not mention is taken to be absent.

A description of species X in flora S is complete for a trait when S describes the organ that
would carry it (stem or whole plant for spines, leaf or leaf blade for leaflets). The absence is
*assumed*, not stated, and it is weighted by how reliable S is:

    recall(S) = of the species another flora reports as positive and S describes, the share S
                reports as positive too   (measured from the floras alone, no labels of ours)
    P(positive | silent in S1..Sn) = prior * prod(1 - recall(Si)) / (same + 1 - prior)

Each assumed label also records how close the nearest positive is (``near``: a positive species in
the same genus, in the same family, or neither). Floras state an absence mostly where it is worth
saying, in groups that have the trait, so near absences are the informative ones.

Species with a positive in any flora, with a stated absence, or in a genus whose own description
is positive, get no assumed label. Assumed labels are for training only; tests use stated labels.

    python -m flopo2.traitvision.labels_cwa local-corpora/trait-vision

Reads ``pilot-assertions.tsv``, ``taxon-names.tsv``, ``pilot-labels-v2.tsv``; writes
``pilot-labels-v3.tsv`` (extra columns ``weight`` and ``assumed``) and ``cwa-summary.json``.
"""
import collections
import csv
import json
import re
import sys
from pathlib import Path

from flopo2.traitvision import labels as L

# trait: (positive class, assumed class, organs whose description makes the flora complete, minimum statements)
RULES = {'spines': ('present', 'absent', {'stem', 'whole plant'}, 1),
         'leaf_complexity': ('compound', 'simple', {'leaf', 'leaf lamina'}, 2)}
MIN_PAIRS, MAX_RISK = 20, 0.15


def main(outdir, tag='v2'):
    outdir = Path(outdir)
    csv.field_size_limit(10 ** 9)
    sup = L.ontology()
    accepted = {r['taxon']: r['accepted'] for r in csv.DictReader(open(outdir / f'taxon-names-{tag}.tsv'), delimiter='\t')}
    scope = {t: collections.defaultdict(collections.Counter) for t in RULES}     # trait -> source -> species -> statements
    positive = {t: collections.defaultdict(set) for t in RULES}                  # trait -> source -> species
    genus_positive = {t: set() for t in RULES}
    fam_of = {}
    for row in csv.DictReader(open(outdir / 'pilot-assertions.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
        found = {(trait, cls) for trait, cls in L.classes(row, sup) if trait in RULES}
        if row['rank'] == 'genus':
            for trait, cls in found:
                if cls == RULES[trait][0] and row['frequency'] not in L.RARE:
                    genus_positive[trait].add(row['taxon'].split()[0])
            continue
        if row['rank'] != 'species' or not re.match(r'[A-Z][a-z-]+ [a-z-]+( |$)', row['taxon']):
            continue
        sp = accepted.get(row['taxon'], ' '.join(row['taxon'].split()[:2]))
        if row['family']:
            fam_of.setdefault(sp, row['family'])
        for trait, (pos, _, organs, _) in RULES.items():
            if row['entity'] in organs:
                scope[trait][row['source']][sp] += 1
            if (trait, pos) in found:
                positive[trait][row['source']].add(sp)
    rows = list(csv.DictReader(open(outdir / f'pilot-labels-{tag}.tsv'), delimiter='\t'))
    labelled = {(r['taxon'], r['trait']) for r in rows}
    summary, new = {}, []
    for trait, (pos, neg, _, least) in RULES.items():
        described = {s: {sp for sp, n in c.items() if n >= least} for s, c in scope[trait].items()}
        recall, pooled = {}, [0, 0]
        for s in described:
            other = set().union(*[v for o, v in positive[trait].items() if o != s]) & described[s]
            hit = len(other & positive[trait][s])
            pooled[0] += hit
            pooled[1] += len(other)
            if len(other) >= MIN_PAIRS:
                recall[s] = hit / len(other)
        pooled_recall = pooled[0] / max(pooled[1], 1)
        allpos = set().union(*positive[trait].values())
        alldesc = set().union(*described.values())
        prior = min(0.9, len(allpos & alldesc) / len(alldesc) / max(pooled_recall, 0.3))
        made = collections.Counter()
        pos_genera = {x.split()[0] for x in allpos}
        pos_families = {fam_of[x] for x in allpos if x in fam_of}
        for sp in sorted(alldesc - allpos):
            if (sp, trait) in labelled or sp.split()[0] in genus_positive[trait]:
                made['skipped: labelled or genus positive'] += 1
                continue
            silent = [s for s in described if sp in described[s]]
            miss = prior
            for s in silent:
                miss *= 1 - recall.get(s, min(pooled_recall, 0.5))     # a flora with too few pairs counts as weak
            risk = miss / (miss + 1 - prior)
            if risk > MAX_RISK:
                made['skipped: flora too unreliable'] += 1
                continue
            near = 'genus' if sp.split()[0] in pos_genera else 'family' if fam_of.get(sp) in pos_families else 'far'
            made['near ' + near] += 1
            new.append({'taxon': sp, 'genus': sp.split()[0], 'family': fam_of.get(sp, ''), 'trait': trait, 'near': near,
                        'allowed': neg, 'rare': '', 'sources': '|'.join(sorted(silent)),
                        'weight': f'{1 - 2 * risk:.3f}', 'assumed': '1'})
            made['assumed ' + neg] += 1
        summary[trait] = {'prior_positive': round(prior, 3), 'pooled_recall': round(pooled_recall, 3),
                          'recall_by_flora': {s: round(v, 3) for s, v in sorted(recall.items())},
                          'stated_labels': sum(t == trait for _, t in labelled), **made}
        print(trait, json.dumps(summary[trait]), flush=True)
    with open(outdir / f'pilot-labels-{tag}-cwa.tsv', 'w') as out:
        cols = ['taxon', 'genus', 'family', 'trait', 'allowed', 'rare', 'sources', 'weight', 'assumed', 'near']
        out.write('\t'.join(cols) + '\n')
        for r in rows + new:
            out.write('\t'.join(r.get(c, {'weight': '1', 'assumed': '0'}.get(c, '')) for c in cols) + '\n')
    (outdir / f'cwa-summary-{tag}.json').write_text(json.dumps(summary, indent=1) + '\n')


if __name__ == '__main__':
    main(*sys.argv[1:3])
