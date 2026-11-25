"""Variation within species, from the per-observation predictions of the trait models (`applications/obs-pred.npz`).

    python -m flopo2.traitvision.within context     # applications/obs-context.npz
    python -m flopo2.traitvision.within slopes      # applications/within-slopes.json
    python -m flopo2.traitvision.within ranges      # applications/within-ranges.json (native against introduced range)
    python -m flopo2.traitvision.within habitat     # applications/within-habitat.json (land cover)

``context``: for every observation the climate at its coordinates (WorldClim 2.1, 10 arc-minutes), elevation, the land
cover of its 1-km cell (EarthEnv consensus land cover, Tuanmu and Jetz 2014: percent of each of 11 classes), the observer,
the day of the year, and whether its botanical country is in the native or the introduced range of the species (WCVP).

Every analysis removes the species mean first (species as fixed effect), so differences between species do not enter.
Signals are the predicted log10 sizes and the logits of predicted probabilities. Control traits are traits that do not vary
within a species (leaf arrangement, leaf complexity, fruit type, inflorescence type, life span): a response of these to the
environment measures how much of a response is read from the surroundings of the plant and not from the plant.
"""
import collections, csv, json, sys
from pathlib import Path
import numpy as np

H = Path('local-corpora/trait-vision')
A = H / 'applications'
LC = {1: 'needleleaf trees', 2: 'evergreen broadleaf trees', 3: 'deciduous broadleaf trees', 4: 'mixed trees', 5: 'shrubs', 6: 'herbaceous',
      7: 'cultivated', 8: 'flooded', 9: 'urban', 11: 'barren', 12: 'water'}
# (name, kind, source, class or second size); kind: plastic = may vary within a species; control = fixed within a species
SIGNALS = [('height', 'plastic', 'size', None), ('leaf area', 'plastic', 'size', ('leaf_length', 'leaf_width')), ('flower diameter', 'plastic', 'size', 'flower_diameter'),
           ('petal length', 'plastic', 'size', 'petal_length'), ('fruit length', 'plastic', 'size', 'fruit_length'),
           ('hairy leaves', 'plastic', 'leaf_hair', 'hairy'), ('hairy stem', 'plastic', 'stem_hair', 'hairy'), ('fleshy leaves', 'plastic', 'leaf_texture', 'fleshy'),
           ('coriaceous leaves', 'plastic', 'leaf_texture', 'coriaceous'), ('prostrate', 'plastic', 'posture', 'prostrate'),
           ('evergreen', 'plastic', 'leaf_persistence', 'evergreen'), ('entire margin', 'plastic', 'leaf_margin', 'entire'),
           ('woody', 'plastic', 'habit', ('tree', 'shrub')),
           ('opposite leaves', 'control', 'leaf_arrangement', 'opposite'), ('compound leaves', 'control', 'leaf_complexity', 'compound'),
           ('capsule', 'control', 'fruit_type', 'capsule'), ('berry', 'control', 'fruit_type', 'berry'), ('capitulum', 'control', 'inflorescence', 'capitulum'),
           ('annual', 'control', 'life_span', 'annual'), ('epiphytic', 'control', 'substrate', 'epiphytic'), ('quadrangular stem', 'control', 'stem_shape', 'quadrangular')]


def signals(z):
    sn = [str(s) for s in z['size_names']]
    out = {}
    for name, kind, src, arg in SIGNALS:
        if src == 'size':
            ks = arg if isinstance(arg, tuple) else (arg or name,)
            if any(k not in sn for k in ks):
                continue
            y = sum(z['sizes'][:, sn.index(k)].astype(np.float64) for k in ks)
        else:
            cl = [str(c) for c in z['c_' + src]]
            p = sum(z['p_' + src][:, cl.index(a)].astype(np.float64) for a in (arg if isinstance(arg, tuple) else (arg,)))
            p = np.clip(p, 1e-4, 1 - 1e-4); y = np.log(p / (1 - p))
        out[name] = (kind, y)
    return out


