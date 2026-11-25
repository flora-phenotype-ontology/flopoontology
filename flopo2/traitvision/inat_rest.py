"""The remaining photographs of the observations already chosen (``inat_select.py`` kept the first two only).

An iNaturalist observation can have many photographs, and the organ a trait is about may be in a late one.
This streams the public photo table once more and writes every photograph of the chosen observations that
the manifest does not have yet, with the same columns.

    python -m flopo2.traitvision.inat_rest local-corpora/trait-vision v3      -> inat-photos-v3-rest.tsv
"""
import csv
import sys
from pathlib import Path

from flopo2.traitvision.inat_select import stream


def main(outdir, tag='v3'):
    outdir = Path(outdir)
    meta, have = {}, set()
    for r in csv.DictReader(open(outdir / f'inat-photos-{tag}.tsv'), delimiter='\t'):
        meta[r['observation_uuid']] = r
        have.add(r['photo_id'])
    print(f'{len(meta)} observations, {len(have)} photographs so far', flush=True)
    n = kept = 0
    cols = ['observation_uuid', 'observer_id', 'observed_on', 'latitude', 'longitude', 'inat_taxon_id', 'taxon']
    with open(outdir / f'inat-photos-{tag}-rest.tsv', 'w') as out:
        out.write('photo_id\textension\tlicense\twidth\theight\tposition\t' + '\t'.join(cols) + '\n')
        for r in stream('photos'):
            n += 1
            if n % 50_000_000 == 0:
                print(f'photos read: {n:,}; kept {kept:,}', flush=True)
            m = meta.get(r['observation_uuid'])
            if m is None or r['photo_id'] in have or not r['position'].isdigit():
                continue
            out.write('\t'.join([r['photo_id'], r['extension'], r['license'], r['width'], r['height'], r['position']]
                                + [m[c] for c in cols]) + '\n')
            kept += 1
    print(f'{kept} more photographs', flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:3])
