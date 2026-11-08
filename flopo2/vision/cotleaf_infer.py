"""Image-only CotLeaf-X inference for the fixed, previously trained trait heads."""
import argparse
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
from PIL import Image
from .extract import digest
from .benchmark_infer import load_bioclip,read_rows
from .full_train import region_features
from .modern import load_encoder,normalize
from .staged_features import tiles
from .staged_train import SpatialTraits


def run(a):
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm GPU required')
    torch.set_num_threads(4);started=time.monotonic();a.out.mkdir(parents=True,exist_ok=True)
    rows=read_rows(a.data/'images.jsonl')
    if any(k in r for r in rows for k in ['expert_score','target']):raise ValueError('References must not enter image inference')
    identity=dict(images_sha256=digest(a.data/'images.jsonl'),source_sha256=digest(__file__),encoder=a.encoder)
    ip=a.out/'identity.json'
    if ip.exists() and json.loads(ip.read_text())!=identity:raise ValueError('Incompatible inference resume')
    ip.write_text(json.dumps(identity,indent=2)+'\n')
    featurefile=a.out/'features.npz'
    if featurefile.exists():
        if digest(featurefile)!=json.loads((a.out/'features.json').read_text())['sha256']:raise ValueError('Changed feature cache')
        features=np.load(featurefile)['features']
    else:
        if a.encoder=='fgclip2':
            model,processor,_,spec=load_encoder(a.models,'fgclip2-large');model.vision_model.use_head=False
            def encode(images):return region_features(model,processor,images)
        else:
            model,processor,spec=load_bioclip(a.extra_models)
            def encode(images):
                with torch.autocast('cuda',dtype=torch.bfloat16):return normalize(model.encode_image(torch.stack([processor(im) for im in images]).cuda()))
        parts=[]
        with torch.inference_mode():
            for start in range(0,len(rows),8):
                chunk=a.out/f'chunk-{start:04d}.npy'
                if chunk.exists():z=np.load(chunk)
                else:
                    images=[]
                    for r in rows[start:start+8]:
                        p=a.data/r['image_file']
                        if digest(p)!=r['sha256']:raise ValueError('Changed image')
                        with Image.open(p) as im:images.extend(tiles(im.convert('RGB')))
                    z=torch.cat([encode(images[i:i+10]) for i in range(0,len(images),10)]).cpu().numpy().reshape(-1,5,1024 if a.encoder=='fgclip2' else 768)
                    temp=chunk.with_suffix('.tmp.npy');np.save(temp,z);temp.replace(chunk)
                parts.append(z);print('encoded',a.encoder,start+len(z),flush=True)
        features=np.concatenate(parts);np.savez_compressed(featurefile,features=features)
        (a.out/'features.json').write_text(json.dumps(dict(sha256=digest(featurefile),model_spec=spec),indent=2)+'\n')
        del model;torch.cuda.empty_cache()
    files=sorted((a.runs/a.encoder).glob('primary-*/complete.json'))
    if len(files)!=19:raise ValueError('Incomplete model grid')
    outputs={};checkpoints={}
    with torch.inference_mode():
        for f in files:
            meta=json.loads(f.read_text());p=f.parent/'model.pt'
            if digest(p)!=meta['checkpoint_sha256']:raise ValueError('Changed checkpoint')
            cp=torch.load(p,map_location='cpu',weights_only=False);state=cp['head']
            head=SpatialTraits(state['reference'].shape[1],cp['traits'],state['reference'],state['centers'],independent=cp['independent']).cuda().eval();head.load_state_dict(state)
            chunks=[]
            for start in range(0,len(rows),128):chunks.append(head(torch.tensor(features[start:start+128],device='cuda'))[0].sigmoid().cpu().numpy())
            q=np.concatenate(chunks)
            if q.shape!=(len(rows),36) or not np.isfinite(q).all():raise ValueError('Invalid model prediction')
            outputs[f.parent.name]=q;checkpoints[f.parent.name]=digest(p)
    np.savez_compressed(a.out/'predictions.npz',**outputs)
    report=dict(identity=identity,images=len(rows),checkpoints=checkpoints,seconds=time.monotonic()-started,
                slurm_job_id=os.environ['SLURM_JOB_ID'],sha256={n:digest(a.out/n) for n in ['identity.json','predictions.npz','features.json']})
    (a.out/'complete.json').write_text(json.dumps(report,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['data','runs','models','extra-models','out']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--encoder',choices=['fgclip2','bioclip2'],required=True);run(p.parse_args())

if __name__=='__main__':main()
