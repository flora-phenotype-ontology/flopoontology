"""Train from research-grade taxon labels and flora events, without manual annotations.

Pretrained image/text features supply a fallible visual prior, not gold anchors. Frozen
proposal gates approximate visibility. All outputs are development fits, never test truth.
"""
import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import re

import numpy as np
import torch

from .extract import digest
from .logic import Expr, probability
from .model import PrimitiveHead, localized_scene, ungrounded_atoms


def truth_mask(expr, vocabulary, ancestors):
    if ungrounded_atoms(expr, vocabulary, ancestors):
        raise ValueError('A source alternative is outside the visual vocabulary')
    scene = localized_scene(vocabulary, ['r0'], {'r0': True}, ancestors)
    formula = scene.ground(expr, 'plant')
    size = len(vocabulary['organs']) * len(vocabulary['colours'])
    mask = []
    for i in range(size):
        one_hot = [float(j == i) for j in range(size)]
        mask.append(probability(formula, {'r0.joint': one_hot}))
    if not any(mask) or all(mask):
        raise ValueError('Source event has no informative visual proof')
    return tuple(mask)


def source_events(profiles, queries, vocabulary):
    """Automatic conservative source filters; none of these records becomes gold."""
    groups = defaultdict(list)
    rejected = Counter()
    colour_attribute = 'http://purl.obolibrary.org/obo/PATO_0000014'
    # No inference about colour changes or developmental stages in this first run.
    scope = re.compile(r'\b(young|matur\w*|unripe|ripe|becom\w*|turn\w*|sometimes|usually|often|rarely|occasionally|immature)\b', re.I)
    cache = {}
    for profile in profiles:
        for r in profile['records']:
            if r.get('attribute') != colour_attribute:
                continue
            key = (profile['taxon'], r['b'])
            if r.get('qualifier') or scope.search(r.get('text', '')) or r.get('status') != 'accepted':
                groups[key].append(None); rejected['qualified_or_stage_sensitive_record'] += 1
                continue
            iri = r.get('pc')
            if iri not in queries['supported']:
                groups[key].append(None); rejected['missing_or_unsupported_definition'] += 1
                continue
            if iri not in cache:
                try:
                    cache[iri] = truth_mask(Expr.from_json(queries['supported'][iri]), vocabulary, queries['ancestors'])
                except ValueError:
                    cache[iri] = None
            if cache[iri] is None:
                groups[key].append(None); rejected['unrepresentable_event'] += 1
            else:
                groups[key].append({'query_iri': iri, 'source_record_id': r['r'], 'mask': cache[iri]})
    accepted = {}
    for key, events in groups.items():
        # A source group with additional unresolved statements is withheld, not forced consistent.
        if any(e is None for e in events):
            rejected['groups_with_unresolved_records'] += 1
            continue
        if len({e['mask'] for e in events}) != 1:
            rejected['groups_with_conflicting_allowed_events'] += 1
            continue
        accepted[key] = {'mask': events[0]['mask'],
            'query_iris': sorted({e['query_iri'] for e in events}),
            'source_record_ids': sorted({e['source_record_id'] for e in events})}
    return accepted, dict(rejected)


