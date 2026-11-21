"""Image (and prompt) embeddings from other published models, as baselines (GPU job; standalone).

Same output layout as ``embed.py`` so that ``train.py`` scores every model in the same way.

    python embed_any.py --kind openclip|timm|siglip --model DIR --manifest inat-photos-v2.tsv \
        --images DIR --out DIR/emb-NAME [--prompts prompts.tsv] [--size 224]
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image


class Photos(torch.utils.data.Dataset):
    def __init__(self, rows, images, transform, size):
        self.rows, self.images, self.transform, self.size = rows, images, transform, size

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        pid, ext = self.rows[i]
        try:
            im = Image.open(self.images / f'{int(pid) % 1000:03d}' / f'{pid}.{ext}').convert('RGB')
            return self.transform(im), int(pid), True
        except Exception:
            return torch.zeros(3, self.size, self.size), int(pid), False


def load(kind, path, size):
    """(image encoder, transform, input size, text encoder or None)"""
    if kind == 'openclip':
        import open_clip
        model, transform = open_clip.create_model_from_pretrained(f'local-dir:{path}', device='cuda')
        tok = open_clip.get_tokenizer(f'local-dir:{path}')
        model.eval()
        return model.encode_image, transform, model.visual.image_size[0] if isinstance(model.visual.image_size, tuple) \
            else model.visual.image_size, lambda texts: model.encode_text(tok(texts).cuda())
    if kind == 'timm':
        import timm
        arch = json.loads((path / 'config.json').read_text())['architecture']
        extra = {'img_size': size} if size else {}
        conf = json.loads((path / 'config.json').read_text())
        model = timm.create_model(arch, pretrained=True, num_classes=conf.get('num_classes', 0),
                                  pretrained_cfg_overlay={'file': str(path / 'model.safetensors'),
                                                          'num_classes': conf.get('num_classes', 0)}, **extra)
        model.reset_classifier(0)
        model = model.cuda().eval()
        cfg = timm.data.resolve_data_config({}, model=model)
        if size:
            cfg['input_size'] = (3, size, size)
        return model, timm.data.create_transform(**cfg), cfg['input_size'][1], None
    if kind == 'siglip':
        from transformers import AutoModel, AutoProcessor
        model = AutoModel.from_pretrained(path, torch_dtype=torch.float32).cuda().eval()
        proc = AutoProcessor.from_pretrained(path)
        size = proc.image_processor.size['height']
        transform = lambda im: proc.image_processor(images=im, return_tensors='pt')['pixel_values'][0]
        text = lambda texts: model.get_text_features(**{k: v.cuda() for k, v in proc.tokenizer(
            [t.lower() for t in texts], padding='max_length', max_length=64, truncation=True, return_tensors='pt').items()})
        return lambda x: model.get_image_features(pixel_values=x), transform, size, text
    raise SystemExit(f'unknown kind {kind}')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kind', required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--prompts', type=Path)
    p.add_argument('--size', type=int, default=0)
    p.add_argument('--batch', type=int, default=384)
    p.add_argument('--workers', type=int, default=14)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    image, transform, size, text = load(a.kind, a.model, a.size)
    if a.prompts and text is not None:
        rows = [r for r in csv.DictReader(open(a.prompts), delimiter='\t')]
        with torch.no_grad():
            t = torch.nn.functional.normalize(text([r['prompt'] for r in rows]).float(), dim=-1)
        np.save(a.out / 'text.npy', t.cpu().numpy())
        (a.out / 'text.tsv').write_text(''.join(f"{r['key']}\t{r['prompt']}\n" for r in rows))
    rows = [(r['photo_id'], r['extension'] or 'jpg') for r in csv.DictReader(open(a.manifest), delimiter='\t')]
    loader = torch.utils.data.DataLoader(Photos(rows, a.images, transform, size), batch_size=a.batch, num_workers=a.workers)
    embs, ids = [], []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
        for n, (x, pid, ok) in enumerate(loader):
            z = torch.nn.functional.normalize(image(x.cuda(non_blocking=True)).float(), dim=-1)
            embs.append(z[ok.cuda()].half().cpu().numpy())
            ids.extend(int(i) for i, k in zip(pid, ok) if k)
            if n % 100 == 0:
                print(n * a.batch, len(rows), flush=True)
    np.save(a.out / 'emb-0.npy', np.concatenate(embs))
    (a.out / 'emb-0.ids').write_text('\n'.join(map(str, ids)) + '\n')
    print('done', len(ids), 'of', len(rows), flush=True)


if __name__ == '__main__':
    main()
