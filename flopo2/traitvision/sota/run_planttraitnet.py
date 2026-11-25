"""PlantTraitNet (Sharma et al., AAAI 2026; weights ayushi3536/PlantTraitNet, CC-BY-NC-SA-4.0) on our photographs.

The published code needs mmcv, omegaconf, sklearn and wandb; this file rebuilds the *inference* graph from the same classes
(DINOv2 ViT-B/14 with registers, Depth-Anything-V2 ViT-B encoder, Climplicit, concatenation, LayerNorm, projection, 8-block residual
MLP with a mean and a log-variance output per trait) and loads the released checkpoints into it, so that it runs in a venv that only
adds rshf (``pilot-v1/../sota-env``). The frozen encoders are identical in every checkpoint and are computed once per photograph; each
checkpoint only adds its own compression layers and head. Exception: the "depth" encoder stored in the checkpoints differs between
the multi-trait seeds 0, 100 and 200 (the single-trait seed-0 checkpoints equal multi-trait seed 0), as expected for a randomly
initialised, never pretrained ViT-B frozen under a fixed seed rather than Depth-Anything-V2 weights (the paper says the latter; I
did not compare with the Depth-Anything-V2 release), so one such encoder is built per distinct state and loaded as stored.

Inputs per photograph: the image (resize 256, centre crop 224, ImageNet statistics) and the location (lon, lat). Photographs
without a location get (0, 0) and are flagged ``has_geo = False``: score them only where ``has_geo`` is true.

Outputs (``--out``):
  pred.npz     ids, has_geo, and per checkpoint ``<name>_mu`` (n, traits) and ``<name>_logvar``; ``traits`` lists the
               trait order of the multi-trait checkpoints (Height, LeafArea, SLA, Leaf_N)
  emb-0.npy / emb-0.ids   the 1024-d representation of ``multitrait_seed0`` before the output layers (float16,
               L2-normalised), in the layout of ``embed.py``, so ``train.py --emb`` and ``probe_any.py`` can use it as a frozen
               encoder
The values are in the model's normalised target space: the released repository does not contain the target scaler
(``scalar.pkl``), so use rank statistics, or calibrate on a labelled set.

    python run_planttraitnet.py --data DIR --manifest sota-photos.tsv --roles pheno,field,train \
        --models DIR/../sota-models/planttraitnet --out DIR/sota-out/planttraitnet
GPU job: tools/orix/traitvision_sota_planttraitnet.sbatch
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from common import imagenet_transform, loader, photo_file, tsv

DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
TRAITS = ['Height', 'LeafArea', 'SLA', 'Leaf_N']
SINGLE = {'plantheight': 'Height', 'LA': 'LeafArea', 'sla': 'SLA', 'LN': 'Leaf_N'}


def depth_encoder(models):
    sys.path.insert(0, str(models / 'Depth-Anything-V2'))
    from depth_anything_v2.dinov2 import DINOv2
    return DINOv2(model_name='vitb').eval().requires_grad_(False)


class Frozen(nn.Module):
    """DINOv2 ViT-B/14 (registers) and Climplicit: frozen and identical in all checkpoints."""

    def __init__(self, models):
        super().__init__()
        from rshf.climplicit import Climplicit
        hub = models / 'torch-home' / 'hub' / 'facebookresearch_dinov2_main'
        self.dino = torch.hub.load(str(hub), 'dinov2_vitb14_reg', source='local', pretrained=False)
        self.climate = Climplicit.from_pretrained(str(models / 'climplicit'), config={'return_chelsa': False})
        self.eval().requires_grad_(False)

    @torch.no_grad()
    def forward(self, image, loc):
        patch = self.dino.forward_features(image)['x_norm_patchtokens'].permute(0, 2, 1)          # (B, 768, 256)
        return patch.float(), self.climate(loc).float()


class Block(nn.Module):
    def __init__(self, d, h):
        super().__init__()
        self.normalization = nn.BatchNorm1d(d)
        self.linear1, self.activation, self.dropout1 = nn.Linear(d, h), nn.LeakyReLU(), nn.Dropout(0.2)
        self.linear2, self.dropout2 = nn.Linear(h, d), nn.Dropout(0.2)

    def forward(self, x):
        return self.dropout2(self.linear2(self.dropout1(self.activation(self.linear1(self.normalization(x))))))


class ResNet(nn.Module):
    def __init__(self, d, n_traits, n_blocks=8, mult=2.0):
        super().__init__()
        self.input_projection = nn.Linear(d, d)
        self.blocks = nn.ModuleList([Block(d, int(d * mult)) for _ in range(n_blocks)])
        self.mu_heads = nn.ModuleList([nn.Sequential(nn.Linear(d, 1), nn.Softplus()) for _ in range(n_traits)])
        self.logvar_linears = nn.ModuleList([nn.Linear(d, 1) for _ in range(n_traits)])

    def forward(self, x):
        x = self.input_projection(x)
        for b in self.blocks:
            x = x + b(x)
        return (torch.cat([m(x) for m in self.mu_heads], 1), torch.cat([m(x) for m in self.logvar_linears], 1), x)


class Head(nn.Module):
    """The trainable part of one checkpoint (names as in the released state dict, below the encoder prefixes)."""

    def __init__(self, n_traits):
        super().__init__()
        self.compress_dino_feat = nn.Sequential(nn.AdaptiveAvgPool1d(32), nn.Flatten(), nn.Linear(32 * 768, 768))
        self.compress_depth_enc = nn.Sequential(nn.AdaptiveAvgPool1d(64), nn.Flatten(), nn.Linear(64 * 768, 768))
        self.Linear = nn.Linear(1024, 256)
        self.layernorm = nn.LayerNorm(1792, eps=1e-6)
        self.input_proj = nn.Linear(1792, 1024)
        self.multimodal = ResNet(1024, n_traits)

    def forward(self, patch, depth, clim):          # depth: last of the intermediate layers 2, 5, 8, 11
        z = torch.cat([self.compress_depth_enc(depth), self.Linear(clim), self.compress_dino_feat(patch)], 1)   # keys sorted: depthmap, geo, image
        return self.multimodal(self.input_proj(self.layernorm(z)))


def load_state(path):
    ck = torch.load(path, map_location='cpu', weights_only=False)
    return ck['model'] if 'model' in ck else ck


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--manifest', default='sota-photos.tsv')
    p.add_argument('--roles', default='pheno,field,train')
    p.add_argument('--models', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--items', help='instead of the manifest: a TSV with columns key, path (relative to --root), latitude, longitude')
    p.add_argument('--root', type=Path)
    p.add_argument('--batch', type=int, default=256)
    p.add_argument('--workers', type=int, default=44)
    p.add_argument('--limit', type=int, default=0, help='only the first N photographs (smoke test)')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.items:
        rows = tsv(a.items)
        keys = [r['key'] for r in rows]
        paths = [a.root / r['path'] for r in rows]
    else:
        roles = set(a.roles.split(','))
        rows = [r for r in tsv(a.data / a.manifest) if roles & set(r['role'].split(','))]
        keys = [int(r['photo_id']) for r in rows]
        paths = [photo_file(a.data, r['image_dir'], r['photo_id'], r['extension']) for r in rows]
    if a.limit:
        rows, keys, paths = rows[:a.limit], keys[:a.limit], paths[:a.limit]
    geo = np.array([[float(r['longitude']), float(r['latitude'])] if r.get('longitude') and r.get('latitude') else [0.0, 0.0]
                    for r in rows], np.float32)
    has_geo = np.array([bool(r.get('longitude') and r.get('latitude')) for r in rows])
    frozen = Frozen(a.models).to(DEV)
    ckpts = sorted((a.models / 'weights').glob('*.pth'))
    heads, names, hkeys, depths = [], [], [], {}
    for k, f in enumerate(ckpts):
        sd = load_state(f)
        n_traits = len([x for x in sd if x.startswith('multimodal.mu_heads.') and x.endswith('.0.weight')])
        head = Head(n_traits)
        mine = {key.split('.', 1)[1] if key.split('.', 1)[0] in ('image_encoder', 'depth_encoder', 'geo_encoder') else key: v
                for key, v in sd.items()}
        mine = {key.replace('compress_dino_feat', 'compress_dino_feat'): v for key, v in mine.items()}
        want = {key: v for key, v in mine.items() if key.split('.')[0] in ('compress_dino_feat', 'compress_depth_enc', 'Linear',
                                                                            'layernorm', 'input_proj', 'multimodal')}
        msg = head.load_state_dict(want, strict=False)
        print(f.name, 'traits', n_traits, 'missing', list(msg.missing_keys)[:4], 'unexpected', list(msg.unexpected_keys)[:4], flush=True)
        assert not msg.missing_keys, msg.missing_keys
        if k == 0:                                                      # frozen encoders from the first checkpoint
            enc = {key: v for key, v in sd.items() if key.startswith(('image_encoder.dinomodel.', 'geo_encoder.model.'))}
            for prefix, mod in (('image_encoder.dinomodel.', frozen.dino), ('geo_encoder.model.', frozen.climate)):
                m = mod.load_state_dict({key[len(prefix):]: v for key, v in enc.items() if key.startswith(prefix)}, strict=False)
                print('frozen', prefix, 'missing', len(m.missing_keys), 'unexpected', len(m.unexpected_keys), flush=True)
                assert all(k.startswith('chelsa_regressor') for k in m.missing_keys), m.missing_keys[:5]   # the unused CHELSA decoder
        dkey = round(float(sd['depth_encoder.depth_encoder.pos_embed'].double().sum()), 6)
        if dkey not in depths:
            d = depth_encoder(a.models)
            dm = d.load_state_dict({key[len('depth_encoder.depth_encoder.'):]: v for key, v in sd.items()
                                    if key.startswith('depth_encoder.depth_encoder.')}, strict=True)
            depths[dkey] = d.to(DEV)
        heads.append(head.to(DEV).eval())
        hkeys.append(dkey)
        names.append(f.stem.replace('_checkpoint', ''))
    dl = loader(paths, imagenet_transform(), a.batch, a.workers)
    out = {n: ([], []) for n in names}
    embs, ids, oks = [], [], []
    with torch.no_grad():
        for b, (x, idx, ok) in enumerate(dl):
            x = x.to(DEV, non_blocking=True)
            loc = torch.from_numpy(geo[idx.numpy()]).to(DEV)
            with torch.autocast(DEV, dtype=torch.bfloat16):
                patch, clim = frozen(x, loc)
                dtok = {k: d.get_intermediate_layers(x, [2, 5, 8, 11], return_class_token=False)[-1].permute(0, 2, 1).float()
                        for k, d in depths.items()}
            for n, h, k in zip(names, heads, hkeys):
                mu, lv, z = h(patch, dtok[k], clim)
                out[n][0].append(mu.float().cpu().numpy())
                out[n][1].append(lv.float().cpu().numpy())
                if n == 'multitrait_seed0':
                    embs.append(torch.nn.functional.normalize(z.float(), dim=-1).half().cpu().numpy())
            ids += idx.tolist()
            oks += ok.tolist()
            if b % 50 == 0:
                print(b * a.batch, len(paths), flush=True)
    oks = np.array(oks)
    res = {'ids': np.array([str(keys[i]) for i in ids])[oks], 'has_geo': has_geo[ids][oks], 'traits': np.array(TRAITS),
           'names': np.array(names)}
    for n in names:
        res[f'{n}_mu'] = np.concatenate(out[n][0])[oks]
        res[f'{n}_logvar'] = np.concatenate(out[n][1])[oks]
    np.savez(a.out / 'pred.npz', **res)
    np.save(a.out / 'emb-0.npy', np.concatenate(embs)[oks])
    (a.out / 'emb-0.ids').write_text('\n'.join(res['ids']) + '\n')
    print('done', int(oks.sum()), 'of', len(paths), flush=True)


if __name__ == '__main__':
    main()
