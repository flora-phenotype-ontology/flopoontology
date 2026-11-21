"""Fine-tune the BioCLIP 2 image model itself on the flora trait labels (GPU job on ORIX).

``train.py`` keeps the image model frozen and learns one small layer per trait. Here the image
model is trained too, for all traits at once: one shared image model, one small layer per trait,
the same set-valued loss (a photo is pushed towards the classes the floras allow for its species)
and the same weights (equal per species and per class). The trait layers start from the ones
``train.py`` learned, so the scores before the first step are the frozen-model baseline, measured
in exactly the same way as the scores after each epoch.

Scores (no labels of ours): held-out genera against the floras, and iNaturalist observation fields.
``field_unseen_genera`` counts observations whose genus has no training species for that trait
(comparable with train.py); ``field_unseen_strict`` those whose genus has no training photo at all.

    python finetune.py --data DIR --model DIR/bioclip2 --heads DIR/run-N --out DIR/ft-1
"""
import argparse
import collections
import csv
import json
import math
import time
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image
from torchvision import transforms as T

from train import aggregate, balanced_accuracy, bucket, confusion, in_set_accuracy


class Photos(torch.utils.data.Dataset):
    def __init__(self, items, transform):
        self.items, self.transform = items, transform       # items: (path, row index)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        path, row = self.items[i]
        try:
            return self.transform(Image.open(path).convert('RGB')), row, True
        except Exception:
            return torch.zeros(3, 224, 224), row, False


