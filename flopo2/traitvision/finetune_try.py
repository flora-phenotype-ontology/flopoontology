"""Train the BioCLIP 2 image model itself on TRY values and flora labels together (GPU job on ORIX).

Two streams of photographs, mixed in every batch:
* PlantTraitNet's training photographs with their TRY values (height, leaf area, specific leaf area, leaf nitrogen);
* our iNaturalist photographs with what the floras state for the species: sizes (``measure-labels-v3.tsv``) and
  categorical traits (``pilot-labels-v3.tsv``, ``extra-labels.tsv``), a species counting once (up to 50 photographs).

One image model (the last ``--blocks`` blocks are trained), one head for the TRY values (optionally also given the
Climplicit embedding of the location, as in PlantTraitNet), one head for the flora labels. Both heads are first
fitted on the stored embeddings of the untouched model, so "epoch 0" is the frozen-model result, measured on the same
rows as the results after each epoch. The species name is a label only: never an input, no species classifier.

Regimes: ``all`` as PlantTraitNet (every training photograph); ``fold`` leaves out the genera of one fold from both
streams and scores only the benchmark photographs of those genera.

Stopping on unseen genera (``--val-genera``, default on): the genera of the next fold are kept out of both streams as
well; every ``--eval-every`` steps their TRY photographs (a sample) are scored (mean Spearman over the four traits),
and the weights with the best score are the ones reported as ``best`` and saved. Step 0 is the untouched model, so a
model that never improves on unseen genera is not replaced.

    python finetune_try.py --data DIR --model DIR/bioclip2 --root DIR/sota-benchmarks/planttraitnet --out DIR/ft-try [--loc] [--regime fold --fold 0]
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
from torchvision import transforms as TV

import train as T
from try_even import SIZESX, TRAITS, binomial, spearman, tsv

F = torch.nn.functional


class Photos(torch.utils.data.Dataset):
    def __init__(self, items, transform):
        self.items, self.transform = items, transform       # items: (path, kind, row)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        path, kind, row = self.items[i]
        try:
            return self.transform(Image.open(path).convert('RGB')), kind, row, True
        except Exception:
            return torch.zeros(3, 224, 224), kind, row, False


def mlp(n_in, n_out):
    return torch.nn.Sequential(torch.nn.Linear(n_in, 2048), torch.nn.GELU(), torch.nn.Dropout(0.3),
                               torch.nn.Linear(2048, 512), torch.nn.GELU(), torch.nn.Linear(512, n_out))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--regime', choices=('all', 'fold'), default='all')
    p.add_argument('--fold', type=int, default=0)
    p.add_argument('--loc', action='store_true')
    p.add_argument('--epochs', type=int, default=3)
    p.add_argument('--batch', type=int, default=384)
    p.add_argument('--blocks', type=int, default=6)
    p.add_argument('--lr', type=float, default=2e-5)
    p.add_argument('--decay', type=float, default=0.8)
    p.add_argument('--head-lr', type=float, default=2e-4)
    p.add_argument('--head-steps', type=int, default=8000)
    p.add_argument('--flora-ratio', type=float, default=1.0, help='flora photographs per TRY photograph (0: TRY only)')
    p.add_argument('--flora-weight', type=float, default=1.0)
    p.add_argument('--workers', type=int, default=44)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--val-genera', type=int, default=1, help='1: stop on the genera of the next fold (kept out of training); 0: off')
    p.add_argument('--val-photos', type=int, default=6000)
    p.add_argument('--eval-every', type=int, default=300)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(0)
    rng = np.random.default_rng(0)
    D, S, DEV = a.data, a.data / 'sota-out', 'cuda'
    test_g = lambda g: a.regime == 'fold' and (T.bucket(g) - 2 * a.fold) % 10 < 2
    val_g = lambda g: a.val_genera and (T.bucket(g) - 2 * (a.fold + 1)) % 10 < 2
    held = lambda g: test_g(g) or val_g(g)

    # ---- the benchmark: rows, stored embeddings, locations
    def load(name, emb_dir):
        rows = tsv(S / f'{name}.tsv')
        e = np.load(S / emb_dir / 'emb-0.npy')
        k = {key: i for i, key in enumerate((S / emb_dir / 'emb-0.keys').read_text().split('\n')[:len(e)])}
        rows = [r for r in rows if r['key'] in k]
        l = np.load(S / f'loc-{name}.npy')
        lk = {key: i for i, key in enumerate((S / f'loc-{name}.keys').read_text().split('\n'))}
        loc = l[[lk[r['key']] for r in rows]].astype(np.float32) if a.loc else np.zeros((len(rows), 0), np.float32)
        return rows, torch.from_numpy(e[[k[r['key']] for r in rows]].astype(np.float32)).to(DEV), torch.from_numpy(loc).to(DEV)
    trn, XT, LT = load('ptn-train', 'emb-ptn-train')
    val, XV, LV = load('ptn-val', 'emb-ptn-val')
    ref, XR, LR = load('ptn-reference', 'emb-ptn-ref')
    seen = {r['species'] for r in trn}
    tr_rows = np.array([i for i, r in enumerate(trn) if not held(r['genus'])])
    if a.regime == 'fold':
        kv, kr = [i for i, r in enumerate(val) if test_g(r['genus'])], [i for i, r in enumerate(ref) if test_g(r['genus'])]
        val, XV, LV = [val[i] for i in kv], XV[kv], LV[kv]
        ref, XR, LR = [ref[i] for i in kr], XR[kr], LR[kr]
    y = np.log10(np.array([[float(r[t]) for t in TRAITS] for r in trn]).clip(1e-6))
    mu, sd = y[tr_rows].mean(0), y[tr_rows].std(0)
    stop_rows = np.array([i for i, r in enumerate(trn) if val_g(r['genus']) and not test_g(r['genus'])], int)
    stop_rows = np.sort(rng.permutation(stop_rows)[:a.val_photos])
    yz = torch.tensor((y - mu) / sd, dtype=torch.float32, device=DEV)
    nt, nl = len(TRAITS), LT.shape[1]

    # ---- the flora stream
    size = collections.defaultdict(dict)
    for r in tsv(D / 'measure-labels-v3.tsv'):
        if r['trait'] in SIZESX:
            size[r['taxon']][r['trait']] = float(r['log10_m'])
    allowed = collections.defaultdict(dict)
    for r in tsv(D / 'pilot-labels-v3.tsv') + tsv(D / 'extra-labels.tsv'):
        allowed[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
    cats = sorted(allowed)
    classes = {t: sorted({c for s in allowed[t].values() for c in s}) for t in cats}
    labelled = set(size) | {t for d in allowed.values() for t in d}
    emb, ids = T.load_embeddings(D / 'emb')
    row = {}
    for n, i in enumerate(ids):
        row.setdefault(int(i), n)
    frows, fpath, taxa = [], [], []
    for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
        if int(r['photo_id']) in row and r['taxon'] in labelled and not held(r['taxon'].split()[0]):
            frows.append(row[int(r['photo_id'])]); taxa.append(r['taxon'])
            fpath.append(D / 'images' / f"{int(r['photo_id']) % 1000:03d}" / f"{r['photo_id']}.{r['extension'] or 'jpg'}")
    names, inv = np.unique(np.array(taxa), return_inverse=True)
    XF = torch.from_numpy(emb[frows].astype(np.float32)).to(DEV)
    del emb
    ys = np.array([[size[t].get(k, np.nan) for k in SIZESX] for t in names], np.float32)
    ys = (ys - np.nanmean(ys, 0)) / np.nanstd(ys, 0)
    ns = len(SIZESX)
    tgt = [np.nan_to_num(ys)]
    msk = [(~np.isnan(ys)).astype(np.float32)]
    for t in cats:
        ci = {c: n for n, c in enumerate(classes[t])}
        m = np.zeros((len(names), len(classes[t])), np.float32)
        for n, s in enumerate(names):
            for c in allowed[t].get(s, ()):
                m[n, ci[c]] = 1
        tgt.append(m)
    ftgt = torch.from_numpy(np.concatenate(tgt, 1)).to(DEV)             # per species: sizes, then allowed classes
    fmsk = torch.from_numpy(msk[0]).to(DEV)
    inv_t = torch.from_numpy(inv).to(DEV)
    pw = 1.0 / np.minimum(np.bincount(inv), 50)[inv]
    nout = ftgt.shape[1]
    print(f'regime {a.regime} TRY photographs {len(tr_rows)} flora photographs {len(frows)} species {len(names)} '
          f'validation {len(val)} reference {len(ref)} location {nl}', flush=True)

    def flora_loss(o, sp, w):
        m = fmsk[sp] * w[:, None]
        t = ftgt[sp]
        loss = (F.smooth_l1_loss(o[:, :ns], t[:, :ns], reduction='none') * m).sum() / m.sum().clamp(min=1e-6)
        k = ns
        for c in cats:
            C = len(classes[c])
            s = t[:, k:k + C]
            has = (s.sum(1) > 0).float() * w
            mass = (torch.softmax(o[:, k:k + C].float(), 1) * s).sum(1).clamp(min=1e-6)
            loss = loss + (-torch.log(mass) * has).sum() / has.sum().clamp(min=1e-6) / len(cats)
            k += C
        return loss

    # ---- heads, fitted on the stored embeddings of the untouched model
    try_head, flora_head = mlp(768 + nl, nt).to(DEV), mlp(768, nout).to(DEV)
    opt = torch.optim.AdamW([*try_head.parameters(), *flora_head.parameters()], lr=1e-3, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=a.head_steps)
    trt = torch.from_numpy(tr_rows).to(DEV)
    pwt = torch.from_numpy(pw.astype(np.float32)).to(DEV)
    for _ in range(a.head_steps):
        b = trt[torch.randint(len(trt), (1024,), device=DEV)]
        fb = torch.randint(len(XF), (2048,), device=DEV)
        loss = F.smooth_l1_loss(try_head(torch.cat([XT[b], LT[b]], 1)), yz[b]) + a.flora_weight * flora_loss(flora_head(XF[fb]), inv_t[fb], pwt[fb])
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    del XF

    def report(tag, zv, zr):
        try_head.eval()
        with torch.no_grad():
            pv = try_head(torch.cat([zv, LV], 1)).float().cpu().numpy() * sd + mu
            pr = try_head(torch.cat([zr, LR], 1)).float().cpu().numpy() * sd + mu
        try_head.train()
        res = {}
        for ti, t in enumerate(TRAITS):
            rk = [i for i, r in enumerate(ref) if r['trait'] == t]
            un = [i for i in rk if binomial(ref[i]['species']) and binomial(ref[i]['species']) not in seen]
            sp = lambda ks: round(spearman([float(ref[i]['value']) for i in ks], pr[ks, ti]), 3) if len(ks) >= 20 else None
            res[t] = {'validation': round(spearman([float(r[t]) for r in val], pv[:, ti]), 3) if len(val) >= 20 else None, 'n_validation': len(val),
                      'reference': sp(rk), 'n_reference': len(rk), 'reference, species without a TRY label in training': sp(un), 'n_unseen': len(un)}
            print('RESULT', tag, t, res[t], flush=True)
        np.savez(a.out / f'pred-{tag}.npz', val_keys=np.array([r['key'] for r in val]), val_pred=pv,
                 ref_keys=np.array([r['key'] for r in ref]), ref_pred=pr, traits=np.array(TRAITS))
        return res
    results = {'args': {k: str(v) for k, v in vars(a).items()}, 'epochs': {'0': report('epoch0', XV, XR)}}

    def stop_score(z):
        try_head.eval()
        with torch.no_grad():
            q = try_head(torch.cat([z, LT[stop_rows]], 1)).float().cpu().numpy()
        try_head.train()
        return float(np.mean([spearman(y[stop_rows, k], q[:, k]) for k in range(nt)]))

    # ---- the image model
    cfg = json.loads((a.model / 'open_clip_config.json').read_text())['preprocess_cfg']
    model, _, plain = open_clip.create_model_and_transforms(
        'ViT-L-14', pretrained=str(a.model / 'open_clip_model.safetensors'), device='cuda', image_mean=cfg['mean'], image_std=cfg['std'])
    visual = model.visual.float()
    del model
    augment = TV.Compose([TV.RandomResizedCrop(224, scale=(0.4, 1), interpolation=TV.InterpolationMode.BICUBIC),
                          TV.RandomHorizontalFlip(), TV.ToTensor(), TV.Normalize(cfg['mean'], cfg['std'])])
    blocks = list(visual.transformer.resblocks)
    for q in visual.parameters():
        q.requires_grad_(False)
    groups = []
    for depth in range(len(blocks) - a.blocks, len(blocks)):
        ps = list(blocks[depth].parameters())
        for q in ps:
            q.requires_grad_(True)
        groups.append({'params': ps, 'lr': a.lr * a.decay ** (len(blocks) - 1 - depth)})
    late = [q for n, q in visual.named_parameters() if n.startswith('ln_post') or n == 'proj']
    for q in late:
        q.requires_grad_(True)
    groups += [{'params': late, 'lr': a.lr}, {'params': [*try_head.parameters(), *flora_head.parameters()], 'lr': a.head_lr}]
    opt = torch.optim.AdamW(groups, weight_decay=0.05)
    peak = [g['lr'] for g in groups]

    def embed(rows):
        visual.eval()
        out = torch.zeros(len(rows), 768, device=DEV)
        ld = torch.utils.data.DataLoader(Photos([(a.root / r['path'], 0, n) for n, r in enumerate(rows)], plain), batch_size=768, num_workers=a.workers)
        with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
            for x, _, n, _ in ld:
                out[n.to(DEV)] = F.normalize(visual(x.cuda(non_blocking=True)).float(), dim=-1)
        visual.train()
        return out

    trainable = lambda: {**{'v.' + k: v for k, v in visual.state_dict().items()}, **{'t.' + k: v for k, v in try_head.state_dict().items()},
                         **{'f.' + k: v for k, v in flora_head.state_dict().items()}}
    best = (None, 0, None)
    if len(stop_rows) >= 200:
        best = (stop_score(XT[stop_rows]), 0, {k: v.detach().clone() for k, v in trainable().items()})
        results['stopping'] = [{'step': 0, 'unseen genera, mean Spearman': best[0]}]
        print('STOP step 0 (untouched model)', round(best[0], 4), 'photographs', len(stop_rows), flush=True)
    ntry = len(tr_rows) if not a.limit else a.limit
    step, start = 0, time.time()
    steps = a.epochs * (int(ntry * (1 + a.flora_ratio)) // a.batch)
    warm = max(1, int(0.05 * steps))
    for epoch in range(1, a.epochs + 1):
        items = [(a.root / trn[i]['path'], 0, int(i)) for i in rng.permutation(tr_rows)[:ntry]]
        fl = rng.choice(len(fpath), int(ntry * a.flora_ratio), p=pw / pw.sum()) if a.flora_ratio else []
        items += [(fpath[i], 1, int(i)) for i in fl]
        loader = torch.utils.data.DataLoader(Photos(items, augment), batch_size=a.batch, shuffle=True, drop_last=True,
                                             num_workers=a.workers, pin_memory=True, prefetch_factor=4)
        for x, kind, r, ok in loader:
            if step >= steps:
                break
            for g, lr in zip(opt.param_groups, peak):
                g['lr'] = lr * (step / warm if step < warm else 0.5 * (1 + math.cos(math.pi * (step - warm) / (steps - warm))))
            kind, r, ok = kind.to(DEV), r.to(DEV), ok.to(DEV)
            with torch.autocast('cuda', dtype=torch.bfloat16):
                z = F.normalize(visual(x.cuda(non_blocking=True)).float(), dim=-1)
            it, jf = torch.nonzero((kind == 0) & ok)[:, 0], torch.nonzero((kind == 1) & ok)[:, 0]
            loss = z.sum() * 0
            if len(it):
                loss = loss + F.smooth_l1_loss(try_head(torch.cat([z[it], LT[r[it]]], 1)), yz[r[it]])
            if len(jf):
                loss = loss + a.flora_weight * flora_loss(flora_head(z[jf]), inv_t[r[jf]], torch.ones(len(jf), device=DEV))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([q for q in visual.parameters() if q.requires_grad], 1.0)
            opt.step()
            step += 1
            if step % 100 == 0:
                print(f'step {step}/{steps} loss {loss.item():.3f} {step * a.batch / (time.time() - start):.0f} photos/s', flush=True)
            if best[0] is not None and (step % a.eval_every == 0 or step == steps):
                sc = stop_score(embed([trn[i] for i in stop_rows]))
                results['stopping'].append({'step': step, 'unseen genera, mean Spearman': sc})
                print('STOP step', step, round(sc, 4), '(best so far', round(best[0], 4), 'at step', str(best[1]) + ')', flush=True)
                if sc > best[0]:
                    best = (sc, step, {k: v.detach().clone() for k, v in trainable().items()})
        results['epochs'][str(epoch)] = report(f'epoch{epoch}', embed(val), embed(ref))
        (a.out / 'results.json').write_text(json.dumps(results, indent=1, default=float) + '\n')
    if best[0] is not None:
        visual.load_state_dict({k[2:]: v for k, v in best[2].items() if k.startswith('v.')})
        try_head.load_state_dict({k[2:]: v for k, v in best[2].items() if k.startswith('t.')})
        flora_head.load_state_dict({k[2:]: v for k, v in best[2].items() if k.startswith('f.')})
        results['best'] = {'step': best[1], 'unseen genera, mean Spearman': best[0],
                           'scores': results['epochs']['0'] if best[1] == 0 else report('best', embed(val), embed(ref))}
        print('BEST step', best[1], 'of', steps, flush=True)
        (a.out / 'results.json').write_text(json.dumps(results, indent=1, default=float) + '\n')
    torch.save({'visual': {k: v.half() for k, v in visual.state_dict().items()}, 'try_head': try_head.state_dict(),
                'flora_head': flora_head.state_dict(), 'classes': classes, 'sizes': SIZESX, 'mu': mu, 'sd': sd}, a.out / 'model.pt')
    print('done', flush=True)


if __name__ == '__main__':
    main()
