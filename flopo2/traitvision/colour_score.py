"""Score colour predictions by how far the predicted colour is from the stated one.

Exact-match accuracy counts "orange" for a red fruit as wrong as "blue". The colour value space
(``colour-space.json``, CIEDE2000 distances between the basic colours, from ``colour_space.py``) gives the
distance of every miss. Per trait and test, from the confusion counts that ``allphotos_train.py`` stores:

* exact      balanced accuracy (mean over true colours of the share predicted exactly), as before;
* near       the same, counting a prediction within NEAR colour-distance units of the truth as right
             (red/purple, red/brown, purple/blue, pink/white, orange/brown are the pairs within 15);
* distance   mean colour distance of the prediction from the truth, averaged per true colour;
* chance     the same distance when the model's predictions are dealt out at random (same share per colour);
* skill      1 - distance / chance: 0 for a model that knows nothing, 1 for a perfect one.

    python -m flopo2.traitvision.colour_score local-corpora/trait-vision RESULT.json [...]
"""
import collections
import json
import sys
from pathlib import Path

import numpy as np

NEAR = 15.0


def score(confusion, dist, near=NEAR):
    """confusion: {'true>predicted': count}; dist: {a: {b: distance}}."""
    by = collections.defaultdict(collections.Counter)
    pred = collections.Counter()
    for k, n in confusion.items():
        t, q = k.split('>')
        by[t][q] += n
        pred[q] += n
    total = sum(pred.values())
    rows = []
    for t, c in by.items():
        n = sum(c.values())
        if n < 5:
            continue
        rows.append((c[t] / n, sum(v for q, v in c.items() if dist[t][q] <= near) / n,
                     sum(v * dist[t][q] for q, v in c.items()) / n, sum(v * dist[t][q] for q, v in pred.items()) / total))
    exact, close, d, chance = (float(x) for x in np.mean(rows, 0))
    return {'n': total, 'exact': exact, 'near': close, 'distance': d, 'chance': chance, 'skill': 1 - d / chance}


def main(folder, *files):
    dist = json.loads((Path(folder) / 'colour-space.json').read_text())['class_dist']
    for f in files:
        rep = json.loads(Path(f).read_text())
        for trait, r in rep.items():
            if 'colour' not in trait or 'confusion' not in r:
                continue
            print(f'{Path(f).name}  {trait}')
            for key, conf in r['confusion'].items():
                s = score(conf, dist)
                print(f"  {key:28s} n={s['n']:5d}  exact {s['exact']:.3f}  near {s['near']:.3f}  distance {s['distance']:5.1f}"
                      f"  (chance {s['chance']:5.1f})  skill {s['skill']:.3f}")


if __name__ == '__main__':
    main(*sys.argv[1:])
