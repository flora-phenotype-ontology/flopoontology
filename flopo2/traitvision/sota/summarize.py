"""Collect the results of the SOTA comparison jobs into markdown tables (plain python, login node).

    python summarize.py DIR/sota-out > sota-results.md
"""
import collections
import glob
import json
import sys
from pathlib import Path

import numpy as np


def main(out):
    out = Path(out)
    print('## Probe on our tests (balanced accuracy; mean over seeds)\n')
    rows = collections.defaultdict(dict)
    for f in sorted(glob.glob(str(out / 'probe-*' / 'probe.json'))):
        for key, per in json.load(open(f)).items():
            name, seed = key.split('|')
            for trait, v in per.items():
                if trait != 'mean':
                    rows[name].setdefault(trait, []).append((v['agreed'], v['observers']))
    traits = sorted({t for r in rows.values() for t in r})
    if rows:
        print('| encoder | ' + ' | '.join(traits) + ' | mean |\n|---|' + '---|' * (len(traits) + 1))
        for test, k in (('agreed species', 0), ('observers', 1)):
            for name, r in rows.items():
                cells = []
                for t in traits:
                    v = [x[k] for x in r.get(t, []) if x[k] is not None]
                    cells.append(f'{np.mean(v):.3f}' if v else '-')
                vals = [float(c) for c in cells if c != '-']
                print(f'| {name} ({test}) | ' + ' | '.join(cells) + f' | {np.mean(vals):.3f} |' if vals else '')
    for f, title in (('phenovision/phenology-compare.json', 'PhenoVision vs our phenology head (iNaturalist annotations)'),
                     ('plantnet-organ/plantnet-organ.json', 'Pl@ntNet-300K organ head'),
                     ('ptn/ptn-scores.json', 'PlantTraitNet benchmark photographs')):
        p = out / f
        if p.exists():
            print(f'\n## {title}\n\n```json\n{p.read_text()}```')


if __name__ == '__main__':
    main(sys.argv[1])
