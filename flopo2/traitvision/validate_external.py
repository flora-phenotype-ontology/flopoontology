"""Our flora labels and our predictions from photographs against trait data that other people curated.

References (used for testing only, never for training):
* Marcos et al. 2025 (github.com/konpanousis/AutomaticTraitExtraction): three hand-built species x trait matrices,
  West African savanna trees (Bonnet et al. 2005), Dutch Caribbean woody species, palms (Kissling et al. 2019);
* GIFT 3 (Weigelt et al.; public API, ``external/gift_fetch.py``): growth form, epiphytism, life cycle, deciduousness,
  fruit type, flower and fruit colour, leaf spines; maximum height, leaf length and width, fruit length and width.

Each reference value is mapped to one of our classes (tables below); a value without a counterpart is dropped, and a
trait is scored only over the classes the reference can express. Per reference and trait, over species with both:

* labels   our flora label (set of values) against the reference set: share of species whose sets share a value,
           and precision / recall / F1 over the values (micro);
* photos   the class with the highest mean probability over the species' photographs (model that saw no species of the
           genus): share inside the reference set, and balanced accuracy over species with one reference value;
* sizes    Spearman of the flora value and of the photograph prediction with the reference value.

    python -m flopo2.traitvision.validate_external local-corpora/trait-vision [baseline-v5]
"""
import collections
import csv
import gzip
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

COLOURS = ('white', 'yellow', 'red', 'pink', 'purple', 'blue', 'orange', 'green', 'brown', 'black')
WEST = {
    'plant type': ('habit', {'Tree': 'tree', 'Palm tree': 'tree', 'Shrub': 'shrub', 'Bush': 'shrub', 'Liana': 'climber', 'Herbaceous': 'herb'}),
    'phyllotaxis': ('leaf_arrangement', {'Phyllotaxis alternate': 'alternate', 'Opposite phyllotaxis': 'opposite', 'Phyllotaxis whorled': 'whorled'}),
    'stem shape': ('stem_shape', {'Circular stem section': 'terete', 'Square stem section': 'quadrangular'}),
    'leaf shape': ('leaf_complexity', {'Simple leaf': 'simple', 'Bifoliate leaf': 'compound', 'Trifoliate leaf': 'compound', 'Digitized leaf': 'compound',
                                       'Paripinnate leaf': 'compound', 'Unipinnate leaf with opposite leaflets': 'compound',
                                       'Imperipinnate leaf with alternate leaflets': 'compound', 'Bipinnate leaf': 'compound', 'Three-pinnate leaf': 'compound'}),
    'petiole': ('leaf_attachment', {'Sessile leaf': 'sessile', 'Petiolated leaf': 'petiolate'}),
    'leaf blade': ('leaf_shape', {'Linear leaf blade': 'linear', 'lanceolate blade': 'lanceolate', 'elliptical blade': 'elliptic', 'obovate blade': 'obovate', 'orbicular blade': 'round'}),
    'leaf margin': ('leaf_margin', {'Smooth leaf margin': 'entire', 'Margin of crenate leaf': 'toothed', 'Margin of toothed leaf': 'toothed'}),
    'leaf base': ('leaf_base', {'Leaf base attenuated': 'cuneate', 'Rounded leaf base': 'rounded', 'Leaf base cordate': 'cordate'}),
    'leaf apex': ('leaf_apex', {'Leaf apex sharp corner': 'acute', 'Leaf apex with wide corners': 'obtuse', 'Leaf apex acuminate': 'acuminate', 'Leaf apex apiculate': 'mucronate',
                                'Leaf apex mucronate': 'mucronate', 'Rounded leaf apex': 'obtuse', 'Leaf apex emarginated': 'emarginate'}),
    'spine': ('spines', {'Plant without spines': 'absent', '*': 'present'}),
    'fruit': ('fruit_type', {'Drupe, or drupe-like fruit': 'drupe', 'Berry, or berry-like fruit': 'berry', 'Capsule': 'capsule', 'Pod': 'legume', 'Follicle': 'follicle',
                             'Achene': 'achene', 'Winged fruit': 'samara'}),
    'inflorescences': ('inflorescence', {'Spike of flowers or inflorescences': 'spike', 'Rootlet or cluster of flowers or inflorescences': 'raceme',
                                         'Corymb of flowers or inflorescences': 'corymb', 'Umbel of flowers or inflorescences': 'umbel', 'Cyme of flowers or inflorescences': 'cyme',
                                         'Flower head': 'capitulum', 'Panicle of flowers or inflorescences': 'panicle'}),
    'sexuality': ('flower_position', {'Axillary sexuality': 'axillary', 'Terminal sexuality': 'terminal'}),
    'flower color': ('flower_colour', {'White flower': 'white', 'Pink coloured flower': 'pink', 'Red coloured flower': 'red', 'Yellow coloured flower': 'yellow', 'Green coloured flower': 'green'}),
}
TOKENS = {  # Caribbean and palm matrices: a cell is a comma-separated list; token -> our class
    'Life form': ('habit', {'liana': 'climber', 'tree': 'tree'}),
    'Leaf position': ('leaf_arrangement', {'alternate': 'alternate', 'opposite': 'opposite', 'whorls of 3': 'whorled'}),
    'Leaf shape': ('leaf_shape', {'elliptic': 'elliptic', 'lanceolate': 'lanceolate', 'obovate': 'obovate', 'ovate': 'ovate', 'linear': 'linear', 'round': 'round',
                                  'circular': 'round', 'heart-shaped': 'cordate', 'elongate': 'oblong'}),
    'Leaf margin': ('leaf_margin', {'crenate': 'toothed', 'serrate': 'toothed', 'entire': 'entire'}),
    'Leaf upper side': ('leaf_hair', {'glabrous': 'glabrous', 'pubescent': 'hairy'}),
    'Leaf lower side': ('leaf_hair', {'glabrous': 'glabrous', 'pubescent': 'hairy'}),
    'Thorns spines': ('spines', {'absent': 'absent', '*': 'present'}),
    'Inflorescence type': ('inflorescence', {'panicle': 'panicle', 'raceme': 'raceme', 'spike': 'spike', 'umbel': 'umbel', 'dichasium': 'cyme'}),
    'Petals corolla colour': ('flower_colour', {c: c for c in COLOURS}),
    'Fruit type': ('fruit_type', {'berry': 'berry', 'capsule': 'capsule', 'drupe': 'drupe', 'fleshy drupe': 'drupe', 'follicle': 'follicle', 'nutlet': 'nut', 'pod': 'legume'}),
    'Fruit shape': ('fruit_shape', {'globose': 'globose', 'elongate': 'elongate', 'linear': 'elongate', 'ovoid': 'ovoid', 'ellipsoid': 'ovoid', 'fusiform': 'elongate', 'rounded': 'globose'}),
    'Fruit colour': ('fruit_colour', {c: c for c in COLOURS}),
    'Fruit Colour': ('fruit_colour', {c: c for c in COLOURS}),
    'Fruit Shape': ('fruit_shape', {'globose': 'globose', 'elongate': 'elongate', 'ovoid': 'ovoid', 'ellipsoid': 'ovoid', 'fusiform': 'elongate', 'rounded': 'globose'}),
}
PALM_SIZES = {'Maximum Stem Height in Meters': ('height', 1.0), 'Average Fruit Length in Centimeters': ('fruit_length', 0.01), 'Average Fruit Width in Centimeters': ('fruit_width', 0.01)}
GIFT = {'1.2.1': ('habit', {'herb': 'herb', 'shrub': 'shrub', 'tree': 'tree'}),
        '1.3.1': ('substrate', {'obligatory': 'epiphytic', 'terrestrial': 'terrestrial'}),
        '2.1.1': ('life_span', {'annual': 'annual', 'biennial': 'biennial', 'perennial': 'perennial'}),
        '2.4.1': ('leaf_persistence', {'deciduous': 'deciduous', 'evergreen': 'evergreen'}),
        '3.16.1': ('fruit_type', {'achene': 'achene', 'berry': 'berry', 'baccate': 'berry', 'capsule': 'capsule', 'drupe': 'drupe', 'follicle': 'follicle', 'nut': 'nut',
                                  'pod': 'legume', 'schizocarp': 'schizocarp', 'siliqua': 'silique', 'utricle': 'utricle'}),
        '3.21.1': ('flower_colour', {**{c: c for c in COLOURS}, 'violet': 'purple'}),
        '3.22.1': ('fruit_colour', {**{c: c for c in COLOURS}, 'violet': 'purple'}),
        '4.13.1': ('spines', {'yes': 'present'})}
