"""Coordinates and dates of the observer-labelled observations (needed by PlantTraitNet, which takes a location).

The observations are those of ``field-test-v3.tsv`` and ``phenology-v3.tsv``'s sibling ``field-obs-photos.tsv``.
iNaturalist's public API gives ``location`` ("lat,lon") and ``observed_on``; obscured observations carry the
public (coarse) location. 200 observations per request, one request per second, resumable. Login-node or
laptop job (network only):

    python fetch_field_coords.py DIR/field-test-v3.tsv DIR/field-coords.tsv
"""
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

API = 'https://api.inaturalist.org/v1/observations?per_page=200&id='


def main(test, out):
    obs = list(dict.fromkeys(r['observation'] for r in csv.DictReader(open(test), delimiter='\t')))
    done = set()
    out = Path(out)
    if out.exists():
        done = {l.split('\t')[0] for l in open(out)}
    f = open(out, 'a')
    if not done:
        f.write('observation\tlatitude\tlongitude\tobserved_on\n')
    todo = [o for o in obs if o not in done]
    for i in range(0, len(todo), 200):
        chunk = todo[i:i + 200]
        for attempt in range(6):
            try:
                req = urllib.request.Request(API + ','.join(chunk), headers={'User-Agent': 'research-client/1.0'})
                res = json.load(urllib.request.urlopen(req, timeout=120))['results']
                break
            except Exception:
                time.sleep(20 * (attempt + 1))
                res = []
        got = {}
        for r in res:
            lat, lon = (r.get('location') or ',').split(',')[:2] if r.get('location') else ('', '')
            got[str(r['id'])] = (lat, lon, r.get('observed_on') or '')
        for o in chunk:                                        # every requested observation gets a row
            f.write('\t'.join([o, *got.get(o, ('', '', ''))]) + '\n')
        f.flush()
        time.sleep(1)
        print(i + len(chunk), len(todo), flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:3])
