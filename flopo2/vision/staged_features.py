"""Frozen whole-organ plus four overlapping spatial views; no trait references read."""
import argparse
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
from PIL import Image,ImageOps
from .extract import digest
from .modern import load_encoder,load_images,normalize
from .full_train import region_features

TILES=[[0.,0.,1.,1.],[0.,0.,.65,.65],[.35,0.,1.,.65],[0.,.35,.65,1.],[.35,.35,1.,1.]]


def tiles(image):
    w,h=image.size
    return [image.crop((int(x0*w),int(y0*h),max(int(x0*w)+1,int(x1*w)),max(int(y0*h)+1,int(y1*h)))) for x0,y0,x1,y1 in TILES]


def extract(a):
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Orix Slurm GPU required')
    torch.set_num_threads(4);started=time.monotonic();a.out.mkdir(parents=True,exist_ok=True)
    if (a.out/'extraction.json').exists():raise ValueError('Completed extraction already exists')
    base=json.loads((a.features/'extraction.json').read_text())
    for f,k in [('regions.jsonl','regions_sha256'),('inventory.json','inventory_sha256'),('features.npz','features_sha256')]:
        if digest(a.features/f)!=base[k]:raise ValueError('Changed source features')
    if a.encoder=='fgclip2':
        model,processor,tokenizer,spec=load_encoder(a.models,'fgclip2-large');model.vision_model.use_head=False
        def encode(images):return region_features(model,processor,images)
    else:
        import open_clip
        spec=json.loads((a.extra_models/'manifest.json').read_text())['bioclip2'];path=a.extra_models/'bioclip2'
        for f,h in spec['files'].items():
            if digest(path/f)!=h:raise ValueError('Changed BioCLIP weights/config')
        cfg=json.loads((path/'open_clip_config.json').read_text())
        model,_,processor=open_clip.create_model_and_transforms('ViT-L-14',pretrained=str(path/'open_clip_model.safetensors'),device='cuda',
             image_mean=cfg['preprocess_cfg']['mean'],image_std=cfg['preprocess_cfg']['std'],image_interpolation='bicubic',image_resize_mode='shortest')
        model.eval()
        def encode(images):
            with torch.autocast('cuda',dtype=torch.bfloat16):return normalize(model.encode_image(torch.stack([processor(im) for im in images]).cuda()))
    rows=[json.loads(s) for s in (a.features/'regions.jsonl').read_text().splitlines()]
    protocol={'encoder':a.encoder,'model_spec':spec,'source_features_sha256':digest(a.features/'extraction.json'),'tiles':TILES,'source_sha256':digest(__file__)}
    pp=a.out/'protocol.json'
    if pp.exists() and json.loads(pp.read_text())!=protocol:raise ValueError('Incompatible resume')
    pp.write_text(json.dumps(protocol,indent=2)+'\n')
    def run_set(name,records,get_image):
        chunks=[]
        for start in range(0,len(records),32):
            path=a.out/f'{name}-{start:06d}.npy'
            if path.exists():z=np.load(path)
            else:
                images=[im for r in records[start:start+32] for im in tiles(get_image(r))]
                z=torch.cat([encode(images[i:i+16]) for i in range(0,len(images),16)]).cpu().numpy().reshape(-1,5,768 if a.encoder=='bioclip2' else 1024)
                if not np.isfinite(z).all():raise ValueError('Nonfinite features')
                # atomic replace permits resumption after an interrupted job
                tmp=path.with_suffix('.tmp.npy');np.save(tmp,z);tmp.replace(path)
            chunks.append(z)
            if start%320==0:print(a.encoder,name,start,'/',len(records),flush=True)
        return np.concatenate(chunks)
    def crop(r):
        p=a.data/r['image_path']
        if digest(p)!=r['sha256']:raise ValueError('Changed image')
        with Image.open(p) as im:return ImageOps.exif_transpose(im).convert('RGB').crop(r['box'])
    with torch.inference_mode():
        outputs={'regions':run_set('regions',rows,crop)}
        datasets,field,external=load_images(a.small,a.external)
        for name,images in datasets.items():outputs[name]=run_set(name,list(range(len(images))),lambda i:images[i])
    np.savez_compressed(a.out/'features.npz',**outputs)
    (a.out/'field-rows.json').write_text(json.dumps(field)+'\n');(a.out/'external-rows.json').write_text(json.dumps(external)+'\n')
    for f in ['regions.jsonl','inventory.json']:(a.out/f).write_bytes((a.features/f).read_bytes())
    manifest={**protocol,'arrays':{k:list(v.shape) for k,v in outputs.items()},'seconds':time.monotonic()-started,'slurm_job_id':os.environ['SLURM_JOB_ID'],
       'sha256':{f:digest(a.out/f) for f in ['features.npz','regions.jsonl','inventory.json','field-rows.json','external-rows.json']}}
    (a.out/'extraction.json').write_text(json.dumps(manifest,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['features','data','models','extra-models','small','external','out']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--encoder',choices=['fgclip2','bioclip2'],required=True);extract(p.parse_args())

if __name__=='__main__':main()