SHARED = re.compile(r'Flora of China|Flora Reipublicae Popularis Sinicae|PLANTS Database|West Tropical Africa|Zambesiaca|Tropical East Africa|'
                    r'Flora of North America|Malesiana|Flore du Gabon|Flora of Gabon|Guianas|Flora of Pakistan|Plants of the World Online|World Flora Online|'
                    r'GrassBase|ILDIS|Flora of Somalia|Flora of Zimbabwe|Cayman|Flora Neotropica|Illinois|Tibet|Flora of Iraq|Kew Bulletin|Silvics|'
                    r'African Plants|Flore d.Afrique Centrale|Central Africa|Korup|Flora of Missouri|Moss Flora|Flora of Chile|Flora of Taiwan|Flora of Nepal', re.I)
GIFT_SIZES = {'1.6.2': ('height', 1.0), '4.6.2': ('leaf_length', 0.01), '4.7.2': ('leaf_width', 0.01), '3.13.3': ('fruit_length', 0.01), '3.14.3': ('fruit_width', 0.01)}


def references(folder, acc):
    """-> cat[name][trait][species] = set of our classes; vocab[name][trait] = classes the reference can express;
    num[name][trait][species] = log10 metres."""
    cat = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(set)))
    vocab = collections.defaultdict(lambda: collections.defaultdict(set))
    num = collections.defaultdict(lambda: collections.defaultdict(dict))
    E = folder / 'external' / 'AutomaticTraitExtraction' / 'LLM' / 'Data' / 'DataFrames'
    for name, f in (('West Africa (Bonnet 2005)', 'DF_West.csv'), ('Caribbean (Marcos 2025)', 'DF_Caribbean.csv'), ('Palms (Kissling 2019)', 'DF_Palm.csv')):
        rows = list(csv.reader(open(E / f)))
        head, vals = rows[0], rows[1]
        for k in range(1, len(head)):
            if head[k] in WEST and name.startswith('West'):
                trait, m = WEST[head[k]]
                vocab[name][trait] |= set(m.values())
            elif head[k] in TOKENS and not name.startswith('West'):
                trait, m = TOKENS[head[k]]
                vocab[name][trait] |= set(m.values())
        for r in rows[3:]:
            sp = acc(r[0])
            for k in range(1, len(head)):
                cell = r[k].strip()
                if head[k] == 'Measurement' and vals[k] in PALM_SIZES and cell and float(cell) > 0:
                    trait, unit = PALM_SIZES[vals[k]]
                    num[name][trait][sp] = math.log10(float(cell) * unit)
                if cell != '1':
                    continue
                if name.startswith('West') and head[k] in WEST:
                    trait, m = WEST[head[k]]
                    c = m.get(vals[k], m.get('*'))
                    if c:
                        cat[name][trait][sp].add(c)
                elif not name.startswith('West') and head[k] in TOKENS:
                    trait, m = TOKENS[head[k]]
                    for tok in vals[k].split(','):
                        tok = tok.strip().lower()
                        c = m.get(tok) or next((v for w, v in m.items() if w != '*' and tok.split('-')[-1].split()[-1:] == [w]), None) or m.get('*')
                        if tok == 'absent' and trait == 'spines':
                            c = 'absent'
                        if c and tok not in ('not applicable',):
                            cat[name][trait][sp].add(c)
    G = folder / 'external' / 'gift'
    if (G / 'species.json').exists():
        species = {r['work_ID']: acc(r['work_species']) for r in json.load(open(G / 'species.json'))}
        # GIFT names the source of every value; sources that are also ours (the same flora, or the database
        # we read) are listed in gift-shared-references.tsv and left out of the "independent" variant
        shared = set()
        if (G / 'references.json').exists():
            with open(G / 'gift-shared-references.tsv', 'w') as f:
                f.write('ref_ID\treference\n')
                for r in json.load(open(G / 'references.json')):
                    if SHARED.search(r.get('ref_long') or ''):
                        shared.add(abs(int(r['ref_ID'])))
                        f.write(f"{r['ref_ID']}\t{(r.get('ref_long') or '')[:200]}\n")
        indep = lambda r: not any(x.strip().lstrip('-').isdigit() and int(x.strip().lstrip('-')) in shared for x in str(r.get('references') or '').split(','))
        for tid, (trait, m) in GIFT.items():
            if (G / f'trait-{tid}.json').exists():
                vocab['GIFT'][trait] |= set(m.values())
                for r in json.load(open(G / f'trait-{tid}.json')):
                    c = m.get(str(r['trait_value']).strip().lower())
                    if c and r['work_ID'] in species:
                        cat['GIFT'][trait][species[r['work_ID']]].add(c)
                        if indep(r):
                            vocab['GIFT, sources not among ours'][trait] |= set(m.values())
                            cat['GIFT, sources not among ours'][trait][species[r['work_ID']]].add(c)
        for tid, (trait, unit) in GIFT_SIZES.items():
            if (G / f'trait-{tid}.json').exists():
                for r in json.load(open(G / f'trait-{tid}.json')):
                    try:
                        v = float(r['trait_value']) * unit
                    except (TypeError, ValueError):
                        continue
                    if v > 0 and r['work_ID'] in species:
                        num['GIFT'][trait][species[r['work_ID']]] = math.log10(v)
                        if indep(r):
                            num['GIFT, sources not among ours'][trait][species[r['work_ID']]] = math.log10(v)
    return cat, vocab, num


