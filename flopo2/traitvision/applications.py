"""Three uses of the trait predictions and the flora values (results under ``local-corpora/trait-vision/applications/``).

``climate``  known relations between traits and climate, on 2-degree cells of the iNaturalist observations: the share of
             species with a trait (or their mean size) against the cell's climate (WorldClim 2.1, 10 arc-minutes), once
             from the flora values of the species seen in the cell, once from the photographs of the observations made
             in the cell (predictions for unseen genera), and once from photographs of species that have no flora value.
``within``   variation inside species: the slope of a predicted size on climate over the observations of one species,
             against the slope between species; and, for traits that observers record, whether the prediction follows
             the observer's value among observations of the same species (``field-pred-<trait>.npz``).
``gaps``     what the floras and the photographs add to GIFT: species with a value per trait, and the number of new
             values from photographs at a stated precision (measured on species where two floras agree).

    python -m flopo2.traitvision.applications climate|within|gaps [RUN default baseline-v6/s0]
"""
import collections
import csv
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np

H = Path('local-corpora/trait-vision')
A = H / 'applications'
NOT_DICOT = {'Poaceae', 'Gramineae', 'Cyperaceae', 'Juncaceae', 'Arecaceae', 'Palmae', 'Orchidaceae', 'Liliaceae', 'Asparagaceae', 'Amaryllidaceae',
             'Iridaceae', 'Araceae', 'Bromeliaceae', 'Zingiberaceae', 'Musaceae', 'Commelinaceae', 'Dioscoreaceae', 'Smilacaceae', 'Pandanaceae',
             'Asphodelaceae', 'Xanthorrhoeaceae', 'Typhaceae', 'Restionaceae', 'Marantaceae', 'Cannaceae', 'Heliconiaceae', 'Strelitziaceae',
             'Alismataceae', 'Potamogetonaceae', 'Hydrocharitaceae', 'Melanthiaceae', 'Colchicaceae', 'Alstroemeriaceae', 'Costaceae', 'Agavaceae',
             'Pinaceae', 'Cupressaceae', 'Podocarpaceae', 'Araucariaceae', 'Taxaceae', 'Cycadaceae', 'Zamiaceae', 'Ephedraceae', 'Gnetaceae', 'Ginkgoaceae'}


def climate_grids():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    g = {}
    for k, b in (('mat', 1), ('map', 12), ('season', 4), ('dry', 14)):
        a = np.array(Image.open(A / 'worldclim' / f'wc2.1_10m_bio_{b}.tif')).astype(np.float32)
        a[a < -1e30] = np.nan
        g[k] = a
    return g


def load(run):
    z = np.load(A / 'obs-pred.npz') if run == 'baseline-v6/s0' else np.load(H / run / 'obs-pred.npz')
    lat, lon = z['lat'], z['lon']
    ok = ~np.isnan(lat) & ~np.isnan(lon)
    g = climate_grids()
    r = np.clip(((90 - lat) * 6).astype(int), 0, 1079); c = np.clip(((lon + 180) * 6).astype(int), 0, 2159)
    r[~ok] = 0; c[~ok] = 0
    clim = {k: np.where(ok, a[r, c], np.nan) for k, a in g.items()}
    labels, family = collections.defaultdict(dict), {}
    for row in csv.DictReader(open(H / 'labels-v5.tsv'), delimiter='\t'):
        labels[row['trait']][row['taxon']] = set(row['allowed'].split('|'))
        family[row['taxon']] = row['family']
    size = collections.defaultdict(dict)
    for row in csv.DictReader(open(H / 'measure-labels-v3.tsv'), delimiter='\t'):
        size[row['trait']][row['taxon']] = float(row['log10_m'])
    return z, clim, labels, family, size


