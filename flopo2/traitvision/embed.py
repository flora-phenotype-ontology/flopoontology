"""BioCLIP 2 image embeddings for a photo manifest (GPU job on ORIX; standalone).

Writes ``<out>/emb-<shard>.npy`` (float16, L2-normalized, one row per readable photo) and
``<out>/emb-<shard>.ids`` (photo ids, same order). Also writes the text embeddings of a prompt
file when given, so that organ visibility and zero-shot baselines use the same model.

    python embed.py --manifest inat-photos.tsv --images DIR --model DIR/bioclip2 --out DIR/emb \
        --shard 0 --shards 4 [--prompts prompts.tsv]
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image


class Photos(torch.utils.data.Dataset):
    def __init__(self, rows, images, transform):
        self.rows, self.images, self.transform = rows, images, transform

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        pid, ext = self.rows[i]
        try:
            im = Image.open(self.images / f'{int(pid) % 1000:03d}' / f'{pid}.{ext}').convert('RGB')
            return self.transform(im), int(pid), True
        except Exception:
            return torch.zeros(3, 224, 224), int(pid), False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--shard', type=int, default=0)
    p.add_argument('--shards', type=int, default=1)
    p.add_argument('--prompts', type=Path)
    p.add_argument('--tag', help='name of the output pair (default: the shard number)')
    p.add_argument('--batch', type=int, default=512)
    p.add_argument('--workers', type=int, default=14)
    a = p.parse_args()
    tag = a.tag or a.shard
    a.out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((a.model / 'open_clip_config.json').read_text())
    model, _, transform = open_clip.create_model_and_transforms(
        'ViT-L-14', pretrained=str(a.model / 'open_clip_model.safetensors'), device='cuda',
        image_mean=cfg['preprocess_cfg']['mean'], image_std=cfg['preprocess_cfg']['std'])
    model.eval()
    if a.prompts and a.shard == 0:
        tok = open_clip.get_tokenizer('ViT-L-14')
        rows = [r for r in csv.DictReader(open(a.prompts), delimiter='\t')]
        with torch.no_grad():
            t = torch.nn.functional.normalize(model.encode_text(tok([r['prompt'] for r in rows]).cuda()), dim=-1)
        np.save(a.out / 'text.npy', t.float().cpu().numpy())
        (a.out / 'text.tsv').write_text(''.join(f"{r['key']}\t{r['prompt']}\n" for r in rows))
    rows = [(r['photo_id'], r['extension'] or 'jpg') for r in csv.DictReader(open(a.manifest), delimiter='\t')]
    rows = [r for r in rows if int(r[0]) % a.shards == a.shard]
    loader = torch.utils.data.DataLoader(Photos(rows, a.images, transform), batch_size=a.batch, num_workers=a.workers)
    embs, ids = [], []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
        for n, (x, pid, ok) in enumerate(loader):
            z = torch.nn.functional.normalize(model.encode_image(x.cuda(non_blocking=True)).float(), dim=-1)
            embs.append(z[ok.cuda()].half().cpu().numpy())
            ids.extend(int(i) for i, k in zip(pid, ok) if k)
            if n % 50 == 0:
                print(n * a.batch, len(rows), flush=True)
    np.save(a.out / f'emb-{tag}.npy', np.concatenate(embs))
    (a.out / f'emb-{tag}.ids').write_text('\n'.join(map(str, ids)) + '\n')
    print('done', len(ids), 'of', len(rows), flush=True)


if __name__ == '__main__':
    main()
