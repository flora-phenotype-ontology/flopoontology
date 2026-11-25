"""Measure flower colour in the photograph instead of learning it.

FLOPO defines every colour class as a set of ISCC-NBS blocks with a central Munsell notation. A pixel gets
the block whose centre is nearest in CIELAB; a detected flower box then has a histogram over the 267 blocks,
and through the class definitions over the basic colours. Nothing is trained.

Per flower box this stores the block histogram of the whole box and of its central part (an ellipse of half
the box size, weighted towards the middle), the mean colour of each, and per photo the histogram of all
pixels outside the flower boxes (the background, for contrast).

    <venv with colour-science, pillow>/python -m flopo2.traitvision.colour_measure \
        local-corpora/trait-vision field-boxes.tsv field-images field-photos.tsv colour-measure-field.npz
"""
import csv
import collections
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

SIDE, MIN_SCORE = 48, 0.25
_centres = None


def srgb_to_lab(rgb):
    """sRGB (0..255, any shape + 3) -> CIELAB, white D65."""
    c = rgb.astype(np.float32) / 255
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def blocks_of(lab):
    """Nearest block centre for every pixel (rows of lab)."""
    d = ((lab[:, None, :] - _centres[None, :, :]) ** 2).sum(-1)
    return d.argmin(1)


def one(job):
    from PIL import Image
    path, boxes = job
    try:
        im = Image.open(path).convert('RGB')
    except Exception:
        return None
    w, h = im.size
    out = []
    mask = np.ones((SIDE * 2, SIDE * 2), bool)             # background: outside every flower box
    for crop_id, x0, y0, x1, y1 in boxes:
        mask[int(y0 * SIDE * 2):int(np.ceil(y1 * SIDE * 2)), int(x0 * SIDE * 2):int(np.ceil(x1 * SIDE * 2))] = False
        box = im.crop((int(x0 * w), int(y0 * h), max(int(x1 * w), int(x0 * w) + 1), max(int(y1 * h), int(y0 * h) + 1)))
        lab = srgb_to_lab(np.asarray(box.resize((SIDE, SIDE), Image.BILINEAR))).reshape(-1, 3)
        b = blocks_of(lab)
        yy, xx = np.mgrid[0:SIDE, 0:SIDE]
        r2 = (((yy + .5) / SIDE - .5) ** 2 + ((xx + .5) / SIDE - .5) ** 2).reshape(-1) / 0.25 ** 2
        cw = np.exp(-r2)                                    # weight towards the middle of the box
        n = len(_centres)
        out.append((crop_id, np.bincount(b, minlength=n).astype(np.float32) / len(b),
                    (np.bincount(b, weights=cw, minlength=n) / cw.sum()).astype(np.float32),
                    lab.mean(0), (lab * cw[:, None]).sum(0) / cw.sum(), (x1 - x0) * (y1 - y0)))
    small = srgb_to_lab(np.asarray(im.resize((SIDE * 2, SIDE * 2), Image.BILINEAR)))
    bg = small[mask]
    bgh = (np.bincount(blocks_of(bg), minlength=len(_centres)).astype(np.float32) / len(bg)) if len(bg) > 50 else None
    return out, bgh


def init(c):
    global _centres
    _centres = c


def main(folder, boxes, images, photos, out):
    from flopo2.traitvision.colour_space import block_lab
    folder = Path(folder)
    lab = block_lab()
    numbers = sorted(lab)
    centres = np.array([lab[n] for n in numbers], np.float32)
    ext = {r['photo_id']: r['extension'] for r in csv.DictReader(open(folder / photos), delimiter='\t')}
    per = collections.defaultdict(list)
    for r in csv.DictReader(open(folder / boxes), delimiter='\t'):
        if r['organ'] == 'flower' and float(r['score']) >= MIN_SCORE:
            per[r['photo_id']].append((int(r['crop_id']), float(r['x0']), float(r['y0']), float(r['x1']), float(r['y1'])))
    jobs = [(folder / images / f'{int(p) % 1000:03d}' / f'{p}.{ext[p]}', b) for p, b in per.items() if p in ext]
    pids = [p for p in per if p in ext]
    ids, hist, chist, mean, cmean, area, bg_pid, bg = [], [], [], [], [], [], [], []
    with Pool(24, init, (centres,)) as pool:
        for pid, res in zip(pids, pool.imap(one, jobs, chunksize=64)):
            if res is None:
                continue
            for c, h, ch, m, cm, a in res[0]:
                ids.append(c); hist.append(h); chist.append(ch); mean.append(m); cmean.append(cm); area.append(a)
            if res[1] is not None:
                bg_pid.append(int(pid)); bg.append(res[1])
    np.savez(folder / out, blocks=np.array(numbers), crop_ids=np.array(ids), hist=np.array(hist), centre_hist=np.array(chist),
             mean=np.array(mean, np.float32), centre_mean=np.array(cmean, np.float32), area=np.array(area, np.float32),
             bg_photo=np.array(bg_pid), bg_hist=np.array(bg), centres=centres)
    print('photos', len(pids), 'flower boxes', len(ids))


if __name__ == '__main__':
    main(*sys.argv[1:])
