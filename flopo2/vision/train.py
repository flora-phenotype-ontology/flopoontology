"""Train organ × colour heads on reviewed localized anchors and audited weak events.

Refuses unreviewed, development-as-test, mismatched crops and unanchored primitives.
This pilot trainer produces training diagnostics, never a held-out accuracy claim.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from .logic import Expr
from .model import PrimitiveHead, localized_scene, ungrounded_atoms, weak_loss


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_anchors(review_path, extraction, vocabulary):
    packet = json.loads(Path(review_path).read_text())
    if packet.get('schema') != 'flopo-visual-review-v1' or packet.get('purpose') != 'development_audit':
        raise ValueError('This trainer accepts the reviewed development audit only')
    metadata = {r['photo_id']: r for r in map(json.loads, (extraction / 'regions.jsonl').read_text().splitlines())}
    organs = [v['name'] for v in vocabulary['organs']]
    colours = [v['name'] for v in vocabulary['colours']]
    samples, seen = {}, set()
    for row in packet['images']:
        photo = row['photo_id']
        if photo in seen or row.get('split') != 'development_audit':
            raise ValueError('Duplicate image or invalid development split')
        seen.add(photo)
        if row.get('review_status') != 'reviewed' or not row.get('reviewer', '').strip():
            raise ValueError('Unreviewed images cannot supply localized anchors')
        stored = metadata.get(photo)
        if stored is None or row['sha256'] != stored['sha256']:
            raise ValueError('Image missing or hash mismatch')
        if len(row['regions']) > 6 or [r['box'] for r in row['regions']] != [r['box'] for r in stored['regions']]:
            raise ValueError('Corrected boxes require re-extraction before training')
        features = np.load(extraction / 'features' / f'{photo}.npz')['region_features']
        if len(features) != len(row['regions']) or not np.isfinite(features).all():
            raise ValueError('Invalid region features')
        if not len(features):
            continue
        labels, masks, eligibility = [], [], []
        for r in row['regions']:
            if not r.get('confirmed') or type(r.get('assessable')) is not bool:
                raise ValueError('Unconfirmed region or missing assessability')
            if r['organ'] not in organs or r['colour'] not in colours + ['unlabelled']:
                raise ValueError('Unsupported primitive label')
            if r['assessable'] and (r['colour'] == 'unknown' or r['organ'] == 'other'):
                raise ValueError('Assessable region needs a supported organ and colour')
            # Unassessable colours supply organ supervision only, never a negative colour.
            oi = organs.index(r['organ'])
            ci = colours.index(r['colour']) if r['colour'] != 'unlabelled' else colours.index('unknown')
            labels.append(oi * len(colours) + ci)
            masks.append(r['assessable'] and r['colour'] != 'unlabelled')
            eligibility.append(r['assessable'])
        samples[photo] = {'features': torch.tensor(features, dtype=torch.float32),
                         'labels': torch.tensor(labels), 'gold_mask': masks, 'assessable': eligibility, 'regions': row['regions']}
    if not samples:
        raise ValueError('No reviewed localized anchors; human review is required')
    return samples


def load_events(path, samples, vocabulary, queries, profiles_path, image_manifest):
    if path is None:
        return []
    rows = json.loads(Path(path).read_text())
    profiles = json.loads(Path(profiles_path).read_text())
    sources = {r['r']: r for p in profiles for r in p['records']}
    taxa = {r['photo_id']: r['taxon'] for r in image_manifest}
    events, seen = [], set()
    for row in rows:
        if row.get('review_status') != 'reviewed' or not row.get('reviewer', '').strip() or row.get('scope_compatible') is not True:
            raise ValueError('Weak events require source/scope audit')
        if not row.get('source_record_ids') or row.get('source_snapshot_sha256') != sha(profiles_path):
            raise ValueError('Weak events require pinned source provenance')
        if not isinstance(row.get('epsilon'), (int, float)) or not 0 < row['epsilon'] < 1:
            raise ValueError('Contamination must be fixed from the development audit')
        if not isinstance(row.get('reliability'), (int, float)) or not 0 <= row['reliability'] <= 1:
            raise ValueError('Source reliability must be an audited value in [0,1]')
        photo = row['photo_id']; sample = samples[photo]
        for source in row['source_record_ids']:
            record = sources[source]
            if record['t'] != taxa[photo] or record.get('pc') != row['query_iri'] or record.get('qualifier'):
                raise ValueError('Source does not match the observation taxon, query or unqualified scope')
        indices = row['regions']
        if not indices or len(indices) != len(set(indices)) or any(type(i) is not int or not 0 <= i < len(sample['regions']) for i in indices):
            raise ValueError('Invalid weak witness regions')
        if not all(sample['assessable'][i] for i in indices):
            raise ValueError('Weak event cannot supervise unassessable regions')
        organ_iris = {v['name']: v['iri'] for v in vocabulary['organs']}
        for i in indices:
            organ = organ_iris[sample['regions'][i]['organ']]
            if not any(sources[source]['b'] in queries['ancestors'].get(organ, [organ]) for source in row['source_record_ids']):
                raise ValueError('Reviewed organ does not match the source bearer')
        # A query must come from the frozen compiler output, not a taxon-derived image fact.
        expr = Expr.from_json(queries['supported'][row['query_iri']])
        if ungrounded_atoms(expr, vocabulary, queries['ancestors']):
            raise ValueError('The full query, including every allowed alternative, needs grounded primitives')
        ids = [f'r{i}' for i in indices]
        scene = localized_scene(vocabulary, ids, dict.fromkeys(ids, True), queries['ancestors'])
        formula = scene.ground(expr, 'plant')
        if formula is False:
            raise ValueError('Query has no proof in the anchored primitive vocabulary')
        key = (photo, tuple(sorted(indices)), repr(formula))
        if key in seen:
            continue
        seen.add(key)
        # Every state that can participate must have visual anchoring somewhere.
        events.append({**row, 'formula': formula, 'key': key})
    return events


def fit(samples, vocabulary, events, *, epochs=100, seed=0, weak_weight=0.2, device='cpu'):
    torch.manual_seed(seed)
    if epochs < 1 or weak_weight < 0:
        raise ValueError('Invalid training settings')
    head = PrimitiveHead(next(iter(samples.values()))['features'].shape[1], vocabulary['organs'], vocabulary['colours']).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-3)
    count_colours = len(vocabulary['colours'])
    anchored = {s['labels'][i].item() for s in samples.values() for i, a in enumerate(s['gold_mask']) if a}
    if events:
        used_organs = {index // count_colours for index in anchored}
        used_colours = {index % count_colours for index in anchored}
        needed_organs = {i for i, v in enumerate(vocabulary['organs']) if v['iri']}
        needed_colours = {i for i, v in enumerate(vocabulary['colours']) if v['iri']}
        if not needed_organs <= used_organs or not needed_colours <= used_colours:
            raise ValueError('Weak training requires visual anchors for every active organ and colour; narrow the vocabulary or annotate missing primitives')
    history = []
    for epoch in range(epochs):
        optimizer.zero_grad()
        predictions = {photo: head(s['features'].to(device)) for photo, s in samples.items()}
        gold = []
        for photo, sample in samples.items():
            for i, target in enumerate(sample['labels']):
                p = predictions[photo][i]
                value = p[target] if sample['gold_mask'][i] else p.reshape(-1, count_colours)[target.item() // count_colours].sum()
                gold.append(-value.clamp_min(1e-8).log())
        supervised = torch.stack(gold).mean()
        losses = []
        for event in events:
            ps = {f'r{i}.joint': predictions[event['photo_id']][i] for i in event['regions']}
            losses.append(weak_loss(event['formula'], ps, eligible=True, epsilon=event['epsilon'], weight=event['reliability']))
        weak = torch.stack(losses).mean() if losses else supervised * 0
        loss = supervised + weak_weight * weak
        loss.backward(); optimizer.step()
        if epoch in (0, epochs - 1):
            history.append({'epoch': epoch + 1, 'loss': loss.item(), 'supervised': supervised.item(), 'weak': weak.item()})
    return head, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--reviewed', type=Path, required=True)
    parser.add_argument('--extraction', type=Path, required=True)
    parser.add_argument('--weak-events', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    args = parser.parse_args()
    vocabulary = json.loads((args.data / 'vocabulary.json').read_text())
    queries = json.loads((args.data / 'queries.json').read_text())
    samples = load_anchors(args.reviewed, args.extraction, vocabulary)
    manifest = [json.loads(line) for line in (args.data / 'images.jsonl').read_text().splitlines()]
    events = load_events(args.weak_events, samples, vocabulary, queries, args.data / 'profiles.json', manifest)
    head, history = fit(samples, vocabulary, events, epochs=args.epochs, seed=args.seed, device=args.device)
    args.out.mkdir(parents=True, exist_ok=True)
    torch.save({'state_dict': head.state_dict(), 'vocabulary': vocabulary}, args.out / 'head.pt')
    report = {'status': 'development_fit_only', 'images': len(samples), 'weak_events': len(events),
              'seed': args.seed, 'epochs': args.epochs, 'history': history,
              'reviews_sha256': sha(args.reviewed), 'vocabulary_sha256': sha(args.data / 'vocabulary.json'),
              'queries_sha256': sha(args.data / 'queries.json'),
              'extraction_sha256': sha(args.extraction / 'run.json'),
              'weak_events_sha256': sha(args.weak_events) if args.weak_events else None,
              'note': 'No test evaluation. Independent grounded, genus-held-out labels are still required.'}
    (args.out / 'training.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