def context():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    z = np.load(A / 'obs-pred.npz')
    lat, lon = z['lat'].astype(np.float64), z['lon'].astype(np.float64)
    ok = ~np.isnan(lat) & ~np.isnan(lon)
    W = A / 'worldclim'
    rd = lambda f: (lambda a: np.where(a < -1e30, np.nan, a))(np.array(Image.open(W / f)).astype(np.float32))
    r = np.clip(((90 - lat) * 6).astype(int), 0, 1079); c = np.clip(((lon + 180) * 6).astype(int), 0, 2159)
    r[~ok] = 0; c[~ok] = 0
    out = {}
    for k, f in (('mat', 'wc2.1_10m_bio_1.tif'), ('map', 'wc2.1_10m_bio_12.tif'), ('elev', 'wc2.1_10m_elev.tif')):
        out[k] = np.where(ok, rd(f)[r, c], np.nan).astype(np.float32)
    out['logmap'] = np.log10(np.maximum(out.pop('map'), 10))
    # land cover: 30 arc-seconds, 90 N to 56 S
    r2 = ((90 - lat) * 120).astype(int); c2 = np.clip(((lon + 180) * 120).astype(int), 0, 43199)
    cover = np.full((len(lat), len(LC)), np.nan, dtype=np.float32)
    for j, i in enumerate(LC):
        a = np.array(Image.open(A / 'landcover' / f'class_{i}.tif'))
        inside = ok & (r2 >= 0) & (r2 < a.shape[0])
        cover[inside, j] = a[r2[inside], c2[inside]]
        print(LC[i], a.shape, float(np.nanmean(cover[:, j])), flush=True)
        del a
    out['cover'] = cover; out['cover_names'] = np.array(list(LC.values()))
    # observer
    obs = {}
    for f in ('inat-photos-v3-all.tsv', 'inat-photos-v3.tsv', 'inat-photos-v3-rest.tsv'):
        if (H / f).exists():
            for row in csv.DictReader(open(H / f), delimiter='\t'):
                obs[row['observation_uuid']] = row['observer_id']
    out['observer'] = np.array([obs.get(str(o), '') for o in z['observation']])
    out['doy'] = np.array([(int(d[5:7]) - 1) * 30.4 + int(d[8:10]) if len(d) == 10 else np.nan for d in z['date']], dtype=np.float32)
    # native or introduced range
    csv.field_size_limit(10 ** 9)
    ids = {}
    for row in csv.DictReader(open('local-corpora/wcvp/raw/wcvp_names.csv'), delimiter='|', quoting=csv.QUOTE_NONE):
        if row['taxon_rank'] == 'Species' and row['taxon_status'] == 'Accepted':
            ids[row['plant_name_id']] = row['taxon_name']
    nat, intro = collections.defaultdict(set), collections.defaultdict(set)
    for row in csv.DictReader(open('local-corpora/wcvp/raw/wcvp_distribution.csv'), delimiter='|', quoting=csv.QUOTE_NONE):
        if row['plant_name_id'] in ids and row['area_code_l3'] and row['extinct'] != '1' and row['location_doubtful'] != '1':
            (intro if row['introduced'] == '1' else nat)[ids[row['plant_name_id']]].add(row['area_code_l3'].upper())
    region = {row['observation']: row['region'] for row in csv.DictReader(open(A / 'obs-regions.tsv'), delimiter='\t')}
    st = []
    for o, t in zip(z['observation'], z['taxon']):
        g = region.get(str(o)); t = str(t)
        st.append('' if not g or t not in nat else 'native' if g in nat[t] else 'introduced' if g in intro[t] else 'other')
    out['range'] = np.array(st)
    out['region'] = np.array([region.get(str(o), '') for o in z['observation']])
    np.savez_compressed(A / 'obs-context.npz', **out)
    print({k: int((out['range'] == k).sum()) for k in ('native', 'introduced', 'other', '')}, 'observers', len(set(out['observer'])))


RUN = ''          # '' = whole photographs (applications/obs-pred.npz); else a run folder under baseline-v6 with its own obs-pred.npz


def _data():
    """Predictions per observation and the context rows of the same observations."""
    cx = np.load(A / 'obs-context.npz')
    if not RUN:
        return np.load(A / 'obs-pred.npz'), cx
    z = dict(np.load(H / 'baseline-v6' / RUN / 'obs-pred.npz'))
    row = {str(o): n for n, o in enumerate(np.load(A / 'obs-pred.npz')['observation'])}
    idx = np.array([row.get(str(o), -1) for o in z['observation']])
    keep = idx >= 0
    z = {k: (v[keep] if len(v) == len(keep) and not k.startswith('c_') and k != 'size_names' else v) for k, v in z.items()}
    return z, {k: (cx[k][idx[keep]] if k != 'cover_names' else cx[k]) for k in cx.files}


