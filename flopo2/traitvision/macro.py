"""Species-level tests of trait hypotheses with the flora values (no photographs, no iNaturalist data).

    python -m flopo2.traitvision.macro table     # applications/species-traits.tsv
    python -m flopo2.traitvision.macro island    # applications/island.json

``table``: one row per species with any flora value: family, tip in the seed-plant tree (Smith and Brown 2018), growth form, life
span, binary traits, log10 sizes and counts, climate of the native range (mean over WCVP botanical countries; the country
values are those of ``applications.py colour-data``), and whether all / none of its countries are isolated islands.
``island``: island endemics against mainland congeners (island rule, woodiness, spines, hairs), with a null from random
splits of the mainland species of the same genera.
"""
import collections, csv, json, re, sys
from pathlib import Path
import numpy as np

H = Path('local-corpora/trait-vision')
A = H / 'applications'
# botanical countries that are oceanic or long-isolated islands
ISLANDS = set('''ALD ASC ASP ATP AZO BER CGS CKI CNY COM COO CPI CRL CRZ CTM CVI DSV EAS FIJ GAL GGI GIL HAW HBI JNF KEG KER KZN LDV
LIN MAQ MAU MCI MCS MDG MDR MDV MPE MRN MRQ MRS NFK NRU NUE NWC NZN NZS OGA PHX PIT REU ROD SAM SCI SCZ SEL SEY SOC STH TDC TOK
TON TUA TUB TUV VAN WAK WAL XMS'''.split())
# other islands: a species that occurs on these is neither "island endemic" nor "mainland"
OTHER_ISLANDS = set('''ALU AND BAH BAL BIS BOR CAY CHH COR CUB CYP DOM EAI FAL FOR GNL GRB HAI ICE IRE JAM JAP JAW KRI KUR LEE LSI
MOL MXI NCB NFL NLA NNS NWG PHI PUE SAK SAR SCS SGE SIC SOL SRL SUL SUM SVA SWC TAI TAS TCI TRT VNA WIN ARU PEI'''.split())
SIZES = ['height', 'leaf_length', 'leaf_width', 'leaf_area', 'petal_length', 'flower_diameter', 'fruit_length', 'fruit_width',
         'seed_length', 'n_flowers', 'n_stamens', 'n_petals', 'n_seeds']
FLESHY, DRY = {'berry', 'drupe'}, {'capsule', 'achene', 'legume', 'nut', 'follicle', 'utricle', 'caryopsis', 'schizocarp', 'silique', 'samara'}


def table():
    country = {r['country']: r for r in csv.DictReader(open(A / 'colour-countries.tsv'), delimiter='\t')}
    labels, family = collections.defaultdict(dict), {}
    for r in csv.DictReader(open(H / 'labels-v5.tsv'), delimiter='\t'):
        labels[r['trait']][r['taxon']] = set(r['allowed'].split('|')); family[r['taxon']] = r['family']
    size = collections.defaultdict(dict)
    for r in csv.DictReader(open(H / 'measure-labels-v3.tsv'), delimiter='\t'):
        size[r['trait']][r['taxon']] = r['log10_m']
    csv.field_size_limit(10 ** 9)
    # sexual system, from the statements of the catalogue (not among the 26 traits of the photograph models)
    sex = collections.defaultdict(set)
    for r in csv.DictReader(open(H / 'pilot-assertions-v5.tsv'), delimiter='\t'):
        q = r['qlabel'].lower()
        if r['negated'] == '0' and r['rank'] == 'species':
            for k, v in (('dioecious', 'dioecious'), ('monoecious', 'monoecious'), ('hermaphrodit', 'bisexual'), ('bisexual', 'bisexual')):
                if k in q and 'gyno' not in q and 'andro' not in q and 'poly' not in q:
                    sex[r['taxon']].add(v)
    ids, fam2 = {}, {}
    for r in csv.DictReader(open('local-corpora/wcvp/raw/wcvp_names.csv'), delimiter='|', quoting=csv.QUOTE_NONE):
        if r['taxon_rank'] == 'Species' and r['taxon_status'] == 'Accepted':
            ids[r['plant_name_id']] = r['taxon_name']; fam2[r['taxon_name']] = r['family']
    dist = collections.defaultdict(set)
    for r in csv.DictReader(open('local-corpora/wcvp/raw/wcvp_distribution.csv'), delimiter='|', quoting=csv.QUOTE_NONE):
        if r['plant_name_id'] in ids and r['area_code_l3'] and r['introduced'] != '1' and r['extinct'] != '1' and r['location_doubtful'] != '1':
            dist[ids[r['plant_name_id']]].add(r['area_code_l3'].upper())
    tips = set(re.findall(r'[(,]([A-Z][a-z-]+_[a-z-]+):', open(A / 'phylo' / 'v0.1' / 'ALLMB.tre').read()))
    taxa = sorted(set(family) | {t for d in size.values() for t in d} | set(sex))
    keys = ('mat', 'logmap', 'elev', 'srad', 'abslat')

    def flag(trait, t, yes, no):
        v = labels[trait].get(t)
        return 'NA' if not v else '1' if v <= yes else '0' if v <= no else 'NA'
    n = 0
    with open(A / 'species-traits.tsv', 'w') as f:
        f.write('taxon\ttip\tgenus\tfamily\tgrowth\tannual\thairy\tspiny\tfleshy_fruit\tclimber\tsucculent\tdioecious\tsex\tpale_flower\t' + '\t'.join(SIZES) + '\t'
                + '\t'.join(keys) + '\tcountries\tisland\n')
        for t in taxa:
            if len(t.split()) != 2:
                continue
            h = labels['habit'].get(t, set())
            growth = 'climber' if 'climber' in h else 'herb' if h == {'herb'} else 'woody' if h and h <= {'tree', 'shrub'} else 'mixed' if h else 'NA'
            cs = dist.get(t, set())
            cl = [c for c in cs if c in country]
            clim = [f"{np.mean([float(country[c][k]) for c in cl]):.3f}" if cl else 'NA' for k in keys]
            island = 'NA' if not cs else 'endemic' if cs <= ISLANDS else 'mainland' if not cs & (ISLANDS | OTHER_ISLANDS) else 'other'
            tip = t.replace(' ', '_')
            row = [t, tip if tip in tips else 'NA', t.split()[0], family.get(t) or fam2.get(t, 'NA'), growth,
                   flag('life_span', t, {'annual'}, {'perennial', 'biennial'}), flag('leaf_hair', t, {'hairy'}, {'glabrous'}),
                   flag('spines', t, {'present'}, {'absent'}), flag('fruit_type', t, FLESHY, DRY),
                   '1' if 'climbing' in labels['posture'].get(t, set()) or 'climber' in h else '0' if h or t in labels['posture'] else 'NA',
                   flag('leaf_texture', t, {'fleshy'}, {'coriaceous', 'papery', 'membranous'}),
                   'NA' if len(sex.get(t, ())) != 1 else str(int(sex[t] == {'dioecious'})), '|'.join(sorted(sex.get(t, ()))) or 'NA',
                   flag('flower_colour', t, {'white', 'green'}, {'blue', 'purple', 'pink', 'red', 'orange', 'yellow'})]
            f.write('\t'.join(row + [size[k].get(t, 'NA') for k in SIZES] + clim + [str(len(cs)), island]) + '\n'); n += 1
    print('species', n)


