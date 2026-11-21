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

import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

ORGANS = ['leaf', 'flower', 'fruit', 'stem', 'thorn']
PROMPT = 'a leaf. a flower. a fruit. a stem. a thorn.'
KEEP, MIN_SIDE = 12, 0.06


class Photos(torch.utils.data.Dataset):
    def __init__(self, rows, images):
        self.rows, self.images = rows, images

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        pid, ext = self.rows[i]
        try:
            return Image.open(self.images / f'{int(pid) % 1000:03d}' / f'{pid}.{ext}').convert('RGB'), int(pid)
        except Exception:
            return None, int(pid)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--shard', type=int, default=0)
    p.add_argument('--shards', type=int, default=1)
    p.add_argument('--batch', type=int, default=48)
    p.add_argument('--workers', type=int, default=14)
    p.add_argument('--threshold', type=float, default=0.25)
    a = p.parse_args()
    proc = AutoProcessor.from_pretrained(a.model)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(a.model).cuda().eval()
    rows = [(r['photo_id'], r['extension'] or 'jpg') for r in csv.DictReader(open(a.manifest), delimiter='\t')]
    rows = [r for r in rows if int(r[0]) % a.shards == a.shard]
    loader = torch.utils.data.DataLoader(Photos(rows, a.images), batch_size=a.batch, num_workers=a.workers,
                                         collate_fn=lambda b: [x for x in b if x[0] is not None])
    n = boxes = 0
    with open(a.out, 'w') as out, torch.no_grad():
        out.write('crop_id\tphoto_id\torgan\tscore\tx0\ty0\tx1\ty1\n')
        for batch in loader:
            if not batch:
                continue
            images = [b[0] for b in batch]
            inputs = proc(images=images, text=[PROMPT] * len(images), return_tensors='pt',
                          size={'shortest_edge': 480, 'longest_edge': 640}).to('cuda')
            with torch.autocast('cuda', dtype=torch.float16):
                outputs = model(**inputs)
            outputs.logits, outputs.pred_boxes = outputs.logits.float(), outputs.pred_boxes.float()
            res = proc.post_process_grounded_object_detection(
                outputs, inputs.input_ids, threshold=a.threshold, text_threshold=0.2,
                target_sizes=[im.size[::-1] for im in images])
            for (im, pid), r in zip(batch, res):
                w, h = im.size
                names = r.get('text_labels', r.get('labels'))
                found = []
                for s, b, name in zip(r['scores'].tolist(), r['boxes'].tolist(), names):
                    organ = next((o for o in ORGANS if o in str(name)), None)
                    x0, y0, x1, y1 = max(b[0], 0) / w, max(b[1], 0) / h, min(b[2], w) / w, min(b[3], h) / h
                    if organ and x1 - x0 >= MIN_SIDE and y1 - y0 >= MIN_SIDE:
                        found.append((s, organ, x0, y0, x1, y1))
                for k, (s, organ, x0, y0, x1, y1) in enumerate(sorted(found, reverse=True)[:KEEP]):
                    out.write(f'{pid * 16 + k}\t{pid}\t{organ}\t{s:.3f}\t{x0:.4f}\t{y0:.4f}\t{x1:.4f}\t{y1:.4f}\n')
                    boxes += 1
            n += len(batch)
            if n % (a.batch * 50) < a.batch:
                print(n, len(rows), boxes, flush=True)
    print('done', n, 'photos', boxes, 'boxes', flush=True)


if __name__ == '__main__':
    main()
