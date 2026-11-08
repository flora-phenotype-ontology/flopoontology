"""Verify pxGPT images and audit fine-tuning image overlap before scoring."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps

from .extract import digest


def signatures(path):
    with path.open('rb') as f:
        data = f.read()
    with Image.open(path) as source:
        im = ImageOps.exif_transpose(source).convert('RGB')
        pixels = list(im.convert('L').resize((9, 8)).getdata())
        bits = sum(int(pixels[y*9+x] > pixels[y*9+x+1]) << (y*8+x)
                   for y in range(8) for x in range(8))
        rgb = hashlib.sha256(str(im.size).encode()+im.tobytes()).hexdigest()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'sha512': hashlib.sha512(data).hexdigest(),
            'dhash': f'{bits:016x}', 'decoded_rgb_sha256': rgb}


def segments(h):
    # Five disjoint segments ensure every <=4-bit neighbour shares a segment.
    return [(i, (h >> (i*13)) & ((1 << (12 if i == 4 else 13))-1)) for i in range(5)]


def run(a):
    rows = [json.loads(s) for s in (a.benchmark / 'images.jsonl').read_text().splitlines()]
    train = [json.loads(s) for s in a.training.read_text().splitlines() if json.loads(s)['split'] == 'train']
    by_hash = defaultdict(list); buckets = defaultdict(set)
    for i, r in enumerate(train):
        by_hash[r['sha256']].append(i)
        for segment in segments(int(r['dhash'], 16)): buckets[segment].add(i)
    matches = []; computed = []; excluded = set(); decoded = defaultdict(set)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = pool.map(signatures, [a.images / r['image_file'] for r in rows])
        for i, (r, sig) in enumerate(zip(rows, values)):
            if sig['sha512'] != r['sha512']: raise ValueError('Changed image: '+r['image_file'])
            h = int(sig['dhash'], 16); candidates = set(by_hash[sig['sha256']])
            for segment in segments(h): candidates.update(buckets[segment])
            for j in sorted(candidates):
                other = train[j]; dist = (h ^ int(other['dhash'], 16)).bit_count()
                if sig['sha256'] == other['sha256'] or dist <= 4:
                    excluded.add(r['cultivar_id'])
                    matches.append({'image_file': r['image_file'], 'cultivar_id': r['cultivar_id'],
                        'training_photo_id': other['photo_id'], 'exact': sig['sha256'] == other['sha256'], 'dhash_distance': dist})
            decoded[sig['decoded_rgb_sha256']].add(r['cultivar_id'])
            computed.append({'image_file': r['image_file'], **sig})
            if (i+1) % 500 == 0: print('Audited', i+1, '/', len(rows), flush=True)
    duplicates = [sorted(v) for v in decoded.values() if len(v) > 1]
    for group in duplicates: excluded.update(group)
    result = {'images_manifest_sha256': digest(a.benchmark / 'images.jsonl'),
        'training_manifest_sha256': digest(a.training), 'source_sha256': digest(__file__),
        'training_images': len(train), 'verified_images': len(rows),
        'exact_matches': sum(r['exact'] for r in matches), 'perceptual_candidates': len(matches),
        'cross_cultivar_identical_pixels': duplicates, 'excluded_cultivars': sorted(excluded),
        'matches': matches, 'limitations': 'Perceptual candidates are conservatively excluded, not asserted duplicates. Foundation-model training overlap is unknown.'}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2)+'\n')
    a.out.with_name('image-signatures.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in computed))
    print(json.dumps({k:v for k,v in result.items() if k != 'matches'}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ['benchmark', 'images', 'training', 'out']: p.add_argument('--'+n, type=Path, required=True)
    run(p.parse_args())


if __name__ == '__main__': main()