def fit(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~np.isnan(x) & ~np.isnan(y)
    x, y = x[ok], y[ok]
    if len(x) < 10:
        return None
    b, a = np.polyfit(x, y, 1)
    rk = lambda v: np.argsort(np.argsort(v)).astype(float)
    return {'cells': int(len(x)), 'slope': float(b), 'intercept': float(a), 'r': float(np.corrcoef(x, y)[0, 1]), 'spearman': float(np.corrcoef(rk(x), rk(y))[0, 1])}


def climate(run='baseline-v6/s0', min_species=20):
    z, clim, labels, family, size = load(run)
    taxon = z['taxon']
    names, tinv = np.unique(taxon, return_inverse=True)
    cell = (np.floor(z['lat'] / 2).astype(int) + 45) * 180 + (np.floor(z['lon'] / 2).astype(int) + 90)
    valid = ~np.isnan(clim['mat'])
    cl = lambda t: [str(c) for c in z['c_' + t]]
    # species-level habit: flora value, else the mean prediction
    hab_c = cl('habit'); hp = np.zeros((len(names), len(hab_c))); np.add.at(hp, tinv, z['p_habit'].astype(np.float32))
    woody_pred = np.isin(np.array(hab_c)[hp.argmax(1)], ('tree', 'shrub'))
    woody = np.array([(bool(labels['habit'][t] & {'tree', 'shrub'}) and 'herb' not in labels['habit'][t]) if t in labels['habit'] else woody_pred[n] for n, t in enumerate(names)])
    herb = np.array([labels['habit'][t] == {'herb'} if t in labels['habit'] else np.array(hab_c)[hp[n].argmax()] == 'herb' for n, t in enumerate(names)])
    dicot = np.array([family.get(t, '') not in NOT_DICOT for t in names])
    every = np.ones(len(names), bool)

    def share(trait, value):                                   # (flora value per species or nan, prediction per observation)
        c = cl(trait)
        fl = np.array([(len(labels[trait][t] & {value}) / len(labels[trait][t])) if t in labels[trait] else np.nan for t in names])
        return fl, z['p_' + trait][:, c.index(value)].astype(np.float32)

    def measure(k, k2=None):
        sn = [str(s) for s in z['size_names']]
        fl = np.array([size[k].get(t, np.nan) + (size[k2].get(t, np.nan) if k2 else 0) for t in names])
        pr = z['sizes'][:, sn.index(k)] + (z['sizes'][:, sn.index(k2)] if k2 else 0)
        return fl, pr

    tests = [('entire leaf margin, woody dicots', share('leaf_margin', 'entire'), woody & dicot, 'mat', 'mean annual temperature (C)', '+', 'leaf margin analysis: about +0.03 per degree'),
             ('leaf area (log10 length x width, m2)', measure('leaf_length', 'leaf_width'), every, 'mat', 'mean annual temperature (C)', '+', 'larger leaves in warm, wet places'),
             ('leaf area (log10 length x width, m2)', measure('leaf_length', 'leaf_width'), every, 'logmap', 'log10 annual precipitation (mm)', '+', 'larger leaves in warm, wet places'),
             ('plant height (log10 m)', measure('height'), every, 'mat', 'mean annual temperature (C)', '+', 'taller plants towards the tropics'),
             ('plant height (log10 m)', measure('height'), every, 'logmap', 'log10 annual precipitation (mm)', '+', 'taller plants in wet places'),
             ('spines present, woody species', share('spines', 'present'), woody, 'logmap', 'log10 annual precipitation (mm)', '-', 'more spiny plants in dry places'),
             ('annual, herbs', share('life_span', 'annual'), herb, 'logmap', 'log10 annual precipitation (mm)', '-', 'more annuals in dry places'),
             ('annual, herbs', share('life_span', 'annual'), herb, 'mat', 'mean annual temperature (C)', '+', 'more annuals in hot places'),
             ('compound leaves, woody dicots', share('leaf_complexity', 'compound'), woody & dicot, 'mat', 'mean annual temperature (C)', '+', 'more compound leaves in warm places'),
             ('evergreen, woody species', share('leaf_persistence', 'evergreen'), woody, 'season', 'temperature seasonality (sd x 100)', '-', 'fewer evergreens where seasons are strong'),
             ('epiphytic', share('substrate', 'epiphytic'), every, 'logmap', 'log10 annual precipitation (mm)', '+', 'more epiphytes in wet places'),
             ('succulent or fleshy leaves', share('leaf_texture', 'fleshy'), every, 'logmap', 'log10 annual precipitation (mm)', '-', 'more succulents in dry places')]
    cv = dict(clim, logmap=np.log10(np.maximum(clim['map'], 10)))
    report, lines = {}, ['trait\tclimate\texpected\tsource\tcells\tslope\tr\tSpearman']
    cells, cinv = np.unique(cell[valid], return_inverse=True)
    vi = np.flatnonzero(valid)
    for name, (fl, pr), keep, var, vname, sign, note in tests:
        x = np.zeros(len(cells)); np.add.at(x, cinv, cv[var][vi]); x /= np.bincount(cinv)
        # one value per (cell, species): flora value; mean prediction over the observations of the species in the cell
        pair, pinv = np.unique(cinv.astype(np.int64) * len(names) + tinv[vi], return_inverse=True)
        pc, ps = pair // len(names), pair % len(names)
        pm = np.zeros(len(pair)); np.add.at(pm, pinv, pr[vi].astype(np.float64)); pm /= np.bincount(pinv)
        row = {}
        for src, val, sel in (('floras', fl[ps], keep[ps] & ~np.isnan(fl[ps])), ('photographs', pm, keep[ps]),
                              ('photographs, species without a flora value', pm, keep[ps] & np.isnan(fl[ps]))):
            tot = np.zeros(len(cells)); cnt = np.zeros(len(cells))
            np.add.at(tot, pc[sel], val[sel]); np.add.at(cnt, pc[sel], 1)
            need = min_species if 'without' not in src else 10
            y = np.where(cnt >= need, tot / np.maximum(cnt, 1), np.nan)
            row[src] = fit(x, y)
            if row[src]:
                row[src]['species_cell_pairs'] = int(sel.sum())
                lines.append(f"{name}\t{vname}\t{sign} ({note})\t{src}\t{row[src]['cells']}\t{row[src]['slope']:+.4f}\t{row[src]['r']:+.3f}\t{row[src]['spearman']:+.3f}")
                if src != 'floras' and name.startswith('entire'):
                    np.savez(A / f"cells-{src.split(',')[0]}-{'nofl' if 'without' in src else 'all'}.npz", x=x, y=y)
        report[f'{name} | {vname}'] = dict(row, expected=sign, note=note)
    (A / 'climate.json').write_text(json.dumps(report, indent=1) + '\n')
    (A / 'climate.tsv').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def within(run='baseline-v6/s0', min_obs=30):
    z, clim, labels, family, size = load(run)
    names, tinv = np.unique(z['taxon'], return_inverse=True)
    sn = [str(s) for s in z['size_names']]
    cv = {'mean annual temperature (C)': clim['mat'], 'log10 annual precipitation (mm)': np.log10(np.maximum(clim['map'], 10))}
    order = np.argsort(tinv, kind='stable'); start = np.r_[0, np.flatnonzero(np.diff(tinv[order])) + 1, len(order)]
    report, rng = {}, np.random.default_rng(0)
    print('size\tclimate\tspecies\tmedian slope within species\tshare of slopes > 0\tslope between species (predicted)\tslope between species (floras)')
    for k, k2 in (('leaf_length', 'leaf_width'), ('height', None), ('leaf_length', None), ('flower_diameter', None), ('fruit_length', None)):
        y = z['sizes'][:, sn.index(k)] + (z['sizes'][:, sn.index(k2)] if k2 else 0)
        for vname, x in cv.items():
            slopes, mx, my, mf = [], [], [], []
            for n in range(len(names)):
                idx = order[start[n]:start[n + 1]]
                idx = idx[~np.isnan(x[idx])]
                if len(idx) < min_obs:
                    continue
                xs, ys = x[idx].astype(float), y[idx].astype(float)
                mx.append(xs.mean()); my.append(ys.mean())
                mf.append(size[k].get(names[n], np.nan) + (size[k2].get(names[n], np.nan) if k2 else 0))
                if xs.std() >= (3.0 if 'temperature' in vname else 0.15):       # the species spans a real range of climate
                    slopes.append(np.polyfit(xs, ys, 1)[0])
            slopes = np.array(slopes)
            between = fit(mx, my); bf = fit(mx, mf)
            null = []
            row = {'species': int(len(slopes)), 'median_within': float(np.median(slopes)), 'share_positive': float((slopes > 0).mean()),
                   'between_predicted': between['slope'], 'between_floras': bf['slope'] if bf else None}
            report[f"{k}{'+' + k2 if k2 else ''} | {vname}"] = row
            print(f"{k}{' x ' + k2 if k2 else ''}\t{vname}\t{row['species']}\t{row['median_within']:+.4f}\t{row['share_positive']:.3f}\t{row['between_predicted']:+.4f}\t" + (f"{row['between_floras']:+.4f}" if bf else '-'))
    # observers' values within species
    print('\ntrait\tspecies with 2+ observed values\tobservations\tprediction follows the observer\tsame after shuffling observers within species\tmost common value of the species')
    for f in sorted((H / Path(run).parent / 'field').glob('field-pred-*.npz')):
        q = np.load(f)
        trait = f.name[11:-4]
        classes = [str(c) for c in q['classes']]
        by = collections.defaultdict(list)
        for n, t in enumerate(q['taxon']):
            by[str(t)].append(n)
        hit = tot = base = 0
        shuf = []
        groups = []
        for t, idx in by.items():
            vals = [str(q['value'][i]) for i in idx]
            seen = sorted(set(vals))
            if len(seen) < 2 or len(idx) < 4:
                continue
            cols = [classes.index(v) for v in seen]
            guess = [seen[int(np.argmax(q['prob'][i][cols]))] for i in idx]          # among the values observers recorded for the species
            groups.append((vals, guess))
            hit += sum(a == b for a, b in zip(vals, guess)); tot += len(idx)
            base += collections.Counter(vals).most_common(1)[0][1]
        if tot < 50:
            continue
        for _ in range(200):
            shuf.append(sum(sum(a == b for a, b in zip(rng.permutation(v), g)) for v, g in groups) / tot)
        row = {'species': len(groups), 'observations': tot, 'follows': hit / tot, 'shuffled': float(np.mean(shuf)), 'shuffled_97.5': float(np.percentile(shuf, 97.5)), 'majority': base / tot}
        report[f'observers | {trait}'] = row
        print(f"{trait}\t{row['species']}\t{tot}\t{row['follows']:.3f}\t{row['shuffled']:.3f} (97.5%: {row['shuffled_97.5']:.3f})\t{row['majority']:.3f}")
    (A / 'within.json').write_text(json.dumps(report, indent=1) + '\n')


def gaps(run='baseline-v6/s0'):
    from flopo2.traitvision import validate_external as V
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(H / 'taxon-names-v3.tsv'), delimiter='\t')}
    acc = lambda t: name.get(t) or ' '.join(t.replace('_', ' ').split()[:2])
    labels = collections.defaultdict(dict)
    for r in csv.DictReader(open(H / 'labels-v5.tsv'), delimiter='\t'):
        labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    size = collections.defaultdict(dict)
    for r in csv.DictReader(open(H / 'measure-labels-v3.tsv'), delimiter='\t'):
        size[r['trait']][r['taxon']] = float(r['log10_m'])
    agreed = collections.defaultdict(dict)
    for r in csv.DictReader(open(H / 'agreed-v5.tsv'), delimiter='\t'):
        if int(r['floras']) >= 2:
            agreed[r['trait']][r['taxon']] = r['value']
    pred, psize = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in csv.DictReader(gzip.open(H / run / 'species-pred.tsv.gz', 'rt'), delimiter='\t'):
        if '=' in r['values']:
            pred[r['trait']][r['taxon']] = {k: float(v) for k, v in (x.split('=') for x in r['values'].split(';'))}
        else:
            psize[r['trait']][r['taxon']] = float(r['values'])
    G = H / 'external' / 'gift'
    species = {r['work_ID']: acc(r['work_species']) for r in json.load(open(G / 'species.json'))}
    gift = collections.defaultdict(set)
    ids = {**{t: tr for tr, (t, _) in V.GIFT.items()}, **{t: tr for tr, (t, _) in V.GIFT_SIZES.items()}}
    for t, tid in ids.items():
        if (G / f'trait-{tid}.json').exists():
            gift[t] = {species[r['work_ID']] for r in json.load(open(G / f'trait-{tid}.json')) if r['work_ID'] in species}
    report = {}
    print('trait\tGIFT species\tflora species\tfloras, not in GIFT\tphotograph species\tphotographs only (no flora, no GIFT)\tof these at precision >= 0.9\tthreshold')
    tot = collections.Counter()
    for trait in sorted(set(labels) | set(size)):
        ours = set(labels[trait]) if trait in labels else set(size[trait])
        ph = set(pred[trait]) if trait in pred else set(psize.get(trait, {}))
        g = gift.get(trait, set())
        only = ph - ours - g
        sure, thr = None, None
        if trait in pred:                                      # confidence at which the predictions for agreed species are 90% right
            sc = sorted(((max(p.values()), max(p, key=p.get) == agreed[trait][t]) for t, p in pred[trait].items() if t in agreed[trait]), reverse=True)
            if len(sc) >= 100:
                cum = np.cumsum([h for _, h in sc]) / np.arange(1, len(sc) + 1)
                good = np.flatnonzero((cum >= 0.9) & (np.arange(len(sc)) >= 49))
                if len(good):
                    thr = sc[int(good[-1])][0]
                    sure = sum(max(pred[trait][t].values()) >= thr for t in only)
        row = {'gift': len(g), 'floras': len(ours), 'floras_not_gift': len(ours - g) if g else None, 'photographs': len(ph), 'photographs_only': len(only),
               'photographs_only_precision_0.9': sure, 'threshold': thr}
        report[trait] = row
        tot['floras'] += len(ours); tot['only'] += len(only); tot['sure'] += sure or 0; tot['floras_not_gift'] += len(ours - g) if g else 0; tot['gift'] += len(g)
        print(f"{trait}\t{len(g) or '-'}\t{len(ours)}\t{len(ours - g) if g else '-'}\t{len(ph)}\t{len(only)}\t{sure if sure is not None else '-'}\t{'' if thr is None else round(thr, 2)}")
    report['ALL'] = dict(tot)
    print('ALL', dict(tot))
    (A / 'gaps.json').write_text(json.dumps(report, indent=1) + '\n')




