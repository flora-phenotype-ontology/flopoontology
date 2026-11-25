"""The CNNs of Schiller et al. (2021, Sci. Rep. 11:16395) on our photographs: six continuous TRY traits.

The released models are the authors' "Ensemble" setup: each network has TWO inputs, the image and six WorldClim
variables of the photograph's location (BIO1, BIO12, BIO4, BIO7, BIO15 and BIO13-BIO14, WorldClim 1.4 at 10 arc-minutes, scaled to 0..1 with
the per-trait minima and maxima in the figshare ``metadata.csv``; the authors' ``range01_v2`` is not in their repository and is taken to be a
clipped min-max). Photographs without a location (or on a no-data cell) get 0.5 for every variable and ``has_geo = False``. The
output is the trait on a min-max scaled log10 axis; ``<trait>_value`` converts the architecture ensemble back with the ``ref_min``/``ref_max`` of
the same file (units of TRY: height m, leaf area mm2, SLA mm2/mg, leaf N mg/g, seed mass mg, stem specific density mg/mm3).

Weights: figshare 10.6084/m9.figshare.13312040 (CC BY 4.0), Keras HDF5, one model per trait and architecture
(Inception-ResNet-v2, Xception, MobileNet-v2; traits gh growth height, la leaf area, lnc leaf nitrogen, sla, sm seed mass, ssd stem
specific density). Needs TensorFlow 2.15 / Keras 2 (``sota-tf-env``; the pixi environment has no TensorFlow). Inputs follow the
authors' pipeline: square centre crop resized to 512 x 512, pixel values 0..1, no other preprocessing. Output is the trait on a
min-max scaled log10 axis (the min/max of their training data are not distributed with the weights), so use rank statistics or
calibrate; ``ens_<trait>`` is the mean of the three architectures.

    python run_schiller.py --data DIR --manifest sota-photos.tsv --roles small,field --models DIR/../sota-models/schiller2021 \
        --out DIR/sota-out/schiller --worldclim DIR/../sota-benchmarks/worldclim14 [--archs inception_resnet_v2,xception,mobilenet_v2]
GPU job: tools/orix/traitvision_sota_schiller.sbatch. (Plain numpy + PIL + TensorFlow; decoding runs in a process pool.)
"""
import argparse
import csv
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

TRAITS = ['gh', 'la', 'lnc', 'sla', 'sm', 'ssd']
BIO = ['bio1', 'bio12', 'bio4', 'bio7', 'bio15', 'bio13-14']          # the order of the auxiliary input


def worldclim(folder):
    """WorldClim 1.4, 10 arc-minute BIL rasters (int16, 900 x 2160, rows from 89.9167 N, columns from -179.9167 E)."""
    r = {}
    for k in ('bio1', 'bio4', 'bio7', 'bio12', 'bio13', 'bio14', 'bio15'):
        r[k] = np.fromfile(Path(folder) / f'{k}.bil', dtype='<i2').reshape(900, 2160).astype(np.float32)
    return r