def spearman(a, b):
    r = lambda v: np.argsort(np.argsort(np.asarray(v, float))).astype(float)
    return float(np.corrcoef(r(a), r(b))[0, 1])


def main(folder, run='baseline-v5'):
    folder = Path(folder)
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / 'taxon-names-v3.tsv'), delimiter='\t')}
    acc = lambda t: name.get(t) or ' '.join(t.replace('_', ' ').split()[:2])
    cat, vocab, num = references(folder, acc)
    ours = collections.defaultdict(dict)
    for f in ('labels-v5.tsv',) if (folder / 'labels-v5.tsv').exists() else ('pilot-labels-v3.tsv', 'extra-labels.tsv'):
        for r in csv.DictReader(open(folder / f), delimiter='\t'):
            ours[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    size = collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'measure-labels-v3.tsv'), delimiter='\t'):
        size[r['trait']][r['taxon']] = float(r['log10_m'])
    pred, psize = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in csv.DictReader(gzip.open(folder / run / 'species-pred.tsv.gz', 'rt'), delimiter='\t'):
        if '=' in r['values']:
            pred[r['trait']][r['taxon']] = {k: float(v) for k, v in (x.split('=') for x in r['values'].split(';'))}
        else:
            psize[r['trait']][r['taxon']] = float(r['values'])
    report = {}
    for ref in list(cat) + [k for k in num if k not in cat]:
        print(f'\n== {ref}')
        for trait in sorted(cat[ref]):
            V = vocab[ref][trait]
            R = cat[ref][trait]
            row = {'reference_species': len(R)}
            both = [(ours[trait][s] & V, R[s]) for s in R if s in ours[trait] and ours[trait][s] & V]
            if len(both) >= 10:
                tp = sum(len(a & b) for a, b in both)
                p, rc = tp / sum(len(a) for a, _ in both), tp / sum(len(b) for _, b in both)
                row['labels'] = {'n': len(both), 'compatible': sum(bool(a & b) for a, b in both) / len(both), 'precision': p, 'recall': rc, 'f1': 2 * p * rc / (p + rc) if p + rc else 0}
            ph = [(max(V & set(pred[trait][s]), key=pred[trait][s].get), R[s]) for s in R if s in pred[trait] and V & set(pred[trait][s])]
            if len(ph) >= 10:
                per = collections.defaultdict(list)
                for q, b in ph:
                    if len(b) == 1:
                        per[next(iter(b))].append(q in b)
                row['photos'] = {'n': len(ph), 'in_reference_set': sum(q in b for q, b in ph) / len(ph),
                                 'balanced_accuracy': float(np.mean([np.mean(v) for v in per.values() if len(v) >= 5])) if any(len(v) >= 5 for v in per.values()) else None,
                                 'classes': sum(len(v) >= 5 for v in per.values())}
            report[f'{ref} | {trait}'] = row
            l, q = row.get('labels'), row.get('photos')
            print(f"{trait:17s} " + (f"labels n={l['n']:6d} compatible {l['compatible']:.3f} P {l['precision']:.3f} R {l['recall']:.3f} F1 {l['f1']:.3f}" if l else 'labels -' + ' ' * 52)
                  + '   ' + (f"photos n={q['n']:6d} in set {q['in_reference_set']:.3f} balanced {q['balanced_accuracy'] if q['balanced_accuracy'] is None else round(q['balanced_accuracy'], 3)} ({q['classes']} classes)" if q else 'photos -'))
        for trait in sorted(num[ref]):
            R = num[ref][trait]
            a = [(size[trait][s], R[s]) for s in R if s in size[trait]]
            b = [(psize[trait][s], R[s]) for s in R if s in psize[trait]]
            row = {'labels': {'n': len(a), 'spearman': spearman(*zip(*a))} if len(a) >= 20 else None, 'photos': {'n': len(b), 'spearman': spearman(*zip(*b))} if len(b) >= 20 else None}
            report[f'{ref} | {trait}'] = row
            print(f"{trait:17s} " + (f"labels n={row['labels']['n']:6d} Spearman {row['labels']['spearman']:.3f}" if row['labels'] else 'labels -') + '   '
                  + (f"photos n={row['photos']['n']:6d} Spearman {row['photos']['spearman']:.3f}" if row['photos'] else 'photos -'))
    (folder / 'external-validation.json').write_text(json.dumps(report, indent=1) + '\n')




