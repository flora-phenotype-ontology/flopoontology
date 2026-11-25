"""Find plant organs in photographs with a text-prompted detector (GPU job on ORIX; standalone).

Grounding DINO is asked for leaves, flowers, fruits, stems and thorns; no plant-specific
training and no labels of ours. Output, one row per kept box:

    crop_id  photo_id  organ  score  x0  y0  x1  y1      (box corners as fractions of the image)

``crop_id`` = photo_id * 16 + rank of the box in its photo (at most 12 boxes per photo).

    python detect.py --manifest inat-photos-v3.tsv --images DIR --model DIR/detector --out boxes.tsv
"""
import argparse
import csv
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

ORGANS = ['leaf', 'flower', 'fruit', 'stem', 'thorn']
PROMPT = 'a leaf. a flower. a fruit. a stem. a thorn.'
KEEP, MIN_SIDE = 12, 0.06


SIZE = {'shortest_edge': 480, 'longest_edge': 640}


class Photos(torch.utils.data.Dataset):
    """Decodes, resizes and normalises in the loader workers, so the main process only feeds the GPU."""

    def __init__(self, rows, images, image_processor):
        self.rows, self.images = rows, images
        self.mean = torch.tensor(image_processor.image_mean).view(3, 1, 1)
        self.std = torch.tensor(image_processor.image_std).view(3, 1, 1)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        pid, ext = self.rows[i]
        try:
            im = Image.open(self.images / f'{int(pid) % 1000:03d}' / f'{pid}.{ext}').convert('RGB')
            w, h = im.size                                  # the processor's resize and normalisation, done with PIL and torch (faster)
            scale = min(SIZE['shortest_edge'] / min(w, h), SIZE['longest_edge'] / max(w, h))
            small = im.resize((max(round(w * scale), 1), max(round(h * scale), 1)), Image.BILINEAR)
            x = torch.from_numpy(np.asarray(small).copy()).permute(2, 0, 1).float().div_(255)
            x = (x - self.mean) / self.std
            return x, im.size, int(pid)
        except Exception:
            return None


def collate(batch):
    """Pad to the largest image of the batch (bottom and right), with the mask the model expects."""
    batch = [b for b in batch if b is not None]
    if not batch:
        return None
    h, w = max(b[0].shape[1] for b in batch), max(b[0].shape[2] for b in batch)
    pixels = torch.zeros(len(batch), 3, h, w)
    mask = torch.zeros(len(batch), h, w, dtype=torch.long)
    for k, (x, _, _) in enumerate(batch):
        pixels[k, :, :x.shape[1], :x.shape[2]] = x
        mask[k, :x.shape[1], :x.shape[2]] = 1
    return pixels, mask, [b[1] for b in batch], [b[2] for b in batch]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--shard', type=int, default=0)
    p.add_argument('--shards', type=int, default=1)
    p.add_argument('--batch', type=int, default=64)
    p.add_argument('--workers', type=int, default=28)
    p.add_argument('--threshold', type=float, default=0.25)
    p.add_argument('--skip', type=Path, nargs='*', help='files whose first column lists photographs to leave out')
    p.add_argument('--min-side', type=float, default=MIN_SIDE, help='smallest box side, as a share of the image side')
    p.add_argument('--prompt', help='another prompt; the matched words are then written as they are, for trying prompts')
    a = p.parse_args()
    proc = AutoProcessor.from_pretrained(a.model)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(a.model).cuda().eval()
    rows = [(r['photo_id'], r['extension'] or 'jpg') for r in csv.DictReader(open(a.manifest), delimiter='\t')]
    rows = [r for r in rows if int(r[0]) % a.shards == a.shard]
    if a.skip:                                             # photographs that already have a result
        done = {l.split('\t')[0].strip() for f in a.skip for l in open(f)}
        rows = [r for r in rows if r[0] not in done]
    loader = torch.utils.data.DataLoader(Photos(rows, a.images, proc.image_processor), batch_size=a.batch,
                                         num_workers=a.workers, collate_fn=collate, prefetch_factor=4)
    text = proc.tokenizer([a.prompt or PROMPT], return_tensors='pt').to('cuda')
    n = boxes = 0
    with open(a.out, 'w') as out, open(str(a.out) + '.seen', 'w') as seen, torch.no_grad():
        out.write('crop_id\tphoto_id\torgan\tscore\tx0\ty0\tx1\ty1\tphrase\n')    # phrase: the matched words; 'a flower a fruit' is filed under flower
        for item in loader:
            if item is None:
                continue
            pixels, mask, sizes, pids = item
            k = len(pids)
            ids = text.input_ids.expand(k, -1)
            with torch.autocast('cuda', dtype=torch.float16):
                outputs = model(pixel_values=pixels.cuda(non_blocking=True), pixel_mask=mask.cuda(non_blocking=True), input_ids=ids,
                                token_type_ids=text.token_type_ids.expand(k, -1), attention_mask=text.attention_mask.expand(k, -1))
            outputs.logits, outputs.pred_boxes = outputs.logits.float(), outputs.pred_boxes.float()
            res = proc.post_process_grounded_object_detection(
                outputs, ids, threshold=a.threshold, text_threshold=0.2, target_sizes=[s[::-1] for s in sizes])
            batch = [(type('S', (), {'size': s}), pid) for s, pid in zip(sizes, pids)]
            seen.write(''.join(f'{pid}\n' for pid in pids))
            for (im, pid), r in zip(batch, res):
                w, h = im.size
                names = r.get('text_labels', r.get('labels'))
                found = []
                for s, b, name in zip(r['scores'].tolist(), r['boxes'].tolist(), names):
                    organ = (str(name).strip() or None) if a.prompt else next((o for o in ORGANS if o in str(name)), None)
                    x0, y0, x1, y1 = max(b[0], 0) / w, max(b[1], 0) / h, min(b[2], w) / w, min(b[3], h) / h
                    if organ and x1 - x0 >= a.min_side and y1 - y0 >= a.min_side:
                        found.append((s, organ, x0, y0, x1, y1, str(name).strip()))
                for k, (s, organ, x0, y0, x1, y1, phrase) in enumerate(sorted(found, reverse=True)[:KEEP]):
                    out.write(f'{pid * 16 + k}\t{pid}\t{organ}\t{s:.3f}\t{x0:.4f}\t{y0:.4f}\t{x1:.4f}\t{y1:.4f}\t{phrase}\n')
                    boxes += 1
            n += len(batch)
            if n % (a.batch * 50) < a.batch:
                print(n, len(rows), boxes, flush=True)
    print('done', n, 'photos', boxes, 'boxes', flush=True)


if __name__ == '__main__':
    main()