def prepare(data, *, threshold=.30, min_side=32):
    vocab = json.loads((data / 'vocabulary.json').read_text())
    queries = json.loads((data / 'queries.json').read_text())
    profiles = json.loads((data / 'profiles.json').read_text())
    profile_ids = {p['taxon']: p['inat_id'] for p in profiles}
    rows = [json.loads(line) for line in (data / 'images.jsonl').read_text().splitlines()]
    metadata = {r['photo_id']: r for r in map(json.loads, (data / 'extraction/regions.jsonl').read_text().splitlines())}
    run = json.loads((data / 'extraction/run.json').read_text())
    if run['input_manifest_sha256'] != digest(data / 'images.jsonl'):
        raise ValueError('Frozen extraction and observation manifests differ')
    events_by_group, excluded = source_events(profiles, queries, vocab)
    organ_iris = {o['name']: o['iri'] for o in vocab['organs'] if o['iri']}
    samples, features, events, seen = [], [], [], set()
    photo_taxa = defaultdict(set)
    for row in rows:
        photo_taxa[row['photo_id']].add(row['taxon'])
    for row in rows:
        photo = row['photo_id']
        if photo in seen or len(photo_taxa[photo]) != 1:
            continue
        seen.add(photo)
        if row['quality_grade'] != 'research' or row['inat_id'] != profile_ids[row['taxon']]:
            raise ValueError('Weak species supervision requires the exact frozen research-grade taxon link')
        record = metadata[photo]
        if record['sha256'] != row['sha256']:
            raise ValueError('Feature/image hash mismatch')
        fs = np.load(data / 'extraction/features' / f'{photo}.npz')['region_features']
        if len(fs) != len(record['regions']) or not np.isfinite(fs).all():
            raise ValueError('Invalid crop features')
        # One focal region per organ per image: overlapping crops do not become independent proofs.
        chosen = {}
        for i, region in enumerate(record['regions']):
            box = region['box']; organ = region['organ']
            if organ not in organ_iris or region['score'] < threshold or min(box[2]-box[0], box[3]-box[1]) < min_side:
                continue
            if organ not in chosen or region['score'] > record['regions'][chosen[organ]]['score']:
                chosen[organ] = i
        for organ, i in sorted(chosen.items()):
            index = len(samples)
            samples.append({'photo_id': photo, 'region_index': i, 'organ_proposal': organ,
                'observation_id': row['observation_id'], 'taxon': row['taxon'], 'genus': row['genus'],
                'gate': 'frozen_machine_proposal_heuristic', 'review_status': 'unreviewed',
                'detector_score': record['regions'][i]['score']})
            features.append(fs[i])
            event = events_by_group.get((row['taxon'], organ_iris[organ]))
            if event:
                events.append({**event, 'sample_index': index, 'photo_id': photo,
                    'observation_id': row['observation_id'], 'taxon': row['taxon'], 'region_index': i,
                    'supervision': 'research_grade_taxon_plus_automatically_filtered_flora', 'review_status': 'unreviewed'})
    if not events:
        raise ValueError('No eligible weak events; inspect source/gate exclusions')
    return vocab, torch.tensor(np.stack(features), dtype=torch.float32), samples, events, {
        'source_exclusions': excluded, 'accepted_source_groups': len(events_by_group),
        'regions': len(samples), 'images': len({s['photo_id'] for s in samples}),
        'weak_events': len(events), 'weak_observations': len({e['observation_id'] for e in events}),
        'weak_taxa': len({e['taxon'] for e in events}), 'threshold': threshold, 'min_side': min_side,
        'visibility': 'uncalibrated frozen proposal/size heuristic; not a reviewed assessability decision'}


def balanced_weights(rows):
    """Equal taxon weight, then observation weight; repeated photos do not multiply influence."""
    observations = defaultdict(set)
    counts = Counter((r['taxon'], r['observation_id']) for r in rows)
    for row in rows:
        observations[row['taxon']].add(row['observation_id'])
    weights = torch.tensor([1 / len(observations) / len(observations[r['taxon']]) /
                            counts[(r['taxon'], r['observation_id'])] for r in rows], dtype=torch.float32)
    return weights / weights.sum()


def initialize(vocab, prior):
    prototype = np.load(prior / 'prototypes.npz')
    report = json.loads((prior / 'prototypes.json').read_text())
    if digest(prior / 'prototypes.npz') != report['prototypes_sha256']:
        raise ValueError('Changed text prototypes')
    head = PrimitiveHead(prototype['organ'].shape[-1], vocab['organs'], vocab['colours'])
    # Temper the pretrained scale; this is a specified prior, not calibrated confidence.
    scale = min(float(prototype['logit_scale']), 50.0)
    with torch.no_grad():
        head.organ.weight.copy_(torch.from_numpy(prototype['organ']) * scale)
        head.organ.bias.zero_()
        head.colour_given_organ.weight.copy_(torch.from_numpy(prototype['colour']).flatten(0, 1) * scale)
        head.colour_given_organ.bias.zero_()
    return head, scale