def compare(folder):
    """Our flora labels and the published LLM extraction of Marcos et al. 2025 (their ``summary.csv`` per data set, from web
    text) against the same three hand-built matrices, through the same mapping to our classes and with the same score.
    Per data set and trait: species with a value, precision / recall / F1 on each method's species and on the species both have.

        python -m flopo2.traitvision.validate_external compare local-corpora/trait-vision
    """
    folder = Path(folder)
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / 'taxon-names-v3.tsv'), delimiter='\t')}
    acc = lambda t: name.get(t) or ' '.join(t.replace('_', ' ').split()[:2])
    ours = collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'labels-v5.tsv'), delimiter='\t'):
        ours[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    E = folder / 'external' / 'AutomaticTraitExtraction' / 'LLM'
    low = lambda m: {k.lower(): (t, {a.lower(): c for a, c in v.items()}) for k, (t, v) in m.items()}

    def matrix(path, west):
        m = low(WEST if west else TOKENS)
        rows = list(csv.reader(open(path)))
        head, vals = [h.strip().lower() for h in rows[0]], [v.strip().lower() for v in rows[1]]
        out, vocab = collections.defaultdict(lambda: collections.defaultdict(set)), collections.defaultdict(set)
        for k in range(1, len(head)):
            if head[k] in m:
                vocab[m[head[k]][0]] |= set(m[head[k]][1].values())
        for r in rows[3:]:
            sp = acc(r[0])
            for k in range(1, min(len(head), len(r))):
                if r[k].strip() != '1' or head[k] not in m:
                    continue
                trait, mm = m[head[k]]
                if west:
                    cs = [mm.get(vals[k], mm.get('*'))]
                else:
                    cs = []
                    for tok in vals[k].split(','):
                        tok = tok.strip()
                        c = mm.get(tok) or next((v for w, v in mm.items() if w != '*' and tok.split('-')[-1].split()[-1:] == [w]), None) or mm.get('*')
                        if tok == 'absent' and trait == 'spines':
                            c = 'absent'
                        if tok != 'not applicable':
                            cs.append(c)
                for c in cs:
                    if c:
                        out[trait][sp].add(c)
        return out, vocab

    def prf(pairs):
        if len(pairs) < 10:
            return None
        tp = sum(len(a & b) for a, b in pairs)
        p, r = tp / sum(len(a) for a, _ in pairs), tp / sum(len(b) for _, b in pairs)
        return {'n': len(pairs), 'precision': p, 'recall': r, 'f1': 2 * p * r / (p + r) if p + r else 0.0}

    report, lines = {}, ['data set\ttrait\treference species\tMarcos: species\tMarcos: P\tMarcos: R\tMarcos: F1\tMarcos: macro F1\tours: species\tours: P\tours: R\tours: F1\tours: macro F1'
                         '\teither: species\tboth: species\tMarcos: F1 (both)\tours: F1 (both)\tours - Marcos (both), 95% interval']
    fmt = lambda s: '-' if s is None else f"{s['f1']:.3f}"
    full = lambda s, mc: '-\t-\t-\t-' if s is None else f"{s['precision']:.3f}\t{s['recall']:.3f}\t{s['f1']:.3f}\t" + ('-' if mc['f1'] is None else f"{mc['f1']:.3f}")
    rng = np.random.default_rng(0)

    def interval(pm, po):
        """Bootstrap over the species-trait pairs both methods have: F1 of ours minus F1 of theirs."""
        if len(pm) < 10:
            return '-'
        f1 = lambda pairs, idx: (lambda tp, na, nb: 2 * tp / (na + nb) if na + nb else 0.0)(
            sum(len(pairs[i][0] & pairs[i][1]) for i in idx), sum(len(pairs[i][0]) for i in idx), sum(len(pairs[i][1]) for i in idx))
        d = []
        for _ in range(1000):
            idx = rng.integers(0, len(pm), len(pm))
            d.append(f1(po, idx) - f1(pm, idx))
        lo, hi = np.percentile(d, [2.5, 97.5])
        return f'{f1(po, range(len(po))) - f1(pm, range(len(pm))):+.3f} ({lo:+.3f} to {hi:+.3f})'

    for ds, f in (('West Africa', 'West'), ('Caribbean', 'Caribbean'), ('Palms', 'Palm')):
        ref, vocab = matrix(E / 'Data' / 'DataFrames' / f'DF_{f}.csv', f == 'West')
        llm, _ = matrix(E / 'Results' / 'Mistral' / f / 'summary.csv', f == 'West')
        tot = collections.defaultdict(list)
        for trait in sorted(ref):
            V, R = vocab[trait], ref[trait]
            M = {s: llm[trait][s] & V for s in R if llm[trait].get(s, set()) & V}
            O = {s: ours[trait][s] & V for s in R if ours[trait].get(s, set()) & V}
            both = [s for s in M if s in O]
            row = {'reference_species': len(R), 'marcos': prf([(M[s], R[s]) for s in M]), 'ours': prf([(O[s], R[s]) for s in O]),
                   'marcos_both': prf([(M[s], R[s]) for s in both]), 'ours_both': prf([(O[s], R[s]) for s in both]),
                   'marcos_species': len(M), 'ours_species': len(O)}
            report[f'{ds} | {trait}'] = row
            for k, d in (('marcos', M), ('ours', O)):
                tot[k] += [(d[s], R[s]) for s in d]
                tot[k + '_both'] += [(d[s], R[s]) for s in both]
            tot['ref'] += list(R)
            pm, po = [(M[s], R[s]) for s in both], [(O[s], R[s]) for s in both]
            row['macro_marcos'], row['macro_ours'] = macro([(M[s], R[s]) for s in M], V), macro([(O[s], R[s]) for s in O], V)
            row['either_species'], row['difference_both'] = len(set(M) | set(O)), interval(pm, po)
            lines.append(f"{ds}\t{trait}\t{len(R)}\t{len(M)}\t{full(row['marcos'], row['macro_marcos'])}\t{len(O)}\t{full(row['ours'], row['macro_ours'])}\t{row['either_species']}"
                         f"\t{len(both)}\t{fmt(row['marcos_both'])}\t{fmt(row['ours_both'])}\t{row['difference_both']}")
        allrow = {k: prf(tot[k]) for k in ('marcos', 'ours', 'marcos_both', 'ours_both')}
        report[f'{ds} | ALL'] = dict(allrow, reference_pairs=len(tot['ref']))
        none = {'f1': None}
        diff = interval(tot['marcos_both'], tot['ours_both'])
        report[f'{ds} | ALL']['difference_both'] = diff
        lines.append(f"{ds}\tALL (species-trait pairs)\t{len(tot['ref'])}\t{len(tot['marcos'])}\t{full(allrow['marcos'], none)}\t{len(tot['ours'])}\t{full(allrow['ours'], none)}\t-\t"
                     f"{len(tot['marcos_both'])}\t{fmt(allrow['marcos_both'])}\t{fmt(allrow['ours_both'])}\t{diff}")
    (folder / 'external-comparison.tsv').write_text('\n'.join(lines) + '\n')
    (folder / 'external-comparison.json').write_text(json.dumps(report, indent=1) + '\n')
    print('\n'.join(lines))


def macro(pairs, classes):
    """Per class precision, recall, F1 over (ours, reference) sets, and their means (the measure of Domazetoski et al. 2025)."""
    rows = {}
    for c in sorted(classes):
        tp = sum(c in a and c in b for a, b in pairs)
        na, nb = sum(c in a for a, _ in pairs), sum(c in b for _, b in pairs)
        if nb >= 5:
            p, r = (tp / na if na else 0.0), tp / nb
            rows[c] = {'precision': p, 'recall': r, 'f1': 2 * p * r / (p + r) if p + r else 0.0, 'reference': nb}
    mean = lambda k: float(np.mean([v[k] for v in rows.values()])) if rows else None
    return {'n': len(pairs), 'precision': mean('precision'), 'recall': mean('recall'), 'f1': mean('f1'), 'classes': rows}


def gift_compare(folder):
    """Our flora labels against GIFT on the traits of Domazetoski et al. 2025 (growth form, epiphyte, climber, life cycle;
    plant height, leaf length, leaf width), with their measures: macro precision / recall / F1 over the classes, and for
    sizes the mean absolute error of the log value over the range of the log values. Their models were trained on GIFT
    values and tested on held-out descriptions; ours never saw GIFT.

        python -m flopo2.traitvision.validate_external gift local-corpora/trait-vision
    """
    folder = Path(folder)
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / 'taxon-names-v3.tsv'), delimiter='\t')}
    acc = lambda t: name.get(t) or ' '.join(t.replace('_', ' ').split()[:2])
    ours, src = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'labels-v5.tsv'), delimiter='\t'):
        ours[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    size = collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'measure-labels-v3.tsv'), delimiter='\t'):
        size[r['trait']][r['taxon']] = float(r['log10_m'])
    G = folder / 'external' / 'gift'
    species = {r['work_ID']: acc(r['work_species']) for r in json.load(open(G / 'species.json'))}
    shared = {abs(int(r['ref_ID'])) for r in json.load(open(G / 'references.json')) if SHARED.search(r.get('ref_long') or '')}
    indep = lambda r: not any(x.strip().lstrip('-').isdigit() and int(x.strip().lstrip('-')) in shared for x in str(r.get('references') or '').split(','))
    climb = {}
    for t in set(ours['habit']) | set(ours['posture']):
        h, p = ours['habit'].get(t, set()), ours['posture'].get(t, set())
        if 'climber' in h or 'climbing' in p:
            climb[t] = {'climber'} | ({'self-supporting'} if (h - {'climber'}) and 'climbing' not in p and False else set())
        elif h:
            climb[t] = {'self-supporting'}
    TR = {'growth form': ('1.2.1', {'herb': 'herb', 'shrub': 'shrub', 'tree': 'tree'}, {t: s & {'herb', 'shrub', 'tree'} for t, s in ours['habit'].items()}),
          'epiphyte': ('1.3.1', {'obligatory': 'epiphytic', 'terrestrial': 'terrestrial'}, ours['substrate']),
          'climber': ('1.4.1', {'obligatory': 'climber', 'self-supporting': 'self-supporting'}, climb),
          'life cycle': ('2.1.1', {'annual': 'annual', 'perennial': 'perennial'}, {t: s & {'annual', 'perennial'} for t, s in ours['life_span'].items()})}
    report = {}
    print('trait\treference\tspecies\tmacro precision\tmacro recall\tmacro F1\tper class F1')
    for trait, (tid, m, mine) in TR.items():
        ref = {'GIFT, all sources': collections.defaultdict(set), 'GIFT, sources not among ours': collections.defaultdict(set)}
        for r in json.load(open(G / f'trait-{tid}.json')):
            c = m.get(str(r['trait_value']).strip().lower())
            if c and r['work_ID'] in species:
                ref['GIFT, all sources'][species[r['work_ID']]].add(c)
                if indep(r):
                    ref['GIFT, sources not among ours'][species[r['work_ID']]].add(c)
        for rn, R in ref.items():
            pairs = [(mine[s], R[s]) for s in R if mine.get(s)]
            row = macro(pairs, set(m.values()))
            report[f'{trait} | {rn}'] = row
            print(f"{trait}\t{rn}\t{row['n']}\t{row['precision']:.3f}\t{row['recall']:.3f}\t{row['f1']:.3f}\t" + ', '.join(f"{c} {v['f1']:.3f}" for c, v in row['classes'].items()))
    for trait, (tid, unit) in {'height': ('1.6.2', 1.0), 'leaf_length': ('4.6.2', 0.01), 'leaf_width': ('4.7.2', 0.01)}.items():
        for rn, keep in (('GIFT, all sources', lambda r: True), ('GIFT, sources not among ours', indep)):
            pairs = []
            for r in json.load(open(G / f'trait-{tid}.json')):
                try:
                    v = float(r['trait_value']) * unit
                except (TypeError, ValueError):
                    continue
                s = species.get(r['work_ID'])
                if v > 0 and s in size[trait] and keep(r):
                    pairs.append((size[trait][s], math.log10(v)))
            a, b = np.array(pairs).T
            row = {'n': len(pairs), 'nmae_log': float(np.abs(a - b).mean() / (b.max() - b.min())), 'median_factor': float(10 ** np.median(np.abs(a - b))), 'spearman': spearman(a, b)}
            report[f'{trait} | {rn}'] = row
            print(f"{trait}\t{rn}\t{row['n']}\tnMAE of log {row['nmae_log']:.3f}\tmedian factor {row['median_factor']:.2f}\tSpearman {row['spearman']:.3f}")
    (folder / 'external-comparison-gift.json').write_text(json.dumps(report, indent=1) + '\n')


