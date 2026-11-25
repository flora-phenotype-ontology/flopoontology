"""Colour labels that use the colour value space (flower and fruit colour).

Next to the set of basic colours a flora states for a species (``allowed``, as in ``labels.py``), this writes

* ``to_ends``: the two ends of every "X to Y" statement (these statements have no value term, so the first
  labels left them out);
* ``to_between``: the basic colours that lie between the two ends (``colour_space.between_classes``);
* ``dist``: for every other training class, the colour distance to the nearest value any flora states for the
  species, taken from the stated value itself ("magenta", "lilac"), not from its basic colour;
  ``dist_all`` is the same with the ends of the "to" statements counted as stated;
* ``to_pairs``: the ends as stated, for measuring how such species look in photographs.

Names are the accepted names of the label file it extends.

    python -m flopo2.traitvision.colour_labels local-corpora/trait-vision [TAG]
"""
import collections
import csv
import json
import sys
from pathlib import Path

from flopo2.traitvision import labels as L
from flopo2.traitvision.colour_space import between_classes


def main(folder, tag='v3'):
    folder = Path(folder)
    space = json.loads((folder / 'colour-space.json').read_text())
    sup = L.ontology()
    acc = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / f'taxon-names-{tag}.tsv'), delimiter='\t')}
    family = {}
    for r in csv.DictReader(open(folder / f'pilot-labels-{tag}.tsv'), delimiter='\t'):
        family[r['taxon']] = r['family']
    class_lab = {c: space['lab'][c] for c in space['classes']}
    rec = collections.defaultdict(lambda: {'allowed': set(), 'ends': set(), 'between': set(), 'values': set(), 'end_values': set(),
                                           'pairs': set(), 'sources': set()})
    n = collections.Counter()
    for row in csv.DictReader(open(folder / 'pilot-assertions-v4.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row['rank'] != 'species' or row['attr'] != 'PATO_0000014' or row['taxon'] not in acc:
            continue
        ent = row['entity']
        if not (ent in L.FLOWER or ent.endswith('fruit')):
            continue
        if row['negated'] == '1' or ':ctx' in row['operator'] or row['frequency'] in L.RARE:
            continue
        m = rec[acc[row['taxon']], 'flower_colour' if ent in L.FLOWER else 'fruit_colour']
        if row['rel_from'] and row['rel_to']:
            n[row['rel']] += 1
            a, b = row['rel_from'], row['rel_to']
            ea, eb = L.basic_colours(a, sup), L.basic_colours(b, sup)
            if not ea or not eb or a not in space['lab'] or b not in space['lab']:
                n['ends outside the basic colours'] += 1
                continue
            m['ends'] |= ea | eb
            m['end_values'] |= {a, b}
            if row['rel'] == 'continuum':                    # "turning" and "or" statements have two ends and nothing between
                m['between'] |= set(between_classes(space['lab'][a], space['lab'][b], class_lab, ea | eb))
            m['pairs'].add(f'{"+".join(sorted(ea))}>{"+".join(sorted(eb))}')
            m['sources'].add(row['source'])
        else:
            for v in row['values'].split('|'):
                found = L.basic_colours(v, sup)
                if found:
                    m['allowed'] |= found
                    m['sources'].add(row['source'])
                    if v in space['dist']:
                        m['values'].add(v)
    out_n = collections.Counter()
    with open(folder / 'colour-labels-v4.tsv', 'w') as out:
        out.write('taxon\tgenus\tfamily\ttrait\tallowed\tto_ends\tto_between\tdist\tdist_all\tto_pairs\tsources\n')
        for (taxon, trait), m in sorted(rec.items()):
            if not (m['allowed'] or m['ends']):
                continue
            stated = m['allowed'] | m['ends']

            def dist(values, classes):                       # class -> distance to the nearest of these stated values
                d = {c: min([space['dist'][v][c] for v in values] + [space['class_dist'][s][c] for s in classes])
                     for c in space['classes']} if classes else {}
                return '|'.join(f'{c}:{x:.1f}' for c, x in sorted(d.items()) if c not in classes)
            out.write('\t'.join((taxon, taxon.split()[0], family.get(taxon, ''), trait, '|'.join(sorted(m['allowed'])),
                                 '|'.join(sorted(m['ends'] - m['allowed'])), '|'.join(sorted(m['between'] - stated)),
                                 dist(m['values'], m['allowed']), dist(m['values'] | m['end_values'], stated),
                                 '|'.join(sorted(m['pairs'])), '|'.join(sorted(m['sources'])))) + '\n')
            out_n[trait, 'species'] += 1
            out_n[trait, 'only "to" statements'] += not m['allowed']
            out_n[trait, 'with a "to" statement'] += bool(m['ends'])
            out_n[trait, '"to" adds a colour'] += bool(m['ends'] - m['allowed'])
            out_n[trait, 'with a colour in between'] += bool(m['between'] - stated)
    print(dict(n))
    for k, v in sorted(out_n.items()):
        print(k, v)


if __name__ == '__main__':
    main(*sys.argv[1:3])
