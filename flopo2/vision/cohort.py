"""Audit visual trait coverage and prepare a genus/observer-separated weak cohort.

Source assertions are positive disjunctions, never a dense negative matrix.
Training/evaluation partitions are not image-level trait reference annotations.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from .extract import digest


VISUAL = {
    'ovate', 'oblong', 'lanceolate', 'petiolate', 'alternate placement',
    'sessile (sensu botany)', 'opposite', 'elliptic', 'glabrous', 'obovate',
    'linear', 'orbicular', 'pubescent hair', 'serrated', 'heart shaped',
    'oblanceolate', 'green', 'spherical', 'red', 'yellow', 'orange', 'brown',
    'purple', 'white', 'hairy', 'tomentose', 'spatulate', 'dentated', 'blue', 'pink',
}
SCOPED = re.compile(r'\b(young|matur\w*|ripe|unripe|becom\w*|turn\w*|sometimes|usually|often|rarely|occasionally|immature|upper|lower)\b', re.I)
SURFACE = re.compile(r'\b(above|below|beneath|adaxial\w*|abaxial\w*|veins?|midrib|margin)\b', re.I)


def scoped(record):
    return (bool(record.get('qualifier')) or bool(SCOPED.search(record['text'])) or
            (record['ql'] in {'glabrous', 'hairy', 'pubescent hair', 'tomentose'} and
             bool(SURFACE.search(record['text']))))


def hash_bucket(value, modulus=100):
    return int(hashlib.sha256(str(value).encode()).hexdigest()[:12], 16) % modulus


def inventory(profiles, max_traits=30, minimum_taxa=5):
    supports = defaultdict(set); examples = {}; skipped = Counter()
    assertions = defaultdict(list)
    for p in profiles:
        for r in p['records']:
            assertions[(p['taxon'], r['r'])].append(r)
            if r['ql'] not in VISUAL:
                skipped['outside_selected_visual_qualities'] += 1; continue
            if scoped(r) or r['status'] != 'accepted':
                skipped['scope_or_status'] += 1; continue
            key = (r['b'], r['q'])
            supports[key].add(p['taxon']); examples[key] = r
    selected = sorted((k for k in supports if len(supports[k]) >= minimum_taxa),
                      key=lambda k: (-len(supports[k]), k))[:max_traits]
    index = {k: i for i, k in enumerate(selected)}
    traits = [{'index': i, 'organ': examples[k]['bl'], 'bearer': k[0], 'quality': k[1],
               'label': examples[k]['bl'] + ' ' + examples[k]['ql'],
               'quality_label': examples[k]['ql'], 'source_support_taxa': len(supports[k])}
              for i, k in enumerate(selected)]
    events = []
    for (taxon, assertion), records in assertions.items():
        if any(scoped(r) or r['status'] != 'accepted' for r in records):
            continue
        # A partially represented alternative must not become a narrower target.
        keys = {(r['b'], r['q']) for r in records}
        if not keys <= index.keys() or len({r['bl'] for r in records}) != 1:
            skipped['unrepresented_alternative'] += 1; continue
        allowed = sorted({index[k] for k in keys})
        if allowed:
            events.append({'taxon': taxon, 'source_record': assertion,
                'source': records[0]['src'], 'text': records[0]['text'],
                'organ': records[0]['bl'], 'any_of': allowed,
                'supervision': 'positive_source_disjunction', 'image_truth': 'unknown'})
    by_taxon = defaultdict(set)
    for e in events:
        by_taxon[e['taxon']].update(e['any_of'])
    counts = Counter(tuple(sorted(v)) for v in by_taxon.values())
    return {'traits': traits, 'events': events, 'taxa_with_events': len(by_taxon),
            'profile_patterns': len(counts), 'repeated_profile_patterns': sum(n > 1 for n in counts.values()),
            'excluded': dict(skipped), 'negative_policy': 'Unmentioned traits are unknown; no automatic negative labels.',
            'scope': 'Positive bearer-quality assertions. No claim of complete or exception-free taxon phenotypes.'}


def partition(rows, excluded_observers=(), excluded_hashes=(), heldout_taxa=()):
    excluded_observers, excluded_hashes, heldout_taxa = set(excluded_observers), set(excluded_hashes), set(heldout_taxa)
    kept, rejected = [], Counter()
    seen_photos = set(); hash_split = {}; observer_splits = defaultdict(set)
    image_taxa = defaultdict(set)
    for r in rows: image_taxa[r['sha256']].add(r['taxon'])
    # Taxa are selected one per genus; hash genus explicitly to retain that invariant.
    for r in sorted(rows, key=lambda x: (x['observation_id'], x['photo_id'])):
        if len(image_taxa[r['sha256']]) > 1:
            rejected['conflicting_image_taxa'] += 1; continue
        if r.get('observer_id') is None:
            rejected['missing_observer'] += 1; continue
        if r['observer_id'] in excluded_observers or r['sha256'] in excluded_hashes:
            rejected['previous_audit_overlap'] += 1; continue
        b = hash_bucket(r['genus'])
        split = 'train' if b < 70 else 'validation' if b < 85 else 'test'
        if r['taxon'] in heldout_taxa: split = 'test'
        observer_splits[r['observer_id']].add(split)
        kept.append({**r, 'split': split})
    # Remove cross-partition observers entirely; never move a held-out genus to train.
    result = []
    for r in kept:
        if len(observer_splits[r['observer_id']]) > 1:
            rejected['cross_split_observer'] += 1; continue
        if r['photo_id'] in seen_photos:
            rejected['reused_photo'] += 1; continue
        old = hash_split.get(r['sha256'])
        if old is not None:
            rejected['duplicate_image'] += 1; continue
        seen_photos.add(r['photo_id']); hash_split[r['sha256']] = r['split']; result.append(r)
    # dHash is only a candidate duplicate filter, not a guarantee of visual uniqueness.
    remove = set()
    for i, a in enumerate(result):
        if not a.get('dhash'): continue
        for b in result[:i]:
            if a['split'] != b['split'] and b.get('dhash') and (int(a['dhash'], 16) ^ int(b['dhash'], 16)).bit_count() <= 3:
                remove.update((a['photo_id'], b['photo_id']))
    rejected['cross_split_near_duplicate'] = len(remove)
    result = [r for r in result if r['photo_id'] not in remove]
    return result, dict(rejected)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['inventory', 'partition'])
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--previous', type=Path)
    args = p.parse_args()
    profiles = json.loads((args.data / 'profiles.json').read_text())
    result = inventory(profiles)
    result['profiles_sha256'] = digest(args.data / 'profiles.json')
    (args.data / 'trait-inventory.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.command == 'partition':
        old = [json.loads(x) for x in (args.previous / 'splits.jsonl').read_text().splitlines()] if args.previous else []
        rows = [json.loads(x) for x in (args.data / 'images.jsonl').read_text().splitlines()]
        eligible = {e['taxon'] for e in result['events']}
        rows, rejected = partition([r for r in rows if r['taxon'] in eligible],
            excluded_observers={r['observer_id'] for r in old if r['split'] != 'train'},
            excluded_hashes={r['sha256'] for r in old if r['split'] != 'train'},
            heldout_taxa={r['taxon'] for r in old})
        split_file = args.data / 'splits.jsonl'
        split_file.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        info = {'images': dict(Counter(r['split'] for r in rows)),
            'taxa': {s: len({r['taxon'] for r in rows if r['split'] == s}) for s in ['train', 'validation', 'test']},
            'observations': {s: len({r['observation_id'] for r in rows if r['split'] == s}) for s in ['train', 'validation', 'test']},
            'rejected': rejected, 'splits_sha256': digest(split_file),
            'source_sha256': digest(__file__), 'reference_status': 'No image-level gold labels; validation/test images reserved for annotation.',
            'previous_splits_sha256': digest(args.previous / 'splits.jsonl') if args.previous else None}
        (args.data / 'split-audit.json').write_text(json.dumps(info, indent=2) + '\n')
        print(json.dumps(info, indent=2))
    print(json.dumps({'traits': len(result['traits']), 'events': len(result['events']),
                      'taxa_with_events': result['taxa_with_events'], 'profile_patterns': result['profile_patterns']}))


if __name__ == '__main__': main()