AUS = {  # AusTraits trait -> (our trait, their token -> shared class, our class -> shared class)
    'plant_growth_form': ('habit', {'herb': 'herb', 'graminoid': 'herb', 'tussock': 'herb', 'shrub': 'shrub', 'subshrub': 'shrub', 'tree': 'tree', 'mallee': 'tree',
                                    'climber_herbaceous': 'climber', 'climber_woody': 'climber', 'climber': 'climber'}, None),
    'life_history': ('life_span', {'annual': 'annual', 'ephemeral': 'annual', 'biennial': 'biennial', 'perennial': 'perennial', 'short_lived_perennial': 'perennial'}, None),
    'fruit_type': ('fruit_type', {k: k for k in ('capsule', 'legume', 'caryopsis', 'follicle', 'drupe', 'achene', 'nut', 'berry', 'utricle', 'silique', 'samara', 'schizocarp')}, None),
    'leaf_compoundness': ('leaf_complexity', {'simple': 'simple', 'compound': 'compound'}, None),
    'leaf_shape': ('leaf_shape', {'linear': 'linear', 'elliptical': 'elliptic', 'narrowly_elliptical': 'elliptic', 'broadly_elliptical': 'elliptic', 'ovate': 'ovate',
                                  'lanceolate': 'lanceolate', 'oblanceolate': 'lanceolate', 'obovate': 'obovate', 'oblong': 'oblong', 'cordate': 'cordate',
                                  'orbicular': 'round', 'circular': 'round'}, None),
    'leaf_margin': ('leaf_margin', {'entire': 'entire', 'toothed': 'toothed', 'toothed_dentate': 'toothed', 'toothed_serrate': 'toothed', 'toothed_crenate': 'toothed', 'lobed': 'lobed'}, None),
    'leaf_phyllotaxis': ('leaf_arrangement', {'alternate': 'alternate', 'opposite': 'opposite', 'whorled': 'whorled'}, None),
    'leaf_phenology': ('leaf_persistence', {'evergreen': 'evergreen', 'deciduous': 'deciduous'}, None),
    'flower_colour': ('flower_colour', {'white_cream': 'white', 'yellow_orange': 'yellow-orange', 'blue_purple': 'blue-purple', 'red_brown': 'red-brown', 'green': 'green', 'pink': 'pink'},
                      {'white': 'white', 'yellow': 'yellow-orange', 'orange': 'yellow-orange', 'blue': 'blue-purple', 'purple': 'blue-purple', 'red': 'red-brown', 'brown': 'red-brown',
                       'green': 'green', 'pink': 'pink'}),
    'fruit_colour': ('fruit_colour', {k: k for k in COLOURS}, None),
    'leaf_base_shape': ('leaf_base', {'attenuate': 'cuneate', 'cuneate': 'cuneate', 'cordate': 'cordate', 'rounded': 'rounded', 'obtuse': 'rounded', 'truncate': 'truncate'}, None),
    'leaf_hairs_adult_leaves': ('leaf_hair', {'glabrous': 'glabrous', 'hairy': 'hairy'}, None),
    'plant_growth_substrate': ('substrate', {'terrestrial': 'terrestrial', 'epiphyte': 'epiphytic'}, None),
    'plant_physical_defence_structures': ('spines', {'absent': 'absent', 'sharp_pointed_defence': 'present', 'thorn': 'present', 'spine': 'present', 'prickle': 'present'}, None),
    'stem_growth_habit': ('posture', {'erect': 'erect', 'prostrate': 'prostrate', 'decumbent': 'ascending', 'ascending': 'ascending', 'climbing': 'climbing', 'twining': 'climbing'}, None),
}
AUS_SIZES = {'plant_height': ('height', 'max'), 'leaf_length': ('leaf_length', 'mid'), 'leaf_width': ('leaf_width', 'mid'), 'fruit_length': ('fruit_length', 'mid'),
             'fruit_width': ('fruit_width', 'mid'), 'seed_length': ('seed_length', 'mid')}
