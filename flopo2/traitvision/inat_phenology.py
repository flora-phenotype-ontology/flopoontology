"""Fetch iNaturalist's plant phenology annotations for our observations (flowering, fruiting, budding).

The annotations are made by observers and identifiers on the observation; they are not in the open-data dump,
so they come from the public API, 200 observations per request, a few requests at a time. Annotations voted
down (vote score below 0) are left out. The run can be stopped and started again.

    python -m flopo2.traitvision.inat_phenology local-corpora/trait-vision [TAG]

Writes ``phenology-<TAG>.tsv``: observation_uuid, observation, values (flowering|fruiting|budding|none, '' when
the observation has no phenology annotation), photos (photo ids in the order shown).
"""
import csv
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VALUES = {13: 'flowering', 14: 'fruiting', 15: 'budding', 21: 'none'}
API = 'https://api.inaturalist.org/v1/observations?per_page=200&uuid='


def fetch(uuids):
    for attempt in range(8):
        try:
            req = urllib.request.Request(API + ','.join(uuids), headers={'User-Agent': 'research-client/1.0'})
            return json.load(urllib.request.urlopen(req, timeout=120))['results']
        except Exception:
            time.sleep(20 * (attempt + 1))
    return []


def main(folder, tag='v3'):
    folder = Path(folder)
    out = folder / f'phenology-{tag}.tsv'
    uuids = list(dict.fromkeys(r['observation_uuid'] for r in csv.DictReader(open(folder / f'inat-photos-{tag}.tsv'), delimiter='\t')))
    done = set()
    if out.exists():
        done = {l.split('\t')[0] for l in open(out)}
    todo = [u for u in uuids if u not in done]
    chunks = [todo[i:i + 200] for i in range(0, len(todo), 200)]
    print(len(uuids), 'observations', len(todo), 'to fetch', flush=True)
    with open(out, 'a') as f, ThreadPoolExecutor(3) as pool:
        if not done:
            f.write('observation_uuid\tobservation\tvalues\tphotos\n')
        for n, (chunk, res) in enumerate(zip(chunks, pool.map(fetch, chunks))):
            got = set()
            for o in res:
                vals = sorted({VALUES[a['controlled_value_id']] for a in o.get('annotations') or []
                               if a.get('controlled_attribute_id') == 12 and a.get('controlled_value_id') in VALUES
                               and (a.get('vote_score') or 0) >= 0})
                photos = '|'.join(str(p['id']) for p in o.get('photos') or [])
                f.write(f"{o['uuid']}\t{o['id']}\t{'|'.join(vals)}\t{photos}\n")
                got.add(o['uuid'])
            if res:                                        # observations that no longer exist
                for u in set(chunk) - got:
                    f.write(f'{u}\t\tgone\t\n')
            f.flush()
            if n % 50 == 0:
                print(n, len(chunks), flush=True)
    print('done', flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:3])