def island(null=1000):
    """Island endemics against mainland congeners. For each genus with both: mean of the island endemics minus mean of the mainland
    species (log10 sizes; shares for binary traits). The island rule is a negative slope of the difference on the mainland mean;
    the same slope arises from sampling error alone, so the null splits the mainland species of each genus at random into a
    pseudo-island set of the same size as the real one (genera with enough mainland species)."""
    rows = list(csv.DictReader(open(A / 'species-traits.tsv'), delimiter='\t'))
    rng = np.random.default_rng(0)
    out = {}
    val = lambda r, k: (1.0 if r[k] == 'woody' else 0.0 if r[k] == 'herb' else None) if k == 'growth' else (None if r[k] == 'NA' else float(r[k]))
    for k in ['height', 'leaf_area', 'leaf_length', 'seed_length', 'fruit_length', 'petal_length', 'n_flowers', 'growth', 'spiny', 'hairy', 'fleshy_fruit', 'annual']:
        g = collections.defaultdict(lambda: {'endemic': [], 'mainland': []})
        for r in rows:
            v = val(r, k)
            if v is not None and r['island'] in ('endemic', 'mainland'):
                g[r['genus']][r['island']].append(v)
        g = {x: d for x, d in g.items() if d['endemic'] and d['mainland']}
        if len(g) < 20:
            continue
        m = np.array([np.mean(d['mainland']) for d in g.values()]); i = np.array([np.mean(d['endemic']) for d in g.values()])
        diff = i - m
        res = {'genera': len(g), 'island species': sum(len(d['endemic']) for d in g.values()), 'mainland species': sum(len(d['mainland']) for d in g.values()),
               'mean difference (island - mainland)': float(diff.mean()), 'share of genera with island larger': float((diff > 0).mean() + 0.5 * (diff == 0).mean())}
        boot = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(2000)]
        res['difference 95% interval'] = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
        # island rule with a null of the same sampling error
        ok = [d for d in g.values() if len(d['mainland']) >= len(d['endemic']) + 2]
        if len(ok) >= 20 and k not in ('growth', 'spiny', 'hairy', 'fleshy_fruit', 'annual'):
            def slope(pairs):
                a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
                return float(np.polyfit(a, b - a, 1)[0])
            real = slope([(np.mean(d['mainland']), np.mean(d['endemic'])) for d in ok])
            nul = []
            for _ in range(null):
                pairs = []
                for d in ok:
                    p = rng.permutation(d['mainland']); ne = len(d['endemic'])
                    pairs.append((p[ne:].mean(), p[:ne].mean()))
                nul.append(slope(pairs))
            res['island rule'] = {'genera': len(ok), 'slope of difference on mainland size': real, 'null slope mean': float(np.mean(nul)),
                                  'null 95% interval': [float(np.percentile(nul, 2.5)), float(np.percentile(nul, 97.5))],
                                  'p (slope below null)': float((np.array(nul) <= real).mean())}
            # small and large mainland genera separately (terciles of the mainland mean)
            q = np.quantile(m, [1 / 3, 2 / 3])
            res['difference by mainland size'] = {'small third': float(diff[m <= q[0]].mean()), 'middle third': float(diff[(m > q[0]) & (m <= q[1])].mean()),
                                                  'large third': float(diff[m > q[1]].mean())}
        out[k] = res
        print(k, json.dumps(res))
    (A / 'island.json').write_text(json.dumps(out, indent=1) + '\n')


if __name__ == '__main__':
    {'table': table, 'island': island}[sys.argv[1]]()
