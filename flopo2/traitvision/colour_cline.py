"""Flower colour within species: many observations of species with several colour forms.

    python -m flopo2.traitvision.colour_cline select local-corpora/trait-vision   # cline/inat-photos-cline.tsv, cline/species.tsv

``select``: one pass over the iNaturalist Open Data observation table and one over the photo table (streamed). Targets are
(a) species with a published geographic pattern of flower colour forms (``KNOWN``; the expected direction is checked against
the publication afterwards, not here) and (b) the species for which the floras state two or more flower colours and that are
among the most observed. For each target up to ``POOL`` research-grade observations with coordinates are kept (sample by hash
of the observation id, at most ``PER_OBSERVER`` per observer) and the first photograph of each.
"""
import collections, csv, gzip, hashlib, heapq, sys
from pathlib import Path
from .inat_select import stream

POOL, PER_OBSERVER, TOP = 2500, 20, 60
COLOURS = {'blue', 'purple', 'pink', 'red', 'orange', 'yellow', 'white'}
KNOWN = '''Lysimachia arvensis;Phlox drummondii;Gentiana lutea;Boechera stricta;Anemone coronaria;Dactylorhiza sambucina;
Raphanus raphanistrum;Raphanus sativus;Ipomoea purpurea;Linanthus parryae;Claytonia virginica;Hepatica nobilis;Iris lutescens;
Antirrhinum majus;Delphinium nuttallianum;Monarda fistulosa;Leptosiphon parviflorus;Parrya nudicaulis;Cirsium palustre;
Digitalis purpurea;Diplacus aurantiacus;Diplacus puniceus;Aquilegia coerulea;Ipomopsis aggregata;Trillium erectum;Lysimachia monelli;
Lotus corniculatus;Viola tricolor;Silene littorea;Platystemon californicus;Erythranthe lewisii;Lupinus nanus;Clarkia xantiana;
Polygala vulgaris;Trillium grandiflorum;Geranium maculatum;Phlox divaricata;Impatiens capensis;Castilleja miniata;Castilleja coccinea;
Aquilegia formosa;Iris pumila;Anacamptis morio;Orchis mascula;Corydalis solida;Pulmonaria officinalis;Symphytum officinale;
Lathyrus vernus;Vicia sativa;Papaver rhoeas;Centaurea cyanus;Campanula rotundifolia;Echium plantagineum;Lupinus perennis;
Sisyrinchium bellum;Dodecatheon meadia;Primula vulgaris;Anemone nemorosa;Hepatica americana;Erythronium americanum'''
KNOWN = [k.strip() for k in KNOWN.replace('\n', '').split(';') if k.strip()]


