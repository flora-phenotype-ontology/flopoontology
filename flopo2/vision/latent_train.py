"""Orix development training: pretrained traits -> DeepLog taxon WMC + BEARS.

Prepare on CPU before allocating a GPU. Train and evaluate only train/validation;
test observations are excluded from feature loading and all losses/metrics.
"""
import argparse
from collections import Counter, defaultdict
import copy
import importlib.metadata
import json
import math
from pathlib import Path
import time

import numpy as np
import torch

from .bears import diversification, uncertainty
from .extract import digest
from .latent import LatentTaxonWMC
from .logic import combine
from .multi import MultiHead, compile_profiles, load_regions, ranking_profiles


def group_specs(schema):
    return {f'{organ}.{attr}': {'attribute': attr, 'organ': organ,
            'organ_index': [o['name'] for o in vocab['organs']].index(organ),
            'size': len(vocab['colours'])}
            for attr, vocab in schema['groups'].items() for organ in vocab['organs_in_scope']}


def concepts(model, features, specs):
    # Condition on the frozen detector's organ assignment. No image taxon enters.
    result = {}
    logits = {name: h.colour_given_organ(features).reshape(
        len(features), len(h.organs), len(h.colours)) for name, h in model.heads.items()}
    for group, spec in specs.items():
        result[group] = logits[spec['attribute']][:, spec['organ_index']].softmax(-1)
    return result


def observations(rows, samples, specs):
    rows_by_id = {r['observation_id']: r for r in rows}
    focal = {}
    for i, s in enumerate(samples):
        key = (s['observation_id'], s['organ'])
        if key not in focal or s['detector_score'] > samples[focal[key]]['detector_score']:
            focal[key] = i
    result = []
    for obs, row in sorted(rows_by_id.items()):
        regions = {}
        for g, spec in specs.items():
            index = focal.get((obs, spec['organ']))
            if index is None:
                continue
            box = samples[index]['box']
            if spec['attribute'] == 'hairiness' and min(box[2]-box[0], box[3]-box[1]) < 96:
                continue
            regions[g] = index
        result.append({'observation_id': obs, 'taxon': row['taxon'], 'genus': row['genus'],
                       'split': row['split'], 'regions': regions})
    return result


def profile_formula(profile, groups):
    return combine('and', [combine('or', [('eq', g, int(i)) for i in profile[g]['allowed']])
                           for g in groups if g in profile])


