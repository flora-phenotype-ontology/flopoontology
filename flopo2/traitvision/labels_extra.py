"""Flora labels for the traits that go with leaf nitrogen, leaf mass per area and leaf area.

From the statements of ``extract.py`` (``pilot-assertions-v4.tsv``) and the measurements of
``extract_measures.py`` (``measures-all.tsv``); taxa are brought to the accepted name with ``taxon-names-v3.tsv``.

``extra-labels.tsv`` (columns of ``pilot-labels-v3.tsv``) and ``agreed-extra.tsv`` (2+ floras, one value each, the same):

* leaf_texture      coriaceous | papery | membranous | fleshy   (leaf, leaf lamina, leaflet)
* life_span         annual | biennial | perennial               (whole plant)
* leaf_persistence  evergreen | deciduous                       (whole plant; leaf deciduous / non-deciduous)
* leaf_shape        linear | lanceolate | elliptic | ovate | oblong | obovate | cordate | round
* leaf_hair, stem_hair (glabrous | hairy), leaf_apex, leaf_base (by the statement's wording: apex or base),
  leaf_attachment (sessile | petiolate), leaf_position (basal | cauline), posture (erect | ascending | prostrate |
  climbing), branching, stem_shape, substrate (epiphytic | terrestrial), fruit_type (the fruit class the floras
  name: capsule, achene, legume, ...), fruit_shape, corolla_shape, flower_position (terminal | axillary)

``measure-labels-v3.tsv``: the sizes of ``baseline_v2.py`` plus leaflet length and width, and ``leaf_area``
(log10 m2): length x width x a factor for the shape (0.7 when no shape is stated), of the leaf.
``leaflet_area`` likewise for the leaflet. TRY's leaf area does not say whether a compound leaf or its leaflet
was measured; ``ceiling`` compares both readings with TRY.

    python3 -m flopo2.traitvision.labels_extra labels local-corpora/trait-vision
    python3 -m flopo2.traitvision.labels_extra ceiling local-corpora/trait-vision TRY-SPECIES.tsv
"""
import collections
import csv
import math
import re
import statistics
import sys
from pathlib import Path

from flopo2.traitvision.baseline_v2 import RULES as SIZE_RULES

RARE = {'rarely', 'sometimes', 'occasionally', 'seldom', 'rare'}
LEAF = {'leaf', 'leaf lamina', 'leaflet'}
TEXTURE = {'coriaceous': 'coriaceous', 'subcoriaceous': 'coriaceous', 'increased thickness': 'coriaceous',
           'papyraceous': 'papery', 'chartaceous': 'papery',
           'membranous': 'membranous', 'herbaceous': 'membranous', 'decreased thickness': 'membranous',
           'fleshy': 'fleshy', 'succulent': 'fleshy'}
SPAN = {'annual life span': 'annual', 'biennial life span': 'biennial', 'perennial life span': 'perennial'}
PERSIST = {('whole plant', 'evergreen (plant)'): 'evergreen', ('whole plant', 'deciduous (plant)'): 'deciduous',
           ('leaf', 'deciduous (generic)'): 'deciduous', ('leaf', 'non-deciduous (any body part)'): 'evergreen'}
SHAPE = {'linear': 'linear', 'lanceolate': 'lanceolate', 'oblanceolate': 'lanceolate', 'elliptic': 'elliptic',
         'ovate': 'ovate', 'oblong': 'oblong', 'obovate': 'obovate', 'heart shaped': 'cordate',
         'orbicular': 'round', 'circular': 'round', 'round': 'round'}
HAIRY = {'pubescent hair', 'hairy', 'puberulous', 'tomentose', 'pilose', 'villous', 'hirsute', 'strigose', 'scabrous'}
APEX = {'acute (sensu botany)': 'acute', 'acuminate': 'acuminate', 'obtuse': 'obtuse', 'rounded': 'obtuse',
        'mucronate': 'mucronate', 'emarginate': 'emarginate'}