def errors(run='baseline-v6/s0'):
    """Are the mistakes semantically close? On species where two floras agree (unseen genera): of the wrong answers, the
    share that falls on a value next to the true one on its scale (``baseline_v2.NEIGHBOURS``), against the share expected
    if the wrong answers were spread as the model's answers are overall; and the same with the answers in order of
    probability (true value second when first is wrong)."""
    from flopo2.traitvision.baseline_v2 import NEIGHBOURS
    agreed = collections.defaultdict(dict)
    for r in csv.DictReader(open(H / 'agreed-v5.tsv'), delimiter='\t'):
        if int(r['floras']) >= 2:
            agreed[r['trait']][r['taxon']] = r['value']
    pred = collections.defaultdict(dict)
    for r in csv.DictReader(gzip.open(H / run / 'species-pred.tsv.gz', 'rt'), delimiter='\t'):
        if '=' in r['values'] and r['trait'] in NEIGHBOURS:
            pred[r['trait']][r['taxon']] = {k: float(v) for k, v in (x.split('=') for x in r['values'].split(';'))}
    report = {}
    print('trait\tspecies\twrong\twrong answers on a neighbouring value\texpected by chance\tratio\tcorrect with neighbours counted half')
    for trait, nb in sorted(NEIGHBOURS.items()):
        near = collections.defaultdict(set)
        for u, v in nb:
            near[u].add(v); near[v].add(u)
        rows = [(agreed[trait][t], max(p, key=p.get)) for t, p in pred[trait].items() if agreed[trait].get(t) in p]
        if len(rows) < 100:
            continue
        freq = collections.Counter(g for _, g in rows)
        wrong = [(a, g) for a, g in rows if a != g]
        hit = sum(g in near[a] for a, g in wrong)
        exp = sum(sum(freq[c] for c in near[a]) / max(sum(n for c, n in freq.items() if c != a), 1) for a, _ in wrong)
        soft = (len(rows) - len(wrong) + 0.5 * hit) / len(rows)
        report[trait] = {'species': len(rows), 'wrong': len(wrong), 'near': hit / len(wrong), 'chance': exp / len(wrong), 'accuracy': 1 - len(wrong) / len(rows), 'accuracy_half_credit': soft}
        print(f"{trait}\t{len(rows)}\t{len(wrong)}\t{hit / len(wrong):.3f}\t{exp / len(wrong):.3f}\t{hit / max(exp, 1e-9):.2f}\t{soft:.3f} (plain {1 - len(wrong) / len(rows):.3f})")
    (A / 'errors.json').write_text(json.dumps(report, indent=1) + '\n')


