"""Independent specimen-linked geometry control; numeric targets are not FLOPO labels."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from .extract import digest

CLASSES=(1,3,5,7,8,9,10,11)
TARGETS={'aspect_ratio':3,'elongation':4,'solidity':5,'lobedness':9}


def prepare(source,out):
    table=np.loadtxt(source/'leaf.csv',delimiter=',')
    out.mkdir(parents=True,exist_ok=False);(out/'images').mkdir();(out/'masks').mkdir()
    rows=[]
    for cls in CLASSES:
        values=table[table[:,0]==cls]
        ordered=sorted(values,key=lambda v:hashlib.sha256(f'leaf-control-v1:{cls}:{int(v[1])}'.encode()).hexdigest())
        n=len(ordered);nt=max(2,n//5);nv=max(2,n//5)
        for j,v in enumerate(ordered):
            specimen=int(v[1]);key=f'C{cls:02}_EX{specimen:02}'
            photos=list(source.glob(f'RGB/{cls}.*/*{key}.JPG'))
            masks=list(source.glob(f'BW/{cls}.*/*{key}_B.TIFF'))
            if len(photos)!=1 or len(masks)!=1:raise ValueError(f'Ambiguous specimen join {key}')
            image=out/'images'/f'{key}.jpg';mask=out/'masks'/f'{key}.tif'
            shutil.copy2(photos[0],image);shutil.copy2(masks[0],mask)
            rows.append(dict(id=key,species=photos[0].parent.name.split('. ',1)[1],class_id=cls,
                specimen=specimen,image=f'images/{key}.jpg',mask=f'masks/{key}.tif',
                sha256=digest(image),mask_sha256=digest(mask),
                split='test' if j<nt else 'validation' if j<nt+nv else 'train',
                targets={k:float(v[i]) for k,i in TARGETS.items()}))
    (out/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
    report=dict(source='https://archive.ics.uci.edu/dataset/288/leaf',doi='10.24432/C53C78',
        license='CC BY 4.0',specimens=len(rows),classes=CLASSES,counts=dict(Counter(r['split'] for r in rows)),
        target_names=list(TARGETS),source_table_sha256=digest(source/'leaf.csv'),
        manifest_sha256=digest(out/'manifest.json'),
        role='Independent quantitative image-geometry control; not categorical FLOPO ground truth.',
        controls=['species-mean lookup (label-assisted reference)','measured geometry -> species',
                  'image features -> species','supervised numeric trait probe',
                  'PlantTraitNet-inspired image-only weak Gaussian trait regression'],
        caveats=['small controlled-background dataset','unknown foundation-model pretraining overlap',
                 'specimen split, not independently sampled sites or populations'])
    (out/'protocol.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


def encode(data,models):
    import torch,open_clip
    from PIL import Image,ImageOps
    if not torch.cuda.is_available():raise RuntimeError('Use an Orix GPU allocation')
    rows=json.loads((data/'manifest.json').read_text());manifest=json.loads((models/'manifest.json').read_text())
    for filename,sha in manifest['encoder']['files'].items():
        if digest(models/'encoder'/filename)!=sha:raise ValueError('Changed encoder')
    model,_,transform=open_clip.create_model_and_transforms('ViT-L-14',
        pretrained=str(models/'encoder/open_clip_model.safetensors'),device='cuda')
    model.eval();features={};torch.set_num_threads(4)
    for kind in ('original','masked'):
        tensors=[]
        for row in rows:
            if digest(data/row['image'])!=row['sha256'] or digest(data/row['mask'])!=row['mask_sha256']:
                raise ValueError('Changed specimen image/mask')
            # Mask coordinates refer to the supplied raw RGB image, before EXIF reorientation.
            im=Image.open(data/row['image']).convert('RGB')
            if kind=='masked':
                mask=Image.open(data/row['mask']).convert('L')
                if mask.size!=im.size:raise ValueError('Misaligned specimen mask')
                im=Image.composite(im,Image.new('RGB',im.size,(127,127,127)),mask)
                box=mask.getbbox()
                if not box:raise ValueError('Empty leaf mask')
                x0,y0,x1,y1=box;pad=max(8,int(.05*max(x1-x0,y1-y0)))
                im=im.crop((max(0,x0-pad),max(0,y0-pad),min(im.width,x1+pad),min(im.height,y1+pad)))
            tensors.append(transform(im))
        encoded=[]
        with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
            for i in range(0,len(tensors),24):
                encoded.append(model.encode_image(torch.stack(tensors[i:i+24]).cuda(),normalize=True).float().cpu().numpy())
        features[kind]=np.concatenate(encoded)
    np.savez_compressed(data/'features.npz',**features)
    (data/'extraction.json').write_text(json.dumps(dict(encoder=manifest['encoder'],
        manifest_sha256=digest(data/'manifest.json'),features_sha256=digest(data/'features.npz'),
        gpu=torch.cuda.get_device_name(),scope='original RGB and supplied-mask foreground crop'),indent=2)+'\n')
    print(json.dumps({'images':len(rows),'views':2,'features':list(features)}),flush=True)


def ridge_fit(x,y,alpha):
    mean=x.mean(0);scale=x.std(0).clip(.01)
    z=(x-mean)/scale
    ym=y.mean(0)
    weight=z.T@np.linalg.solve(z@z.T+alpha*np.eye(len(z)),y-ym)
    return lambda q:((q-mean)/scale)@weight+ym


def evaluate(data):
    rows=json.loads((data/'manifest.json').read_text());features=np.load(data/'features.npz')
    protocol=json.loads((data/'protocol.json').read_text())
    if protocol['manifest_sha256']!=digest(data/'manifest.json'):raise ValueError('Changed manifest')
    indices={s:np.array([i for i,r in enumerate(rows) if r['split']==s]) for s in ('train','validation','test')}
    tr,va,te=(indices[s] for s in ('train','validation','test'))
    classes=sorted({r['class_id'] for r in rows});labels=np.array([classes.index(r['class_id']) for r in rows])
    y=np.array([[r['targets'][g] for g in TARGETS] for r in rows]);ys=y[tr].std(0).clip(1e-8)
    onehot=np.eye(len(classes))[labels]
    def trait_metrics(pred):
        return {g:{'mae':float(np.abs(pred[:,i]-y[te,i]).mean()),
                   'r2':float(1-((pred[:,i]-y[te,i])**2).sum()/((y[te,i]-y[te,i].mean())**2).sum())}
                for i,g in enumerate(TARGETS)}
    species_means=np.stack([y[tr][labels[tr]==c].mean(0) for c in range(len(classes))])
    report={'species_mean_reference':trait_metrics(species_means[labels[te]]),'models':{}}
    def tuned(x,target):
        best=None
        for alpha in (.01,.1,1.,10.,100.):
            f=ridge_fit(x[tr],target[tr],alpha)
            error=float(((f(x[va])-target[va])**2).mean())
            if best is None or error<best[0]:best=(error,alpha,f)
        return best[1],best[2]
    alpha,oracle=tuned(y/ys,onehot)
    report['measured_traits_species_accuracy']=float((oracle(y[te]/ys).argmax(1)==labels[te]).mean())
    for view in features.files:
        x=features[view].astype('float64')
        alpha,predict=tuned(x,y/ys)
        pred=predict(x[te])*ys
        sa,sp=tuned(x,onehot)
        report['models'][view]=dict(supervised_numeric_probe=trait_metrics(pred),ridge_alpha=alpha,
            image_species_accuracy=float((sp(x[te]).argmax(1)==labels[te]).mean()),species_alpha=sa)
    report['protocol']=protocol
    report['note']='These ridge controls are not PlantTraitNet; its adapted uncertainty baseline is specified separately.'
    (data/'ridge-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


def weak_gaussian(data):
    """Adapted image-only uncertainty baseline; not a reproduction of PlantTraitNet.

    Species-level moments come only from training specimens (a TRY-like control).
    Individual training measurements never serve as per-image regression targets.
    Validation measurements select a checkpoint; test measurements are scored once.
    """
    import copy
    import torch
    from torch import nn
    if not torch.cuda.is_available():raise RuntimeError('Use an Orix GPU allocation')
    rows=json.loads((data/'manifest.json').read_text());features=np.load(data/'features.npz')
    ids={s:torch.tensor([i for i,r in enumerate(rows) if r['split']==s],device='cuda')
         for s in ('train','validation','test')}
    tr,va,te=(ids[s] for s in ('train','validation','test'))
    y=torch.tensor([[r['targets'][g] for g in TARGETS] for r in rows],dtype=torch.float32,device='cuda')
    centre=y[tr].mean(0);scale=y[tr].std(0).clamp_min(1e-6);z=(y-centre)/scale
    labels=torch.tensor([r['class_id'] for r in rows],device='cuda')
    weak_mean=torch.empty_like(z[tr]);weak_var=torch.empty_like(z[tr])
    for c in labels[tr].unique():
        mask=labels[tr]==c
        weak_mean[mask]=z[tr][mask].mean(0)
        weak_var[mask]=z[tr][mask].var(0,unbiased=False).clamp_min(.01)
    results={}
    for view in features.files:
        torch.manual_seed(20261025)
        x=torch.tensor(features[view],device='cuda');xm=x[tr].mean(0);xs=x[tr].std(0).clamp_min(.01)
        x=(x-xm)/xs
        model=nn.Sequential(nn.Linear(x.shape[1],128),nn.ReLU(),nn.Dropout(.1),
                            nn.Linear(128,128),nn.ReLU(),nn.Linear(128,8)).cuda()
        opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
        best=None
        for step in range(501):
            model.train();opt.zero_grad();mu,lv=model(x[tr]).chunk(2,-1);lv=lv.clamp(-5,5)
            # Exact expected Gaussian NLL over the training-species distribution.
            loss=.5*(lv+(weak_var+(weak_mean-mu).square())/lv.exp()).mean()
            if step%10==0:
                model.eval()
                with torch.no_grad():validation=float((model(x[va])[:,:4]-z[va]).abs().mean())
                if best is None or validation<best[0]:best=(validation,step,copy.deepcopy(model.state_dict()))
            if step==500:break
            loss.backward();opt.step()
        model.load_state_dict(best[2]);model.eval()
        with torch.no_grad():
            mu,lv=model(x[te]).chunk(2,-1);pred=mu*scale+centre
            errors=(pred-y[te]).abs().mean(0)
            r2=1-(pred-y[te]).square().sum(0)/(y[te]-y[te].mean(0)).square().sum(0)
        results[view]={'selected_step':best[1],'validation_normalized_mae':best[0],
            'traits':{g:{'mae':float(errors[i]),'r2':float(r2[i])} for i,g in enumerate(TARGETS)}}
        torch.save(dict(state_dict={k:v.cpu() for k,v in model.state_dict().items()},
                        feature_mean=xm.cpu(),feature_scale=xs.cpu(),target_mean=centre.cpu(),
                        target_scale=scale.cpu(),target_names=list(TARGETS)),data/f'weak-gaussian-{view}.pt')
    report={'name':'PlantTraitNet-inspired image-only weak Gaussian regression',
        'source':'https://github.com/GeoSense-Freiburg/PlantTraitNet',
        'differences':['different numeric targets and smaller MLP','no depth/geolocation inputs',
                       'no iterative uncertainty filtering','training-specimen moments instead of TRY',
                       'exact expected Gaussian NLL instead of sampled targets'],
        'results':results,'training':'species-level aggregate targets only',
        'test':'untouched individual specimen measurements','seed':20261025}
    (data/'weak-gaussian-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','encode','evaluate','weak-gaussian'])
    p.add_argument('--source',type=Path);p.add_argument('--data',type=Path,required=True);p.add_argument('--models',type=Path)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.source,a.data)
    elif a.command=='encode':encode(a.data,a.models)
    elif a.command=='evaluate':evaluate(a.data)
    else:weak_gaussian(a.data)

if __name__=='__main__':main()
