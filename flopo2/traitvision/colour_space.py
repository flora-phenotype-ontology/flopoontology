"""Distances between colour values, from the colour value space that FLOPO already records.

Every FLOPO colour class is a union of ISCC-NBS level-3 blocks (annotation FLOPO_0988903), and every block
has a central Munsell notation (Kelly 1958, in ``config/iscc_nbs_backbone.tsv``). This turns the centres
into CIELAB and writes, for every colour value used in the floras:

* ``dist``: its distance to each training class (a basic colour): the mean, over the blocks of the value,
  of the CIEDE2000 difference to the nearest block of the class, averaged with the same from the class to
  the value (so a class is near only when most of it is near). 0 when the value lies inside the class.
* ``lab``: the centre of each value and class; ``between_classes`` gives the classes on the way from one
  value to another: c is between a and b when the path a -> c -> b is at most ``SLACK`` times a -> b.

    <venv with colour-science>/python -m flopo2.traitvision.colour_space local-corpora/trait-vision/colour-space.json
"""
import csv
import itertools
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np

from flopo2.traitvision import labels as L

ROOT = Path(__file__).resolve().parents[2]
SLACK = 1.15
NEUTRAL = {'N': 0.0}


def block_lab():
    """Block number -> CIELAB of its central notation."""
    import colour
    out = {}
    for r in csv.DictReader(open(ROOT / 'config/iscc_nbs_backbone.tsv'), delimiter='\t'):
        if r['level'] != '3' or not r['centroid_munsell']:
            continue
        m = r['centroid_munsell'].strip()
        n = re.fullmatch(r'N\s*([\d.]+)/?', m)
        h = re.fullmatch(r'([\d.]+)([A-Z]+)\s+([\d.]+)/([\d.]+)', m)
        clamp = lambda v: min(max(float(v), 1.0), 9.0)        # the renotation tables cover values 1 to 9
        spec = f'N{clamp(n.group(1)):.1f}' if n else f'{h.group(1)}{h.group(2)} {clamp(h.group(3)):.1f}/{h.group(4)}'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                xyY = colour.munsell_colour_to_xyY(spec)
            except Exception:                                # chroma beyond the tables: step it down
                c = float(h.group(4))
                while True:
                    c -= 1
                    try:
                        xyY = colour.munsell_colour_to_xyY(f'{h.group(1)}{h.group(2)} {clamp(h.group(3)):.1f}/{c:.1f}')
                        break
                    except Exception:
                        if c <= 1:
                            raise
            out[int(r['iscc_nbs_number'])] = colour.XYZ_to_Lab(colour.xyY_to_XYZ(xyY), colour.CCS_ILLUMINANTS[
                'CIE 1931 2 Degree Standard Observer']['C'])
    return out


def value_blocks():
    """Colour class -> its blocks; a class without blocks of its own takes those of its nearest ancestors."""
    text = (ROOT / 'ontology/flopo.owl').read_text()
    own = {}
    pat = r'<(?:rdf:Description|owl:Class) rdf:about="http://purl.obolibrary.org/obo/(\w+)">(.*?)</(?:rdf:Description|owl:Class)>'
    for m in re.finditer(pat, text, re.S):
        b = re.search(r'<obo:FLOPO_0988903>([\d ]+)</obo:FLOPO_0988903>', m.group(2))
        n = re.search(r'<obo:FLOPO_0988901[^>]*>(\d+)</obo:FLOPO_0988901>', m.group(2))
        if b:
            own[m.group(1)] = {int(x) for x in b.group(1).split()}
        elif n:
            own.setdefault(m.group(1), {int(n.group(1))})
    sup = L.ontology()

    def blocks(v, seen=()):
        if v in own:
            return own[v]
        found = set()
        for s in sup.get(v, ()):
            if s not in seen and s != 'PATO_0000014':
                found |= blocks(s, seen + (v,))
        return found
    return blocks


def between_classes(a, b, class_lab, skip=()):
    """Classes whose centre lies on the way from a to b (CIELAB points): a -> c -> b at most SLACK times a -> b."""
    a, b = np.array(a), np.array(b)
    direct = np.linalg.norm(a - b)
    return sorted(c for c, p in class_lab.items() if c not in skip and direct > 0
                  and np.linalg.norm(a - np.array(p)) + np.linalg.norm(np.array(p) - b) <= SLACK * direct)


def main(out):
    import colour
    lab = block_lab()
    blocks = value_blocks()
    numbers = sorted(lab)
    pts = np.array([lab[n] for n in numbers])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        de = colour.delta_E(pts[:, None, :], pts[None, :, :], method='CIE 2000')
    at = {n: i for i, n in enumerate(numbers)}
    basic = {name: sorted(at[b] for b in blocks(cid) if b in at) for cid, name in L.BASIC.items()}
    values = set()
    for f in ('pilot-assertions-v4.tsv', 'pilot-assertions.tsv'):
        p = Path(out).parent / f
        if p.exists():
            for r in csv.DictReader(open(p), delimiter='\t', quoting=csv.QUOTE_NONE):
                if r['attr'] == 'PATO_0000014':
                    values.update(v for v in r['values'].split('|') + [r.get('rel_from') or '', r.get('rel_to') or ''] if v)
            break
    rows = {v: sorted(at[b] for b in blocks(v) if b in at) for v in sorted(values)}
    rows = {v: b for v, b in rows.items() if b}

    def chamfer(a, b):                                          # 0 when a lies inside b
        if set(a) <= set(b):
            return 0.0
        return float(de[np.ix_(a, b)].min(1).mean() + de[np.ix_(b, a)].min(1).mean()) / 2
    chroma = np.hypot(pts[:, 1], pts[:, 2])

    def centre(b):                                              # of the more saturated half: colour words name clear colours
        b = np.array(b)
        return pts[b[chroma[b] >= np.median(chroma[b])]].mean(0)
    dist = {v: {c: round(chamfer(b, cb), 2) for c, cb in basic.items()} for v, b in rows.items()}
    class_dist = {a: {b: round(chamfer(ab, bb), 2) for b, bb in basic.items()} for a, ab in basic.items()}
    lab_of = {v: [round(float(x), 2) for x in centre(b)] for v, b in rows.items()}
    lab_of.update({c: [round(float(x), 2) for x in centre(cb)] for c, cb in basic.items()})
    between = {}
    for a, b in itertools.combinations(sorted(basic), 2):
        between[f'{a}|{b}'] = between_classes(lab_of[a], lab_of[b], {c: lab_of[c] for c in basic}, {a, b})
    Path(out).write_text(json.dumps({'classes': sorted(basic), 'class_dist': class_dist, 'dist': dist, 'lab': lab_of,
                                     'between_basic': between}, indent=1, sort_keys=True) + '\n')
    names = sorted(basic)
    print('distance between basic colours (CIEDE2000, nearest blocks, both directions)')
    print(' ' * 8 + ''.join(f'{n[:6]:>7s}' for n in names))
    for a in names:
        print(f'{a:8s}' + ''.join(f'{class_dist[a][b]:7.1f}' for b in names))
    print('between:', {k: v for k, v in between.items() if v})
    print('values with blocks:', len(rows), 'of', len(values))


if __name__ == '__main__':
    main(sys.argv[1])