def colour(run='baseline-v6/s0', min_species=20, min_obs=30):
    """Flower colour and climate. Between species, on 2-degree cells: the share of species with each colour (floras;
    photographs) against temperature, precipitation and elevation. Within species: for species whose floras allow white
    and a pigmented colour (pink, purple, red, blue), the slope of the predicted probability of the pigmented colour on
    climate over the species' observations."""
    from PIL import Image
    z, clim, labels, family, size = load(run)
    el = np.array(Image.open(A / 'worldclim' / 'wc2.1_10m_elev.tif')).astype(np.float32)
    lat, lon = z['lat'], z['lon']
    ok = ~np.isnan(lat) & ~np.isnan(lon)
    r = np.clip(np.nan_to_num((90 - lat) * 6).astype(int), 0, 1079); c = np.clip(np.nan_to_num((lon + 180) * 6).astype(int), 0, 2159)
    elev = np.where(ok, el[r, c], np.nan); elev[elev < -1000] = np.nan
    cv = {'temperature': clim['mat'], 'log precipitation': np.log10(np.maximum(clim['map'], 10)), 'elevation (km)': elev / 1000, 'absolute latitude': np.abs(lat)}
    names, tinv = np.unique(z['taxon'], return_inverse=True)
    classes = [str(x) for x in z['c_flower_colour']]
    P = z['p_flower_colour'].astype(np.float32)
    valid = ~np.isnan(clim['mat'])
    cell = (np.floor(np.nan_to_num(lat) / 2).astype(int) + 45) * 180 + (np.floor(np.nan_to_num(lon) / 2).astype(int) + 90)
    cells, cinv = np.unique(cell[valid], return_inverse=True)
    vi = np.flatnonzero(valid)
    pair, pinv = np.unique(cinv.astype(np.int64) * len(names) + tinv[vi], return_inverse=True)
    pc, ps = pair // len(names), pair % len(names)
    report = {}
    print('colour\tsource\t' + '\t'.join(f'r with {k}' for k in cv) + '\tcells')
    xs = {}
    for k, v in cv.items():
        x = np.zeros(len(cells)); n = np.zeros(len(cells)); g = ~np.isnan(v[vi])
        np.add.at(x, cinv[g], v[vi][g]); np.add.at(n, cinv[g], 1); xs[k] = np.where(n > 0, x / np.maximum(n, 1), np.nan)
    for col in classes:
        fl = np.array([(len(labels['flower_colour'][t] & {col}) / len(labels['flower_colour'][t])) if t in labels['flower_colour'] else np.nan for t in names])
        pm = np.zeros(len(pair)); np.add.at(pm, pinv, P[vi, classes.index(col)].astype(np.float64)); pm /= np.bincount(pinv)
        for src, val, sel in (('floras', fl[ps], ~np.isnan(fl[ps])), ('photographs', pm, np.ones(len(pair), bool))):
            tot = np.zeros(len(cells)); cnt = np.zeros(len(cells))
            np.add.at(tot, pc[sel], val[sel]); np.add.at(cnt, pc[sel], 1)
            y = np.where(cnt >= min_species, tot / np.maximum(cnt, 1), np.nan)
            fits = {k: fit(x, y) for k, x in xs.items()}
            report[f'{col} | {src}'] = fits
            print(f'{col}\t{src}\t' + '\t'.join(f"{f['r']:+.2f}" for f in fits.values()) + f"\t{next(iter(fits.values()))['cells']}")
    # within species: white against pigmented
    pig = [c for c in ('pink', 'purple', 'red', 'blue') if c in classes]
    order = np.argsort(tinv, kind='stable'); start = np.r_[0, np.flatnonzero(np.diff(tinv[order])) + 1, len(order)]
    print('\nclimate\tspecies\tshare of species more pigmented where the value is higher\tmedian slope\tz of the sign test')
    for k, v in cv.items():
        slopes = []
        for n, t in enumerate(names):
            al = labels['flower_colour'].get(t, set())
            pg = [c for c in pig if c in al]
            if 'white' not in al or not pg:
                continue
            idx = order[start[n]:start[n + 1]]
            idx = idx[~np.isnan(v[idx])]
            if len(idx) < min_obs or np.std(v[idx]) < {'temperature': 2.0, 'log precipitation': 0.1, 'elevation (km)': 0.2, 'absolute latitude': 2.0}[k]:
                continue
            pw = P[idx, classes.index('white')]; pp = P[idx][:, [classes.index(c) for c in pg]].sum(1)
            y = pp / np.maximum(pw + pp, 1e-6)
            slopes.append(np.polyfit(v[idx].astype(float), y.astype(float), 1)[0])
        slopes = np.array(slopes)
        share = float((slopes > 0).mean()); zt = (share - 0.5) / math.sqrt(0.25 / len(slopes))
        report[f'within | {k}'] = {'species': int(len(slopes)), 'share_positive': share, 'median_slope': float(np.median(slopes)), 'z': zt}
        print(f'{k}\t{len(slopes)}\t{share:.3f}\t{np.median(slopes):+.4f}\t{zt:+.1f}')
    (A / 'colour.json').write_text(json.dumps(report, indent=1) + '\n')