def prepare(data, out, epsilon):
    started = time.monotonic()
    schema = json.loads((data/'multi-vocabulary.json').read_text())
    protocol = json.loads((data/'protocol.json').read_text())
    hashes = {name: digest(data/name) for name in ('multi-vocabulary.json', 'splits.jsonl',
              'profiles.json', 'queries.json', 'images.jsonl')}
    if protocol['split_sha256'] != hashes['splits.jsonl'] or protocol['schema_sha256'] != hashes['multi-vocabulary.json']:
        raise ValueError('Changed split/schema')
    for name in ('profiles.json', 'queries.json'):
        if schema[name.replace('.json', '_sha256')] != hashes[name]:
            raise ValueError('Changed frozen source')
    extraction = json.loads((data/'extraction/run.json').read_text())
    if extraction['input_manifest_sha256'] != hashes['images.jsonl']:
        raise ValueError('Changed image manifest')
    for group in schema['groups']:
        meta = json.loads((data/'multi-priors'/group/'prototypes.json').read_text())
        if meta['vocabulary_sha256'] != digest(data/f'vocabulary-{group}.json'):
            raise ValueError('Changed prototype vocabulary')
        if meta['encoder']['revision'] != extraction['models']['encoder']['revision']:
            raise ValueError('Image/text encoder mismatch')
    rows = [r for r in map(json.loads, (data/'splits.jsonl').read_text().splitlines())
            if r['split'] in ('train', 'validation')]
    raw_profiles = json.loads((data/'profiles.json').read_text())
    queries = json.loads((data/'queries.json').read_text())
    compiled, excluded = compile_profiles(raw_profiles, queries, schema, allow_partial=True)
    catalogue = ranking_profiles(compiled, schema)
    for p in raw_profiles:
        catalogue.setdefault(p['taxon'], {})
    features, samples = load_regions(data, rows)
    initial = MultiHead(schema, data/'multi-priors')
    specs = group_specs(schema)
    obs = observations(rows, samples, specs)
    with torch.no_grad():
        teacher = concepts(initial, features, specs)
    reference = {}
    for g, spec in specs.items():
        indices = [o['regions'][g] for o in obs if o['split'] == 'train' and g in o['regions']]
        if indices:
            # Smooth a train-only pretrained reference; do not infer it from validation.
            p = teacher[g][indices].mean(0).double() + 1e-6
            reference[g] = (p / p.sum()).tolist()
        else:
            reference[g] = [1/spec['size']] * spec['size']
    training_taxa = sorted({o['taxon'] for o in obs if o['split'] == 'train'})
    validation_taxa = sorted(catalogue)
    banks, timings = {}, []
    for mode, taxa in [('train', training_taxa), ('validation', validation_taxa)]:
        signatures = sorted({tuple(sorted(o['regions'])) for o in obs if o['split'] == mode and o['regions']})
        for signature in signatures:
            start = time.monotonic()
            profiles = {t: profile_formula(catalogue[t], signature) for t in taxa}
            bank = LatentTaxonWMC({g: specs[g]['size'] for g in signature}, profiles,
                                 {g: reference[g] for g in signature}, epsilon=epsilon).float()
            banks[(mode, signature)] = bank
            timings.append({'split': mode, 'groups': signature, 'taxa': len(taxa),
                            'unique_nonconstant_roots': len(bank.wmc.roots),
                            'compile_seconds': time.monotonic()-start})
    payload = dict(schema=schema, catalogue=catalogue, features=features, samples=samples,
                   observations=obs, specs=specs, reference=reference, banks=banks,
                   teacher=teacher, initial_state=initial.state_dict(), epsilon=epsilon,
                   training_taxa=training_taxa, validation_taxa=validation_taxa,
                   preparation=dict(input_hashes=hashes, excluded_profiles=excluded,
                                    observation_counts=dict(Counter(o['split'] for o in obs)),
                                    compilation=timings, elapsed_seconds=time.monotonic()-started,
                                    source_policy='partial', test_images_loaded=0,
                                    encoder=extraction['models']['encoder'],
                                    package_versions={p: importlib.metadata.version(p)
                                                      for p in ('torch','pydeeplog','mv-sdd','klaycircuits')}))
    out.mkdir(parents=True, exist_ok=False)
    torch.save(payload, out/'prepared.pt')
    (out/'preparation.json').write_text(json.dumps(payload['preparation'], indent=2)+'\n')
    print(json.dumps(payload['preparation']), flush=True)


def batches(payload, split, device, eligible_only=False):
    grouped = defaultdict(list)
    for o in payload['observations']:
        if o['split'] != split or not o['regions']:
            continue
        if eligible_only and not (o['regions'].keys() & payload['catalogue'][o['taxon']].keys()):
            continue
        grouped[tuple(sorted(o['regions']))].append(o)
    counts = Counter(o['taxon'] for obs in grouped.values() for o in obs)
    result = []
    for signature, obs in sorted(grouped.items()):
        bank = payload['banks'][(split, signature)].to(device)
        ids = {g: torch.tensor([o['regions'][g] for o in obs], device=device) for g in signature}
        weights = torch.tensor([1/(len(counts)*counts[o['taxon']]) for o in obs], device=device)
        targets = torch.tensor([bank.taxa.index(o['taxon']) for o in obs], device=device)
        masks, availability = {}, {}
        for g in signature:
            masks[g] = torch.zeros(len(obs), payload['specs'][g]['size'], device=device)
            availability[g] = torch.tensor([g in payload['catalogue'][o['taxon']] for o in obs], device=device)
            for i, o in enumerate(obs):
                for state in payload['catalogue'][o['taxon']].get(g, {}).get('allowed', []):
                    masks[g][i, int(state)] = 1
        result.append(dict(signature=signature, observations=obs, bank=bank, indices=ids,
                           weights=weights, targets=targets, masks=masks, availability=availability))
    return result


def gather(pred, batch):
    return {g: pred[g][indices] for g, indices in batch['indices'].items()}


