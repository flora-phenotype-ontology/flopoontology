"""Choose iNaturalist photographs for the pilot taxa from the iNaturalist Open Data metadata.

Streams the public metadata tables (nothing but the small taxon table is stored), so it needs
no API calls and no disk. All photographs in that bucket carry a Creative Commons licence, which
is kept per photograph. Sampling is by hash of the observation id, so a rerun gives the same choice.

    python -m flopo2.traitvision.inat_select local-corpora/trait-vision

Run ``names.py`` first: it maps iNaturalist taxa (synonyms and infraspecific taxa included) to our
accepted species names. Writes ``inat-photos-TAG.tsv`` (the manifest).
"""
import collections
import csv
import hashlib
import heapq
import subprocess
import sys
from pathlib import Path

BUCKET = 'https://inaturalist-open-data.s3.amazonaws.com'
POOL, KEEP, PER_OBSERVER, PHOTOS = 60, 30, 3, 2


def stream(name):
    """Lines of a gzip-compressed table of the bucket, decompressed on the fly."""
    proc = subprocess.Popen(f"curl -s -A research-client/1.0 {BUCKET}/{name}.csv.gz | gzip -dc",
                            shell=True, stdout=subprocess.PIPE, text=True, bufsize=1 << 20)
    header = proc.stdout.readline().rstrip('\n').split('\t')
    for line in proc.stdout:
        yield dict(zip(header, line.rstrip('\n').split('\t')))


def taxa(outdir, tag):
    """iNaturalist taxon id -> our accepted species name (table written by ``names.py``)."""
    return {r['inat_taxon_id']: r['taxon'] for r in csv.DictReader(open(outdir / f'inat-names-{tag}.tsv'), delimiter='\t')}


def main(outdir, tag='v2'):
    outdir = Path(outdir)
    to_species = taxa(outdir, tag)
    print(f'{len(set(to_species.values()))} pilot species have iNaturalist taxa', flush=True)

    pools = collections.defaultdict(list)     # species name -> heap of (-hash, uuid, observer, date, lat, lon)
    n = 0
    for r in stream('observations'):
        n += 1
        if n % 20_000_000 == 0:
            print(f'observations read: {n:,}', flush=True)
        sp = to_species.get(r['taxon_id'])
        if sp is None or r['quality_grade'] != 'research':
            continue
        h = int(hashlib.md5(r['observation_uuid'].encode()).hexdigest()[:12], 16)
        item = (-h, r['observation_uuid'], r['observer_id'], r['observed_on'], r['latitude'], r['longitude'], r['taxon_id'])
        heap = pools[sp]
        if len(heap) < POOL:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    chosen = {}
    for sp, heap in pools.items():
        per_observer, kept = collections.Counter(), 0
        for item in sorted(heap, reverse=True):
            if per_observer[item[2]] >= PER_OBSERVER:
                continue
            per_observer[item[2]] += 1
            chosen[item[1]] = (sp, item)
            kept += 1
            if kept >= KEEP:
                break
    print(f'{len(chosen)} observations chosen for {len(pools)} taxa', flush=True)

    n = kept = 0
    with open(outdir / f'inat-photos-{tag}.tsv', 'w') as out:
        out.write('photo_id\textension\tlicense\twidth\theight\tposition\tobservation_uuid\tobserver_id\t'
                  'observed_on\tlatitude\tlongitude\tinat_taxon_id\ttaxon\n')
        for r in stream('photos'):
            n += 1
            if n % 50_000_000 == 0:
                print(f'photos read: {n:,}; kept {kept:,}', flush=True)
            hit = chosen.get(r['observation_uuid'])
            if hit is None or not r['position'].isdigit() or int(r['position']) >= PHOTOS:
                continue
            sp, item = hit
            out.write('\t'.join((r['photo_id'], r['extension'], r['license'], r['width'], r['height'], r['position'],
                                 item[1], item[2], item[3], item[4], item[5], item[6], sp)) + '\n')
            kept += 1
    print(f'{kept} photographs in the manifest', flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:3])