def colour_family(run='baseline-v6/s0', min_species=20):
    """Flower colour and climate with the family taken out: every species' colour share minus the mean of its family
    (flora values), then the cell means of these differences against climate; and the same for herbs and for woody
    species separately. Tells turnover of families from change within families."""
    from PIL import Image
    z, clim, labels, family, size = load(run)
    el = np.array(Image.open(A / 'worldclim' / 'wc2.1_10m_elev.tif')).astype(np.float32)
    lat, lon = z['lat'], z['lon']
    ok = ~np.isnan(lat) & ~np.isnan(lon)
    r = np.clip(np.nan_to_num((90 - lat) * 6).astype(int), 0, 1079); c = np.clip(np.nan_to_num((lon + 180) * 6).astype(int), 0, 2159)
    elev = np.where(ok, el[r, c], np.nan); elev[elev < -1000] = np.nan
    cv = {'temperature': clim['mat'], 'log precipitation': np.log10(np.maximum(clim['map'], 10)), 'elevation (km)': elev / 1000, 'absolute latitude': np.abs(lat)}
    names, tinv = np.unique(z['taxon'], return_inverse=True)
    valid = ~np.isnan(clim['mat'])
    cell = (np.floor(np.nan_to_num(lat) / 2).astype(int) + 45) * 180 + (np.floor(np.nan_to_num(lon) / 2).astype(int) + 90)
    cells, cinv = np.unique(cell[valid], return_inverse=True)
    vi = np.flatnonzero(valid)
    pair = np.unique(cinv.astype(np.int64) * len(names) + tinv[vi])
    pc, ps = pair // len(names), pair % len(names)
    xs = {}
    for k, v in cv.items():
        x = np.zeros(len(cells)); n = np.zeros(len(cells)); g = ~np.isnan(v[vi])
        np.add.at(x, cinv[g], v[vi][g]); np.add.at(n, cinv[g], 1); xs[k] = np.where(n > 0, x / np.maximum(n, 1), np.nan)
    fam = np.array([family.get(t, '') for t in names])
    hab = [labels['habit'].get(t, set()) for t in names]
    groups = {'all species': np.ones(len(names), bool), 'herbs': np.array([h == {'herb'} for h in hab]), 'woody': np.array([bool(h) and h <= {'tree', 'shrub'} for h in hab])}
    report = {}
    print('colour\tspecies\tfamily taken out\t' + '\t'.join(f'r with {k}' for k in cv) + '\tcells')
    for col in ('blue', 'purple', 'orange', 'red', 'white', 'yellow', 'pink', 'green'):
        fl = np.array([(len(labels['flower_colour'][t] & {col}) / len(labels['flower_colour'][t])) if t in labels['flower_colour'] else np.nan for t in names])
        fm = {}
        for f in set(fam):
            v = fl[(fam == f) & ~np.isnan(fl)]
            if len(v) >= 10:
                fm[f] = v.mean()
        centred = np.array([fl[n] - fm[fam[n]] if fam[n] in fm else np.nan for n in range(len(names))])
        for gname, g in groups.items():
            for cname, val in (('no', fl), ('yes', centred)):
                sel = g[ps] & ~np.isnan(val[ps])
                tot = np.zeros(len(cells)); cnt = np.zeros(len(cells))
                np.add.at(tot, pc[sel], val[ps][sel]); np.add.at(cnt, pc[sel], 1)
                y = np.where(cnt >= min_species, tot / np.maximum(cnt, 1), np.nan)
                fits = {k: fit(x, y) for k, x in xs.items()}
                if all(fits.values()):
                    report[f'{col} | {gname} | family out {cname}'] = fits
                    print(f'{col}\t{gname}\t{cname}\t' + '\t'.join(f"{f['r']:+.2f}" for f in fits.values()) + f"\t{next(iter(fits.values()))['cells']}")
    (A / 'colour-family.json').write_text(json.dumps(report, indent=1) + '\n')