BASE = {'cuneate': 'cuneate', 'attenuate': 'cuneate', 'tapered': 'cuneate', 'heart shaped': 'cordate', 'rounded': 'rounded',
        'obtuse': 'rounded', 'truncated': 'truncate', 'decurrent': 'decurrent', 'clasping': 'clasping'}
ATTACH = {'sessile (sensu botany)': 'sessile', 'petiolate': 'petiolate'}
POSITION = {'basal': 'basal', 'rosulate': 'basal', 'cauline': 'cauline'}
POSTURE = {'erect': 'erect', 'ascending': 'ascending', 'decumbent': 'ascending', 'prostrate': 'prostrate',
           'procumbent': 'prostrate', 'creeping': 'prostrate', 'climbing': 'climbing'}
BRANCHING = {'branched': 'branched', 'unbranched': 'unbranched', 'simple': 'unbranched'}
STEM_SHAPE = {'terete': 'terete', 'cylindrical': 'terete', 'quadrangular': 'quadrangular', 'angular': 'angular',
              'trigonous': 'angular', 'ribbed': 'angular'}
FRUIT_SHAPE = {'spherical': 'globose', 'spheroid': 'globose', 'ovate': 'ovoid', 'obovoid': 'ovoid', 'elliptic': 'ovoid',
               'oblong': 'elongate', 'prolate': 'elongate', 'cylindrical': 'elongate', 'linear': 'elongate',
               'fusiform': 'elongate', 'flattened': 'flattened'}
FRUIT_TYPE = {'capsule', 'achene', 'legume', 'nut', 'berry', 'drupe', 'utricle capsule', 'follicle', 'caryopsis',
              'schizocarp', 'samara', 'silique'}
COROLLA = {'funnel-shaped': 'funnel', 'tubular': 'tubular', 'campanulate': 'bell', 'rotate': 'rotate',
           'salverform': 'salverform', 'urceolate': 'urn', 'bilabiate': 'two-lipped'}
INFL_POS = {'terminal': 'terminal', 'subterminal': 'terminal', 'axillary': 'axillary'}
SUBSTRATE = {'epiphytic': 'epiphytic', 'terrestrial': 'terrestrial'}
COUNTS = {'flower': 'n_flowers', 'stamen': 'n_stamens', 'petal': 'n_petals', 'corolla lobe': 'n_petals', 'tepal': 'n_petals',
          'perianth lobe': 'n_petals', 'sepal': 'n_sepals', 'calyx lobe': 'n_sepals', 'leaflet': 'n_leaflets', 'seed': 'n_seeds',
          'ray flower': 'n_ray_flowers', 'secondary leaf vein': 'n_veins',
          'lateral leaf vein': 'n_veins', 'style': 'n_styles', 'stigma': 'n_styles', 'carpel': 'n_carpels'}
# area / (length x width) of the outline
FACTOR = {'linear': 0.85, 'lanceolate': 0.66, 'elliptic': 0.75, 'ovate': 0.68, 'oblong': 0.85, 'obovate': 0.68,
          'cordate': 0.70, 'round': 0.79}
RULES = {**{k: v for k, v in SIZE_RULES.items() if k != ('corolla', 'length')},   # mostly the corolla tube (judge_extraction.py)
         ('leaflet', 'length'): ('leaflet_length', 'mid'), ('leaflet', 'width'): ('leaflet_width', 'mid')}


FINE = False                                                  # variant ``fine``: the class is named coarse/term


def _fine(m, part):
    return m[part] + '/' + part if FINE else m[part]


