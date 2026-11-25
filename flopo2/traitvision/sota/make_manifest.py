"""One photo list for every model of the SOTA comparison, so that all of them are scored on the same photographs.

Roles (a photograph can have several):
  train  at most --per-species photographs (default 8, fixed by a hash) of every species that has flora labels
  field  every photograph of the observations with an observer's value (field-test-v3.tsv / field-obs-photos.tsv)
  pheno  every photograph of the observations with an iNaturalist phenology annotation (phenology-v3.tsv)
  small  the first 3 (of those 8) photographs of every labelled species, for slow models (Schiller CNNs at 512 px)
  all    every photograph of inat-photos-v3-all.tsv (1.56 million; only for cheap models such as PhenoVision)

Writes ``sota-photos.tsv``: photo_id, extension, image_dir, role, taxon, observation, latitude, longitude,
month (empty when unknown). Plain python; run it on the ORIX login node (a few seconds, no GPU).

    python make_manifest.py --data DIR [--coords DIR/field-coords.tsv]
"""
import argparse
import collections
import csv
import hashlib
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--coords', type=Path)
    p.add_argument('--per-species', type=int, default=8)
    a = p.parse_args()
    D = a.data
    rd = lambda f: csv.DictReader(open(D / f, newline=''), delimiter='\t')
    labelled = {r['taxon'] for r in rd('pilot-labels-v3.tsv')}
    pheno = {r['observation_uuid'] for r in rd('phenology-v3.tsv') if r['values'] and r['values'] != 'gone'}
    rows = collections.OrderedDict()                       # photo id -> dict

    def add(pid, ext, image_dir, role, taxon, obs, lat, lon, date):
        r = rows.get(pid)                                  # lists, not dicts: 1.7 million rows
        if r is None:
            r = rows[pid] = [pid, ext or 'jpg', image_dir, set(), sys.intern(taxon), obs, lat, lon, (date or '')[5:7]]
        r[3].add(role)

    per = collections.defaultdict(list)
    for r in rd('inat-photos-v3-all.tsv'):
        add(r['photo_id'], r['extension'], 'images', 'all', r['taxon'], r['observation_uuid'], r['latitude'],
            r['longitude'], r['observed_on'])
        if r['taxon'] in labelled:
            per[r['taxon']].append((hashlib.md5(r['photo_id'].encode()).hexdigest(), r))
        if r['observation_uuid'] in pheno:
            add(r['photo_id'], r['extension'], 'images', 'pheno', r['taxon'], r['observation_uuid'], r['latitude'],
                r['longitude'], r['observed_on'])
    for taxon, lst in per.items():
        for k, (_, r) in enumerate(sorted(lst, key=lambda t: t[0])[:a.per_species]):
            for role in (('train', 'small') if k < 3 else ('train',)):
                add(r['photo_id'], r['extension'], 'images', role, taxon, r['observation_uuid'], r['latitude'],
                    r['longitude'], r['observed_on'])
    coords = {}
    if a.coords and a.coords.exists():
        coords = {r['observation']: r for r in csv.DictReader(open(a.coords), delimiter='\t')}
    taxon_of = {r['observation']: r['taxon'] for r in rd('field-test-v3.tsv')}
    for r in rd('field-obs-photos.tsv'):
        c = coords.get(r['observation'], {})
        add(r['photo_id'], r['extension'], 'field/images', 'field', taxon_of.get(r['observation'], ''), r['observation'],
            c.get('latitude', ''), c.get('longitude', ''), c.get('observed_on', ''))
    cols = ['photo_id', 'extension', 'image_dir', 'role', 'taxon', 'observation', 'latitude', 'longitude', 'month']
    with open(D / 'sota-photos.tsv', 'w') as f:
        f.write('\t'.join(cols) + '\n')
        for r in rows.values():
            r[3] = ','.join(sorted(r[3]))
            f.write('\t'.join(str(c) for c in r) + '\n')
    print(len(rows), 'photographs;', collections.Counter(x for r in rows.values() for x in r[3].split(',')))


if __name__ == '__main__':
    main()
