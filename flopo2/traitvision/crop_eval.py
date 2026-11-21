"""Test-time organ crops: apply whole-photo trait heads to detected organ crops of the test photos.

  python -m flopo2.traitvision.crop_eval DATA HEADS [CROPS]

Compares, per trait, on the iNaturalist observation-field test: whole photo; crops of the relevant organ
(mean, detector-score-weighted mean, max); whole photo and crops together.  Observations without a crop of
the organ fall back to the whole photo.
"""
import collections
import csv
import sys
from pathlib import Path

import numpy as np
import torch

from flopo2.traitvision.train import balanced_accuracy, bucket, load_embeddings

ORGANS = {'flower_colour': {'flower'}, 'inflorescence': {'flower'}, 'fruit_colour': {'fruit'},
          'leaf_arrangement': {'leaf', 'stem'}, 'leaf_complexity': {'leaf'}, 'leaf_margin': {'leaf'},
          'spines': {'thorn', 'stem'}, 'habit': set()}


def main(data, heads, crops='crops-field', field='field-test-v3.tsv'):
    data, heads = Path(data), Path(heads)
    wemb, wids = load_embeddings(data / 'emb-field')
    wrow = {int(p): i for i, p in enumerate(wids)}
    cemb, cids = load_embeddings(data / crops)
    crow = {int(c): i for i, c in enumerate(cids)}
    boxes = collections.defaultdict(list)          # photo -> [(organ, score, crop row)]
    for f in sorted((data / crops).glob('boxes-*.tsv')):
        for r in csv.DictReader(open(f), delimiter='\t'):
            if int(r['crop_id']) in crow:
                boxes[int(r['photo_id'])].append((r['organ'], float(r['score']), crow[int(r['crop_id'])]))
    obs = collections.defaultdict(list)
    for r in csv.DictReader(open(data / field), delimiter='\t'):
        photos = [int(p) for p in r['photos'].split('|') if int(p) in wrow]
        if photos:
            obs[r['trait']].append((r['class'], photos, r['taxon'].split()[0]))
    for hf in sorted(heads.glob('head-*.pt')):
        trait = hf.stem[5:]
        ck = torch.load(hf, map_location='cpu')
        classes = ck['classes']
        head = torch.nn.Linear(wemb.shape[1], len(classes))
        head.load_state_dict(ck['state'])
        prob = lambda x: torch.softmax(head(torch.from_numpy(x)), 1).detach().numpy()
        pw, pc = prob(wemb), prob(cemb)
        cidx = {c: i for i, c in enumerate(classes)}
        for scope in ('all', 'unseen_genera'):
            sel = [o for o in obs[trait] if o[0] in cidx and (scope == 'all' or bucket(o[2]) < 2)]
            if len(sel) < 20:
                continue
            preds = collections.defaultdict(list)
            covered = 0
            for cls, photos, _ in sel:
                whole = pw[[wrow[p] for p in photos]].mean(0)
                cr = [(s, i) for p in photos for o, s, i in boxes.get(p, []) if o in ORGANS[trait]]
                preds['whole'].append(whole.argmax())
                if not cr:
                    for k in ('crop_mean', 'crop_weighted', 'crop_max', 'whole+crop'):
                        preds[k].append(whole.argmax())
                    continue
                covered += 1
                sc = np.array([s for s, _ in cr])
                p = pc[[i for _, i in cr]]
                preds['crop_mean'].append(p.mean(0).argmax())
                preds['crop_weighted'].append((p * sc[:, None]).sum(0).argmax())
                preds['crop_max'].append(p.max(0).argmax())
                preds['whole+crop'].append((whole + p.mean(0)).argmax())
            allowed = [{cidx[c]} for c, _, _ in sel]
            print(f'{trait:17s} {scope:14s} n={len(sel):5d} with_crop={covered / len(sel):.2f}  ' + '  '.join(
                f'{k} {balanced_accuracy([int(v) for v in pv], allowed, classes)[0]:.3f}' for k, pv in preds.items()))


if __name__ == '__main__':
    main(*sys.argv[1:])