def path_for(folder, pid, ext):
    return folder / f'{int(pid) % 1000:03d}' / f'{pid}.{ext or "jpg"}'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--heads', type=Path, required=True, help='run folder of train.py with head-<trait>.pt')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--labels', default='pilot-labels-v2.tsv')
    p.add_argument('--photos', default='inat-photos-v2.tsv')
    p.add_argument('--field', default='field-test-v2.tsv')
    p.add_argument('--epochs', type=int, default=3)
    p.add_argument('--batch', type=int, default=256)
    p.add_argument('--lr', type=float, default=2e-5)
    p.add_argument('--head-lr', type=float, default=5e-4)
    p.add_argument('--decay', type=float, default=0.8, help='learning rate shrinks by this per layer towards the input')
    p.add_argument('--workers', type=int, default=14)
    p.add_argument('--train-blocks', type=int, default=0, help='train only the last N blocks (0 = all)')
    p.add_argument('--limit', type=int, default=0, help='use only this many training photos (test run)')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(0)

    # ---- labels, photos, split by genus (0 test, 1 validation, rest training) ----
    heads_ckpt = {f.stem[5:]: torch.load(f, map_location='cpu') for f in sorted(a.heads.glob('head-*.pt'))}
    traits = sorted(heads_ckpt)
    classes = {t: heads_ckpt[t]['classes'] for t in traits}
    offset, total = {}, 0
    for t in traits:
        offset[t], total = total, total + len(classes[t])
    labels = collections.defaultdict(dict)
    for r in csv.DictReader(open(a.data / a.labels), delimiter='\t'):
        if r['trait'] in classes:
            s = set(r['allowed'].split('|')) & set(classes[r['trait']])
            if s:
                labels[r['trait']][r['taxon']] = s
    labelled = {t for lab in labels.values() for t in lab}
    photos = [(path_for(a.data / 'images', r['photo_id'], r['extension']), r['taxon'])
              for r in csv.DictReader(open(a.data / a.photos), delimiter='\t') if r['taxon'] in labelled]
    taxa = np.array([t for _, t in photos])
    split = np.array([bucket(t.split()[0]) for t in taxa])
    tr = np.flatnonzero(split >= 2)
    te = np.flatnonzero(split == 0)
    if a.limit:
        tr, te = np.random.default_rng(0).permutation(tr)[:a.limit], te[:a.limit]
    train_genera = {t.split()[0] for t in taxa[tr]}
    target = np.zeros((len(photos), total), np.float32)      # allowed classes, all traits side by side
    weight = np.zeros((len(photos), len(traits)), np.float32)
    trait_train_genera = {}
    for k, t in enumerate(traits):
        lab, cidx = labels[t], {c: i for i, c in enumerate(classes[t])}
        has = np.array([x in lab for x in taxa])
        for n in np.flatnonzero(has):
            for c in lab[taxa[n]]:
                target[n, offset[t] + cidx[c]] = 1
        rows = tr[has[tr]]
        trait_train_genera[t] = {x.split()[0] for x in taxa[rows]}
        per_taxon = collections.Counter(taxa[rows])
        tg = target[rows, offset[t]:offset[t] + len(cidx)]
        freq = np.maximum(tg[tg.sum(1) == 1].sum(0), 1)
        cw = freq.sum() / freq / len(cidx)
        w = np.array([1 / per_taxon[x] for x in taxa[rows]]) * (tg * cw).max(1)
        weight[rows, k] = w / w.mean()
    print(f'photos {len(photos)}; training {len(tr)}; test {len(te)}; traits {traits}', flush=True)

    field = collections.defaultdict(list)       # trait -> (class, [positions in fitems], genus)
    fitems, fpos = [], {}
    fext = {r['photo_id']: r['extension'] for r in csv.DictReader(open(a.data / 'field-photos.tsv'), delimiter='\t')}
    for r in csv.DictReader(open(a.data / a.field), delimiter='\t'):
        if r['trait'] not in classes or r['class'] not in classes[r['trait']]:
            continue
        rows = []
        for x in r['photos'].split('|'):
            if x not in fpos:
                fpos[x] = len(fitems)
                fitems.append((path_for(a.data / 'field' / 'images', x, fext.get(x, 'jpg')), fpos[x]))
            rows.append(fpos[x])
        field[r['trait']].append((r['class'], rows, r['taxon'].split()[0]))

    # ---- model ----
    cfg = json.loads((a.model / 'open_clip_config.json').read_text())['preprocess_cfg']
    model, _, plain = open_clip.create_model_and_transforms(
        'ViT-L-14', pretrained=str(a.model / 'open_clip_model.safetensors'), device='cuda',
        image_mean=cfg['mean'], image_std=cfg['std'])
    visual = model.visual.float()
    del model
    heads = torch.nn.ModuleDict({t: torch.nn.Linear(768, len(classes[t])) for t in traits}).cuda()
    for t in traits:
        heads[t].load_state_dict(heads_ckpt[t]['state'])
    augment = T.Compose([T.RandomResizedCrop(224, scale=(0.4, 1), interpolation=T.InterpolationMode.BICUBIC),
                         T.RandomHorizontalFlip(), T.ToTensor(), T.Normalize(cfg['mean'], cfg['std'])])
    blocks = list(visual.transformer.resblocks)
    groups, seen = [], set()
    for depth, block in enumerate(blocks):
        ps = list(block.parameters())
        seen.update(map(id, ps))
        groups.append({'params': ps, 'lr': a.lr * a.decay ** (len(blocks) - depth)})
    late = [q for n, q in visual.named_parameters() if id(q) not in seen and (n.startswith('ln_post') or n == 'proj')]
    early = [q for q in visual.parameters() if id(q) not in seen and all(q is not x for x in late)]
    groups += [{'params': late, 'lr': a.lr}, {'params': early, 'lr': a.lr * a.decay ** (len(blocks) + 1)},
               {'params': list(heads.parameters()), 'lr': a.head_lr}]
    if a.train_blocks:              # keep the early layers exactly as they are
        frozen = groups[:len(blocks) - a.train_blocks] + [groups[len(blocks) + 1]]
        for g in frozen:
            for q in g['params']:
                q.requires_grad_(False)
        groups = [g for g in groups if all(g is not f for f in frozen)]
    opt = torch.optim.AdamW(groups, weight_decay=0.05)
    peak = [g['lr'] for g in groups]
    loader = torch.utils.data.DataLoader(
        Photos([(photos[i][0], int(i)) for i in tr], augment), batch_size=a.batch, shuffle=True, drop_last=True,
        num_workers=a.workers, pin_memory=True, persistent_workers=True, prefetch_factor=4)
    steps, warm = a.epochs * len(loader), max(1, int(0.05 * a.epochs * len(loader)))
    target_g, weight_g = torch.from_numpy(target).cuda(), torch.from_numpy(weight).cuda()

    def logits(x):
        z = torch.nn.functional.normalize(visual(x).float(), dim=-1)
        return {t: heads[t](z) for t in traits}

    def probabilities(items):
        visual.eval()
        out = {t: np.zeros((len(items), len(classes[t])), np.float32) for t in traits}
        ld = torch.utils.data.DataLoader(Photos(items, plain), batch_size=768, num_workers=a.workers)
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            for x, row, _ in ld:
                for t, l in logits(x.cuda(non_blocking=True)).items():
                    out[t][row.numpy()] = torch.softmax(l.float(), 1).cpu().numpy()
        visual.train()
        return out

    def evaluate(tag):
        ptest = probabilities([(photos[i][0], n) for n, i in enumerate(te)])
        pfield = probabilities(fitems) if fitems else None
        res = {}
        for t in traits:
            lab, cidx = labels[t], {c: i for i, c in enumerate(classes[t])}
            keep = np.array([x in lab for x in taxa[te]])
            agg = aggregate(ptest[t][keep], np.ones(keep.sum(), np.float32), taxa[te][keep])
            names = sorted(agg)
            pred = [int(np.argmax(agg[x])) for x in names]
            allowed = [{cidx[c] for c in lab[x]} for x in names]
            bal, per = balanced_accuracy(pred, allowed, classes[t])
            r = {'heldout_genus_in_set_accuracy': in_set_accuracy(pred, allowed),
                 'heldout_genus_balanced_accuracy': bal, 'per_class': per, 'test_taxa': len(names)}
            for scope, genera in (('all', None), ('unseen_genera', 'bucket'), ('unseen_strict', train_genera)):
                obs = [o for o in field[t] if genera is None or (bucket(o[2]) < 2 if genera == 'bucket' else o[2] not in genera)]
                if obs and pfield is not None:
                    pr = [int(np.argmax(pfield[t][o[1]].sum(0))) for o in obs]
                    al = [{cidx[o[0]]} for o in obs]
                    fb, fper = balanced_accuracy(pr, al, classes[t])
                    r[f'field_{scope}'] = {'observations': len(obs), 'accuracy': in_set_accuracy(pr, al),
                                           'balanced_accuracy': fb, 'per_class': fper,
                                           'confusion': confusion(pr, al, classes[t])}
            res[t] = r
            f = lambda k: f"{(r.get(k) or {}).get('balanced_accuracy') or 0:.3f}"
            print(tag, t, f"heldout {bal or 0:.3f}", 'field_unseen', f('field_unseen_genera'),
                  'strict', f('field_unseen_strict'), flush=True)
        return res

    results = {'args': {k: str(v) for k, v in vars(a).items()}, 'training_photos': len(tr), 'epochs': {}}
    results['epochs']['0'] = evaluate('epoch 0 (frozen model)')
    step, start = 0, time.time()
    for epoch in range(1, a.epochs + 1):
        for x, row, ok in loader:
            for g, lr in zip(opt.param_groups, peak):
                g['lr'] = lr * (step / warm if step < warm else 0.5 * (1 + math.cos(math.pi * (step - warm) / (steps - warm))))
            row = row.cuda(non_blocking=True)
            okf = ok.cuda().float()
            with torch.autocast('cuda', dtype=torch.bfloat16):
                out = logits(x.cuda(non_blocking=True))
            loss = 0
            for k, t in enumerate(traits):
                w = weight_g[row, k] * okf
                tg = target_g[row, offset[t]:offset[t] + len(classes[t])]
                logp = torch.log_softmax(out[t].float(), 1)
                nll = -torch.logsumexp(logp + torch.log(tg + 1e-12), 1)
                loss = loss + (torch.where(w > 0, nll, torch.zeros_like(nll)) * w).sum() / (w.sum() + 1e-6)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([q for q in visual.parameters() if q.requires_grad], 1.0)
            opt.step()
            step += 1
            if step % 100 == 0:
                print(f'step {step}/{steps} loss {loss.item():.3f} {step * a.batch / (time.time() - start):.0f} photos/s', flush=True)
        results['epochs'][str(epoch)] = evaluate(f'epoch {epoch}')
        (a.out / 'results.json').write_text(json.dumps(results, indent=1, default=float) + '\n')
    torch.save({'visual': {k: v.half() for k, v in visual.state_dict().items()},
                'heads': heads.state_dict(), 'classes': classes}, a.out / 'model.pt')
    print('done', flush=True)


if __name__ == '__main__':
    main()
