"""Orix GPU pilot: frozen organ proposals and BioCLIP 2 region features, never gold labels."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def overlap(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return area / max(1, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reviewed', type=Path, help='Re-extract corrected crops from a human review export')
    args = parser.parse_args()
    # Network-free allocation: all weights must already be present and hash-verified.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    import numpy as np
    import torch
    import open_clip
    from PIL import Image, ImageOps
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    if not torch.cuda.is_available():
        raise RuntimeError('GPU extraction requires a Slurm GPU allocation')
    torch.set_num_threads(4)
    started = time.monotonic()
    manifest = json.loads((args.models / 'manifest.json').read_text())
    for name, spec in manifest.items():
        for filename, sha in spec['files'].items():
            if digest(args.models / name / filename) != sha:
                raise ValueError(f'Changed model artifact: {name}/{filename}')
    config = json.loads((args.models / 'encoder/open_clip_config.json').read_text())
    if config['model_cfg'] != open_clip.get_model_config('ViT-L-14'):
        raise ValueError('Pinned BioCLIP configuration differs from ViT-L-14')
    model, _, transform = open_clip.create_model_and_transforms('ViT-L-14',
        pretrained=str(args.models / 'encoder/open_clip_model.safetensors'), device='cuda')
    model.eval()
    detector_path = args.models / 'detector'
    processor = AutoProcessor.from_pretrained(detector_path, local_files_only=True) if not args.reviewed else None
    detector = AutoModelForZeroShotObjectDetection.from_pretrained(detector_path, local_files_only=True).cuda().eval() if not args.reviewed else None
    rows = [json.loads(line) for line in (args.data / 'images.jsonl').read_text().splitlines()]
    unique = {row['photo_id']: row for row in rows}
    reviewed = {}
    if args.reviewed:
        reviewed = {r['photo_id']: r for r in json.loads(args.reviewed.read_text())['images']}
        if not reviewed or any(r.get('review_status') != 'reviewed' or not r.get('reviewer', '').strip() for r in reviewed.values()):
            raise ValueError('All supplied annotations must be signed human reviews')
        if not reviewed.keys() <= unique.keys():
            raise ValueError('Unknown reviewed photos')
        unique = {key: row for key, row in unique.items() if key in reviewed}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'features').mkdir(exist_ok=True)
    regions, counts = [], []
    with torch.inference_mode():
        for index, row in enumerate(unique.values()):
            path = args.data / row['image_path']
            if digest(path) != row['sha256']:
                raise ValueError(f'Image hash mismatch: {row["photo_id"]}')
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert('RGB')
            if reviewed:
                review = reviewed[row['photo_id']]
                if review['sha256'] != row['sha256'] or len(review['regions']) > 6:
                    raise ValueError('Invalid reviewed image or region count')
                proposals = review['regions']
                for p in proposals:
                    x1, y1, x2, y2 = p['box']
                    if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
                        raise ValueError('Invalid reviewed bounding box')
            else:
                inputs = processor(images=image, text='leaf. petal. flower. fruit.', return_tensors='pt').to('cuda')
                outputs = detector(**inputs)
                result = processor.post_process_grounded_object_detection(outputs, inputs.input_ids,
                    threshold=0.30, text_threshold=0.25, target_sizes=[(image.height, image.width)])[0]
                proposals = select_proposals(result, image)
            crops = [image] + [image.crop(p['box']) for p in proposals]
            tensor = torch.stack([transform(crop) for crop in crops]).cuda()
            with torch.autocast('cuda', dtype=torch.bfloat16):
                features = model.encode_image(tensor, normalize=True).float().cpu().numpy()
            np.savez_compressed(args.out / 'features' / f'{row["photo_id"]}.npz',
                global_feature=features[0], region_features=features[1:])
            record = {'photo_id': row['photo_id'], 'sha256': row['sha256'], 'regions': proposals,
                      'status': 'reviewed_crops' if reviewed else 'machine_proposals_unreviewed', 'width': image.width, 'height': image.height}
            regions.append(record); counts.append(len(proposals))
            with (args.out / 'regions.jsonl').open('a' if index else 'w') as handle:
                handle.write(json.dumps(record) + '\n')
            if (index + 1) % 20 == 0:
                print(f'Extracted {index+1}/{len(unique)} images; {sum(counts)} proposals', flush=True)
    report = {'status': 'complete_reviewed_crops' if reviewed else 'complete_unreviewed', 'images': len(unique), 'regions': sum(counts),
        'without_proposals': counts.count(0), 'model_manifest_sha256': digest(args.models / 'manifest.json'),
        'input_manifest_sha256': digest(args.data / 'images.jsonl'), 'models': manifest,
        'review_sha256': digest(args.reviewed) if args.reviewed else None,
        'extractor_sha256': digest(__file__),
        'environment_lock_sha256': digest(Path(__file__).with_name('pixi.lock')) if Path(__file__).with_name('pixi.lock').exists() else None,
        'slurm_job_id': os.environ.get('SLURM_JOB_ID'), 'gpu': torch.cuda.get_device_name(),
        'torch': torch.__version__, 'seconds': time.monotonic() - started,
        'precision': 'detector float32; encoder bfloat16 autocast; normalized float32 features',
        'threshold': 0.30, 'text_threshold': 0.25, 'max_regions': 6,
        'note': 'Frozen features; machine proposals are not gold. No accuracy estimates.'}
    (args.out / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('images', 'regions', 'without_proposals', 'seconds')}), flush=True)


def select_proposals(result, image):
    proposals = []
    for box, score, label in sorted(zip(result['boxes'].cpu().tolist(),
            result['scores'].cpu().tolist(), result['text_labels']), key=lambda p: -p[1]):
        # Ambiguous text phrases are withheld; flower is never silently called petal.
        if label not in ('leaf', 'petal', 'flower', 'fruit'):
            continue
        box = [max(0, min(image.width, box[0])), max(0, min(image.height, box[1])),
               max(0, min(image.width, box[2])), max(0, min(image.height, box[3]))]
        if box[2] - box[0] < 12 or box[3] - box[1] < 12:
            continue
        if any(p['organ'] == label and overlap(box, p['box']) > 0.7 for p in proposals):
            continue
        proposals.append({'organ': label, 'box': box, 'score': score})
        if len(proposals) == 6:
            break
    return proposals

if __name__ == '__main__':
    main()
