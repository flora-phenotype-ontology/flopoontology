"""Bring flora names and iNaturalist names to one accepted species name (Kew WCVP).

Floras and iNaturalist often use different names for the same species. Both sides are matched
to WCVP and reduced to the accepted binomial; a name WCVP does not know keeps its own spelling,
so exact matches still work. Labels of names that fall together are merged.

    python -m flopo2.traitvision.names local-corpora/trait-vision [TAG]

Reads ``pilot-labels.tsv`` and ``inat-taxa.csv.gz``; writes ``pilot-labels-v2.tsv`` (same
columns, taxon = accepted binomial), ``taxon-names.tsv``, ``inat-names.tsv`` and ``field-test-v2.tsv``.
"""
import collections
import csv
import gzip
import sys
from pathlib import Path

from flopo2.taxon.wcvp import Wcvp

PLANTAE = '47126'


def binomial(wcvp, name, family=''):
    """Accepted binomial of a name, or the name itself when WCVP has no clear answer."""
    m = wcvp.match(name, family=family)
    words = m.accepted_name.split()
    if m.how in ('none', 'ambiguous') or len(words) < 2 or '×' in m.accepted_name or not words[1].islower():
        return ' '.join(name.split()[:2]), False
    return ' '.join(words[:2]), True


def main(outdir, tag='v2'):
    outdir = Path(outdir)
    wcvp = Wcvp()
    rows = list(csv.DictReader(open(outdir / 'pilot-labels.tsv'), delimiter='\t'))
    family = {r['taxon']: r['family'] for r in rows}
    accepted, hit = {}, 0
    for t, f in family.items():
        accepted[t], ok = binomial(wcvp, t, f)
        hit += ok
    print(f'flora names: {len(accepted)}; matched to WCVP {hit}; renamed {sum(k != v for k, v in accepted.items())}; '
          f'distinct accepted {len(set(accepted.values()))}', flush=True)
    with open(outdir / f'taxon-names-{tag}.tsv', 'w') as out:
        out.write('taxon\taccepted\n')
        for t in sorted(accepted):
            out.write(f'{t}\t{accepted[t]}\n')
    merged = collections.defaultdict(lambda: {'allowed': set(), 'rare': set(), 'sources': set(), 'family': collections.Counter()})
    for r in rows:
        m = merged[accepted[r['taxon']], r['trait']]
        m['allowed'] |= set(filter(None, r['allowed'].split('|')))
        m['rare'] |= set(filter(None, r['rare'].split('|')))
        m['sources'] |= set(filter(None, r['sources'].split('|')))
        if r['family']:
            m['family'][r['family']] += 1
    with open(outdir / f'pilot-labels-{tag}.tsv', 'w') as out:
        out.write('taxon\tgenus\tfamily\ttrait\tallowed\trare\tsources\n')
        for (t, trait), m in sorted(merged.items()):
            fam = m['family'].most_common(1)[0][0] if m['family'] else ''
            out.write('\t'.join((t, t.split()[0], fam, trait, '|'.join(sorted(m['allowed'])),
                                 '|'.join(sorted(m['rare'] - m['allowed'])), '|'.join(sorted(m['sources'])))) + '\n')
    wanted = set(accepted.values())

    taxa, fam_name = [], {}
    with gzip.open(outdir / 'inat-taxa.csv.gz', 'rt') as fh:
        for r in csv.DictReader(fh, delimiter='\t', quoting=csv.QUOTE_NONE):
            anc = r['ancestry'].split('/')
            if PLANTAE not in anc:
                continue
            if r['rank'] == 'family':
                fam_name[r['taxon_id']] = r['name']
            elif r['active'] == 'true' and float(r['rank_level'] or 99) <= 10:
                taxa.append((r['taxon_id'], r['name'], anc))
    n = exact = 0
    with open(outdir / f'inat-names-{tag}.tsv', 'w') as out:
        out.write('inat_taxon_id\tinat_name\ttaxon\n')
        for tid, name, anc in taxa:
            fam = next((fam_name[a] for a in anc if a in fam_name), '')
            species = ' '.join(name.split()[:2])
            target = species if species in wanted else binomial(wcvp, name, fam)[0]
            if target not in wanted:
                target = binomial(wcvp, species, fam)[0]
            if target in wanted:
                out.write(f'{tid}\t{name}\t{target}\n')
                n += 1
                exact += target == species
    print(f'iNaturalist taxa mapped: {n} ({exact} by the same name)', flush=True)

    ftest = outdir / 'field-test.tsv'           # the human-labelled test observations, under the same names
    if ftest.exists():
        rows = list(csv.DictReader(open(ftest), delimiter='\t'))
        cache = {}
        with open(outdir / f'field-test-{tag}.tsv', 'w') as out:
            out.write('\t'.join(rows[0]) + '\n')
            for r in rows:
                t = ' '.join(r['taxon'].split()[:2])
                if t not in cache:
                    cache[t] = t if t in wanted else binomial(wcvp, t)[0]
                r['taxon'] = cache[t]
                out.write('\t'.join(r.values()) + '\n')


if __name__ == '__main__':
    main(*sys.argv[1:3])