def select(outdir):
    H = Path(outdir); out = H / 'cline'; out.mkdir(exist_ok=True)
    # iNaturalist taxa of the known species: the species and its infraspecific taxa
    target = {}
    with gzip.open(H / 'inat-taxa.csv.gz', 'rt') as f:
        for r in csv.DictReader(f, delimiter='\t'):
            name = ' '.join(r['name'].split()[:2])
            if name in KNOWN and r['rank'] in ('species', 'subspecies', 'variety', 'form', 'hybrid'):
                target[r['taxon_id']] = name
    known_found = set(target.values())
    poly = {}
    for r in csv.DictReader(open(H / 'labels-v5.tsv'), delimiter='\t'):
        if r['trait'] == 'flower_colour' and len(set(r['allowed'].split('|')) & COLOURS) >= 2:
            poly[r['taxon']] = sorted(set(r['allowed'].split('|')) & COLOURS)
    n = collections.Counter()
    seen = set()
    for r in csv.DictReader(open(H / 'inat-photos-v3-all.tsv'), delimiter='\t'):
        if r['observation_uuid'] not in seen:
            seen.add(r['observation_uuid']); n[r['taxon']] += 1
    del seen
    for r in csv.DictReader(open(H / 'inat-names-v3.tsv'), delimiter='\t'):
        if r['taxon'] in poly and n[r['taxon']] >= 30:
            target.setdefault(r['inat_taxon_id'], r['taxon'])
    print(len(known_found), 'known species found;', len(set(target.values())), 'target species', flush=True)
    pools, total = collections.defaultdict(list), collections.Counter()
    for k, r in enumerate(stream('observations')):
        if k % 20_000_000 == 0:
            print(f'observations read: {k:,}', flush=True)
        sp = target.get(r['taxon_id'])
        if sp is None or r['quality_grade'] != 'research' or not r['latitude'] or not r['longitude']:
            continue
        total[sp] += 1
        h = int(hashlib.md5(r['observation_uuid'].encode()).hexdigest()[:12], 16)
        item = (-h, r['observation_uuid'], r['observer_id'], r['observed_on'], r['latitude'], r['longitude'], r['taxon_id'])
        heap = pools[sp]
        if len(heap) < 2 * POOL:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    top = [sp for sp, c in total.most_common() if sp not in known_found and c >= 1500][:TOP]
    keep = [sp for sp in known_found if total[sp] >= 300] + top
    chosen = {}
    with open(out / 'species.tsv', 'w') as f:
        f.write('taxon\tsource\tobservations\tchosen\tflora colours\n')
        for sp in keep:
            per, kept = collections.Counter(), 0
            for item in sorted(pools[sp], reverse=True):
                if per[item[2]] >= PER_OBSERVER:
                    continue
                per[item[2]] += 1; chosen[item[1]] = (sp, item); kept += 1
                if kept >= POOL:
                    break
            f.write(f"{sp}\t{'known' if sp in known_found else 'floras'}\t{total[sp]}\t{kept}\t{'|'.join(poly.get(sp, []))}\n")
    print(len(chosen), 'observations of', len(keep), 'species', flush=True)
    del pools
    kept = 0
    with open(out / 'inat-photos-cline.tsv', 'w') as f:
        f.write('photo_id\textension\tlicense\twidth\theight\tposition\tobservation_uuid\tobserver_id\tobserved_on\tlatitude\tlongitude\tinat_taxon_id\ttaxon\n')
        for k, r in enumerate(stream('photos')):
            if k % 50_000_000 == 0:
                print(f'photos read: {k:,}; kept {kept:,}', flush=True)
            hit = chosen.get(r['observation_uuid'])
            if hit is None or r['position'] != '0':
                continue
            sp, item = hit
            f.write('\t'.join((r['photo_id'], r['extension'], r['license'], r['width'], r['height'], r['position'], item[1], item[2], item[3],
                               item[4], item[5], item[6], sp)) + '\n')
            kept += 1
    print(kept, 'photographs in the manifest', flush=True)




