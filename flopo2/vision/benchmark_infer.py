"""Image-only pxGPT benchmark inference using the pinned staged models.

Run under a Slurm GPU allocation. This module never reads reference labels or
published pxGPT model outputs. Resumable feature chunks precede all head scoring.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from PIL import Image, ImageOps

from .extract import digest, select_proposals
from .modern import load_encoder, normalize
from .full_train import region_features
from .staged_features import tiles
from .staged_train import SpatialTraits


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def load_bioclip(path):
    import open_clip
    spec = json.loads((path / 'manifest.json').read_text())['bioclip2']
    folder = path / 'bioclip2'
    for name, expected in spec['files'].items():
        if digest(folder / name) != expected:
            raise ValueError('Changed BioCLIP weights')
    cfg = json.loads((folder / 'open_clip_config.json').read_text())
    model, _, processor = open_clip.create_model_and_transforms('ViT-L-14',
        pretrained=str(folder / 'open_clip_model.safetensors'), device='cuda',
        image_mean=cfg['preprocess_cfg']['mean'], image_std=cfg['preprocess_cfg']['std'],
        image_interpolation='bicubic', image_resize_mode='shortest')
    model.eval()
    return model, processor, spec


def run(a):
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('A Slurm GPU allocation is required')
    if not 0 <= a.shard_index < a.shards:
        raise ValueError('Invalid shard')
    torch.set_num_threads(4); started = time.monotonic()
    a.out.mkdir(parents=True, exist_ok=True)
    if (a.out / 'complete.json').exists():
        raise ValueError('Inference already complete')
    protocol = json.loads((a.benchmark / 'protocol.json').read_text())
    for name in ['records.jsonl', 'images.jsonl', 'inventory.json']:
        if digest(a.benchmark / name) != protocol['sha256'][name]:
            raise ValueError('Changed frozen input: ' + name)
    rows = read_rows(a.benchmark / 'images.jsonl')[a.shard_index::a.shards]
    if a.limit:
        rows = rows[:a.limit]
    inv = json.loads((a.benchmark / 'inventory.json').read_text())
    models = {}
    for encoder in protocol['encoders']:
        folders = sorted((a.runs / encoder).glob('primary-*/complete.json'))
        if len(folders) != 19:
            raise ValueError('Expected baseline and six three-seed arms per encoder')
        models[encoder] = []
        for path in folders:
            meta = json.loads(path.read_text())
            if meta['mode'] not in protocol['modes'] or meta['traits'] != inv['traits']:
                raise ValueError('Unexpected model or vocabulary')
            if digest(path.parent / 'model.pt') != meta['checkpoint_sha256']:
                raise ValueError('Checkpoint hash mismatch')
            models[encoder].append({'name': path.parent.name,
                'checkpoint_sha256': meta['checkpoint_sha256'], 'completion_sha256': digest(path)})
    detector_spec = json.loads((a.detector / 'manifest.json').read_text())['detector']
    for name, expected in detector_spec['files'].items():
        if digest(a.detector / 'detector' / name) != expected:
            raise ValueError('Changed organ detector')
    identity = {'protocol_sha256': digest(a.benchmark / 'protocol.json'),
        'source_sha256': digest(__file__), 'shards': a.shards, 'shard_index': a.shard_index,
        'detector': detector_spec, 'models': models, 'preflight_limit': a.limit,
        'encoder_manifests_sha256': {str(p): digest(p) for p in
                                    [a.models / 'manifest.json', a.extra_models / 'manifest.json']},
        'dependencies': {n: digest(Path(__file__).with_name(n)) for n in
                         ['staged_features.py', 'staged_train.py', 'full_train.py', 'modern.py', 'extract.py']}}
    frozen = a.out / 'inference.json'
    if frozen.exists() and json.loads(frozen.read_text()) != identity:
        raise ValueError('Incompatible inference resume')
    frozen.write_text(json.dumps(identity, indent=2) + '\n')
    (a.out / 'images.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))

    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    dp = AutoProcessor.from_pretrained(a.detector / 'detector', local_files_only=True)
    detector = AutoModelForZeroShotObjectDetection.from_pretrained(
        a.detector / 'detector', local_files_only=True).cuda().eval()
    detection_dir = a.out / 'detections'; detection_dir.mkdir(exist_ok=True)
    detected = []
    with torch.inference_mode():
        for i, row in enumerate(rows):
            out = detection_dir / f'{i:06d}.json'
            image_path = a.images / row['image_file']
            with image_path.open('rb') as handle:
                if hashlib.file_digest(handle, 'sha512').hexdigest() != row['sha512']:
                    raise ValueError('Changed source photograph')
            if out.exists():
                rec = json.loads(out.read_text())
                if rec['sha512'] != row['sha512']:
                    raise ValueError('Wrong cached detection')
            else:
                with Image.open(image_path) as source:
                    im = ImageOps.exif_transpose(source).convert('RGB')
                inputs = dp(images=im, text='leaf. petal. flower. fruit.', return_tensors='pt').to('cuda')
                result = dp.post_process_grounded_object_detection(detector(**inputs), inputs.input_ids,
                    threshold=.4, text_threshold=.25, target_sizes=[(im.height, im.width)])[0]
                selected = [p for p in select_proposals(result, im) if p['organ'] == 'leaf'
                            and min(p['box'][2]-p['box'][0], p['box'][3]-p['box'][1]) >= 96]
                rec = {'sha512': row['sha512'], 'box': selected[0]['box'] if selected else None,
                       'score': selected[0]['score'] if selected else None}
                temp = out.with_suffix('.tmp'); temp.write_text(json.dumps(rec)); temp.replace(out)
            detected.append(rec)
            if (i+1) % 100 == 0:
                print('Detected', i+1, '/', len(rows), flush=True)
    del detector, dp; torch.cuda.empty_cache()
    masks = np.array([r['box'] is not None for r in detected])
    np.save(a.out / 'detected.npy', masks)
    (a.out / 'detections.json').write_text(json.dumps(detected) + '\n')

    for encoder in protocol['encoders']:
        folder = a.out / encoder; folder.mkdir(exist_ok=True)
        feature_file = folder / 'features.npz'
        if not feature_file.exists() or not (folder / 'features.json').exists():
            if encoder == 'fgclip2':
                model, proc, _, spec = load_encoder(a.models, 'fgclip2-large')
                model.vision_model.use_head = False
                def encode(ims):
                    return region_features(model, proc, ims)
                dim = 1024
            else:
                model, proc, spec = load_bioclip(a.extra_models)
                def encode(ims):
                    with torch.autocast('cuda', dtype=torch.bfloat16):
                        return normalize(model.encode_image(torch.stack([proc(im) for im in ims]).cuda()))
                dim = 768
            chunks = []
            with torch.inference_mode():
                for start in range(0, len(rows), 16):
                    chunk = folder / f'chunk-{start:06d}.npz'
                    if not chunk.exists():
                        ims, positions = [], []
                        n = len(rows[start:start+16])
                        z = np.zeros((n, 2, 5, dim), np.float32)
                        for j, row in enumerate(rows[start:start+16]):
                            with Image.open(a.images / row['image_file']) as source:
                                im = ImageOps.exif_transpose(source).convert('RGB')
                            for view in [0, 1]:
                                if view == 0 and not masks[start+j]:
                                    continue
                                image = im.crop(detected[start+j]['box']) if view == 0 else im
                                ims.extend(tiles(image)); positions.extend((j, view, k) for k in range(5))
                        values = torch.cat([encode(ims[i:i+16]) for i in range(0, len(ims), 16)]).cpu().numpy()
                        if not np.isfinite(values).all():
                            raise ValueError('Nonfinite features')
                        for pos, value in zip(positions, values):
                            z[pos] = value
                        temp = chunk.with_suffix('.tmp.npz'); np.savez_compressed(temp, features=z); temp.replace(chunk)
                    chunks.append(np.load(chunk)['features'])
                    if start % 160 == 0:
                        print(encoder, 'encoded', start, '/', len(rows), flush=True)
            z = np.concatenate(chunks)
            temp = feature_file.with_suffix('.tmp.npz')
            np.savez_compressed(temp, detected_leaf=z[:, 0], whole_image=z[:, 1]); temp.replace(feature_file)
            (folder / 'features.json').write_text(json.dumps({'sha256': digest(feature_file), 'model_spec': spec}) + '\n')
            del model, proc; torch.cuda.empty_cache()
        if digest(feature_file) != json.loads((folder / 'features.json').read_text())['sha256']:
            raise ValueError('Changed extracted features')
        features = np.load(feature_file)
        with torch.inference_mode():
            for meta in models[encoder]:
                output = folder / (meta['name'] + '.npz')
                if output.exists():
                    continue
                cp = torch.load(a.runs / encoder / meta['name'] / 'model.pt', map_location='cpu', weights_only=False)
                state = cp['head']
                head = SpatialTraits(state['reference'].shape[1], cp['traits'], state['reference'],
                                     state['centers'], independent=cp['independent']).cuda().eval()
                head.load_state_dict(state)
                predictions = {}
                for view in protocol['views']:
                    values = []
                    for start in range(0, len(rows), 128):
                        x = torch.tensor(features[view][start:start+128], device='cuda')
                        values.append(head(x)[0].sigmoid().cpu().numpy())
                    predictions[view] = np.concatenate(values)
                    if not np.isfinite(predictions[view]).all():
                        raise ValueError('Nonfinite predictions')
                temp = output.with_suffix('.tmp.npz'); np.savez_compressed(temp, **predictions); temp.replace(output)
                print('Predicted', encoder, meta['name'], flush=True)
    paths = ['images.jsonl', 'detected.npy', 'detections.json', 'inference.json']
    paths += [str(p.relative_to(a.out)) for encoder in protocol['encoders']
              for p in (a.out / encoder).glob('primary-*.npz')]
    report = {'images': len(rows), 'detected_leaf': int(masks.sum()), 'shard_index': a.shard_index,
              'shards': a.shards, 'seconds': time.monotonic()-started,
              'slurm_job_id': os.environ['SLURM_JOB_ID'],
              'sha256': {name: digest(a.out / name) for name in paths}}
    (a.out / 'complete.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ['benchmark', 'images', 'runs', 'models', 'extra-models', 'detector', 'out']:
        p.add_argument('--'+n, type=Path, required=True)
    p.add_argument('--shards', type=int, default=1)
    p.add_argument('--shard-index', type=int, default=0)
    p.add_argument('--limit', type=int, default=0, help='Preflight only; incomplete outputs cannot be scored')
    run(p.parse_args())


if __name__ == '__main__':
    main()
