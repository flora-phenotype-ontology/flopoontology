"""PhenoVision (flower / fruit presence) and PhenoVisionL (green leaves / coloured leaves / breaking buds) on our photographs.

Published models of Phenobase (Hugging Face ``phenobase/phenovision`` and ``phenovisionL``, MIT), ViT-L/16, sigmoid outputs.
The label order is read from each ``config.json`` (the card says PhenoVision answers [fruit, flower]).
Preprocessing follows ``preprocessor_config.json``: resize the short side to 256 (bicubic), centre crop 224, ImageNet
statistics.

    python run_phenovision.py --data DIR --manifest sota-photos.tsv --models MODELDIR --out DIR/sota-out/phenovision [--roles pheno,field,train]

Writes ``scores.npz``: ids (photo ids), per model ``<name>_prob`` (n, n_labels) and ``<name>_labels``.
GPU job (see tools/orix/traitvision_sota_phenovision.sbatch); the scoring is ``score_phenology.py``.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from common import imagenet_transform, loader, photo_file, tsv


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--manifest', default='sota-photos.tsv')
    p.add_argument('--models', type=Path, required=True, help='folder holding phenovision/hf and phenovisionL/hf')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--roles', default='all,field', help='comma-separated manifest roles')
    p.add_argument('--batch', type=int, default=384)
    p.add_argument('--workers', type=int, default=44)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    from transformers import AutoModelForImageClassification
    roles = set(a.roles.split(','))
    rows = [r for r in tsv(a.data / a.manifest) if roles & set(r['role'].split(','))]
    items = [photo_file(a.data, r['image_dir'], r['photo_id'], r['extension']) for r in rows]
    nets = {}
    for name in ('phenovision', 'phenovisionL'):
        net = AutoModelForImageClassification.from_pretrained(a.models / name / 'hf', torch_dtype=torch.float16).cuda().eval()
        nets[name] = (net, [net.config.id2label[i] for i in range(net.config.num_labels)])
        print(name, nets[name][1], flush=True)
    probs = {n: [] for n in nets}
    ids, ok_all = [], []
    dl = loader(items, imagenet_transform(), a.batch, a.workers)
    with torch.no_grad():
        for k, (x, idx, ok) in enumerate(dl):
            x = x.cuda(non_blocking=True).half()
            for n, (net, _) in nets.items():
                probs[n].append(torch.sigmoid(net(pixel_values=x).logits.float()).cpu().numpy())       # one read of each batch, both models
            ids += [int(rows[i]['photo_id']) for i in idx]
            ok_all += ok.tolist()
            if k % 50 == 0:
                print(k * a.batch, len(items), flush=True)
    ok_all = np.array(ok_all)
    out = {'ids': np.array(ids)[ok_all]}
    for n, (_, labels) in nets.items():
        out[f'{n}_prob'] = np.concatenate(probs[n])[ok_all].astype(np.float32)
        out[f'{n}_labels'] = np.array(labels)
    np.savez(a.out / 'scores.npz', **out)
    print('done', int(ok_all.sum()), 'of', len(items), flush=True)


if __name__ == '__main__':
    main()
