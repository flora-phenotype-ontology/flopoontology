"""Turn organ crops into training sets that ``train.py`` reads, one per organ group (standalone; runs on ORIX).

    python crop_split.py --data DIR --crops crops-v3 --field-crops crops-field \
        --photos inat-photos-v3.tsv --field field-test-v3.tsv [--whole]

Every crop of the organ becomes one "photo" of its species or observation, so that ``train.py`` pools over
crops as it pools over photos (``--pool mean`` or ``max``).  For each group G this writes

    emb-crop-G/ and emb-crop-G-field/     crop embeddings (ids are crop ids = photo id * 16 + k)
    crop-photos-G.tsv                     photo_id (the crop id), taxon
    crop-field-G.tsv                      the test observations, with crop ids in ``photos``

Training photos without a crop of the organ are left out.  A test observation without one keeps its whole
photos (id = photo id * 16 + 15), so every method is scored on the same observations.  With ``--whole`` the
whole photo is added for every photo, in training too (group names end in ``+w``).
"""
import argparse
import collections
import csv
from pathlib import Path

import numpy as np

GROUPS = {'flower': {'flower'}, 'fruit': {'fruit'}, 'leaf': {'leaf'}, 'leafstem': {'leaf', 'stem'},
          'thornstem': {'thorn', 'stem'}}
TRAITS = {'flower': 'flower_colour,inflorescence', 'fruit': 'fruit_colour', 'leaf': 'leaf_complexity,leaf_margin',
          'leafstem': 'leaf_arrangement', 'thornstem': 'spines'}


def load(folder):
    embs, ids = [], []
    for f in sorted(Path(folder).glob('emb-*.npy')):
        embs.append(np.load(f, mmap_mode='r'))
        ids.extend(int(x) for x in f.with_suffix('.ids').read_text().split())
    return embs, np.array(ids)


def take(embs, rows):
    """Rows (global indices over the concatenated files), in order."""
    out = np.empty((len(rows), embs[0].shape[1]), np.float16)
    start = 0
    rows = np.asarray(rows)
    for e in embs:
        m = (rows >= start) & (rows < start + len(e))
        if m.any():
            out[m] = e[rows[m] - start]
        start += len(e)
    return out


def boxes(folder, organs):
    by_photo = collections.defaultdict(list)
    for f in sorted(Path(folder).glob('boxes-*.tsv')):
        for r in csv.DictReader(open(f), delimiter='\t'):
            if r['organ'] in organs:
                by_photo[int(r['photo_id'])].append(int(r['crop_id']))
    return by_photo


def write(folder, vectors, ids):
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / 'emb-0.npy', vectors)
    (folder / 'emb-0.ids').write_text('\n'.join(map(str, ids)) + '\n')


def build(crop_dir, whole_dir, photos, organs, whole, fallback):
    """photos: photo ids to cover. Returns (vectors, ids, {photo: [ids]})."""
    cembs, cids = load(crop_dir)
    crow = {int(c): n for n, c in enumerate(cids)}
    wembs, wids = load(whole_dir)
    wrow = {int(p): n for n, p in enumerate(wids)}
    by_photo = boxes(crop_dir, organs)
    crop_rows, crop_ids, whole_rows, whole_ids, of = [], [], [], [], {}
    for p in photos:
        cs = [c for c in by_photo.get(p, []) if c in crow]
        mine = list(cs)
        crop_rows += [crow[c] for c in cs]
        crop_ids += cs
        if p in wrow and (whole or (fallback and not cs)):
            whole_rows.append(wrow[p])
            whole_ids.append(p * 16 + 15)
            mine.append(p * 16 + 15)
        if mine:
            of[p] = mine
    vec = np.concatenate([take(cembs, crop_rows), take(wembs, whole_rows)])
    return vec, crop_ids + whole_ids, of


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--crops', default='crops-v3')
    p.add_argument('--field-crops', default='crops-field')
    p.add_argument('--photos', default='inat-photos-v3.tsv')
    p.add_argument('--field', default='field-test-v3.tsv')
    p.add_argument('--whole', action='store_true')
    p.add_argument('--groups', default=','.join(GROUPS))
    a = p.parse_args()
    d = a.data
    taxon = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(d / a.photos), delimiter='\t')}
    field = list(csv.DictReader(open(d / a.field), delimiter='\t'))
    fphotos = sorted({int(x) for r in field for x in r['photos'].split('|')})
    for g in a.groups.split(','):
        name = g + ('+w' if a.whole else '')
        vec, ids, of = build(d / a.crops, d / 'emb', sorted(taxon), GROUPS[g], a.whole, False)
        write(d / f'emb-crop-{name}', vec, ids)
        with open(d / f'crop-photos-{name}.tsv', 'w') as f:
            f.write('photo_id\ttaxon\n')
            for ph, cs in of.items():
                f.writelines(f'{c}\t{taxon[ph]}\n' for c in cs)
        fvec, fid, fof = build(d / a.field_crops, d / 'emb-field', fphotos, GROUPS[g], a.whole, True)
        write(d / f'emb-crop-{name}-field', fvec, fid)
        with open(d / f'crop-field-{name}.tsv', 'w') as f:
            w = csv.DictWriter(f, fieldnames=list(field[0]), delimiter='\t', lineterminator='\n')
            w.writeheader()
            for r in field:
                cs = [c for x in r['photos'].split('|') for c in fof.get(int(x), [])]
                if cs:
                    w.writerow({**r, 'photos': '|'.join(map(str, cs))})
        print(name, 'training crops', len(ids), 'photos', len(of), 'of', len(taxon), '| test crops', len(fid), flush=True)


if __name__ == '__main__':
    main()