def fit_member(initial, features, teacher, specs, train_batches, previous, args, seed, mode):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    model = copy.deepcopy(initial)
    # Preserve pretrained semantics, with small seeded perturbations for ensemble diversity.
    with torch.no_grad():
        for head in model.heads.values():
            head.colour_given_organ.weight.add_(torch.randn_like(head.colour_given_organ.weight)*.001)
            head.colour_given_organ.bias.add_(torch.randn_like(head.colour_given_organ.bias)*.01)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0)
    history = []
    for step in range(args.epochs+1):
        optimizer.zero_grad()
        pred = concepts(model, features, specs)
        components = {k: features.sum()*0 for k in ('taxon_nll','grounding_kl','source_loss','diversity_kl','entropy')}
        for batch in train_batches:
            q = gather(pred, batch)
            w = batch['weights']
            logp = batch['bank'](q)
            nll = -logp.gather(1, batch['targets'][:, None]).squeeze(1)
            kl = sum((teacher[g][batch['indices'][g]] *
                      (teacher[g][batch['indices'][g]].clamp_min(1e-30).log()-p.clamp_min(1e-30).log())).sum(-1)
                     for g,p in q.items()) / len(q)
            source = sum(-(.3+.7*(p*batch['masks'][g]).sum(-1)).log()*batch['availability'][g]
                         for g,p in q.items())
            nsource = sum(batch['availability'].values()).clamp_min(1)
            diversity = nll * 0
            entropy = nll * 0
            if mode == 'bears' and previous:
                diversity, entropy = diversification(q, [gather(old, batch) for old in previous], args.world_samples)
            for key,value in [('taxon_nll',nll),('grounding_kl',kl),('source_loss',source/nsource),
                              ('diversity_kl',diversity),('entropy',entropy)]:
                components[key] = components[key] + (value*w).sum()
        loss = (components['taxon_nll'] + args.grounding_weight*components['grounding_kl']
                + args.source_weight*components['source_loss']
                - args.gamma1*components['diversity_kl'] - args.gamma2*components['entropy'])
        if not torch.isfinite(loss):
            raise FloatingPointError('Nonfinite objective')
        if step % 50 == 0 or step == args.epochs:
            row = dict(step=step, objective=loss.item(), **{k:v.item() for k,v in components.items()})
            history.append(row)
            print(json.dumps(dict(mode=mode, seed=seed, **row)), flush=True)
        if step == args.epochs:
            break
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
        optimizer.step()
    with torch.no_grad():
        predictions = {g:p.detach() for g,p in concepts(model, features, specs).items()}
    return model, predictions, history


def evaluate(predictions, payload, val_batches):
    by_obs = {}
    uncertainty_rows = []
    with torch.no_grad():
        for batch in val_batches:
            qs = [gather(p, batch) for p in predictions]
            # Average each member's taxon posterior, never WMC of averaged concept marginals.
            posterior = torch.stack([batch['bank'](q).exp() for q in qs]).mean(0).cpu()
            for i, obs in enumerate(batch['observations']):
                by_obs[obs['observation_id']] = (posterior[i], batch['bank'].taxa)
            for g in batch['signature']:
                mean, ent, mi = uncertainty([q[g] for q in qs])
                for i, obs in enumerate(batch['observations']):
                    uncertainty_rows.append(dict(observation_id=obs['observation_id'], group=g,
                        probabilities=mean[i].cpu().tolist(), predictive_entropy=float(ent[i]),
                        epistemic_mi=float(mi[i])))
    results = []
    for obs in payload['observations']:
        if obs['split'] != 'validation':
            continue
        taxa = payload['validation_taxa']
        p, taxa = by_obs.get(obs['observation_id'], (torch.full((len(taxa),), 1/len(taxa)), taxa))
        true = p[taxa.index(obs['taxon'])]
        better = int((p > true+1e-7).sum())
        ties = int(((p-true).abs() <= 1e-7).sum())
        ordered = p.argsort(descending=True)
        abstain = not obs['regions'] or float(p[ordered[0]]-p[ordered[1]]) <= 1e-7
        results.append(dict(observation_id=obs['observation_id'], taxon=obs['taxon'],
            top1_credit=0. if abstain or better else 1/ties,
            top5_credit=0. if abstain else max(0,min(ties,5-better))/ties,
            nll=-float(true.clamp_min(1e-30).log()), abstain=abstain,
            comparable_true_groups=len(obs['regions'].keys() & payload['catalogue'][obs['taxon']].keys()),
            top_candidates=[dict(taxon=taxa[int(i)], probability=float(p[i])) for i in ordered[:5]]))
    taxa = set(r['taxon'] for r in results)
    metrics = dict(observations=len(results), candidate_species=len(payload['validation_taxa']),
                   top1=float(np.mean([r['top1_credit'] for r in results])),
                   top5=float(np.mean([r['top5_credit'] for r in results])),
                   macro_top1=float(np.mean([np.mean([r['top1_credit'] for r in results if r['taxon']==t]) for t in taxa])),
                   nll=float(np.mean([r['nll'] for r in results])),
                   coverage=float(np.mean([not r['abstain'] for r in results])),
                   comparable_true_observations=sum(r['comparable_true_groups']>0 for r in results),
                   mean_trait_epistemic_mi=float(np.mean([r['epistemic_mi'] for r in uncertainty_rows])),
                   mean_trait_predictive_entropy=float(np.mean([r['predictive_entropy'] for r in uncertainty_rows])))
    return metrics, results, uncertainty_rows