def _out(name):
    return A / (name + ('-' + RUN if RUN else '') + '.json')


def _groups(taxon, keep, min_obs):
    names, inv = np.unique(taxon, return_inverse=True)
    n = np.bincount(inv[keep], minlength=len(names))
    return names, inv, keep & (n[inv] >= min_obs)


def _demean(v, inv, use, k):
    s = np.zeros(k); n = np.zeros(k)
    np.add.at(s, inv[use], v[use]); np.add.at(n, inv[use], 1)
    return v - (s / np.maximum(n, 1))[inv], s / np.maximum(n, 1)


def _fit(X, y, groups, boot=300, rng=None):
    """OLS of y on the columns of X (all demeaned), with intervals from a bootstrap over species."""
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    ug, gi = np.unique(groups, return_inverse=True)
    XtX = np.zeros((len(ug), X.shape[1], X.shape[1])); Xty = np.zeros((len(ug), X.shape[1]))
    for a in range(X.shape[1]):
        np.add.at(Xty[:, a], gi, X[:, a] * y)
        for c in range(X.shape[1]):
            np.add.at(XtX[:, a, c], gi, X[:, a] * X[:, c])
    bs = []
    for _ in range(boot):
        w = np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug)).astype(float)
        bs.append(np.linalg.solve(np.tensordot(w, XtX, 1), w @ Xty))
    bs = np.array(bs)
    return b, np.percentile(bs, 2.5, 0), np.percentile(bs, 97.5, 0)


def slopes(min_obs=20):
    """Response of each signal to temperature, precipitation and elevation within species, and between species for comparison.
    Signals are divided by their standard deviation between species means, climate by its standard deviation over all
    observations, so a slope of 1 would be as steep as a one-to-one relation between species."""
    z, cx = _data()
    rng = np.random.default_rng(0)
    X0 = np.stack([cx['mat'], cx['logmap'], cx['elev'] / 1000], 1).astype(np.float64)
    good = ~np.isnan(X0).any(1)
    names, inv, use = _groups(z['taxon'], good, min_obs)
    sd = X0[use].std(0)
    report = {'species': int(len(set(inv[use]))), 'observations': int(use.sum()), 'climate sd (temperature C, log10 precipitation, elevation km)': sd.tolist(), 'signals': {}}
    Xw = np.zeros_like(X0); Xm = []
    for j in range(3):
        Xw[:, j], m = _demean(X0[:, j] / sd[j], inv, use, len(names)); Xm.append(m)
    Xm = np.stack(Xm, 1)
    present = np.bincount(inv[use], minlength=len(names)) > 0
    obsn = np.log(z['photos'].astype(np.float64)); obsn_w, _ = _demean(obsn, inv, use, len(names))
    doy = cx['doy'].astype(np.float64); season = np.stack([np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365)], 1)
    season[np.isnan(season)] = 0
    # the season is mirrored in the south
    season[cx['mat'] * 0 == 0] = season[cx['mat'] * 0 == 0]
    south = z['lat'] < 0
    season[south] *= -1
    sw = np.stack([_demean(season[:, 0], inv, use, len(names))[0], _demean(season[:, 1], inv, use, len(names))[0]], 1)
    print('signal\tkind\twithin: temperature\tprecipitation\televation\tbetween: temperature\tprecipitation\televation')
    for name, (kind, y) in signals(z).items():
        yw, ym = _demean(y, inv, use, len(names))
        s = ym[present].std()
        Xfull = np.column_stack([Xw[use], obsn_w[use], sw[use]])
        b, lo, hi = _fit(Xfull, yw[use] / s, inv[use], rng=rng)
        Xb = Xm[present] - Xm[present].mean(0); yb = (ym[present] - ym[present].mean()) / s
        bb = np.linalg.lstsq(Xb, yb, rcond=None)[0]
        report['signals'][name] = {'kind': kind, 'within': {k: [float(b[j]), float(lo[j]), float(hi[j])] for j, k in enumerate(('temperature', 'precipitation', 'elevation'))},
                                   'between': {k: float(bb[j]) for j, k in enumerate(('temperature', 'precipitation', 'elevation'))},
                                   'within sd / between sd': float(yw[use].std() / s)}
        print(f"{name}\t{kind}\t" + '\t'.join(f"{b[j]:+.3f} ({lo[j]:+.3f} to {hi[j]:+.3f})" for j in range(3)) + '\t' + '\t'.join(f"{bb[j]:+.3f}" for j in range(3)))
    _out('within-slopes').write_text(json.dumps(report, indent=1) + '\n')