def select_pair(outdir, pool=6000):
    """Scarlet and blue pimpernel as one aggregate (iNaturalist files the blue form as Lysimachia loeflingii): a hash sample of
    ``pool`` research-grade observations over both, so that their shares are those of the observations. Writes cline2/."""
    H = Path(outdir); out = H / 'cline2'; out.mkdir(exist_ok=True)
    names = {'Lysimachia arvensis', 'Lysimachia loeflingii', 'Anagallis arvensis', 'Anagallis foemina', 'Anagallis caerulea'}
    target = {}
    with gzip.open(H / 'inat-taxa.csv.gz', 'rt') as f:
        for r in csv.DictReader(f, delimiter='\t'):
            if ' '.join(r['name'].split()[:2]) in names and '×' not in r['name']:
                target[r['taxon_id']] = r['name']
    heap, total = [], collections.Counter()
    for r in stream('observations'):
        nm = target.get(r['taxon_id'])
        if nm is None or r['quality_grade'] != 'research' or not r['latitude'] or not r['longitude']:
            continue
        total[nm] += 1
        h = int(hashlib.md5(r['observation_uuid'].encode()).hexdigest()[:12], 16)
        item = (-h, r['observation_uuid'], r['observer_id'], r['observed_on'], r['latitude'], r['longitude'], r['taxon_id'], nm)
        if len(heap) < 3 * pool:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    print(dict(total), flush=True)
    per, chosen = collections.Counter(), {}
    for item in sorted(heap, reverse=True):
        if per[item[2]] >= PER_OBSERVER:
            continue
        per[item[2]] += 1; chosen[item[1]] = item
        if len(chosen) >= pool:
            break
    with open(out / 'species.tsv', 'w') as f:
        f.write('taxon\tsource\tobservations\tchosen\tflora colours\n')
        f.write(f"Lysimachia arvensis\tknown\t{sum(total.values())}\t{len(chosen)}\t\n")
    kept = 0
    with open(out / 'inat-photos-cline.tsv', 'w') as f:
        f.write('photo_id\textension\tlicense\twidth\theight\tposition\tobservation_uuid\tobserver_id\tobserved_on\tlatitude\tlongitude\tinat_taxon_id\ttaxon\tidentified_as\n')
        for r in stream('photos'):
            item = chosen.get(r['observation_uuid'])
            if item is None or r['position'] != '0':
                continue
            f.write('\t'.join((r['photo_id'], r['extension'], r['license'], r['width'], r['height'], r['position'], item[1], item[2], item[3],
                               item[4], item[5], item[6], 'Lysimachia arvensis', item[7])) + '\n')
            kept += 1
    print(kept, 'photographs in the manifest', flush=True)


def select_top(outdir, n=1000, pool=1000):
    """The ``n`` most observed species that have flora labels (research-grade observations with coordinates), without the
    species of ``cline/species.tsv``; ``pool`` observations each by hash, at most PER_OBSERVER per observer. Writes atlas/."""
    n, pool = int(n), int(pool)
    H = Path(outdir); out = H / 'atlas'; out.mkdir(exist_ok=True)
    labelled = {r['taxon'] for r in csv.DictReader(open(H / 'labels-v5.tsv'), delimiter='\t')}
    done = {r['taxon'] for r in csv.DictReader(open(H / 'cline' / 'species.tsv'), delimiter='\t')}
    target = {r['inat_taxon_id']: r['taxon'] for r in csv.DictReader(open(H / 'inat-names-v3.tsv'), delimiter='\t')
              if r['taxon'] in labelled and r['taxon'] not in done}
    ok = lambda r: r['quality_grade'] == 'research' and r['latitude'] and r['longitude']
    total = collections.Counter()
    for r in stream('observations'):
        sp = target.get(r['taxon_id'])
        if sp is not None and ok(r):
            total[sp] += 1
    keep = {sp for sp, c in total.most_common(n)}
    print(len(total), 'labelled species observed; kept', len(keep), 'with at least', min(total[sp] for sp in keep), 'observations', flush=True)
    pools = collections.defaultdict(list)
    for r in stream('observations'):
        sp = target.get(r['taxon_id'])
        if sp not in keep or not ok(r):
            continue
        h = int(hashlib.md5(r['observation_uuid'].encode()).hexdigest()[:12], 16)
        item = (-h, r['observation_uuid'], r['observer_id'], r['observed_on'], r['latitude'], r['longitude'], r['taxon_id'])
        heap = pools[sp]
        if len(heap) < 2 * pool:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    chosen = {}
    with open(out / 'species.tsv', 'w') as f:
        f.write('taxon\tsource\tobservations\tchosen\tflora colours\n')
        for sp in sorted(keep, key=lambda s: -total[s]):
            per, kept = collections.Counter(), 0
            for item in sorted(pools[sp], reverse=True):
                if per[item[2]] >= PER_OBSERVER:
                    continue
                per[item[2]] += 1; chosen[item[1]] = (sp, item); kept += 1
                if kept >= pool:
                    break
            f.write(f"{sp}\ttop\t{total[sp]}\t{kept}\t\n")
    del pools
    kept = 0
    with open(out / 'inat-photos-cline.tsv', 'w') as f:
        f.write('photo_id\textension\tlicense\twidth\theight\tposition\tobservation_uuid\tobserver_id\tobserved_on\tlatitude\tlongitude\tinat_taxon_id\ttaxon\n')
        for r in stream('photos'):
            hit = chosen.get(r['observation_uuid'])
            if hit is None or r['position'] != '0':
                continue
            sp, item = hit
            f.write('\t'.join((r['photo_id'], r['extension'], r['license'], r['width'], r['height'], r['position'], item[1], item[2], item[3],
                               item[4], item[5], item[6], sp)) + '\n')
            kept += 1
    print(kept, 'photographs in the manifest', flush=True)