WIND = {'Poaceae', 'Gramineae', 'Cyperaceae', 'Juncaceae', 'Typhaceae', 'Restionaceae', 'Fagaceae', 'Betulaceae', 'Juglandaceae', 'Casuarinaceae', 'Myricaceae',
        'Ulmaceae', 'Cannabaceae', 'Urticaceae', 'Moraceae', 'Plantaginaceae', 'Amaranthaceae', 'Chenopodiaceae', 'Polygonaceae', 'Potamogetonaceae',
        'Pinaceae', 'Cupressaceae', 'Podocarpaceae', 'Araucariaceae', 'Taxaceae', 'Ephedraceae', 'Gnetaceae', 'Ginkgoaceae', 'Cycadaceae', 'Zamiaceae'}
COLS = ('blue', 'purple', 'pink', 'red', 'orange', 'yellow', 'white', 'green')


def _inside(px, py, ring):
    x, y = ring[:, 0], ring[:, 1]
    res = np.zeros(len(px), bool)
    for i in range(len(x) - 1):
        if y[i] != y[i + 1]:
            res ^= ((y[i] > py) != (y[i + 1] > py)) & (px < (x[i + 1] - x[i]) * (py - y[i]) / (y[i + 1] - y[i]) + x[i])
    return res


def colour_data(run='baseline-v6/s0'):
    """Tables for the flower-colour models. ``colour-species.tsv``: every species with a flora flower colour: the colours,
    growth form, corolla shape, family, whether the family is wind-pollinated, the climate of its range (mean over the
    botanical countries WCVP records it from; no iNaturalist data) and of its iNaturalist observations, and its tip in the
    seed-plant tree (Smith and Brown 2018, ALLMB). ``colour-countries.tsv``: per botanical country its climate and the
    share of its species with each colour."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    W = A / 'worldclim'
    rd = lambda f: (lambda a: np.where(a < -1e30, np.nan, a))(np.array(Image.open(W / f)).astype(np.float32))
    grids = {'mat': rd('wc2.1_10m_bio_1.tif'), 'map': rd('wc2.1_10m_bio_12.tif'), 'elev': rd('wc2.1_10m_elev.tif'),
             'srad': np.nanmean(np.stack([rd(f'wc2.1_10m_srad_{m:02d}.tif') for m in range(1, 13)]), 0)}
    grids['elev'][grids['elev'] < -1000] = np.nan
    rr, cc = np.meshgrid(np.arange(1, 1080, 3), np.arange(1, 2160, 3), indexing='ij')
    rr, cc = rr.ravel(), cc.ravel()
    land = ~np.isnan(grids['mat'][rr, cc])
    rr, cc = rr[land], cc[land]
    glat, glon = 90 - (rr + 0.5) / 6, (cc + 0.5) / 6 - 180
    code = np.full(len(glat), '', dtype='U3')
    for f in json.load(open(Path.home() / 'tmp/flopo-trait-vision/geo/level3.geojson'))['features']:
        g = f['geometry']
        for poly in (g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]):
            outer = np.array(poly[0], float)
            idx = np.flatnonzero((glon >= outer[:, 0].min()) & (glon <= outer[:, 0].max()) & (glat >= outer[:, 1].min()) & (glat <= outer[:, 1].max()) & (code == ''))
            if len(idx):
                code[idx[_inside(glon[idx], glat[idx], outer)]] = f['properties']['LEVEL3_COD']
    country = {}
    for c in sorted(set(code) - {''}):
        m = code == c
        country[c] = {'mat': float(np.nanmean(grids['mat'][rr[m], cc[m]])), 'logmap': float(np.log10(max(np.nanmean(grids['map'][rr[m], cc[m]]), 10))),
                      'elev': float(np.nanmean(grids['elev'][rr[m], cc[m]])) / 1000, 'srad': float(np.nanmean(grids['srad'][rr[m], cc[m]])) / 1000,
                      'abslat': float(np.abs(glat[m]).mean()), 'cells': int(m.sum())}
    labels, family = collections.defaultdict(dict), {}
    for row in csv.DictReader(open(H / 'labels-v5.tsv'), delimiter='\t'):
        labels[row['trait']][row['taxon']] = set(row['allowed'].split('|')); family[row['taxon']] = row['family']
    csv.field_size_limit(10 ** 9)
    ids, cont = {}, {}
    for r in csv.DictReader(open('local-corpora/wcvp/raw/wcvp_names.csv'), delimiter='|', quoting=csv.QUOTE_NONE):
        if r['taxon_rank'] == 'Species' and r['taxon_status'] == 'Accepted':
            ids[r['plant_name_id']] = r['taxon_name']
    dist = collections.defaultdict(set)
    for r in csv.DictReader(open('local-corpora/wcvp/raw/wcvp_distribution.csv'), delimiter='|', quoting=csv.QUOTE_NONE):
        if r['plant_name_id'] in ids and r['area_code_l3'] and r['introduced'] != '1' and r['extinct'] != '1' and r['location_doubtful'] != '1':
            dist[ids[r['plant_name_id']]].add(r['area_code_l3'].upper()); cont[r['area_code_l3'].upper()] = r['continent']
    z, clim, _, _, _ = load(run)
    names, tinv = np.unique(z['taxon'], return_inverse=True)
    nobs = np.bincount(tinv)
    omean = {}
    for k, v in (('mat', clim['mat']), ('logmap', np.log10(np.maximum(clim['map'], 10)))):
        s = np.zeros(len(names)); n = np.zeros(len(names)); g = ~np.isnan(v)
        np.add.at(s, tinv[g], v[g]); np.add.at(n, tinv[g], 1); omean[k] = dict(zip(names, np.where(n > 0, s / np.maximum(n, 1), np.nan)))
    oi = {t: n for n, t in enumerate(names)}
    import re
    tips = set(re.findall(r'[(,]([A-Z][a-z-]+_[a-z-]+):', open(A / 'phylo' / 'v0.1' / 'ALLMB.tre').read()))
    keys = ('mat', 'logmap', 'elev', 'srad', 'abslat')
    by_country = collections.defaultdict(lambda: collections.Counter())
    with open(A / 'colour-species.tsv', 'w') as f:
        f.write('taxon\ttip\tfamily\twind\tgrowth\tcorolla\t' + '\t'.join(COLS) + '\t' + '\t'.join(keys) + '\tcountries\tobs\tobs_mat\tobs_logmap\n')
        for t, cols in sorted(labels['flower_colour'].items()):
            h = labels['habit'].get(t, set())
            growth = 'climber' if 'climber' in h else 'herb' if h == {'herb'} else 'woody' if h and h <= {'tree', 'shrub'} else 'mixed' if h else 'NA'
            co = labels['corolla_shape'].get(t, set())
            corolla = 'NA' if not co else 'tube' if co <= {'tubular', 'funnel', 'salverform', 'two-lipped', 'urn'} else 'open' if co <= {'rotate', 'bell'} else 'mixed'
            cs = [c for c in dist.get(t, ()) if c in country]
            for c in cs:
                by_country[c]['n'] += 1
                for col in COLS:
                    by_country[c][col] += (col in cols) / len(cols)
            cl = [f"{np.mean([country[c][k] for c in cs]):.3f}" if cs else 'NA' for k in keys]
            tip = t.replace(' ', '_')
            n = oi.get(t)
            f.write(f"{t}\t{tip if tip in tips else 'NA'}\t{family[t]}\t{int(family[t] in WIND)}\t{growth}\t{corolla}\t" + '\t'.join(str(int(c in cols)) for c in COLS) + '\t' + '\t'.join(cl)
                    + f"\t{len(cs)}\t{nobs[n] if n is not None else 0}\t" + (f"{omean['mat'][t]:.3f}\t{omean['logmap'][t]:.3f}" if n is not None and not np.isnan(omean['mat'][t]) else 'NA\tNA') + '\n')
    with open(A / 'colour-countries.tsv', 'w') as f:
        f.write('country\tcontinent\tspecies\t' + '\t'.join(keys) + '\t' + '\t'.join(COLS) + '\n')
        for c, k in sorted(by_country.items()):
            f.write(f"{c}\t{cont.get(c, '')}\t{k['n']}\t" + '\t'.join(f'{country[c][x]:.3f}' for x in keys) + '\t' + '\t'.join(f"{k[col] / k['n']:.4f}" for col in COLS) + '\n')
    print('countries', len(by_country), 'species', len(labels['flower_colour']), 'tips', len(tips))


def colour_bias(run='baseline-v6/s0'):
    """Checks of the flower-colour patterns against the sampling of iNaturalist. (1) Without iNaturalist: botanical
    countries, the species WCVP records as native there, their flora colours, the country's climate. (2) The cell analysis
    by continent, with other minimum numbers of species, with the number of observations taken out, and with a bootstrap
    over 10-degree blocks (neighbouring cells are not independent)."""
    rows = list(csv.DictReader(open(A / 'colour-countries.tsv'), delimiter='\t'))
    rows = [r for r in rows if int(r['species']) >= 50]
    keys = ('mat', 'logmap', 'elev', 'srad', 'abslat')
    rng = np.random.default_rng(0)
    report = {}
    print(f'botanical countries with 50 or more species: {len(rows)}')
    print('colour\t' + '\t'.join('r with ' + k for k in keys) + '\tpartial: temperature | precipitation, elevation, radiation\tpartial: precipitation | others')
    X = np.array([[float(r[k]) for k in keys] for r in rows])

    def partial(y, j, others):
        Z = np.c_[np.ones(len(y)), X[:, others]]
        ry = y - Z @ np.linalg.lstsq(Z, y, rcond=None)[0]; rx = X[:, j] - Z @ np.linalg.lstsq(Z, X[:, j], rcond=None)[0]
        return float(np.corrcoef(rx, ry)[0, 1])
    for col in COLS:
        y = np.array([float(r[col]) for r in rows])
        rs = [float(np.corrcoef(X[:, j], y)[0, 1]) for j in range(len(keys))]
        report[f'countries | {col}'] = dict(zip(keys, rs), partial_mat=partial(y, 0, [1, 2, 3]), partial_logmap=partial(y, 1, [0, 2, 3]))
        print(f'{col}\t' + '\t'.join(f'{v:+.2f}' for v in rs) + f"\t{partial(y, 0, [1, 2, 3]):+.2f}\t{partial(y, 1, [0, 2, 3]):+.2f}")
    # cells
    z, clim, labels, family, size = load(run)
    lat, lon = z['lat'], z['lon']
    names, tinv = np.unique(z['taxon'], return_inverse=True)
    valid = ~np.isnan(clim['mat'])
    cell = (np.floor(np.nan_to_num(lat) / 2).astype(int) + 45) * 180 + (np.floor(np.nan_to_num(lon) / 2).astype(int) + 90)
    cells, cinv = np.unique(cell[valid], return_inverse=True)
    vi = np.flatnonzero(valid)
    nobs = np.bincount(cinv)
    clat, clon = (cells // 180 - 45) * 2 + 1, (cells % 180 - 90) * 2 + 1
    block = (np.floor(clat / 10).astype(int) + 9) * 36 + (np.floor(clon / 10).astype(int) + 18)
    region = np.where((clon < -30) & (clat > 13), 'North America', np.where((clon < -30), 'South and Central America', np.where((clon < 60) & (clat > 35), 'Europe',
             np.where((clon < 60) & (clat <= 35), 'Africa and Arabia', np.where(clat > 0, 'Asia', 'Australasia')))))
    pair = np.unique(cinv.astype(np.int64) * len(names) + tinv[vi])
    pc, ps = pair // len(names), pair % len(names)
    cv = {'temperature': clim['mat'], 'log precipitation': np.log10(np.maximum(clim['map'], 10))}
    xs = {}
    for k, v in cv.items():
        x = np.zeros(len(cells)); np.add.at(x, cinv, v[vi]); xs[k] = x / nobs
    tests = [('blue', 'temperature'), ('purple', 'temperature'), ('orange', 'temperature'), ('red', 'temperature'), ('white', 'log precipitation'), ('yellow', 'log precipitation')]
    print('\ncolour\tclimate\tr (20+ species)\t95% interval, 10-degree blocks\t10+ species\t50+ species\tnumber of observations taken out\t' + '\t'.join(sorted(set(region))))
    for col, k in tests:
        fl = np.array([(len(labels['flower_colour'][t] & {col}) / len(labels['flower_colour'][t])) if t in labels['flower_colour'] else np.nan for t in names])
        sel = ~np.isnan(fl[ps])
        tot = np.zeros(len(cells)); cnt = np.zeros(len(cells))
        np.add.at(tot, pc[sel], fl[ps][sel]); np.add.at(cnt, pc[sel], 1)
        y = tot / np.maximum(cnt, 1); x = xs[k]
        r_at = lambda m: float(np.corrcoef(x[m], y[m])[0, 1]) if m.sum() >= 10 else float('nan')
        m = cnt >= 20
        boot = []
        bl = np.unique(block[m])
        for _ in range(1000):
            pick = rng.choice(bl, len(bl))
            idx = np.concatenate([np.flatnonzero(m & (block == b)) for b in pick])
            boot.append(np.corrcoef(x[idx], y[idx])[0, 1])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        Z = np.c_[np.ones(m.sum()), np.log10(nobs[m]), np.log10(cnt[m])]
        ry = y[m] - Z @ np.linalg.lstsq(Z, y[m], rcond=None)[0]; rx = x[m] - Z @ np.linalg.lstsq(Z, x[m], rcond=None)[0]
        reg = {g: r_at(m & (region == g)) for g in sorted(set(region))}
        report[f'cells | {col} | {k}'] = {'r': r_at(m), 'low': float(lo), 'high': float(hi), 'r10': r_at(cnt >= 10), 'r50': r_at(cnt >= 50), 'effort_out': float(np.corrcoef(rx, ry)[0, 1]), **reg}
        print(f"{col}\t{k}\t{r_at(m):+.2f}\t{lo:+.2f} to {hi:+.2f}\t{r_at(cnt >= 10):+.2f}\t{r_at(cnt >= 50):+.2f}\t{np.corrcoef(rx, ry)[0, 1]:+.2f}\t" + '\t'.join(f'{v:+.2f}' for v in reg.values()))
    (A / 'colour-bias.json').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    {'climate': climate, 'within': within, 'gaps': gaps, 'errors': errors, 'colour': colour, 'colour-family': colour_family,
     'colour-data': colour_data, 'colour-bias': colour_bias}[sys.argv[1]](*sys.argv[2:])