def bio_at(rast, lat, lon):
    """(n, 6) raw values in BIO order, NaN where the location is missing or on a no-data cell."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    row = np.rint((89.9166666667 - lat) / (1 / 6)).astype(int)
    col = np.rint((lon + 179.9166666667) / (1 / 6)).astype(int)
    ok = np.isfinite(lat) & np.isfinite(lon) & (row >= 0) & (row < 900) & (col >= 0) & (col < 2160)
    row, col = np.clip(row, 0, 899), np.clip(col, 0, 2159)
    v = {k: np.where(ok, a[row, col], np.nan) for k, a in rast.items()}
    out = np.stack([v['bio1'], v['bio12'], v['bio4'], v['bio7'], v['bio15'], v['bio13'] - v['bio14']], 1)
    out[(out <= -9000).any(1)] = np.nan
    return out


def load_keras(tf, path):
    """The files were written by R-keras: layer configs carry ``trainable: null`` (refused by Keras 2.15; fixed here), and the residual
    "scaling" layers of Inception-ResNet-v2 are Lambda layers holding bytecode of an old Python. They all compute
    ``inputs[0] + inputs[1] * scale`` (``arguments.scale`` in the stored config; checked on the stored function names), so they are read as that."""
    import h5py
    import json
    path = str(path)
    with h5py.File(path, 'r') as f:
        cfg = f.attrs['model_config']
        cfg = json.loads(cfg.decode() if isinstance(cfg, bytes) else cfg)

    def fix(o):
        if isinstance(o, dict):
            if 'trainable' in o and o['trainable'] is None:
                o['trainable'] = True
            for v in o.values():
                fix(v)
        elif isinstance(o, list):
            for v in o:
                fix(v)
    fix(cfg)

    class ResidualScale(tf.keras.layers.Layer):
        def __init__(self, scale=1.0, **kw):
            super().__init__(**kw)
            self.scale = scale

        def call(self, inputs):
            return inputs[0] + inputs[1] * self.scale

        @classmethod
        def from_config(cls, config):
            assert config.get('module', '').endswith('inception_resnet_v2') and set(config['arguments']) == {'scale'}, config
            return cls(scale=config['arguments']['scale'], name=config['name'])
    m = tf.keras.models.model_from_config(cfg, custom_objects={'Lambda': ResidualScale})
    m.load_weights(path)
    return m


def load(path):
    try:
        im = Image.open(path)
        im.draft('RGB', (512, 512))
        im = ImageOps.exif_transpose(im.convert('RGB'))
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((512, 512), Image.BILINEAR)
        return np.asarray(im, np.uint8)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--manifest', default='sota-photos.tsv')
    p.add_argument('--roles', default='small,field')
    p.add_argument('--models', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--worldclim', type=Path, required=True, help='folder with the WorldClim 1.4 10-minute bio*.bil files')
    p.add_argument('--archs', default='inception_resnet_v2,xception,mobilenet_v2')
    p.add_argument('--items', help='instead of the manifest: TSV with key, path (relative to --root)')
    p.add_argument('--root', type=Path)
    p.add_argument('--batch', type=int, default=96)
    p.add_argument('--workers', type=int, default=44)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--shard', type=int, default=0)
    p.add_argument('--shards', type=int, default=1, help='process only photographs with index %% shards == shard (split a slow run into jobs)')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    import tensorflow as tf
    for g in tf.config.list_physical_devices('GPU'):
        tf.config.experimental.set_memory_growth(g, True)
    if a.items:
        rows = list(csv.DictReader(open(a.items), delimiter='\t'))
        keys = [r['key'] for r in rows]
        paths = [str(a.root / r['path']) for r in rows]
    else:
        roles = set(a.roles.split(','))
        rows = [r for r in csv.DictReader(open(a.data / a.manifest), delimiter='\t') if roles & set(r['role'].split(','))]
        keys = [r['photo_id'] for r in rows]
        paths = [str(a.data / r['image_dir'] / f"{int(r['photo_id']) % 1000:03d}" / f"{r['photo_id']}.{r['extension'] or 'jpg'}")
                 for r in rows]
    lat = [r.get('latitude') or 'nan' for r in rows]
    lon = [r.get('longitude') or 'nan' for r in rows]
    if a.shards > 1:
        keys, paths, lat, lon = keys[a.shard::a.shards], paths[a.shard::a.shards], lat[a.shard::a.shards], lon[a.shard::a.shards]
    if a.limit:
        keys, paths, lat, lon = keys[:a.limit], paths[:a.limit], lat[:a.limit], lon[:a.limit]
    raw = bio_at(worldclim(a.worldclim), np.array(lat, float), np.array(lon, float))
    has_geo = np.isfinite(raw).all(1)
    meta = {r['trait']: r for r in csv.DictReader(open(a.models / 'weights' / 'metadata.csv'), delimiter=';')}
    aux = {}
    for t in TRAITS:
        m = meta['nm' if t == 'lnc' else t]
        lo = np.array([float(m[f'{b}_min']) for b in BIO])
        hi = np.array([float(m[f'{b}_max']) for b in BIO])
        aux[t] = np.where(has_geo[:, None], np.clip((raw - lo) / (hi - lo), 0, 1), 0.5).astype(np.float32)
    models = {}
    for arch in a.archs.split(','):
        for t in TRAITS:
            f = a.models / 'weights' / f'{t}_{arch}.hdf5'
            if f.exists():
                models[f'{t}_{arch}'] = load_keras(tf, f)
                print('loaded', f.name, flush=True)
    preds = {k: [] for k in models}
    t0 = time.time()
    got = []
    with mp.get_context('fork').Pool(a.workers) as pool:
        it = pool.imap(load, paths, chunksize=8)
        buf, idx = [], []
        def flush():
            x = tf.constant(np.stack(buf), tf.uint8)
            x = tf.cast(x, tf.float32) / 255.0
            for k, m in models.items():
                a_ = tf.constant(aux[k.split('_')[0]][idx])
                preds[k].append(m([x, a_], training=False).numpy().reshape(-1))
            got.extend(idx)
            buf.clear(); idx.clear()
        for n, arr in enumerate(it):
            if arr is not None:
                buf.append(arr); idx.append(n)
            if len(buf) == a.batch:
                flush()
            if n % 2000 == 0:
                print(n, len(paths), f'{n / max(time.time() - t0, 1e-3):.0f} photographs/s', flush=True)
        if buf:
            flush()
    out = {'ids': np.array([keys[i] for i in got])}
    for k in models:
        out[k] = np.concatenate(preds[k]).astype(np.float32)
    out['has_geo'] = has_geo[got]
    for t in TRAITS:
        mem = [out[f'{t}_{arch}'] for arch in a.archs.split(',') if f'{t}_{arch}' in out]
        if mem:
            out[f'ens_{t}'] = np.mean(mem, 0)
            m = meta['nm' if t == 'lnc' else t]
            lo, hi = np.log10(float(m['ref_min'])), np.log10(float(m['ref_max']))
            out[f'{t}_value'] = (10 ** (out[f'ens_{t}'] * (hi - lo) + lo)).astype(np.float32)
    np.savez(a.out / 'pred.npz', **out)
    print('done', len(got), 'of', len(paths), flush=True)


if __name__ == '__main__':
    main()
