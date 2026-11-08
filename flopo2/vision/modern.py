"""Pinned modern encoders and a trait-only development screen on existing images.

This screen reuses the already inspected AI audit, so it is development evidence,
not a new independent test. No taxon prediction or model selection occurs here.
"""
import argparse
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from .extract import digest


DESCRIPTIONS = {
    'ovate': 'an egg-shaped leaf, broader below the middle',
    'elliptic': 'an elliptical leaf, widest near the middle',
    'oblong': 'an oblong leaf with nearly parallel sides',
    'lanceolate': 'a lance-shaped leaf, tapering to a pointed tip',
    'obovate': 'a reverse egg-shaped leaf, broader above the middle',
    'oblanceolate': 'a narrow reverse lance-shaped leaf, broader toward its tip',
    'linear': 'a long narrow leaf with nearly parallel sides',
    'orbicular': 'a round, nearly circular leaf',
    'spatulate': 'a spoon-shaped leaf with a broad rounded tip and narrow base',
    'heart shaped': 'a heart-shaped leaf with two basal lobes and a basal notch',
    'triangular': 'a triangular leaf',
    'glabrous': 'a smooth hairless leaf surface',
    'hairy': 'a leaf surface covered with visible hairs',
    'pubescent': 'a leaf surface covered with short soft hairs',
    'tomentose': 'a leaf surface covered with dense woolly hairs',
}


def trait_prompts(schema):
    result = {}
    for group in ('outline', 'hairiness'):
        result[group] = []
        for item in schema['groups'][group]['colours']:
            name = item['name']
            if name == 'unknown':
                texts = ['a leaf whose ' + group + ' cannot be determined in this photograph']
            else:
                texts = ['a photo of a ' + name + ' leaf', 'a close-up photo of ' + DESCRIPTIONS[name]]
            result[group].append(texts)
    return result


def normalize(x):
    return F.normalize(x.float(), dim=-1)


def load_encoder(models, name):
    from transformers import AutoImageProcessor, AutoTokenizer, AutoModel, AutoModelForCausalLM
    spec = json.loads((models / 'manifest.json').read_text())[name]
    path = models / name
    for filename, expected in spec['files'].items():
        if digest(path / filename) != expected:
            raise ValueError('Changed model artifact: ' + str(path / filename))
    cls = AutoModelForCausalLM if spec['kind'] == 'fgclip2' else AutoModel
    # FG-CLIP's two custom modules are downloaded at the pinned revision,
    # inspected before execution, and hash-verified above. No runtime network.
    model = cls.from_pretrained(path, local_files_only=True,
        trust_remote_code=spec['kind'] == 'fgclip2').cuda().eval()
    return model, AutoImageProcessor.from_pretrained(path, local_files_only=True), \
        AutoTokenizer.from_pretrained(path, local_files_only=True), spec


def text_features(model, tokenizer, prompts, kind, view):
    result = {}
    for group, alternatives in prompts.items():
        features = []
        for texts in alternatives:
            tokens = tokenizer(texts, padding='max_length', truncation=True,
                max_length=64, return_tensors='pt').to('cuda')
            kwargs = {'walk_type': 'box' if view == 'region' else 'short'} if kind == 'fgclip2' else {}
            v = model.get_text_features(**tokens, **kwargs)
            features.append(normalize(normalize(v).mean(0)))
        result[group] = torch.stack(features).cpu().numpy()
    return result


def encode_images(model, processor, images, kind, batch_size=8, views=('global', 'region')):
    global_features, region_features = [], []
    for start in range(0, len(images), batch_size):
        batch = images[start:start + batch_size]
        kwargs = {'max_num_patches': 1024} if kind == 'fgclip2' else {}
        inputs = processor(images=batch, return_tensors='pt', **kwargs).to('cuda')
        with torch.autocast('cuda', dtype=torch.bfloat16):
            if 'global' in views:
                global_features.append(normalize(model.get_image_features(**inputs)).cpu().numpy())
            if kind == 'fgclip2' and 'region' in views:
                regions = model.get_image_region_features(**inputs,
                    image_sizes=[(im.height, im.width) for im in batch],
                    region_infos=[[[0, 0, im.width, im.height]] for im in batch])
                region_features.append(normalize(torch.cat(regions)).cpu().numpy())
    result = {'global': np.concatenate(global_features)} if global_features else {}
    if region_features:
        result['region'] = np.concatenate(region_features)
    return result


