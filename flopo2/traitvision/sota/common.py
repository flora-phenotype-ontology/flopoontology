"""Helpers shared by the SOTA comparison scripts (numpy, torch, PIL only; no pandas).

On ORIX the scripts of this folder are copied flat into ``pilot-v1/src/`` next to ``train.py`` and
``regime_tests.py``; locally they run as ``python -m flopo2.traitvision.sota.<name>``.
"""
import csv
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def tsv(path):
    return list(csv.DictReader(open(path, newline=''), delimiter='\t'))


def photo_file(root, image_dir, pid, ext):
    """pilot-v1 layout: <root>/<image_dir>/<last three digits>/<photo id>.<ext>"""
    return Path(root) / image_dir / f'{int(pid) % 1000:03d}' / f'{pid}.{ext or "jpg"}'


def imagenet_transform(size=224, resize=256):
    """Resize the short side to 256 (bicubic), centre crop 224, ImageNet statistics. This is the PhenoVision
    processor (ConvNext, crop_pct 0.875) and the PlantTraitNet test transform."""
    from torchvision import transforms as Tr
    return Tr.Compose([Tr.Resize(resize, interpolation=Tr.InterpolationMode.BICUBIC), Tr.CenterCrop(size),
                       Tr.ToTensor(), Tr.Normalize(IMAGENET_MEAN, IMAGENET_STD)])


class ImageSet(torch.utils.data.Dataset):
    """Items are file paths, or (zip file, member) pairs. Returns (tensor, index, ok).

    JPEGs are decoded at reduced size (PIL ``draft``), which is several times faster for 2048-pixel
    iNaturalist photographs and is what keeps the GPU busy. Unreadable files give a zero image and ok=False.
    """

    def __init__(self, items, transform, min_side=256):
        self.items, self.transform, self.min_side = items, transform, min_side
        self._zips = {}

    def __len__(self):
        return len(self.items)

    def _open(self, item):
        if isinstance(item, tuple):
            z = self._zips.get(item[0])
            if z is None:
                z = self._zips[item[0]] = zipfile.ZipFile(item[0])
            return Image.open(io.BytesIO(z.read(item[1])))
        return Image.open(item)

    def __getitem__(self, i):
        try:
            im = self._open(self.items[i])
            im.draft('RGB', (self.min_side, self.min_side))
            im = ImageOps.exif_transpose(im.convert('RGB'))
            return self.transform(im), i, True
        except Exception:
            return torch.zeros(3, 224, 224), i, False


def loader(items, transform, batch=256, workers=44, min_side=256):
    return torch.utils.data.DataLoader(ImageSet(items, transform, min_side), batch_size=batch, num_workers=workers,
                                       prefetch_factor=2, pin_memory=True, persistent_workers=False)


def auc(score, truth):
    """Area under the ROC curve (rank form)."""
    score, truth = np.asarray(score, float), np.asarray(truth, float)
    order = np.argsort(score, kind='stable')
    rank = np.empty(len(score))
    rank[order] = np.arange(1, len(score) + 1)
    pos = truth.sum()
    neg = len(truth) - pos
    return float((rank[truth > 0].sum() - pos * (pos + 1) / 2) / (pos * neg)) if pos and neg else float('nan')


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def import_pilot():
    """train.py and regime_tests.py of the pilot (flat on ORIX, a package locally)."""
    try:
        import regime_tests as R
        import train as T
    except ImportError:
        from flopo2.traitvision import regime_tests as R
        from flopo2.traitvision import train as T
    return T, R