def ranges(min_each=15):
    """Species observed in their native and in their introduced range: difference of each signal (introduced minus native),
    with the climate, the season and the number of photographs of the observation in the model."""
    z, cx = _data()
    rng = np.random.default_rng(0)
    intro = (cx['range'] == 'introduced').astype(np.float64)
    X0 = np.stack([cx['mat'], cx['logmap'], cx['elev'] / 1000], 1).astype(np.float64)
    good = ~np.isnan(X0).any(1) & np.isin(cx['range'], ('native', 'introduced'))
    names, inv = np.unique(z['taxon'], return_inverse=True)
    n1 = np.bincount(inv[good], weights=intro[good], minlength=len(names)); n0 = np.bincount(inv[good], minlength=len(names)) - n1
    use = good & (n1[inv] >= min_each) & (n0[inv] >= min_each)
    report = {'species': int(len(set(inv[use]))), 'observations': int(use.sum()), 'introduced observations': int(intro[use].sum()), 'signals': {}}
    print(report)
    cols = [intro] + [X0[:, j] / X0[use, j].std() for j in range(3)] + [np.log(z['photos'].astype(np.float64))]
    Xw = np.column_stack([_demean(c, inv, use, len(names))[0][use] for c in cols])
    present = np.bincount(inv[use], minlength=len(names)) > 0
    print('signal\tkind\tintroduced - native, raw\twith climate in the model\tshare of species with introduced larger')
    for name, (kind, y) in signals(z).items():
        yw, ym = _demean(y, inv, use, len(names))
        s = ym[present].std()
        b1, lo1, hi1 = _fit(Xw[:, :1], yw[use] / s, inv[use], rng=rng)
        b, lo, hi = _fit(Xw, yw[use] / s, inv[use], rng=rng)
        d1 = np.bincount(inv[use], weights=y[use] * intro[use], minlength=len(names))[present] / n1[present]
        d0 = np.bincount(inv[use], weights=y[use] * (1 - intro[use]), minlength=len(names))[present] / n0[present]
        report['signals'][name] = {'kind': kind, 'raw': [float(b1[0]), float(lo1[0]), float(hi1[0])], 'with climate': [float(b[0]), float(lo[0]), float(hi[0])],
                                   'share of species larger in introduced range': float((d1 > d0).mean()),
                                   'difference in original units (log10 or logit)': float(b[0] * s)}
        print(f"{name}\t{kind}\t{b1[0]:+.3f} ({lo1[0]:+.3f} to {hi1[0]:+.3f})\t{b[0]:+.3f} ({lo[0]:+.3f} to {hi[0]:+.3f})\t{(d1 > d0).mean():.3f}")
    _out('within-ranges').write_text(json.dumps(report, indent=1) + '\n')