def load_images(data, external):
    from PIL import Image, ImageOps
    rows = [json.loads(line) for line in (data / 'splits.jsonl').read_text().splitlines()]
    images = []
    for r in rows:
        path = data / r['image_path']
        if digest(path) != r['sha256']:
            raise ValueError('Changed image: ' + str(path))
        with Image.open(path) as im:
            images.append(ImageOps.exif_transpose(im).convert('RGB').crop(r['box']))
    ext_rows = json.loads((external / 'manifest.json').read_text())
    originals, masked = [], []
    for r in ext_rows:
        if digest(external / r['image']) != r['sha256'] or digest(external / r['mask']) != r['mask_sha256']:
            raise ValueError('Changed external image or mask')
        with Image.open(external / r['image']) as im:
            rgb = im.convert('RGB')
        with Image.open(external / r['mask']) as im:
            mask = np.asarray(im) > 0
        arr = np.asarray(rgb).copy()
        arr[~mask] = 255
        originals.append(rgb); masked.append(Image.fromarray(arr))
    return {'field': images, 'external_original': originals, 'external_masked': masked}, rows, ext_rows


def extract(args):
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('Run encoder extraction in a Slurm GPU allocation')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    torch.set_num_threads(4)
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    schema = json.loads((args.data / 'multi-vocabulary.json').read_text())
    prompts = trait_prompts(schema)
    datasets, rows, ext_rows = load_images(args.data, args.external)
    (args.out / 'rows.json').write_text(json.dumps(rows))
    (args.out / 'external-rows.json').write_text(json.dumps(ext_rows))
    (args.out / 'prompts.json').write_text(json.dumps(prompts, indent=2) + '\n')
    (args.out / 'schema.json').write_text(json.dumps(schema, indent=2) + '\n')
    model, processor, tokenizer, spec = load_encoder(args.models, args.model)
    outputs = {}
    with torch.inference_mode():
        for view in ('global', 'region') if spec['kind'] == 'fgclip2' else ('global',):
            for g, f in text_features(model, tokenizer, prompts, spec['kind'], view).items():
                outputs[f'text_{view}_{g}'] = f
        for name, images in datasets.items():
            for view, f in encode_images(model, processor, images, spec['kind']).items():
                outputs[f'{name}_{view}'] = f
            print(args.model, name, len(images), 'encoded', flush=True)
    np.savez_compressed(args.out / 'features.npz', **outputs)
    report = {'model': args.model, 'model_spec': spec,
        'dataset_hashes': {'splits': digest(args.data / 'splits.jsonl'),
            'schema': digest(args.data / 'multi-vocabulary.json'),
            'external_manifest': digest(args.external / 'manifest.json')},
        'features_sha256': digest(args.out / 'features.npz'),
        'rows_sha256': digest(args.out / 'rows.json'), 'external_rows_sha256': digest(args.out / 'external-rows.json'),
        'prompts_sha256': digest(args.out / 'prompts.json'), 'source_sha256': digest(__file__),
        'slurm_job_id': os.environ['SLURM_JOB_ID'], 'gpu': torch.cuda.get_device_name(),
        'torch': torch.__version__, 'seconds': time.monotonic() - started,
        'views': ['global', 'region'] if spec['kind'] == 'fgclip2' else ['global'],
        'note': 'Existing frozen crop selection; native FG-CLIP region head applied to the full high-resolution crop. No newly trained organ detection or trait labels.'}
    (args.out / 'extraction.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('model', 'slurm_job_id', 'seconds')}), flush=True)


def average_precision(target, score):
    pairs = [(int(t), float(s)) for t, s in zip(target, score) if t is not None]
    pos = sum(t for t, _ in pairs)
    if not pos or pos == len(pairs):
        return None
    # Group ties, so input order cannot change AP.
    tp = fp = 0; value = 0.
    for level in sorted({s for _, s in pairs}, reverse=True):
        batch = [t for t, s in pairs if s == level]
        added = sum(batch); tp += added; fp += len(batch) - added
        value += added / pos * tp / (tp + fp)
    return value


def evaluate(args):
    from .trait_eval import score, partial_target
    torch.set_num_threads(2)
    report = json.loads((args.out / 'extraction.json').read_text())
    for name, key in [('features.npz', 'features_sha256'), ('rows.json', 'rows_sha256'),
                      ('external-rows.json', 'external_rows_sha256'), ('prompts.json', 'prompts_sha256')]:
        if digest(args.out / name) != report[key]:
            raise ValueError('Changed extraction artifact: ' + name)
    freeze = json.loads((args.audit / 'annotation-freeze.json').read_text())
    for filename, expected in freeze['sha256'].items():
        if digest(args.audit / filename) != expected:
            raise ValueError('Changed annotation: ' + filename)
    rows = json.loads((args.out / 'rows.json').read_text())
    ext = json.loads((args.out / 'external-rows.json').read_text())
    schema = json.loads((args.out / 'schema.json').read_text())
    arrays = np.load(args.out / 'features.npz')
    phen = json.loads(args.phenotypes.read_text())['supported']
    joins = json.loads((args.audit / 'private-join.json').read_text())
    ejoins = json.loads((args.audit / 'external-join.json').read_text())
    fa = json.loads((args.audit / 'field-annotations.json').read_text())
    ea = json.loads((args.audit / 'external-annotations.json').read_text())
    field_idx = {r['observation_id']: i for i, r in enumerate(rows)}
    ext_idx = {r['id']: i for i, r in enumerate(ext)}
    fi = [field_idx[r['observation_id']] for r in joins]
    ei = [ext_idx[r['specimen_id']] for r in ejoins]
    for a, j, i in zip(fa, joins, fi):
        if a['audit_id'] != j['audit_id'] or rows[i]['sha256'] != j['image_sha256'] or rows[i]['box'] != j['box']:
            raise ValueError('Field audit join mismatch')
    if [a['audit_id'] for a in ea] != [j['audit_id'] for j in ejoins]:
        raise ValueError('External audit join mismatch')
    results, predictions = {}, []
    for view in report['views']:
        results[view] = {}
        for dataset, annotations, indices in [('field', fa, fi), ('external_original', ea, ei), ('external_masked', ea, ei)]:
            x = arrays[f'{dataset}_{view}'][indices]
            # This categorical projection reproduces the previous diagnostic only.
            # It is not a claim that all PATO shape predicates are mutually exclusive.
            probs = {f'leaf.{g}': torch.softmax(torch.tensor(10 * (x @ arrays[f'text_{view}_{g}'].T)), -1).numpy()
                     for g in ('outline', 'hairiness')}
            metrics, detail = score(annotations, probs, schema['groups'], phen)
            names = [v['name'] for v in schema['groups']['outline']['colours']]
            raw = x @ arrays[f'text_{view}_outline'].T
            per_class = {}
            for k, name in enumerate(names):
                truth = [1 if a['outline_allowed'] == [name] else 0 if len(a['outline_allowed']) == 1 else None for a in annotations]
                per_class[name] = {'average_precision': average_precision(truth, raw[:, k]),
                                  'positive': sum(t == 1 for t in truth), 'negative': sum(t == 0 for t in truth)}
            metrics['literal_outline_ranking'] = per_class
            metrics['macro_average_precision'] = float(np.mean([v['average_precision'] for v in per_class.values()
                if v['average_precision'] is not None])) if any(v['average_precision'] is not None for v in per_class.values()) else None
            results[view][dataset] = metrics
            predictions.extend(dict(dataset=dataset, view=view, **r) for r in detail)
    summary = {'model': report['model'], 'extraction': report, 'results': results,
        'no_species_metrics': True, 'no_fitting': True, 'selection': 'None; fixed prompts and all declared encoder views reported.',
        'reference_quality': 'Previously inspected single-AI visual audit; development evidence, not independent expert test.',
        'annotation_freeze': freeze, 'phenotype_queries_sha256': digest(args.phenotypes)}
    (args.out / 'screen.json').write_text(json.dumps(summary, indent=2) + '\n')
    (args.out / 'screen-predictions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in predictions))
    print(json.dumps({v: {d: {'outline': f"{m['outline']['set_compatible_correct']}/{m['outline']['assessable']}",
         'macro_ap': m['macro_average_precision']} for d, m in ds.items()} for v, ds in results.items()}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['extract', 'evaluate'])
    p.add_argument('--data', type=Path); p.add_argument('--external', type=Path)
    p.add_argument('--models', type=Path); p.add_argument('--model')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--audit', type=Path); p.add_argument('--phenotypes', type=Path)
    args = p.parse_args()
    if args.command == 'extract': extract(args)
    else: evaluate(args)


if __name__ == '__main__': main()
