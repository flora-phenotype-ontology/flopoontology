"""Download the photographs of a manifest from the iNaturalist Open Data bucket (resumable).

Standalone (standard library only) so it runs anywhere. Images are the "medium" size (longest
side 500 px) and go to ``<out>/images/<photo_id % 1000>/<photo_id>.<ext>``.

    python download.py inat-photos.tsv /mnt/data/u/hohndor/flopo-vision/pilot-v1 [--threads 24]
"""
import argparse
import csv
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = 'https://inaturalist-open-data.s3.amazonaws.com/photos'


def path_for(out, photo_id, ext):
    return out / 'images' / f'{int(photo_id) % 1000:03d}' / f'{photo_id}.{ext}'


def fetch(job):
    out, photo_id, ext = job
    target = path_for(out, photo_id, ext)
    if target.exists() and target.stat().st_size > 0:
        return 'have'
    for attempt in range(4):
        try:
            req = urllib.request.Request(f'{BUCKET}/{photo_id}/medium.{ext}', headers={'User-Agent': 'research-client/1.0'})
            data = urllib.request.urlopen(req, timeout=60).read()
            tmp = target.with_suffix('.part')
            tmp.write_bytes(data)
            tmp.rename(target)
            return 'ok'
        except Exception as exc:
            if getattr(exc, 'code', None) in (403, 404):
                return 'missing'
            time.sleep(2 * (attempt + 1))
    return 'failed'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('manifest', type=Path)
    p.add_argument('out', type=Path)
    p.add_argument('--threads', type=int, default=24)
    a = p.parse_args()
    for i in range(1000):
        (a.out / 'images' / f'{i:03d}').mkdir(parents=True, exist_ok=True)
    jobs = [(a.out, r['photo_id'], r['extension'] or 'jpg')
            for r in csv.DictReader(open(a.manifest), delimiter='\t')]
    counts, done, start = {}, 0, time.time()
    with ThreadPoolExecutor(a.threads) as pool:
        for status in pool.map(fetch, jobs):
            counts[status] = counts.get(status, 0) + 1
            done += 1
            if done % 20000 == 0:
                print(done, len(jobs), counts, f'{done / (time.time() - start):.0f}/s', flush=True)
    print('done', counts, flush=True)


if __name__ == '__main__':
    main()