UNIT = {'mm': 1e-3, 'cm': 1e-2, 'm': 1.0}


def austraits(folder, run='baseline-v6/s0'):
    """Our flora values and our predictions from photographs (unseen genera) against AusTraits v7.0.0 (Falster et al.; values
    scored by botanists from the Australian floras and field data; none of its sources is among our floras).

        python -m flopo2.traitvision.validate_external austraits local-corpora/trait-vision [RUN]
    """
    folder = Path(folder)
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(folder / 'taxon-names-v3.tsv'), delimiter='\t')}
    acc = lambda t: name.get(t) or ' '.join(t.replace('_', ' ').split()[:2])
    ours, srcs = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'labels-v5.tsv'), delimiter='\t'):
        ours[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    size = collections.defaultdict(dict)
    for r in csv.DictReader(open(folder / 'measure-labels-v3.tsv'), delimiter='\t'):
        size[r['trait']][r['taxon']] = float(r['log10_m'])
    pred, psize = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in csv.DictReader(gzip.open(folder / run / 'species-pred.tsv.gz', 'rt'), delimiter='\t'):
        if '=' in r['values']:
            pred[r['trait']][r['taxon']] = {k: float(v) for k, v in (x.split('=') for x in r['values'].split(';'))}
        else:
            psize[r['trait']][r['taxon']] = float(r['values'])
    ref = collections.defaultdict(lambda: collections.defaultdict(set))
    num = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in csv.DictReader(open(folder / 'external' / 'austraits' / 'data' / 'austraits-7.0.0' / 'traits.csv', encoding='latin-1')):
        t = r['trait_name']
        if len(r['taxon_name'].split()) < 2:
            continue
        sp = acc(' '.join(r['taxon_name'].split()[:2]))
        if t in AUS:
            for tok in r['value'].split():
                c = AUS[t][1].get(tok)
                if c:
                    ref[t][sp].add(c)
        elif t in AUS_SIZES and r['unit'] in UNIT:
            try:
                v = float(r['value']) * UNIT[r['unit']]
            except ValueError:
                continue
            if v > 0:
                num[t][sp].append((r['value_type'], v))
    report = {}
    print('trait\tAusTraits species\tfloras: species\tP\tR\tF1\tmacro F1\tphotographs: species\tin the set\tbalanced accuracy\tclasses')
    for t, (trait, rm, om) in AUS.items():
        R = ref[t]
        V = set(rm.values())
        conv = (lambda s: {om[c] for c in s if c in om}) if om else (lambda s: set(s) & V)
        pairs = [(conv(ours[trait][s]), R[s]) for s in R if s in ours[trait] and conv(ours[trait][s])]
        row = {'reference_species': len(R)}
        if len(pairs) >= 10:
            tp = sum(len(a & b) for a, b in pairs)
            p, rc = tp / sum(len(a) for a, _ in pairs), tp / sum(len(b) for _, b in pairs)
            row['floras'] = {'n': len(pairs), 'precision': p, 'recall': rc, 'f1': 2 * p * rc / (p + rc), 'macro_f1': macro(pairs, V)['f1']}
        ph = []
        for s in R:
            if s in pred[trait]:
                q = collections.Counter()
                for c, v in pred[trait][s].items():
                    k = om.get(c) if om else (c if c in V else None)
                    if k:
                        q[k] += v
                if q:
                    ph.append((max(q, key=q.get), R[s]))
        if len(ph) >= 10:
            per = collections.defaultdict(list)
            for g, b in ph:
                if len(b) == 1:
                    per[next(iter(b))].append(g in b)
            big = [np.mean(v) for v in per.values() if len(v) >= 5]
            row['photographs'] = {'n': len(ph), 'in_reference_set': sum(g in b for g, b in ph) / len(ph), 'balanced_accuracy': float(np.mean(big)) if big else None, 'classes': len(big)}
        report[t] = row
        f, q = row.get('floras'), row.get('photographs')
        print(f"{t}\t{len(R)}\t" + (f"{f['n']}\t{f['precision']:.3f}\t{f['recall']:.3f}\t{f['f1']:.3f}\t{f['macro_f1']:.3f}" if f else '-\t-\t-\t-\t-') + '\t'
              + (f"{q['n']}\t{q['in_reference_set']:.3f}\t{q['balanced_accuracy']:.3f}\t{q['classes']}" if q and q['balanced_accuracy'] is not None else '-\t-\t-\t-'))
    print('\nsize\tAusTraits species\tfloras: species\tSpearman\tmedian factor\tphotographs: species\tSpearman')
    for t, (k, how) in AUS_SIZES.items():
        R = {}
        for s, vals in num[t].items():
            mx = [v for ty, v in vals if ty == 'maximum']; mn = [v for ty, v in vals if ty == 'minimum']; other = [v for ty, v in vals if ty not in ('maximum', 'minimum')]
            if how == 'max':
                v = max(mx or other or mn)
            else:
                v = math.sqrt(np.median(mn) * np.median(mx)) if mn and mx else float(np.median(mx or other or mn))
            R[s] = math.log10(v)
        a = [(size[k][s], R[s]) for s in R if s in size[k]]
        b = [(psize[k][s], R[s]) for s in R if s in psize[k]]
        row = {'reference_species': len(R), 'floras': {'n': len(a), 'spearman': spearman(*zip(*a)), 'median_factor': float(10 ** np.median([abs(x - y) for x, y in a]))} if len(a) >= 20 else None,
               'photographs': {'n': len(b), 'spearman': spearman(*zip(*b))} if len(b) >= 20 else None}
        report[t] = row
        print(f"{t}\t{len(R)}\t" + (f"{row['floras']['n']}\t{row['floras']['spearman']:.3f}\t{row['floras']['median_factor']:.2f}" if row['floras'] else '-\t-\t-') + '\t'
              + (f"{row['photographs']['n']}\t{row['photographs']['spearman']:.3f}" if row['photographs'] else '-\t-'))
    (folder / 'external-austraits.json').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    modes = {'compare': compare, 'gift': gift_compare, 'austraits': austraits}
    modes[sys.argv[1]](*sys.argv[2:]) if sys.argv[1] in modes else main(*sys.argv[1:])
