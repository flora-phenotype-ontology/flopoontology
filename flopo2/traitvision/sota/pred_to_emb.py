"""Turn the continuous trait predictions of PlantTraitNet / Schiller into a tiny "embedding" folder (emb-0.npy / emb-0.ids), so that
``probe_any.py --head linear --standardize`` can ask: how much of OUR categorical traits (habit, leaf margin, ...) is already in the
numbers a TRY-trained model predicts (height, leaf area, SLA, leaf N, seed mass, wood density)?

    python pred_to_emb.py --pred DIR/sota-out/planttraitnet/pred.npz --kind planttraitnet --out DIR/sota-out/planttraitnet-pred
    python pred_to_emb.py --pred DIR/sota-out/schiller/pred.npz      --kind schiller      --out DIR/sota-out/schiller-pred

PlantTraitNet: the mean of the three multi-trait seeds for each of the four traits, plus the four single-trait seed-0 models (8 columns),
and their log-variances as uncertainty (4 columns). Schiller: the architecture ensembles (six columns). Photographs without a location
are dropped for PlantTraitNet. Plain numpy; seconds, login node.
"""
import argparse
from pathlib import Path

import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pred', type=Path, required=True)
    p.add_argument('--kind', required=True, choices=['planttraitnet', 'schiller'])
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    z = np.load(a.pred, allow_pickle=False)
    if a.kind == 'planttraitnet':
        multi = np.mean([z[f'multitrait_seed{s}_mu'] for s in (0, 100, 200)], 0)                    # (n, 4)
        lv = np.mean([z[f'multitrait_seed{s}_logvar'] for s in (0, 100, 200)], 0)
        single = np.concatenate([z[f'singletrait_{k}_seed0_mu'] for k in ('plantheight', 'LA', 'sla', 'LN')], 1)
        X = np.concatenate([multi, single, lv], 1)
        keep = z['has_geo']
    else:
        cols = [k for k in z.files if k.startswith('ens_')]
        X = np.stack([z[k] for k in cols], 1)
        keep = np.ones(len(X), bool)
    a.out.mkdir(parents=True, exist_ok=True)
    np.save(a.out / 'emb-0.npy', X[keep].astype(np.float32))
    (a.out / 'emb-0.ids').write_text('\n'.join(z['ids'][keep]) + '\n')
    print(a.kind, X[keep].shape)


if __name__ == '__main__':
    main()