def train(prepared, out, args):
    if not torch.cuda.is_available():
        raise RuntimeError('Training requires an Orix Slurm GPU allocation')
    started = time.monotonic()
    device = 'cuda'
    # Trusted locally generated artifact; compiled DeepLog modules need full object loading.
    payload = torch.load(prepared/'prepared.pt', weights_only=False, map_location='cpu')
    out.mkdir(parents=True, exist_ok=False)
    features = payload['features'].to(device)
    initial = MultiHead(payload['schema'], feature_dim=features.shape[-1])
    initial.load_state_dict(payload['initial_state'])
    initial = initial.to(device)
    for h in initial.heads.values():
        h.organ.requires_grad_(False)
    teacher = {g:p.to(device) for g,p in payload['teacher'].items()}
    tb = batches(payload, 'train', device, eligible_only=True)
    vb = batches(payload, 'validation', device)
    if not tb or not vb:
        raise ValueError('No eligible train/validation batches')
    reports = {'pretrained': evaluate([teacher], payload, vb)[0]}
    histories = {}
    # Each mode has identical initialization seeds and grounding/source losses.
    for mode in ('ordinary', 'bears'):
        previous = []
        histories[mode] = []
        for member in range(args.members):
            seed = 1729 + member
            model, pred, history = fit_member(initial, features, teacher, payload['specs'], tb,
                                              previous, args, seed, mode)
            previous.append(pred)
            histories[mode].append(history)
            torch.save(dict(state_dict={k:v.cpu() for k,v in model.state_dict().items()},
                            schema=payload['schema'], reference=payload['reference'],
                            catalogue=payload['catalogue'], seed=seed, mode=mode,
                            status='experimental_taxon_supervised_latent_traits'), out/f'{mode}-{member}.pt')
            metric, result, _ = evaluate([pred], payload, vb)
            (out/f'{mode}-{member}-validation.json').write_text(json.dumps(dict(metrics=metric, predictions=result), indent=2)+'\n')
        metrics, results, traits = evaluate(previous, payload, vb)
        reports[mode] = metrics
        (out/f'{mode}-validation.json').write_text(json.dumps(dict(metrics=metrics, predictions=results), indent=2)+'\n')
        (out/f'{mode}-traits.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in traits))
        print(json.dumps(dict(mode=mode, validation=metrics)), flush=True)
    torch.cuda.synchronize()
    report = dict(status='completed_development_run', validation=reports, histories=histories,
                  train_observations_with_profile=sum(len(b['observations']) for b in tb),
                  train_taxa_with_profile=len({o['taxon'] for b in tb for o in b['observations']}),
                  training_candidate_taxa=len(payload['training_taxa']),
                  hyperparameters={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
                  preparation=payload['preparation'], prepared_sha256=digest(prepared/'prepared.pt'),
                  gpu=torch.cuda.get_device_name(), peak_gpu_bytes=torch.cuda.max_memory_allocated(),
                  elapsed_seconds=time.monotonic()-started,
                  limitations=['Validation only; no new test-set claim',
                               'Pretrained BioCLIP features frozen; conditional trait heads adapted',
                               'BEARS joint KL uses Monte Carlo with score-function gradients',
                               'Ensemble disagreement is not verified trait calibration',
                               'Whole-profile contamination and fixed organ/visibility gates'])
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('histories','preparation')}), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare','train'])
    p.add_argument('--data', type=Path)
    p.add_argument('--prepared', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--epochs', type=int, default=200)
    p.add_argument('--members', type=int, default=5)
    p.add_argument('--lr', type=float, default=.001)
    p.add_argument('--epsilon', type=float, default=.3)
    p.add_argument('--grounding-weight', type=float, default=1.)
    p.add_argument('--source-weight', type=float, default=.25)
    p.add_argument('--gamma1', type=float, default=.1)
    p.add_argument('--gamma2', type=float, default=.01)
    p.add_argument('--world-samples', type=int, default=64)
    args = p.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(0)
    if args.command == 'prepare':
        prepare(args.data, args.out, args.epsilon)
    else:
        train(args.prepared, args.out, args)


if __name__ == '__main__':
    main()
