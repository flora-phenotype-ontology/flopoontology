"""Modern organ-region encoder with open-world weak trait supervision.

Stage one fits multilabel heads on frozen features. MIL source bags are an
adaptation, not a reproduction of PCP and not an estimate of trait prevalence.
No species loss, image-level training trait labels or test-based selection.
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .extract import digest, select_proposals
from .modern import load_encoder, encode_images, normalize
from .trait_heads import make_head, organ_centers


CONTEXT_QUALITIES = {'petiolate', 'sessile (sensu botany)', 'opposite', 'alternate placement'}


def extract(args):
    from PIL import Image, ImageOps
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('Use a Slurm GPU allocation')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    torch.set_num_threads(4); started = time.monotonic()
    args.out.mkdir(parents=True, exist_ok=False)
    inv = json.loads((args.data / 'trait-inventory.json').read_text())
    split_audit = json.loads((args.data / 'split-audit.json').read_text())
    if digest(args.data / 'splits.jsonl') != split_audit['splits_sha256']:
        raise ValueError('Changed cohort split')
    rows = [json.loads(s) for s in (args.data / 'splits.jsonl').read_text().splitlines()]
    shard_count = getattr(args, 'shard_count', 1); shard_index = getattr(args, 'shard_index', 0)
    if not 0 <= shard_index < shard_count: raise ValueError('Invalid extraction shard')
    rows = rows[shard_index::shard_count]
    model, processor, tokenizer, spec = load_encoder(args.models, args.model)
    if spec['kind'] != 'fgclip2': raise ValueError('This extraction uses native FG-CLIP region features')
    detector_manifest = json.loads((args.detector / 'manifest.json').read_text())['detector']
    for name, expected in detector_manifest['files'].items():
        if digest(args.detector / 'detector' / name) != expected:
            raise ValueError('Changed detector weights')
    dp = AutoProcessor.from_pretrained(args.detector / 'detector', local_files_only=True)
    detector = AutoModelForZeroShotObjectDetection.from_pretrained(args.detector / 'detector', local_files_only=True).cuda().eval()
    prompts = []
    for t in inv['traits']:
        label = t['label'].replace('pubescent hair', 'pubescent').replace('sessile (sensu botany)', 'sessile')
        prompts.append('a close-up photograph of ' + label)
    with torch.inference_mode():
        tok = tokenizer(prompts, padding='max_length', max_length=64, truncation=True, return_tensors='pt').to('cuda')
        text = normalize(model.get_text_features(**tok, walk_type='box')).cpu().numpy()
    samples, chunks, pending, pending_rows = [], [], [], []
    def flush():
        if not pending: return
        with torch.inference_mode():
            feat = encode_images(model, processor, pending, spec['kind'], views=('region',))['region']
        chunks.append(feat); samples.extend(pending_rows)
        with (args.out / 'regions.jsonl').open('a') as f:
            f.writelines(json.dumps(r) + '\n' for r in pending_rows)
        pending.clear(); pending_rows.clear()
    with torch.inference_mode():
        for index, row in enumerate(rows):
            path = args.data / row['image_path']
            if digest(path) != row['sha256']: raise ValueError('Changed source image')
            with Image.open(path) as im:
                image = ImageOps.exif_transpose(im).convert('RGB')
            inputs = dp(images=image, text='leaf. petal. flower. fruit.', return_tensors='pt').to('cuda')
            output = detector(**inputs)
            detected = dp.post_process_grounded_object_detection(output, inputs.input_ids,
                threshold=.4, text_threshold=.25, target_sizes=[(image.height, image.width)])[0]
            proposals = select_proposals(detected, image)
            chosen = set()
            for prop in proposals:
                organ = prop['organ']; b = prop['box']
                # A flower detection is not silently interpreted as a petal.
                if organ not in ('leaf', 'petal', 'fruit') or organ in chosen or min(b[2]-b[0], b[3]-b[1]) < 96:
                    continue
                chosen.add(organ); pending.append(image.crop(b))
                pending_rows.append(dict(row, organ=organ, box=b, detector_score=prop['score']))
            if len(pending) >= 24: flush()
            if (index + 1) % 100 == 0: print(f"Encoded proposals for {index+1}/{len(rows)} photos; {len(samples)} regions", flush=True)
    flush()
    if not chunks: raise ValueError('No usable organ proposals')
    np.savez_compressed(args.out / 'features.npz', regions=np.concatenate(chunks), text=text)
    (args.out / 'inventory.json').write_text(json.dumps(inv, indent=2) + '\n')
    (args.out / 'prompts.json').write_text(json.dumps(prompts, indent=2) + '\n')
    provenance = {'model': args.model, 'model_spec': spec, 'detector': detector_manifest,
        'splits_sha256': digest(args.data / 'splits.jsonl'), 'inventory_sha256': digest(args.out / 'inventory.json'),
        'features_sha256': digest(args.out / 'features.npz'), 'regions_sha256': digest(args.out / 'regions.jsonl'),
        'source_sha256': digest(__file__), 'slurm_job_id': os.environ['SLURM_JOB_ID'],
        'gpu': torch.cuda.get_device_name(), 'seconds': time.monotonic() - started,
        'regions': len(samples), 'images': len(rows), 'organs': dict(Counter(r['organ'] for r in samples)),
        'shard_index': shard_index, 'shard_count': shard_count,
        'limitations': ['Frozen organ detector, not verified organ visibility.', 'No gold trait labels.',
            'Leaf arrangement and petiole traits require context; excluded from crop-only training.']}
    (args.out / 'extraction.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps(provenance, indent=2), flush=True)


def event_probability(probabilities, indices):
    """Independent Bernoulli disjunction; no closed-world sibling negatives."""
    q = probabilities[..., indices].clamp(1e-6, 1-1e-6)
    return -torch.expm1(torch.log1p(-q).sum(-1))


def bernoulli_kl(reference, prediction):
    p = reference.clamp(1e-6, 1-1e-6); q = prediction.clamp(1e-6, 1-1e-6)
    return p * (p.log()-q.log()) + (1-p) * ((1-p).log()-(1-q).log())


def ontology_edges(traits, ancestors):
    return [(a['index'], b['index']) for a in traits for b in traits
            if a['index'] != b['index'] and a['bearer'] == b['bearer']
            and b['quality'] in ancestors.get(a['quality'], [])]


def source_bags(rows, inventory):
    bags = defaultdict(list)
    for i, r in enumerate(rows):
        if r['split'] == 'train': bags[(r['taxon'], r['organ'])].append(i)
    events = []
    for e in inventory['events']:
        if any(inventory['traits'][k]['quality_label'] in CONTEXT_QUALITIES for k in e['any_of']): continue
        indices = bags.get((e['taxon'], e['organ']), [])
        if indices: events.append((indices, e['any_of'], e['taxon']))
    return events


def negative_pairs(inventory):
    """Only scoped hair-presence contrasts; not arbitrary shape/colour negatives."""
    traits = inventory['traits']; pairs = []
    for a in traits:
        if a['quality_label'] != 'glabrous': continue
        for b in traits:
            if b['bearer'] == a['bearer'] and b['quality_label'] in ('hairy', 'pubescent hair', 'tomentose'):
                pairs.append((a['index'], b['index']))
    return pairs


def fit(args):
    torch.set_num_threads(4)
    device = getattr(args, 'device', 'cpu')
    if device == 'cuda' and (not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID')):
        raise RuntimeError('GPU fitting requires a Slurm allocation')
    ext = json.loads((args.out / 'extraction.json').read_text())
    for filename, key in [('features.npz', 'features_sha256'), ('regions.jsonl', 'regions_sha256'), ('inventory.json', 'inventory_sha256')]:
        if digest(args.out / filename) != ext[key]: raise ValueError('Changed feature artifact')
    inv = json.loads((args.out / 'inventory.json').read_text())
    queries = json.loads((args.data / 'queries.json').read_text())
    rows = [json.loads(s) for s in (args.out / 'regions.jsonl').read_text().splitlines()]
    # Training tensors contain training rows only, not evaluation feature regularizers.
    all_features = np.load(args.out / 'features.npz')
    indices = [i for i, r in enumerate(rows) if r['split'] == 'train']
    train_rows = [rows[i] for i in indices]
    x = torch.tensor(all_features['regions'][indices], dtype=torch.float32, device=device)
    text = torch.tensor(all_features['text'], dtype=torch.float32, device=device)
    events = source_bags(train_rows, inv)
    if not events: raise ValueError('No eligible training events')
    edges = ontology_edges(inv['traits'], queries['ancestors'])
    pairs = negative_pairs(inv)
    # Negatives require an unambiguous positive and no contradictory source event.
    possible = defaultdict(set); single = defaultdict(set)
    for e in inv['events']:
        possible[e['taxon']].update(e['any_of'])
        if len(e['any_of']) == 1: single[e['taxon']].update(e['any_of'])
    negatives = []
    for i, r in enumerate(train_rows):
        for a, b in pairs:
            if inv['traits'][a]['organ'] != r['organ']: continue
            if a in single[r['taxon']] and b not in possible[r['taxon']]: negatives.append((i, b))
            if b in single[r['taxon']] and a not in possible[r['taxon']]: negatives.append((i, a))
    counts = Counter(taxon for _, _, taxon in events)
    event_weights = torch.tensor([1/counts[taxon]/len(counts) for _, _, taxon in events], device=device)
    event_masks = torch.zeros(len(events), len(inv['traits']), device=device)
    for i, (_, allowed, _) in enumerate(events): event_masks[i, allowed] = 1.
    edge_masks = {a: [i for i, r in enumerate(train_rows) if r['organ'] == inv['traits'][a]['organ']] for a, _ in edges}
    checkpoints = []; histories = {}; diagnostics = {}
    modes = ('mil_weak', 'mil_flopo', 'offset_mil', 'offset_flopo', 'centered_mil', 'centered_flopo') if getattr(args, 'followup', False) else ('direct_weak', 'mil_weak', 'mil_flopo')
    centers = organ_centers(x, train_rows, inv['traits'])
    for mode in modes:
        for seed in (20261025, 20261026, 20261027):
            torch.manual_seed(seed); rng = np.random.default_rng(seed)
            kind = 'offset' if mode.startswith('offset_') else 'centered' if mode.startswith('centered_') else 'linear'
            head = make_head(text, kind, centers)
            with torch.no_grad(): teacher = head(x).sigmoid()
            opt = torch.optim.AdamW(head.parameters(), lr=.001, weight_decay=0.)
            history = []
            # Each taxon contributes equal total source-event weight.
            for step in range(args.steps + 1):
                opt.zero_grad(); q = head(x).sigmoid()
                # Fixed four-view bags keep the loss scale independent of taxon size.
                chosen = torch.tensor(np.stack([rng.choice(bag, size=4, replace=len(bag)<4) for bag, _, _ in events]), device=device)
                bag_probs = q[chosen].clamp(1e-6, 1-1e-6)
                event_q = -torch.expm1((torch.log1p(-bag_probs)*event_masks[:, None, :]).sum(-1))
                if mode == 'direct_weak': terms = -(.05 + .95*event_q).log().mean(-1)
                else: terms = -(.05 + .95*event_q.max(-1).values).log()
                weak = (terms * event_weights).sum()
                anchor = bernoulli_kl(teacher, q).mean()
                negative = q.sum() * 0.
                if negatives:
                    ni, nj = zip(*negatives)
                    negative = -(.05 + .95*(1-q[list(ni), list(nj)])).log().mean()
                logical = q.sum() * 0.
                if mode.endswith('_flopo'):
                    penalties = []
                    for a, b in edges:
                        mask = edge_masks[a]
                        if mask: penalties.append(F.relu(q[mask, a]-q[mask, b]).square().mean())
                    if penalties: logical = torch.stack(penalties).mean()
                loss = weak + anchor + negative + logical
                if step % 50 == 0 or step == args.steps:
                    history.append({'step': step, 'positive': float(weak.detach()), 'negative': float(negative.detach()),
                        'anchor': float(anchor.detach()), 'ontology': float(logical.detach())})
                if step == args.steps: break
                loss.backward(); opt.step()
            filename = f'{mode}-{seed}.pt'
            torch.save({'state_dict': {k: v.detach().cpu() for k, v in head.state_dict().items()}, 'traits': inv['traits'], 'model': ext['model'],
                'feature_dim': x.shape[1], 'seed': seed, 'steps': args.steps, 'mode': mode, 'head_kind': kind,
                'source': 'weak flora assertions and pretrained region/text alignment'}, args.out / filename)
            with torch.no_grad():
                delta = head(x) - (10*x@text.T-3.)
                diagnostics[filename] = {}
                for t in inv['traits']:
                    ids = [i for i, r in enumerate(train_rows) if r['organ'] == t['organ']]
                    if ids:
                        z = delta[ids, t['index']]
                        diagnostics[filename][t['label']] = {'mean_logit_change': float(z.mean()), 'std_logit_change': float(z.std(unbiased=False))}
            checkpoints.append(filename); histories[filename] = history
            print(mode, seed, history[-1], flush=True)
    result = {'status': 'trained_unvalidated', 'encoder': ext['model'], 'training_regions': len(train_rows),
        'training_taxa': len({r['taxon'] for r in train_rows}), 'usable_source_events': len(events),
        'source_supervised_traits': sorted({k for _, ks, _ in events for k in ks}),
        'context_traits_withheld': [t['index'] for t in inv['traits'] if t['quality_label'] in CONTEXT_QUALITIES],
        'ontology_edges': edges, 'scoped_hair_contrasts': pairs, 'negative_region_targets': len(negatives),
        'checkpoints': {f: digest(args.out / f) for f in checkpoints}, 'history': histories,
        'modes': modes, 'training_logit_changes': diagnostics,
        'selection': 'Fixed steps; no checkpoint or hyperparameter selection using species or held-out trait labels.',
        'no_species_loss': True, 'no_manual_trait_training_labels': True,
        'device': device, 'slurm_job_id': os.environ.get('SLURM_JOB_ID'),
        'queries_sha256': digest(args.data / 'queries.json'), 'source_sha256': digest(__file__),
        'head_source_sha256': digest(Path(__file__).with_name('trait_heads.py')),
        'extraction_sha256': digest(args.out / 'extraction.json'),
        'limitations': ['Independent trait evaluation pending.', 'Frozen encoder, not end-to-end fine-tuning.',
            'Crop visibility is unverified; positive bags may contain no visible evidence.',
            'MIL and partial priors are our adaptation, not a PCP reproduction.',
            'No quantitative class-conditional prevalence was assumed.',
            'Ontology arm enforces only recorded ancestor implications, not full OWL reasoning.',
            'Initial sigmoid scores are uncalibrated; fixed scale 10 and bias -3 are not fitted probabilities.']}
    (args.out / 'training.json').write_text(json.dumps(result, indent=2) + '\n')


def evaluate(args):
    from .modern import average_precision
    from .trait_eval import binary_metrics
    torch.set_num_threads(2)
    training = json.loads((args.out / 'training.json').read_text())
    own = json.loads((args.out / 'extraction.json').read_text())
    if digest(args.out / 'extraction.json') != training['extraction_sha256']:
        raise ValueError('Training/evaluation feature provenance differs')
    screen = json.loads((args.screen / 'extraction.json').read_text())
    if own['model_spec']['revision'] != screen['model_spec']['revision']:
        raise ValueError('Training/audit encoders differ')
    for directory, meta, filename, key in [(args.screen, screen, 'features.npz', 'features_sha256'),
            (args.screen, screen, 'rows.json', 'rows_sha256'),
            (args.screen, screen, 'external-rows.json', 'external_rows_sha256'),
            (args.out, own, 'features.npz', 'features_sha256'),
            (args.out, own, 'regions.jsonl', 'regions_sha256'),
            (args.out, own, 'inventory.json', 'inventory_sha256')]:
        if digest(directory / filename) != meta[key]: raise ValueError('Changed evaluation input')
    freeze = json.loads((args.audit / 'annotation-freeze.json').read_text())
    for filename, expected in freeze['sha256'].items():
        if digest(args.audit / filename) != expected: raise ValueError('Changed audit reference')
    inv = json.loads((args.out / 'inventory.json').read_text())
    trained_rows = [json.loads(s) for s in (args.out / 'regions.jsonl').read_text().splitlines()]
    train_taxa = {r['taxon'] for r in trained_rows if r['split'] == 'train'}
    train_names = {r['name'].casefold() for r in trained_rows if r['split'] == 'train'}
    field_rows = json.loads((args.screen / 'rows.json').read_text())
    ext_rows = json.loads((args.screen / 'external-rows.json').read_text())
    fa = json.loads((args.audit / 'field-annotations.json').read_text())
    ea = json.loads((args.audit / 'external-annotations.json').read_text())
    fj = json.loads((args.audit / 'private-join.json').read_text())
    ej = json.loads((args.audit / 'external-join.json').read_text())
    fi_lookup = {r['observation_id']: i for i, r in enumerate(field_rows)}
    ei_lookup = {r['id']: i for i, r in enumerate(ext_rows)}
    fi = [fi_lookup[r['observation_id']] for r in fj]; ei = [ei_lookup[r['specimen_id']] for r in ej]
    if len(fi) != len(fa) or len(ei) != len(ea): raise ValueError('Audit size mismatch')
    for a, j, i in zip(fa, fj, fi):
        if a['audit_id'] != j['audit_id'] or field_rows[i]['sha256'] != j['image_sha256'] or field_rows[i]['box'] != j['box']:
            raise ValueError('Audit crop mismatch')
    if [a['audit_id'] for a in ea] != [j['audit_id'] for j in ej]: raise ValueError('External join mismatch')
    overlap = train_taxa & {field_rows[i]['taxon'] for i in fi}
    if overlap: raise ValueError('Field audit taxa occurred in broad-cohort training')
    features = np.load(args.screen / 'features.npz')
    text = torch.tensor(np.load(args.out / 'features.npz')['text'], dtype=torch.float32)
    initial = nn.Linear(text.shape[1], text.shape[0])
    with torch.no_grad(): initial.weight.copy_(10*text); initial.bias.fill_(-3.)
    models = {'pretrained_same_vocabulary': [initial]}
    for mode in training.get('modes', ('direct_weak', 'mil_weak', 'mil_flopo')):
        models[mode] = []
        for seed in (20261025, 20261026, 20261027):
            filename = f'{mode}-{seed}.pt'
            if digest(args.out / filename) != training['checkpoints'][filename]: raise ValueError('Changed checkpoint')
            cp = torch.load(args.out / filename, weights_only=False, map_location='cpu')
            head = make_head(text, cp.get('head_kind', 'linear')); head.load_state_dict(cp['state_dict']); head.eval()
            models[mode].append(head)
    schema = json.loads((args.screen / 'schema.json').read_text())
    outline = {s['name'] for s in schema['groups']['outline']['colours']} - {'unknown'}
    shape_traits = [t for t in inv['traits'] if t['organ'] == 'leaf' and t['quality_label'] in outline]
    shape_ids = [t['index'] for t in shape_traits]
    results, predictions = {}, []
    with torch.inference_mode():
        for dataset, annotations, ids in [('field', fa, fi), ('external_original', ea, ei), ('external_masked', ea, ei)]:
            x = torch.tensor(features[dataset + '_region'][ids], dtype=torch.float32)
            results[dataset] = {}
            for mode, members in models.items():
                probs = torch.stack([m(x).sigmoid() for m in members]).mean(0).numpy()
                top = probs[:, shape_ids].argmax(-1)
                assessed = [i for i, a in enumerate(annotations) if a['outline_allowed']]
                correct = sum(shape_traits[top[i]]['quality_label'] in annotations[i]['outline_allowed'] for i in assessed)
                metrics = {}
                for t in shape_traits:
                    label = t['quality_label']
                    truth = [int(a['outline_allowed'][0] == label) if len(a['outline_allowed']) == 1 else None for a in annotations]
                    q = probs[:, t['index']]
                    metrics[label] = {**binary_metrics(truth, q), 'average_precision': average_precision(truth, q)}
                aps = [m['average_precision'] for m in metrics.values() if m['average_precision'] is not None]
                results[dataset][mode] = {'assessable_outline': len(assessed), 'set_compatible_correct': correct,
                    'set_compatible_accuracy': correct/len(assessed) if assessed else None,
                    'macro_average_precision': float(np.mean(aps)) if aps else None, 'per_literal_shape': metrics}
                for i, a in enumerate(annotations):
                    predictions.append({'dataset': dataset, 'model': mode, 'audit_id': a['audit_id'],
                        'shape_prediction': shape_traits[top[i]]['quality_label'], 'reference': a['outline_allowed'],
                        'probabilities': {t['label']: float(probs[i, t['index']]) for t in inv['traits'] if t['organ'] == 'leaf'}})
    report = {'results': results, 'no_species_metrics': True, 'annotation_freeze': freeze,
        'training_manifest_sha256': digest(args.out / 'training.json'), 'screen_extraction_sha256': digest(args.screen / 'extraction.json'),
        'field_training_taxon_overlap': sorted(overlap),
        'external_training_name_overlap': sorted(train_names & {ext_rows[i]['species'].casefold() for i in ei}),
        'reference_quality': 'Previously inspected AI image audit, not expert gold or untouched final test.',
        'scope': 'Literal shape diagnostics only; not complete multilabel FLOPO truth. No calibration fitting, checkpoint selection or species metrics. Hair references lack negatives and specific subtype labels.',
        'checkpoints': training['checkpoints']}
    (args.out / 'trait-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    (args.out / 'trait-predictions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in predictions))
    print(json.dumps({d: {m: {'correct': r['set_compatible_correct'], 'n': r['assessable_outline'],
        'macro_ap': r['macro_average_precision']} for m, r in models.items()} for d, models in results.items()}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['extract', 'fit', 'evaluate'])
    p.add_argument('--data', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--models', type=Path); p.add_argument('--model', default='fgclip2-base')
    p.add_argument('--detector', type=Path); p.add_argument('--steps', type=int, default=300)
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--followup', action='store_true', help='Compare unrestricted, offset-only and centered residual heads, each +/- FLOPO')
    p.add_argument('--shard-index', type=int, default=0); p.add_argument('--shard-count', type=int, default=1)
    p.add_argument('--screen', type=Path); p.add_argument('--audit', type=Path)
    args = p.parse_args()
    if args.command == 'extract': extract(args)
    elif args.command == 'fit': fit(args)
    else: evaluate(args)


if __name__ == '__main__': main()
