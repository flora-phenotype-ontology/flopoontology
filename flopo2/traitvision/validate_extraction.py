"""Checks of the traits extracted from the floras that need no human labels.

``agreement``  For every trait and every species that two sources describe: do the two sources' value sets share a
               value (compatible), and are they identical? Against chance: the same for the two sources' statements
               about two different species (pairs drawn at random within the trait). Pairs of sources whose
               statements for the species have the same wording are left out (one text copied into two corpora).
               kappa = (compatible - chance) / (1 - chance).

    python -m flopo2.traitvision.validate_extraction agreement local-corpora/trait-vision
"""
import collections
import csv
import itertools
import json
import random
import sys
from pathlib import Path

from flopo2.traitvision import labels as L
from flopo2.traitvision import labels_extra as X


def agreement(folder):
    folder = Path(folder)
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / 'taxon-names-v3.tsv'), delimiter='\t')}
    sup = L.ontology()
    sets = collections.defaultdict(lambda: collections.defaultdict(set))       # trait -> (taxon, source) -> values
    texts = collections.defaultdict(set)
    for r in csv.DictReader(open(folder / 'pilot-assertions-v5.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
        if r['rank'] != 'species' or r['frequency'] in L.RARE:
            continue
        t = name.get(r['taxon']) or ' '.join(r['taxon'].split()[:2])
        for trait, c in L.classes(r, sup) + X.classes(r):
            if trait == 'leaflet_shape':
                continue
            sets[trait][t, r['source']].add(c)
            texts[trait, t, r['source']].add(r['text'].lower().strip())
    rng = random.Random(0)
    out = {}
    for trait, d in sorted(sets.items()):
        by = collections.defaultdict(list)
        for (t, s), v in d.items():
            by[t].append((s, v))
        pairs = [(a, b) for t, ss in by.items() for (sa, a), (sb, b) in itertools.combinations(ss, 2)
                 if not (texts[trait, t, sa] & texts[trait, t, sb])]
        if len(pairs) < 50:
            continue
        comp = sum(bool(a & b) for a, b in pairs) / len(pairs)
        same = sum(a == b for a, b in pairs) / len(pairs)
        left, right = [a for a, _ in pairs], [b for _, b in pairs]
        rng.shuffle(right)
        chance = sum(bool(a & b) for a, b in zip(left, right)) / len(pairs)
        single = [(a, b) for a, b in pairs if len(a) == 1 and len(b) == 1]
        out[trait] = {'species': sum(1 for ss in by.values() if len(ss) > 1), 'pairs': len(pairs), 'compatible': comp, 'identical': same,
                      'chance': chance, 'kappa': (comp - chance) / (1 - chance) if chance < 1 else None,
                      'single_valued_pairs': len(single), 'single_valued_equal': sum(a == b for a, b in single) / max(1, len(single))}
        o = out[trait]
        print(f"{trait:17s} species {o['species']:6d} pairs {o['pairs']:6d}  compatible {comp:.3f} (chance {chance:.3f}, kappa {o['kappa']:.3f})"
              f"  identical {same:.3f}  one value each: equal {o['single_valued_equal']:.3f} (n={len(single)})")
    (folder / 'extraction-agreement.json').write_text(json.dumps(out, indent=1) + '\n')


if __name__ == '__main__':
    {'agreement': agreement}[sys.argv[1]](*sys.argv[2:])