def classes(r):
    ent, q = r['entity'], r['qlabel']
    if r['negated'] == '1' or ':ctx' in r['operator']:
        return []
    out = []
    for part in q.split(' to ') if ' to ' in q else q.split(' - '):       # "papyraceous to coriaceous": both ends
        part = part.strip()
        if ent in LEAF and part in TEXTURE:
            out.append(('leaf_texture', _fine(TEXTURE, part)))
        if ent in ('leaf', 'leaf lamina') and part in SHAPE:
            out.append(('leaf_shape', _fine(SHAPE, part)))
        if ent == 'leaflet' and part in SHAPE:
            out.append(('leaflet_shape', _fine(SHAPE, part)))
        if ent == 'whole plant' and part in SPAN:
            out.append(('life_span', _fine(SPAN, part)))
        if (ent, part) in PERSIST:
            out.append(('leaf_persistence', PERSIST[ent, part]))
        text = r['text'].lower()
        if ent in LEAF or ent == 'stem':
            organ = 'stem' if ent == 'stem' else 'leaf'
            if part == 'glabrous' or part in HAIRY:
                out.append((organ + '_hair', 'glabrous' if part == 'glabrous' else ('hairy/' + part if FINE else 'hairy')))
        if ent in LEAF:
            if part in APEX and not re.search(r'\bbas', text) and (part != 'rounded' or re.search(r'apex|apic|tip', text)):
                out.append(('leaf_apex', _fine(APEX, part)))
            if part in BASE and not re.search(r'apex|apic|tip', text) and (part not in ('rounded', 'obtuse', 'heart shaped') or re.search(r'\bbas', text)):
                out.append(('leaf_base', _fine(BASE, part)))
        if ent in ('leaf', 'leaf lamina'):
            if part in ATTACH:
                out.append(('leaf_attachment', _fine(ATTACH, part)))
            if part in POSITION:
                out.append(('leaf_position', _fine(POSITION, part)))
        if ent in ('stem', 'whole plant') and part in POSTURE:
            out.append(('posture', _fine(POSTURE, part)))
        if ent == 'stem' and part in BRANCHING:
            out.append(('branching', _fine(BRANCHING, part)))
        if ent == 'stem' and part in STEM_SHAPE:
            out.append(('stem_shape', _fine(STEM_SHAPE, part)))
        if ent == 'whole plant' and part in SUBSTRATE:
            out.append(('substrate', _fine(SUBSTRATE, part)))
        if ent.endswith('fruit') and part in FRUIT_SHAPE:
            out.append(('fruit_shape', _fine(FRUIT_SHAPE, part)))
        if ent in ('corolla', 'flower', 'perianth') and part in COROLLA:
            out.append(('corolla_shape', _fine(COROLLA, part)))
        if (ent.endswith('inflorescence') or ent == 'flower') and part in INFL_POS:
            out.append(('flower_position', _fine(INFL_POS, part)))
    if ent.endswith(' fruit') and ent[:-6] in FRUIT_TYPE:
        out.append(('fruit_type', ent[:-6].replace('utricle capsule', 'utricle')))
    return out


def canonical():
    """Variant ``canon``: only the term that names a class counts, not the terms grouped under it."""
    from flopo2.traitvision import labels as L
    for m in (TEXTURE, SHAPE, APEX, BASE, POSITION, POSTURE, BRANCHING, STEM_SHAPE, FRUIT_SHAPE, INFL_POS, L.MARGIN, L.COMPOUND):
        seen = set()
        for k in list(m):
            if m[k] in seen:
                del m[k]
            seen.add(m.get(k))
    HAIRY.intersection_update({'hairy', 'pubescent hair'})


