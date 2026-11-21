"""BioCLIP 2 embeddings of the organ crops found by ``detect.py`` (GPU job on ORIX; standalone).

Each box is widened by a tenth on every side, cut out and embedded like a photo. Writes
``<out>/emb-<tag>.npy`` and ``.ids`` (crop ids), the layout ``train.py`` reads.

    python embed_crops.py --boxes boxes.tsv --manifest inat-photos-v3.tsv --images DIR \
        --model DIR/bioclip2 --out DIR/emb-crops --tag 0
"""
import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image


class Crops(torch.utils.data.Dataset):
    """One item per photo: the photo is decoded once (at reduced size) and all its crops are cut from it."""

    def __init__(self, photos, ext, images, transform):
        self.photos, self.ext, self.images, self.transform = photos, ext, images, transform

    def __len__(self):
        return len(self.photos)

    def __getitem__(self, i):
        pid, boxes = self.photos[i]
        try:
            im = Image.open(self.images / f'{pid % 1000:03d}' / f'{pid}.{self.ext.get(pid, "jpg")}')
            im.draft('RGB', (1024, 1024))            # JPEG: decode at a reduced scale, several times faster
            im = im.convert('RGB')
            w, h = im.size
            out = []
            for cid, x0, y0, x1, y1 in boxes:
                mx, my = 0.1 * (x1 - x0), 0.1 * (y1 - y0)
                box = (max(0, (x0 - mx) * w), max(0, (y0 - my) * h), min(w, (x1 + mx) * w), min(h, (y1 + my) * h))
                out.append(self.transform(im.crop(tuple(int(v) for v in box))))
            return torch.stack(out), [b[0] for b in boxes]
        except Exception:
            return torch.zeros(0, 3, 224, 224), []


def collate(batch):
    return torch.cat([b[0] for b in batch]), [c for b in batch for c in b[1]]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--boxes', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--tag', default='0')
    p.add_argument('--batch', type=int, default=64, help='photos per batch (about 5 crops each)')
    p.add_argument('--workers', type=int, default=max(2, len(os.sched_getaffinity(0)) - 2))
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((a.model / 'open_clip_config.json').read_text())
    model, _, transform = open_clip.create_model_and_transforms(
        'ViT-L-14', pretrained=str(a.model / 'open_clip_model.safetensors'), device='cuda',
        image_mean=cfg['preprocess_cfg']['mean'], image_std=cfg['preprocess_cfg']['std'])
    model.eval()
    ext = {int(r['photo_id']): r['extension'] or 'jpg' for r in csv.DictReader(open(a.manifest), delimiter='\t')}
    by_photo = {}
    for r in csv.DictReader(open(a.boxes), delimiter='\t'):
        by_photo.setdefault(int(r['photo_id']), []).append(
            (int(r['crop_id']), float(r['x0']), float(r['y0']), float(r['x1']), float(r['y1'])))
    photos = list(by_photo.items())
    total = sum(len(b) for _, b in photos)
    loader = torch.utils.data.DataLoader(Crops(photos, ext, a.images, transform), batch_size=a.batch, num_workers=a.workers,
                                         collate_fn=collate, prefetch_factor=2)
    embs, ids = [], []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
        for n, (x, cid) in enumerate(loader):
            if not cid:
                continue
            z = torch.nn.functional.normalize(model.encode_image(x.cuda(non_blocking=True)).float(), dim=-1)
            embs.append(z.half().cpu().numpy())
            ids.extend(cid)
            if n % 100 == 0:
                print(len(ids), total, flush=True)
    np.save(a.out / f'emb-{a.tag}.npy', np.concatenate(embs))
    (a.out / f'emb-{a.tag}.ids').write_text('\n'.join(map(str, ids)) + '\n')
    print('done', len(ids), 'of', total, flush=True)


if __name__ == '__main__':
    main()