def habitat(min_obs=30):
    """Response of each signal within species to the land cover of the 1-km cell (shares of tree cover, cultivated land, urban
    land, shrubs and herbaceous cover; per 100% of cover), with climate, season and number of photographs in the model."""
    z, cx = _data()
    rng = np.random.default_rng(0)
    cn = [str(c) for c in cx['cover_names']]; cov = cx['cover'].astype(np.float64) / 100
    tree = sum(cov[:, cn.index(k)] for k in ('needleleaf trees', 'evergreen broadleaf trees', 'deciduous broadleaf trees', 'mixed trees'))
    L = np.stack([tree, cov[:, cn.index('urban')], cov[:, cn.index('cultivated')], cov[:, cn.index('shrubs')]], 1)
    lname = ['tree cover', 'urban', 'cultivated', 'shrubs']
    X0 = np.stack([cx['mat'], cx['logmap'], cx['elev'] / 1000], 1).astype(np.float64)
    good = ~np.isnan(X0).any(1) & ~np.isnan(L).any(1)
    names, inv, use = _groups(z['taxon'], good, min_obs)
    doy = cx['doy'].astype(np.float64); season = np.stack([np.sin(2 * np.pi * doy / 365), np.cos(2 * np.pi * doy / 365)], 1)
    season[np.isnan(season)] = 0; season[z['lat'] < 0] *= -1
    cols = [L[:, j] for j in range(4)] + [X0[:, j] / X0[use, j].std() for j in range(3)] + [np.log(z['photos'].astype(np.float64)), season[:, 0], season[:, 1]]
    Xw = np.column_stack([_demean(c, inv, use, len(names))[0][use] for c in cols])
    present = np.bincount(inv[use], minlength=len(names)) > 0
    report = {'species': int(present.sum()), 'observations': int(use.sum()), 'mean cover': {k: float(L[use, j].mean()) for j, k in enumerate(lname)}, 'signals': {}}
    print(report)
    print('signal\tkind\t' + '\t'.join(lname))
    for name, (kind, y) in signals(z).items():
        yw, ym = _demean(y, inv, use, len(names))
        s = ym[present].std()
        b, lo, hi = _fit(Xw, yw[use] / s, inv[use], rng=rng)
        report['signals'][name] = {'kind': kind, **{k: [float(b[j]), float(lo[j]), float(hi[j])] for j, k in enumerate(lname)}}
        print(f"{name}\t{kind}\t" + '\t'.join(f"{b[j]:+.3f} ({lo[j]:+.3f} to {hi[j]:+.3f})" for j in range(4)))
    _out('within-habitat').write_text(json.dumps(report, indent=1) + '\n')


def adjusted(min_obs=30):
    """As ``slopes`` for the traits that may vary, with the eight control signals of the same observation as covariates. The
    controls cannot differ between plants of one species, so what they share with a signal is what the photograph shows
    besides the trait (surroundings, organ in view, season)."""
    z, cx = _data()
    rng = np.random.default_rng(0)
    X0 = np.stack([cx['mat'], cx['logmap'], cx['elev'] / 1000], 1).astype(np.float64)
    good = ~np.isnan(X0).any(1)
    names, inv, use = _groups(z['taxon'], good, min_obs)
    sig = signals(z)
    cols = [X0[:, j] / X0[use, j].std() for j in range(3)] + [np.log(z['photos'].astype(np.float64))]
    cols += [y / y[use].std() for k, (kind, y) in sig.items() if kind == 'control']
    Xw = np.column_stack([_demean(c, inv, use, len(names))[0][use] for c in cols])
    present = np.bincount(inv[use], minlength=len(names)) > 0
    report = {}
    print('signal\ttemperature\tprecipitation\televation\tR2 of the controls within species')
    for name, (kind, y) in sig.items():
        if kind != 'plastic':
            continue
        yw, ym = _demean(y, inv, use, len(names)); s = ym[present].std(); yy = yw[use] / s
        b, lo, hi = _fit(Xw, yy, inv[use], rng=rng)
        bc = np.linalg.lstsq(Xw[:, 4:], yy, rcond=None)[0]; r2 = 1 - ((yy - Xw[:, 4:] @ bc) ** 2).sum() / (yy ** 2).sum()
        report[name] = {**{k: [float(b[j]), float(lo[j]), float(hi[j])] for j, k in enumerate(('temperature', 'precipitation', 'elevation'))}, 'R2 of controls': float(r2)}
        print(f"{name}\t" + '\t'.join(f"{b[j]:+.3f} ({lo[j]:+.3f} to {hi[j]:+.3f})" for j in range(3)) + f"\t{r2:.2f}")
    _out('within-adjusted').write_text(json.dumps(report, indent=1) + '\n')


if __name__ == '__main__':
    if len(sys.argv) > 2:
        RUN = sys.argv[2]
    {'context': context, 'slopes': slopes, 'ranges': ranges, 'habitat': habitat, 'adjusted': adjusted}[sys.argv[1]]()
