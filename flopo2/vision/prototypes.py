"""Encode taxon-free organ/colour prompts with pinned BioCLIP 2 on an Orix GPU."""
import argparse
import json
import os
from pathlib import Path
import time

from .extract import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--vocabulary', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    os.environ['HF_HUB_OFFLINE'] = '1'
    import numpy as np
    import torch
    import open_clip
    if not torch.cuda.is_available():
        raise RuntimeError('Run prototype encoding inside an Orix GPU allocation')
    torch.set_num_threads(4)
    start = time.monotonic()
    manifest = json.loads((args.models / 'manifest.json').read_text())
    encoder_dir = args.models / 'encoder'
    for name, expected in manifest['encoder']['files'].items():
        if digest(encoder_dir / name) != expected:
            raise ValueError('Changed encoder artifact')
    config = json.loads((encoder_dir / 'open_clip_config.json').read_text())
    if config['model_cfg'] != open_clip.get_model_config('ViT-L-14'):
        raise ValueError('Encoder configuration mismatch')
    model = open_clip.create_model('ViT-L-14', pretrained=str(encoder_dir / 'open_clip_model.safetensors'), device='cuda').eval()
    tokenizer = open_clip.get_tokenizer('ViT-L-14')
    vocab = json.loads(args.vocabulary.read_text())
    organs = [o['name'] for o in vocab['organs']]
    colours = [c.get('prompt', c['name']) for c in vocab['colours']]
    attribute = vocab.get('attribute_name', 'colour')
    organ_phrases = [f'a plant {o}' if o != 'other' else 'an unidentified plant part' for o in organs]
    colour_phrases = []
    for organ in organs:
        bearer = organ if organ != 'other' else 'plant part'
        for colour in colours:
            colour_phrases.append(f'a {colour} {bearer}' if colour != 'unknown' else f'a {bearer} of uncertain {attribute}')
    phrases = organ_phrases + colour_phrases
    prompts = [[f'a photograph of {phrase}.', f'a close-up photograph of {phrase}.'] for phrase in phrases]
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
        tokens = tokenizer([prompt for group in prompts for prompt in group]).cuda()
        encoded = model.encode_text(tokens, normalize=True).float().reshape(len(phrases), 2, -1).mean(1)
        encoded = torch.nn.functional.normalize(encoded, dim=-1).cpu().numpy()
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / 'prototypes.npz', organ=encoded[:len(organs)],
        colour=encoded[len(organs):].reshape(len(organs), len(colours), -1),
        logit_scale=np.array(float(model.logit_scale.detach().exp().cpu())))
    report = {'status': 'pretrained_text_prior_not_gold', 'prompts': prompts,
        'encoder': manifest['encoder'], 'vocabulary_sha256': digest(args.vocabulary),
        'prototypes_sha256': digest(args.out / 'prototypes.npz'),
        'script_sha256': digest(__file__), 'slurm_job_id': os.environ.get('SLURM_JOB_ID'),
        'gpu': torch.cuda.get_device_name(), 'seconds': time.monotonic() - start,
        'note': 'No species names, flora states per taxon, or image labels enter these prompts. Trait grounding and unknown-state calibration are unverified.'}
    (args.out / 'prototypes.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'slurm_job_id', 'seconds')}))


if __name__ == '__main__':
    main()
