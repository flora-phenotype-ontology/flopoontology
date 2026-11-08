"""Re-encode frozen organ crops, preserving the previous experiment's cohort."""
import argparse
import json
import os
from pathlib import Path
import shutil
import time

import numpy as np
import torch

from .extract import digest
from .modern import load_encoder, encode_images, normalize


def extract(args):
    from PIL import Image, ImageOps
    previous = json.loads((args.previous / 'extraction.json').read_text())
    for filename, key in [('features.npz', 'features_sha256'), ('regions.jsonl', 'regions_sha256'), ('inventory.json', 'inventory_sha256')]:
        if digest(args.previous / filename) != previous[key]:
            raise ValueError('Changed previous artifact: ' + filename)
    if digest(args.data / 'splits.jsonl') != previous['splits_sha256']:
        raise ValueError('Changed cohort split')
    args.out.mkdir(parents=True, exist_ok=False)
    for filename in ('regions.jsonl', 'inventory.json', 'prompts.json'):
        shutil.copy2(args.previous / filename, args.out / filename)
    report = dict(previous, parent_extraction_sha256=digest(args.previous / 'extraction.json'),
                  source_sha256=digest(__file__), model=args.model)
    if args.model == previous['model']:
        shutil.copy2(args.previous / 'features.npz', args.out / 'features.npz')
        report['feature_reuse'] = True
    else:
        if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):
            raise RuntimeError('Use a Slurm GPU allocation')
        torch.set_num_threads(4); started = time.monotonic()
        model, processor, tokenizer, spec = load_encoder(args.models, args.model)
        rows = [json.loads(s) for s in (args.out / 'regions.jsonl').read_text().splitlines()]
        prompts = json.loads((args.out / 'prompts.json').read_text())
        chunks = []
        with torch.inference_mode():
            tok = tokenizer(prompts, padding='max_length', max_length=64, truncation=True, return_tensors='pt').to('cuda')
            text = normalize(model.get_text_features(**tok, walk_type='box')).cpu().numpy()
            for start in range(0, len(rows), 24):
                images = []
                for row in rows[start:start+24]:
                    path = args.data / row['image_path']
                    if digest(path) != row['sha256']: raise ValueError('Changed source image')
                    with Image.open(path) as im:
                        images.append(ImageOps.exif_transpose(im).convert('RGB').crop(row['box']))
                chunks.append(encode_images(model, processor, images, spec['kind'], views=('region',))['region'])
        np.savez_compressed(args.out / 'features.npz', regions=np.concatenate(chunks), text=text)
        report.update(model_spec=spec, feature_reuse=False, seconds=time.monotonic()-started,
                      slurm_job_id=os.environ['SLURM_JOB_ID'], gpu=torch.cuda.get_device_name())
    report['features_sha256'] = digest(args.out / 'features.npz')
    report['prompts_sha256'] = digest(args.out / 'prompts.json')
    (args.out / 'extraction.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'model': args.model, 'regions': report['regions'], 'feature_reuse': report['feature_reuse']}), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('previous', 'data', 'models', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--model', required=True)
    extract(p.parse_args())


if __name__ == '__main__': main()