def labels(folder, variant=''):
    """``variant`` (writes ``labels-v5-<variant>.tsv`` only): ctx (statements about a position or stage taken as general),
    nosub (colours without the ontology's subclasses), canon (no grouping of terms), rare (rare values allowed),
    measure (leaf shape linear from length : width >= 10 where no shape is stated),
    fine (classes at the level of the term: a term stated for 300 or more species is its own class under its coarse
    class; a colour stated as a basic colour allows every finer colour under it, by the ontology's subclasses)."""
    folder = Path(folder)
    global FINE
    FINE = variant == 'fine'
    if variant == 'canon':
        canonical()
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / 'taxon-names-v3.tsv'), delimiter='\t')}
    acc = lambda t: name.get(t) or ' '.join(t.split()[:2])
    allowed, rare, by_src, family = (collections.defaultdict(set), collections.defaultdict(set),
                                     collections.defaultdict(lambda: collections.defaultdict(set)), {})
    from flopo2.traitvision import labels as L
    L_PILOT_MAPS = {'leaf_arrangement': L.ARRANGEMENT, 'leaf_margin': L.MARGIN, 'leaf_complexity': L.COMPOUND}
    sup = L.ontology() if variant != 'nosub' else {}
    v5 = (folder / 'pilot-assertions-v5.tsv').exists()         # extract.py with scope.py: vascular plants, no copies
    for r in csv.DictReader(open(folder / ('pilot-assertions-v5.tsv' if v5 else 'pilot-assertions-v4.tsv')), delimiter='\t', quoting=csv.QUOTE_NONE):
        if r['rank'] != 'species' or not re.match(r'[A-Z][a-z-]+ [a-z-]+( |$)', r['taxon']):
            continue
        t = acc(r['taxon'])
        if variant == 'ctx':
            r['operator'] = r['operator'].replace(':ctx', '')
        found = classes(r) + (L.classes(r, sup) if v5 else [])
        if FINE:                                               # the pilot traits: the term behind the coarse class
            vals = r['values'].split('|')
            fine = []
            for trait, c in found:
                if '/' in c or trait in ('habit', 'spines', 'inflorescence') or trait not in L_PILOT_MAPS and not trait.endswith('_colour'):
                    fine.append((trait, c))
                elif trait.endswith('_colour'):
                    fine += [(trait, c + '/' + v) for v in vals if c in L.basic_colours(v, sup)]
                else:
                    m = L_PILOT_MAPS[trait]
                    hit = [(trait, c + '/' + v) for v in vals if m.get(v) == c]
                    fine += hit or [(trait, c)]
            found = fine
        for trait, c in found:
            family.setdefault(t, r['family'])
            if r['frequency'] in RARE and variant != 'rare':
                rare[t, trait].add(c)
            else:
                allowed[t, trait].add(c); by_src[t, trait][r['source']].add(c)
    count = collections.Counter()
    if FINE:
        basic = {v: k for k, v in L.BASIC.items()}
        seen = collections.Counter((trait, c) for d in (allowed, rare) for (t, trait), cls in d.items() for c in cls)
        generic = lambda trait, c: c.split('/')[1] in (c.split('/')[0], basic.get(c.split('/')[0]))
        keep = {k for k, n in seen.items() if '/' in k[1] and n >= 300 and not generic(*k)}
        kids = collections.defaultdict(set)
        for trait, c in keep:
            kids[trait, c.split('/')[0]].add(c)

        def settle(trait, cls):
            out = set()
            for c in cls:
                if '/' not in c:
                    out.add(c)
                elif (trait, c) in keep:
                    out.add(c)
                elif trait.endswith('_colour') and generic(trait, c):
                    out |= {c.split('/')[0]} | kids[trait, c.split('/')[0]]         # "red": any red
                else:
                    out.add(c.split('/')[0])
            return out
        for d in (allowed, rare):
            for k in list(d):
                d[k] = settle(k[1], d[k])
        for k in list(by_src):
            for src in by_src[k]:
                by_src[k][src] = settle(k[1], by_src[k][src])
        print('fine classes', len(keep), sorted(collections.Counter(t for t, _ in keep).items()))
    if variant == 'measure':                                   # pattern 17: linear is length : width >= 10
        dims = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in csv.DictReader(open(folder / 'measures-all.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
            if r['entity'] in ('leaf', 'leaf lamina') and r['quality'] in ('length', 'width') and r['rank'] == 'species' and not r['ctx']:
                lo, hi = (float(r[k]) if r[k] else None for k in ('low_m', 'high_m'))
                v = math.sqrt(lo * hi) if lo and hi else (hi if hi is not None else lo)
                if v:
                    dims[acc(r['taxon'])][r['quality']].append(v)
        stated = collections.Counter()
        for t, d in dims.items():
            if d['length'] and d['width']:
                ratio = statistics.median(d['length']) / statistics.median(d['width'])
                has = allowed.get((t, 'leaf_shape'))
                if has:
                    stated['linear stated' if 'linear' in has else 'other shape stated', 'ratio >= 10' if ratio >= 10 else 'ratio < 10'] += 1
                elif ratio >= 10 and t in family:
                    allowed[t, 'leaf_shape'].add('linear'); by_src[t, 'leaf_shape']['measure'].add('linear'); count['linear from measure'] += 1
        print(sorted(stated.items()))
    names = ('labels-v5.tsv', 'agreed-v5.tsv') if v5 else ('extra-labels.tsv', 'agreed-extra.tsv')   # v5: all traits in one file
    if variant:
        names = (f'labels-v5-{variant}.tsv', f'agreed-v5-{variant}.tsv')
    with open(folder / names[0], 'w') as out, open(folder / names[1], 'w') as ag:
        out.write('taxon\tgenus\tfamily\ttrait\tallowed\trare\tsources\n')
        ag.write('taxon\ttrait\tvalue\tfloras\n')
        for (t, trait), cls in sorted(allowed.items()):
            if trait == 'leaflet_shape' or (trait == 'spines' and cls == {'present', 'absent'}):
                continue
            out.write(f"{t}\t{t.split()[0]}\t{family[t]}\t{trait}\t{'|'.join(sorted(cls))}\t"
                      f"{'|'.join(sorted(rare.get((t, trait), set()) - cls))}\t{'|'.join(sorted(by_src[t, trait]))}\n")
            count[trait] += 1
            for c in cls:
                count[trait, c] += 1
            single = [next(iter(s)) for s in by_src[t, trait].values() if len(s) == 1]
            if single and len(set(single)) == 1 and len(single) == len(by_src[t, trait]):
                ag.write(f'{t}\t{trait}\t{single[0]}\t{len(single)}\n')
                count[trait, 'agreed by 2+'] += len(single) >= 2
    for k, v in sorted(count.items(), key=str):
        print(k, v)
    if variant:
        (folder / names[1]).unlink()                           # the test species stay those of the standard labels
        return
    # sizes
    vals, srcs = collections.defaultdict(list), collections.defaultdict(set)
    ends = collections.defaultdict(lambda: ([], []))           # the stated range: lower and upper ends (log10)
    for r in csv.DictReader(open(folder / 'measures-all.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
        rule = RULES.get((r['entity'], r['quality']))
        if not rule or r['rank'] != 'species' or r['ctx']:
            continue
        lo = float(r['low_m']) if r['low_m'] else None
        hi = float(r['high_m']) if r['high_m'] else None
        if rule[1] == 'high':
            v = hi if hi is not None else lo
        else:
            v = math.sqrt(lo * hi) if lo and hi else (hi if hi is not None else lo)
        if v and 1e-4 <= v <= (130 if rule[0] == 'height' else 6):
            t = acc(r['taxon'])
            vals[t, rule[0]].append(math.log10(v)); srcs[t, rule[0]].add(r['source'])
            a, b = (lo, hi) if rule[1] == 'mid' and lo and hi and lo <= hi else (v, v)
            ends[t, rule[0]][0].append(math.log10(a)); ends[t, rule[0]][1].append(math.log10(b))
    if (folder / 'counts-all.tsv').exists():                   # extract_counts.py: log10 of the count, middle of a range
        for r in csv.DictReader(open(folder / 'counts-all.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
            k = COUNTS.get(r['entity'])
            if not k or r['rank'] != 'species' or r['ctx'] or r['frequency'] in RARE:
                continue
            if k == 'n_ray_flowers' and r['family'] not in ('Asteraceae', 'Compositae'):
                continue                                       # elsewhere "rays" are umbel stalks or hair arms (judge_extraction.py)
            lo = float(r['low']) if r['low'] else None
            hi = float(r['high']) if r['high'] else None
            v = (lo + hi) / 2 if lo is not None and hi is not None else (hi if hi is not None else lo)
            if 0.5 <= v <= 2000:
                t = acc(r['taxon'])
                vals[t, k].append(math.log10(v)); srcs[t, k].add(r['source'])
                a, b = (lo, hi) if lo is not None and hi is not None and 0.5 <= lo <= hi else (v, v)
                ends[t, k][0].append(math.log10(a)); ends[t, k][1].append(math.log10(b))
    med = {k: statistics.median(v) for k, v in vals.items()}
    factor = lambda t, trait: math.log10(statistics.mean(FACTOR[c] for c in allowed[t, trait]) if allowed.get((t, trait)) else 0.7)
    for t in {t for t, _ in med}:
        for part, shape in (('leaf', 'leaf_shape'), ('leaflet', 'leaflet_shape')):
            if (t, part + '_length') in med and (t, part + '_width') in med:
                med[t, part + '_area'] = med[t, part + '_length'] + med[t, part + '_width'] + factor(t, shape)
                vals[t, part + '_area'] = [0]; srcs[t, part + '_area'] = srcs[t, part + '_length'] | srcs[t, part + '_width']
    with open(folder / 'measure-labels-v3.tsv', 'w') as f:
        f.write('taxon\ttrait\tlog10_m\tstatements\tsources\tlow\thigh\n')
        for (t, k), v in sorted(med.items()):
            a, b = (statistics.median(ends[t, k][0]), statistics.median(ends[t, k][1])) if (t, k) in ends else (v, v)
            f.write(f'{t}\t{k}\t{v:.4f}\t{len(vals[t, k])}\t{len(srcs[t, k])}\t{min(a, v):.4f}\t{max(b, v):.4f}\n')
    print(sorted(collections.Counter(k for _, k in med).items()))


def ceiling(folder, try_file):
    """How well the flora's leaf area agrees with TRY's (Spearman over species with both), by reading."""
    import numpy as np
    folder = Path(folder)
    m = collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'measure-labels-v3.tsv'), delimiter='\t'):
        m[r['taxon']][r['trait']] = float(r['log10_m'])
    cx = {r['taxon']: r['allowed'] for r in csv.DictReader(open(folder / 'pilot-labels-v3.tsv'), delimiter='\t') if r['trait'] == 'leaf_complexity'}
    tr = {r['species']: math.log10(float(r['LeafArea'])) for r in csv.DictReader(open(try_file), delimiter='\t') if r['LeafArea'] not in ('', 'nan') and float(r['LeafArea']) > 0}
    rank = lambda v: np.argsort(np.argsort(v))
    readings = {'length x width (as before)': lambda d, t: d['leaf_length'] + d['leaf_width'] if 'leaf_length' in d and 'leaf_width' in d else None,
                'with shape factor': lambda d, t: d.get('leaf_area'),
                'leaflet where given': lambda d, t: d.get('leaflet_area', d.get('leaf_area')),
                'leaflet for compound leaves': lambda d, t: d.get('leaflet_area', d.get('leaf_area')) if 'compound' in cx.get(t, '') else d.get('leaf_area'),
                'whole leaf, else leaflet': lambda d, t: d.get('leaf_area', d.get('leaflet_area'))}
    for sub, keep in (('all species', lambda t: True), ('compound-leaved', lambda t: 'compound' in cx.get(t, '')), ('simple-leaved', lambda t: cx.get(t) == 'simple')):
        for name, f in readings.items():
            p = [(f(m[t], t), v) for t, v in tr.items() if t in m and keep(t)]
            p = [q for q in p if q[0] is not None]
            if len(p) > 20:
                a, b = zip(*p)
                print(f'{sub:16s} {name:28s} n={len(p):5d}  Spearman {np.corrcoef(rank(a), rank(b))[0, 1]:.3f}')


if __name__ == '__main__':
    {'labels': labels, 'ceiling': ceiling}[sys.argv[1]](*sys.argv[2:])