def analyse(outdir, min_share=0.08, min_obs=300):
    """Predicted flower colour against climate within each species (``cline/pred.npz``; the head never saw the genus).

    For each species the colour forms are the classes with a mean predicted probability of ``min_share`` or more. For each form:
    regression of logit(p) on temperature, log precipitation, elevation (standardised within the species), latitude and longitude
    reported as correlations, intervals from a bootstrap over 1-degree blocks. Photographs that the head does not read as showing
    a flower colour with confidence are kept: the head gives a distribution in every case.
    Across species: the same slopes for the contrast pigmented (blue, purple, pink, red) against white, with a sign test.
    Writes cline/clines.tsv and cline/summary.json."""
    import json
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    H = Path(outdir); C = H / 'cline'; W = H / 'applications' / 'worldclim'
    z = np.load(C / 'pred.npz'); classes = [str(c) for c in z['classes']]
    row = {int(p): n for n, p in enumerate(z['photo_ids'])}
    meta = [r for r in csv.DictReader(open(C / 'inat-photos-cline.tsv'), delimiter='\t') if int(r['photo_id']) in row]
    P = z['prob'][[row[int(r['photo_id'])] for r in meta]].astype(np.float64)
    lat = np.array([float(r['latitude']) for r in meta]); lon = np.array([float(r['longitude']) for r in meta])
    taxon = np.array([r['taxon'] for r in meta])
    rd = lambda f: (lambda a: np.where(a < -1e30, np.nan, a))(np.array(Image.open(W / f)).astype(np.float32))
    rr = np.clip(((90 - lat) * 6).astype(int), 0, 1079); cc = np.clip(((lon + 180) * 6).astype(int), 0, 2159)
    env = {'temperature': rd('wc2.1_10m_bio_1.tif')[rr, cc], 'precipitation': np.log10(np.maximum(rd('wc2.1_10m_bio_12.tif')[rr, cc], 10)),
           'elevation': rd('wc2.1_10m_elev.tif')[rr, cc] / 1000}
    block = np.floor(lat).astype(int) * 1000 + np.floor(lon).astype(int)
    rng = np.random.default_rng(0)
    logit = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))

    def fit(y, idx):
        """standardised slopes of y on the three climate variables, with a block bootstrap; plus r with latitude and longitude"""
        X = np.column_stack([env[k][idx] for k in env]); ok = ~np.isnan(X).any(1)
        X, yy, b = X[ok], y[ok], block[idx][ok]
        if len(yy) < min_obs or yy.std() == 0:
            return None
        Xs = (X - X.mean(0)) / np.maximum(X.std(0), 1e-9); ys = (yy - yy.mean()) / yy.std()
        A = np.column_stack([Xs, np.ones(len(ys))])
        beta = np.linalg.lstsq(A, ys, rcond=None)[0][:3]
        ub, bi = np.unique(b, return_inverse=True)
        boots = []
        for _ in range(200):
            pick = rng.integers(0, len(ub), len(ub)); w = np.bincount(pick, minlength=len(ub))[bi].astype(float)
            Aw = A * w[:, None]
            boots.append(np.linalg.lstsq(Aw.T @ A, Aw.T @ ys, rcond=None)[0][:3])
        boots = np.array(boots)
        return {'n': int(len(ys)), 'blocks': int(len(ub)), 'slope': beta.tolist(), 'low': np.percentile(boots, 2.5, 0).tolist(), 'high': np.percentile(boots, 97.5, 0).tolist(),
                'r latitude': float(np.corrcoef(lat[idx][ok], ys)[0, 1]), 'r longitude': float(np.corrcoef(lon[idx][ok], ys)[0, 1]),
                'sd climate': X.std(0).tolist()}
    src = {r['taxon']: r for r in csv.DictReader(open(C / 'species.tsv'), delimiter='\t')}
    rows, contrast = [], {}
    pig = [classes.index(c) for c in ('blue', 'purple', 'pink', 'red')]; wh = classes.index('white')
    for sp in sorted(set(taxon)):
        idx = np.flatnonzero(taxon == sp)
        mean = P[idx].mean(0)
        for j in np.argsort(-mean):
            if mean[j] < min_share or classes[j] in ('green', 'brown'):
                continue
            f = fit(logit(P[idx, j]), idx)
            if f:
                rows.append((sp, src[sp]['source'], classes[j], mean[j], f))
        if P[idx][:, pig].sum(1).mean() >= min_share and mean[wh] >= min_share:
            f = fit(np.log(np.clip(P[idx][:, pig].sum(1), 1e-4, 1)) - np.log(np.clip(P[idx, wh], 1e-4, 1)), idx)
            if f:
                contrast[sp] = f
    with open(C / 'clines.tsv', 'w') as f:
        f.write('taxon\tsource\tcolour\tmean probability\tobservations\tblocks\ttemperature\tlow\thigh\tprecipitation\tlow\thigh\televation\tlow\thigh\tr latitude\tr longitude\n')
        for sp, s, c, m, r in rows:
            f.write(f"{sp}\t{s}\t{c}\t{m:.3f}\t{r['n']}\t{r['blocks']}\t" + '\t'.join(f"{r['slope'][k]:+.3f}\t{r['low'][k]:+.3f}\t{r['high'][k]:+.3f}" for k in range(3))
                    + f"\t{r['r latitude']:+.3f}\t{r['r longitude']:+.3f}\n")
    summary = {'species': len(set(taxon)), 'photographs': len(taxon), 'pigmented against white': {}}
    for k, name in enumerate(env):
        s = np.array([c['slope'][k] for c in contrast.values()]); sig_pos = sum(c['low'][k] > 0 for c in contrast.values()); sig_neg = sum(c['high'][k] < 0 for c in contrast.values())
        boot = [np.median(s[rng.integers(0, len(s), len(s))]) for _ in range(2000)]
        summary['pigmented against white'][name] = {'species': len(s), 'median slope': float(np.median(s)), 'median 95%': [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                                                    'positive': int((s > 0).sum()), 'interval above zero': sig_pos, 'interval below zero': sig_neg}
    summary['contrast by species'] = {sp: {'n': c['n'], 'temperature': [c['slope'][0], c['low'][0], c['high'][0]], 'precipitation': [c['slope'][1], c['low'][1], c['high'][1]],
                                           'elevation': [c['slope'][2], c['low'][2], c['high'][2]], 'r latitude': c['r latitude'], 'r longitude': c['r longitude']} for sp, c in contrast.items()}
    (C / 'summary.json').write_text(json.dumps(summary, indent=1) + '\n')
    print(json.dumps(summary['pigmented against white'], indent=1))


if __name__ == '__main__':
    {'select': select, 'select_pair': select_pair, 'select_top': select_top, 'analyse': analyse}[sys.argv[1]](*sys.argv[2:])
