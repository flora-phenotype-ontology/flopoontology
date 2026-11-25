"""Per species: the mean of the photographs' predictions of ``baseline_v2.py`` (each made by a model that saw no
species of the genus). Writes ``species-pred.tsv.gz``: taxon, trait, photographs, values (class=prob;... or the size).

    python species_pred.py DIR/inat-photos-v3-all.tsv DIR/baseline-v5
"""
import csv
import gzip
import sys
from pathlib import Path

import numpy as np


def main(photos, folder):
    folder = Path(folder)
    taxon = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(photos), delimiter='\t')}
    with gzip.open(folder / 'species-pred.tsv.gz', 'wt') as out:
        out.write('taxon\ttrait\tphotographs\tvalues\n')
        for f in sorted(folder.glob('pred-*.npz')):
            z = np.load(f)
            names, inv = np.unique(np.array([taxon[int(i)] for i in z['photo_ids']]), return_inverse=True)
            if f.name == 'pred-sizes.npz':
                p = z['pred'].astype(np.float32)
                s = np.zeros((len(names), p.shape[1]), np.float32); np.add.at(s, inv, p)
                n = np.bincount(inv, minlength=len(names))
                for k, size in enumerate(z['sizes']):
                    for t, v, c in zip(names, s[:, k] / n, n):
                        out.write(f'{t}\t{size}\t{c}\t{v:.4f}\n')
                continue
            w = z['chosen'].astype(np.float32)
            p = z['prob'].astype(np.float32) * w[:, None]
            s = np.zeros((len(names), p.shape[1]), np.float32); np.add.at(s, inv, p)
            n = np.bincount(inv, weights=w, minlength=len(names))
            trait = f.stem[5:]
            for t, v, c in zip(names, s, n):
                if c > 0:
                    out.write(f'{t}\t{trait}\t{int(c)}\t' + ';'.join(f'{k}={x / c:.3f}' for k, x in zip(z['classes'], v)) + '\n')
            print(trait, len(names), flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:])