def optimize(initial, features, samples, events, *, epsilon, epochs=100, prior_weight=1.0):
    if not 0 < epsilon < 1 or epochs < 1 or prior_weight <= 0:
        raise ValueError('Invalid training hyperparameters')
    head = copy.deepcopy(initial)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=0)
    with torch.no_grad():
        teacher = initial(features).detach()
    sample_weights = balanced_weights(samples).to(features.device)
    event_weights = balanced_weights(events).to(features.device)
    indices = torch.tensor([e['sample_index'] for e in events], device=features.device)
    masks = torch.tensor([e['mask'] for e in events], dtype=torch.float32, device=features.device)
    history = []
    def objective():
        prediction = head(features)
        mass = (prediction[indices] * masks).sum(-1)
        weak = (-torch.log(epsilon + (1 - epsilon) * mass) * event_weights).sum()
        kl_per_region = (teacher * (teacher.clamp_min(1e-9).log() - prediction.clamp_min(1e-9).log())).sum(-1)
        kl = (kl_per_region * sample_weights).sum()
        return weak + prior_weight * kl, weak, kl, (mass * event_weights).sum(), prediction
    for epoch in range(epochs + 1):
        optimizer.zero_grad()
        loss, weak, kl, mass, prediction = objective()
        if epoch in (0, epochs):
            history.append({'step': epoch, 'objective': loss.item(), 'weak_loss': weak.item(),
                            'kl_to_frozen_prior': kl.item(), 'training_allowed_event_mass': mass.item()})
        if epoch == epochs:
            return head, history, prediction.detach()
        loss.backward(); optimizer.step()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    args = parser.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(0)
    vocab, features, samples, events, audit = prepare(args.data)
    prior = args.data / 'text-prior'
    prior_meta = json.loads((prior / 'prototypes.json').read_text())
    if prior_meta['vocabulary_sha256'] != digest(args.data / 'vocabulary.json'):
        raise ValueError('Text prior and training vocabulary differ')
    initial, scale = initialize(vocab, prior)
    initial = initial.to(args.device)
    features = features.to(args.device)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'samples.json').write_text(json.dumps(samples, indent=2) + '\n')
    (args.out / 'events.json').write_text(json.dumps(events, indent=2) + '\n')
    torch.save({'state_dict': initial.state_dict(), 'vocabulary': vocab, 'feature_dim': features.shape[-1]}, args.out / 'pretrained-prior.pt')
    with torch.no_grad():
        np.savez_compressed(args.out / 'prior-predictions.npz', probabilities=initial(features).cpu().numpy())
    runs = []
    for epsilon in (.1, .3, .5):
        head, history, prediction = optimize(initial, features, samples, events, epsilon=epsilon, epochs=args.epochs)
        name = f'epsilon-{epsilon:.1f}'
        torch.save({'state_dict': head.state_dict(), 'vocabulary': vocab, 'feature_dim': features.shape[-1],
                    'epsilon': epsilon, 'status': 'weakly_trained_development_model'}, args.out / f'{name}.pt')
        np.savez_compressed(args.out / f'{name}-predictions.npz', probabilities=prediction.cpu().numpy())
        runs.append({'epsilon': epsilon, 'checkpoint': f'{name}.pt', 'history': history})
        print(json.dumps(runs[-1]), flush=True)
    report = {'status': 'weak_training_complete_without_manual_annotations', 'audit': audit,
        'epochs': args.epochs, 'prior_weight': 1.0, 'logit_scale': scale, 'runs': runs, 'device': args.device,
        'inputs_sha256': {str(p.relative_to(args.data)): digest(p) for p in [args.data / n for n in
            ('profiles.json', 'queries.json', 'images.jsonl', 'vocabulary.json', 'extraction/run.json', 'text-prior/prototypes.json')]},
        'script_sha256': digest(__file__), 'manual_training_annotations': 0,
        'evaluation_gold_used': 0, 'note': 'Training diagnostics only. Lower weak loss is not evidence of trait accuracy or a benefit from reasoning. No sensitivity setting was selected using test labels.'}
    (args.out / 'training.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
