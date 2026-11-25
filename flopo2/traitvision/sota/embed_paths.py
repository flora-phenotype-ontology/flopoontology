"""BioCLIP 2 image embeddings for a list of image files (benchmark images that are not in the pilot-v1 photo-id layout).

``--list`` is a TSV with columns ``key`` and ``path`` (a file below ``--root``, or a member of ``--zip``). Writes
``<out>/emb-0.npy`` (float16, L2-normalised, rows in list order minus unreadable files) and ``<out>/emb-0.keys``.
Same model and preprocessing as ``embed.py`` (OpenCLIP ViT-L/14 BioCLIP 2 weights, its own mean/std); JPEGs are decoded at reduced size.

    python embed_paths.py --list L.tsv --root DIR --model DIR/staged-models-v1/bioclip2 --out DIR/emb-x
    python embed_paths.py --list L.tsv --zip plantnet_300K.zip --model ... --out ...
GPU job: tools/orix/traitvision_sota_benchmarks.sbatch
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import open_clip
import torch

from common import loader


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--list', type=Path, required=True)
    p.add_argument('--root', type=Path)
    p.add_argument('--zip', type=Path)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--batch', type=int, default=512)
    p.add_argument('--workers', type=int, default=44)
    p.add_argument('--limit', type=int, default=0)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((a.model / 'open_clip_config.json').read_text())
    model, _, transform = open_clip.create_model_and_transforms(
        'ViT-L-14', pretrained=str(a.model / 'open_clip_model.safetensors'), device='cuda',
        image_mean=cfg['preprocess_cfg']['mean'], image_std=cfg['preprocess_cfg']['std'])
    model.eval()
    rows = list(csv.DictReader(open(a.list), delimiter='\t'))
    if a.limit:
        rows = rows[:a.limit]
    items = [(str(a.zip), r['path']) if a.zip else a.root / r['path'] for r in rows]
    dl = loader(items, transform, a.batch, a.workers, min_side=224)
    embs, got = [], []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
        for n, (x, idx, ok) in enumerate(dl):
            z = torch.nn.functional.normalize(model.encode_image(x.cuda(non_blocking=True)).float(), dim=-1)
            embs.append(z[ok.cuda()].half().cpu().numpy())
            got += [int(i) for i, k in zip(idx, ok) if k]
            if n % 50 == 0:
                print(n * a.batch, len(items), flush=True)
    np.save(a.out / 'emb-0.npy', np.concatenate(embs))
    (a.out / 'emb-0.keys').write_text('\n'.join(rows[i]['key'] for i in got) + '\n')
    print('done', len(got), 'of', len(items), flush=True)


if __name__ == '__main__':
    main()
