"""Image-only full-experiment predictions and independent trait review scoring."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path

import numpy as np
import torch

from .extract import digest
from .modern import load_encoder, average_precision, load_images
from .full_train import region_features
from .trait_heads import make_head
from .trait_eval import binary_metrics
from .modern_weak import CONTEXT_QUALITIES


def predict(args):
    from PIL import Image,ImageOps,ImageDraw
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Use Orix Slurm GPU allocation')
    torch.set_num_threads(4)
    report=json.loads((args.run/'training.json').read_text())
    if digest(args.run/'model.pt')!=report['checkpoint_sha256']:raise ValueError('Changed checkpoint')
    if digest(args.features/'extraction.json')!=report['extraction_sha256']:raise ValueError('Changed feature source')
    ext=json.loads((args.features/'extraction.json').read_text())
    for f,k in [('features.npz','features_sha256'),('regions.jsonl','regions_sha256')]:
        if digest(args.features/f)!=ext[k]:raise ValueError('Changed cached input')
    cp=torch.load(args.run/'model.pt',map_location='cpu',weights_only=False)
    arrays=np.load(args.features/'features.npz');text=torch.tensor(arrays['text'],device='cuda',dtype=torch.float32)
    head=make_head(text,'centered');head.load_state_dict(cp['head']);head.eval()
    model,processor,_,spec=load_encoder(args.models,cp['model'])
    if spec!=cp['model_spec']:raise ValueError('Different backbone')
    model.vision_model.use_head=False
    expected=set(dict(model.named_parameters()))
    if not set(cp['adapted'])<=expected:raise ValueError('Unknown adapted parameter')
    model.load_state_dict(cp['adapted'],strict=False);model.eval()
    rows=[json.loads(s) for s in (args.features/'regions.jsonl').read_text().splitlines()]
    output=[];controls=[]
    with torch.inference_mode():
        for start in range(0,len(rows),8):
            part=rows[start:start+8]
            if cp['adapted']:
                images=[]
                for r in part:
                    p=args.data/r['image_path']
                    if digest(p)!=r['sha256']:raise ValueError('Changed image')
                    with Image.open(p) as im:images.append(ImageOps.exif_transpose(im).convert('RGB').crop(r['box']))
                z=region_features(model,processor,images)
            else:z=torch.tensor(arrays['regions'][start:start+len(part)],device='cuda')
            q=head(z).sigmoid().cpu().numpy()
            if not np.isfinite(q).all():raise ValueError('Non-finite trait predictions')
            for r,prob in zip(part,q):
                output.append({'photo_id':r['photo_id'],'observation_id':r['observation_id'],'organ':r['organ'],'split':r['split'],
                    'probabilities':{str(t['index']):float(prob[t['index']]) for t in cp['traits'] if t['organ']==r['organ'] and t['quality_label'] not in CONTEXT_QUALITIES}})
            if start%800==0:print('Predicted regions',start,'/',len(rows),flush=True)
        # Fixed hash-based reserved subset, no labels consulted. Erase the detected organ.
        import hashlib
        selected=sorted([r for r in rows if r['split']!='train'],key=lambda r:hashlib.sha256(str(r['photo_id']).encode()).hexdigest())[:200]
        for start in range(0,len(selected),8):
            part=selected[start:start+8];images=[]
            for r in part:
                with Image.open(args.data/r['image_path']) as im:im=ImageOps.exif_transpose(im).convert('RGB')
                ImageDraw.Draw(im).rectangle(r['box'],fill=(127,127,127));images.append(im)
            q=head(region_features(model,processor,images)).sigmoid().cpu().numpy()
            for r,prob in zip(part,q):controls.append({'photo_id':r['photo_id'],'organ':r['organ'],'control':'detected_organ_erased_whole_image',
                'probabilities':{str(t['index']):float(prob[t['index']]) for t in cp['traits'] if t['organ']==r['organ'] and t['quality_label'] not in CONTEXT_QUALITIES}})
    for name,values in [('predictions.jsonl',output),('background-control.jsonl',controls)]:
        (args.run/name).write_text(''.join(json.dumps(r)+'\n' for r in values))
    summary={'regions':len(output),'control_regions':len(controls),'checkpoint_sha256':report['checkpoint_sha256'],
        'predictions_sha256':digest(args.run/'predictions.jsonl'),'source_sha256':digest(__file__),
        'control_limitation':'Erases detector box only; other organs or foreground plants may remain. Not a verified background mask.',
        'reference_status':'No taxon profile is used as image-level evaluation truth.'}
    (args.run/'prediction-manifest.json').write_text(json.dumps(summary,indent=2)+'\n')


def score_arrays(truth, probabilities, splits):
    """Thresholds use validation only; missing visual predictions are explicit zero evidence."""
    output={}
    for k in range(truth.shape[1]):
        valid=np.isfinite(truth[:,k]);validation=valid&(splits=='validation');test=valid&(splits=='test')
        thresholds=[.5];vt=truth[validation,k];vp=probabilities[validation,k]
        if (vt==1).sum()>=5 and (vt==0).sum()>=5:
            thresholds=np.unique(np.r_[.5,np.quantile(vp,np.linspace(0,1,51))])
        def f1(th):
            tp=((vp>=th)&(vt==1)).sum();fp=((vp>=th)&(vt==0)).sum();fn=((vp<th)&(vt==1)).sum()
            return 2*tp/max(1,2*tp+fp+fn)
        threshold=float(max(thresholds,key=lambda th:(f1(th),-abs(th-.5))))
        y=truth[test,k].astype(int).tolist();q=probabilities[test,k].tolist()
        output[str(k)]={'threshold':threshold,'validation_assessed':int(validation.sum()),
            'test':{**binary_metrics(y,q,threshold),'average_precision':average_precision(y,q)}}
    return output


def review(args):
    packet=json.loads((args.packet/'packet.json').read_text());ref=json.loads(args.review.read_text())
    if ref['packet_id']!=packet['packet_id']:raise ValueError('Wrong annotation packet')
    if not ref.get('reviewer'):raise ValueError('Reviewer attribution required')
    protocol=json.loads((args.packet/'protocol.json').read_text())
    inv=json.loads((args.run/'training-inventory.json').read_text())
    expected=[{k:t[k] for k in ['index','label','bearer','quality']} for t in inv['traits']]
    if packet['traits']!=expected:raise ValueError('Review and model trait vocabularies differ')
    if digest(args.packet/'packet.json')!=protocol['packet_sha256'] or digest(args.packet/'private-join.json')!=protocol['private_join_sha256']:raise ValueError('Changed packet')
    joins={r['audit_id']:r for r in json.loads((args.packet/'private-join.json').read_text())}
    images={r['audit_id']:r for r in packet['images']};pred=defaultdict(dict)
    manifest=json.loads((args.run/'prediction-manifest.json').read_text())
    if digest(args.run/'predictions.jsonl')!=manifest['predictions_sha256']:raise ValueError('Changed predictions')
    for line in (args.run/'predictions.jsonl').read_text().splitlines():
        r=json.loads(line)
        for k,v in r['probabilities'].items():pred[r['photo_id']][k]=max(v,pred[r['photo_id']].get(k,0.))
    n=len(packet['traits']);truth=[];prob=[];splits=[];taxa=[];covered=[];seen=set()
    for r in ref['annotations']:
        aid=r['audit_id']
        if aid in seen or aid not in images:raise ValueError('Repeated/unknown annotation')
        seen.add(aid)
        if r['image_sha256']!=images[aid]['image_sha256']:raise ValueError('Changed reviewed image')
        if not r.get('reviewed'):continue
        j=joins[aid];values=r.get('traits',{})
        if any(v not in ['present','absent','unknown'] for v in values.values()):raise ValueError('Invalid trait state')
        truth.append([{'present':1,'absent':0}.get(values.get(str(k)),np.nan) for k in range(n)])
        prob.append([pred[j['photo_id']].get(str(k),0.) for k in range(n)])
        covered.append([str(k) in pred[j['photo_id']] for k in range(n)])
        splits.append(j['split']);taxa.append(j['taxon'])
    if not truth:raise ValueError('No reviewed images')
    truth=np.array(truth);prob=np.array(prob);splits=np.array(splits);taxa=np.array(taxa);covered=np.array(covered)
    result=score_arrays(truth,prob,splits)
    for k,r in result.items():
        mask=(splits=='test')&np.isfinite(truth[:,int(k)])
        r['test']['prediction_coverage']=float(covered[mask,int(k)].mean()) if mask.any() else None
    aps=[r['test']['average_precision'] for r in result.values() if r['test']['average_precision'] is not None]
    rng=np.random.default_rng(20261026);groups=np.unique(taxa[splits=='test']);boot=[]
    if len(groups)>=2:
        for _ in range(500):
            ids=np.concatenate([np.flatnonzero((taxa==t)&(splits=='test')) for t in rng.choice(groups,len(groups),replace=True)])
            vals=[]
            for k in range(n):
                y=[None if not np.isfinite(v) else int(v) for v in truth[ids,k]];ap=average_precision(y,prob[ids,k])
                if ap is not None:vals.append(ap)
            if vals:boot.append(float(np.mean(vals)))
    report={'reviewer':ref['reviewer'],'review_type':ref.get('review_type','unspecified'),'reference_sha256':digest(args.review),
        'packet_id':packet['packet_id'],'reviewed_images':len(truth),'traits':result,'macro_AP':float(np.mean(aps)) if aps else None,
        'macro_AP_taxon_bootstrap_95':np.quantile(boot,[.025,.975]).tolist() if boot else None,
        'bootstrap_limit':'Taxon bootstrap; supported trait set can vary in resamples. Small numbers of taxa give unstable intervals.',
        'missing_prediction_policy':'Zero visual evidence for missing organ predictions; coverage is reported. Unknown reference labels are excluded, never negative.',
        'no_species_metrics':True}
    (args.run/'review-evaluation.json').write_text(json.dumps(report,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['predict','review'])
    for name in ['data','features','models','run','packet','review']:p.add_argument('--'+name,type=Path,required=name=='run')
    a=p.parse_args();{'predict':predict,'review':review}[a.command](a)


if __name__=='__main__':main()
