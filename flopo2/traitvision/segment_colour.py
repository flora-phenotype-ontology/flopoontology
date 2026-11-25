"""Flower colour measured on the petals: a segmentation mask inside each detected flower box (standalone; ORIX).

For every flower box (Grounding DINO, ``detect.py``) SAM is prompted with the box and returns the outline of
the object in it. The pixels inside the outline are given their nearest ISCC-NBS block (CIELAB, block centres
from ``colour_space.block_lab``) and counted; the pixels of the box outside the outline are counted separately
(the flower's own surroundings). Images are decoded and resized in the loader workers; the rest runs on the GPU.

    python segment_colour.py --boxes crops-field/boxes-0.tsv --manifest field/field-photos.tsv --images field/images \
        --model DIR/sam-vit-huge --centres block-centres.npz --out colour-segment-field.npz
"""
import argparse
import collections
import csv
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import SamModel, SamProcessor

K, SIDE = 6, 256


class Photos(torch.utils.data.Dataset):
    def __init__(self, rows, images, proc):
        self.rows, self.images, self.proc = rows, images, proc

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        pid, ext, boxes = self.rows[i]
        try:
            im = Image.open(self.images / f'{int(pid) % 1000:03d}' / f'{pid}.{ext}').convert('RGB')
        except Exception:
            return None
        w, h = im.size
        ids = [b[0] for b in boxes] + [-1] * (K - len(boxes))
        px = [[b[1] * w, b[2] * h, b[3] * w, b[4] * h] for b in boxes]
        px += [px[0]] * (K - len(px))
        x = self.proc(images=im, input_boxes=[px], return_tensors='pt')
        return x['pixel_values'][0], x['input_boxes'][0], torch.tensor(ids)


def lab_of(rgb):
    """sRGB 0..1, (..., 3) -> CIELAB (D65)."""
    c = torch.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = torch.tensor([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], device=rgb.device)
    xyz = c @ m.T / torch.tensor([0.95047, 1.0, 1.08883], device=rgb.device)
    f = torch.where(xyz > 0.008856, xyz.clamp(min=1e-8) ** (1 / 3), 7.787 * xyz + 16 / 116)
    return torch.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--boxes', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--centres', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--batch', type=int, default=24)
    p.add_argument('--workers', type=int, default=28)
    p.add_argument('--min-score', type=float, default=0.25)
    a = p.parse_args()
    proc = SamProcessor.from_pretrained(a.model)
    model = SamModel.from_pretrained(a.model).cuda().eval()
    z = np.load(a.centres)
    centres = torch.from_numpy(z['centres']).cuda()
    n_blocks = len(centres)
    ext = {r['photo_id']: r['extension'] or 'jpg' for r in csv.DictReader(open(a.manifest), delimiter='\t')}
    per = collections.defaultdict(list)
    for r in csv.DictReader(open(a.boxes), delimiter='\t'):
        if r['organ'] == 'flower' and float(r['score']) >= a.min_score and r['photo_id'] in ext:
            per[r['photo_id']].append((int(r['crop_id']), float(r['x0']), float(r['y0']), float(r['x1']), float(r['y1']), float(r['score'])))
    rows = [(pid, ext[pid], sorted(b, key=lambda t: -t[5])[:K]) for pid, b in per.items()]
    loader = torch.utils.data.DataLoader(Photos(rows, a.images, proc), batch_size=a.batch, num_workers=a.workers,
                                         collate_fn=lambda b: [x for x in b if x is not None], prefetch_factor=4)
    mean = torch.tensor(proc.image_processor.image_mean, device='cuda').view(1, 3, 1, 1)
    std = torch.tensor(proc.image_processor.image_std, device='cuda').view(1, 3, 1, 1)
    full = model.config.vision_config.image_size
    yy, xx = torch.meshgrid(torch.arange(SIDE, device='cuda'), torch.arange(SIDE, device='cuda'), indexing='ij')
    out = collections.defaultdict(list)
    done = 0
    with torch.no_grad():
        for batch in loader:
            if not batch:
                continue
            pv = torch.stack([b[0] for b in batch]).cuda(non_blocking=True)
            boxes = torch.stack([b[1] for b in batch]).cuda().float()
            ids = torch.stack([b[2] for b in batch])
            with torch.autocast('cuda', dtype=torch.float16):
                emb = model.get_image_embeddings(pv)
                res = model(image_embeddings=emb, input_boxes=boxes, multimask_output=False)
            masks = res.pred_masks[:, :, 0].float() > 0                       # B, K, 256, 256 (the padded square image)
            iou = res.iou_scores[:, :, 0].float().cpu().numpy()
            small = torch.nn.functional.interpolate(pv.float() * std + mean, size=(SIDE, SIDE), mode='bilinear', antialias=True)
            lab = lab_of(small.clamp(0, 1).permute(0, 2, 3, 1))                # B, 256, 256, 3
            block = torch.cdist(lab.reshape(len(pv), -1, 3), centres[None].expand(len(pv), -1, -1)).argmin(-1)   # B, 65536
            sb = boxes * SIDE / full
            for i in range(len(pv)):
                for k in range(K):
                    if ids[i, k] < 0:
                        continue
                    x0, y0, x1, y1 = sb[i, k]
                    rect = (xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)
                    m = (masks[i, k] & rect).reshape(-1)
                    ring = (rect.reshape(-1)) & ~m
                    n = int(m.sum())
                    hist = torch.bincount(block[i][m], minlength=n_blocks).float() / max(n, 1)
                    rhist = torch.bincount(block[i][ring], minlength=n_blocks).float() / max(int(ring.sum()), 1)
                    out['crop_ids'].append(int(ids[i, k]))
                    out['hist'].append(hist.cpu().numpy())
                    out['ring_hist'].append(rhist.cpu().numpy())
                    out['mean'].append(lab[i].reshape(-1, 3)[m].mean(0).cpu().numpy() if n else np.zeros(3, np.float32))
                    out['frac'].append(n / max(int(rect.sum()), 1))
                    out['iou'].append(float(iou[i, k]))
            done += len(pv)
            if done % (a.batch * 20) < a.batch:
                print(done, len(rows), len(out['crop_ids']), flush=True)
    np.savez(a.out, blocks=z['blocks'], centres=z['centres'], crop_ids=np.array(out['crop_ids']),
             hist=np.array(out['hist'], np.float32), ring_hist=np.array(out['ring_hist'], np.float32),
             mean=np.array(out['mean'], np.float32), frac=np.array(out['frac'], np.float32), iou=np.array(out['iou'], np.float32))
    print('done', done, 'photos', len(out['crop_ids']), 'masks', flush=True)


if __name__ == '__main__':
    main()
