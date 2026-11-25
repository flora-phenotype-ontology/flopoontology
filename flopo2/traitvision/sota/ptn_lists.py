"""Image lists of the PlantTraitNet benchmark data that were downloaded (and extracted) on ORIX.

* ``ptn-val.tsv``        the rows of ``val/val.csv`` whose image exists (a subset of 15 of the 26 species-initial tar files,
                         about 20,600 photographs): species, genus, PFT, location and the TRY species values
                         (Height, LeafArea, SLA, Leaf_N; PlantTraitNet's own validation split, not used to train its weights)
* ``ptn-reference.tsv``  the in-situ reference data (``reference_data/<trait>.csv``): photographs of individual plants with the
                         trait measured on that plant (height in m, leaf area, SLA, leaf N), one row per photograph and trait

Columns: key (unique), path (below --root), latitude, longitude, species, genus, pft, trait, value (reference) or the four value columns (val).
Plain python (checks that files exist; login node, seconds to minutes).

    python ptn_lists.py --root DIR/sota-benchmarks/planttraitnet --out DIR/sota-out
"""
import argparse
import csv
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / 'ptn-val.tsv', 'w') as f:
        cols = ['key', 'path', 'latitude', 'longitude', 'species', 'genus', 'pft', 'Height', 'LeafArea', 'SLA', 'Leaf_N']
        f.write('\t'.join(cols) + '\n')
        n = 0
        for r in csv.DictReader(open(a.root / 'val' / 'val.csv')):
            vals = [r[c] for c in ('Height', 'LeafArea', 'SLA', 'Leaf_N')]
            if all(v not in ('', 'NA', 'nan') for v in vals) and (a.root / r['Image']).exists():
                f.write('\t'.join([r['Image'], r['Image'], r['Latitude'], r['Longitude'], r['Species'], r['Species'].split()[0],
                                   r['PFT'], r['Height'], r['LeafArea'], r['SLA'], r['Leaf_N']]) + '\n')
                n += 1
    print('val photographs', n)
    cols = ['key', 'path', 'latitude', 'longitude', 'species', 'genus', 'pft', 'trait', 'value']
    names = {'plant_height.csv': ('Height', 'Height'), 'leaf_area.csv': ('LeafArea', 'LeafArea'),
             'specific_leaf_area.csv': ('SLA', 'SLA'), 'leaf_nitrogen.csv': ('Leaf_N', 'Leaf_N')}
    tot = 0
    with open(a.out / 'ptn-reference.tsv', 'w') as f:
        f.write('\t'.join(cols) + '\n')
        for fn, (trait, col) in names.items():
            k = 0
            for r in csv.DictReader(open(a.root / 'reference_data' / fn)):
                if r.get(col) in (None, '') or not (a.root / r['Image']).exists():
                    continue
                sp = (r.get('Species') or '').strip()
                if not sp:
                    continue
                f.write('\t'.join([f"{trait}:{r['id']}", r['Image'], r['Latitude'], r['Longitude'], sp, sp.split()[0], r['PFT'],
                                   trait, r[col]]) + '\n')
                k += 1
            print('reference', trait, k)
            tot += k


if __name__ == '__main__':
    main()
