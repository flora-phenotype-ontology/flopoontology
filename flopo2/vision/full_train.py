"""Partial FG-CLIP 2 fine-tuning using flora assertions, without image trait labels.

Training never reads trait audit labels. Fixed-step comparisons precede independent
benchmark validation. The projected arm uses approximate marginal implications,
not exact joint WMC or full OWL reasoning.
"""
import argparse
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .extract import digest
from .modern import load_encoder, normalize
from .modern_weak import source_bags, negative_pairs, ontology_edges, bernoulli_kl
from .trait_heads import make_head, organ_centers


def training_subset(rows, observations=200):
    by_taxon=defaultdict(set)
    for r in rows:
        if r['split']=='train': by_taxon[r['taxon']].add(r['observation_id'])
    selected={t:set(sorted(obs,key=lambda o:hashlib.sha256(str(o).encode()).hexdigest())[:observations]) for t,obs in by_taxon.items()}
    return [i for i,r in enumerate(rows) if r['split']=='train' and r['observation_id'] in selected[r['taxon']]]


def project_implications(q, edges, iterations=40):
    """Alternating pairwise KL(r||q) projections; approximate for overlapping edges."""
    r=q.detach().clamp(1e-5,1-1e-5).clone()
    for _ in range(iterations):
        for child,parent in edges:
            violated=r[:,child]>r[:,parent]
            middle=torch.sigmoid((torch.logit(r[:,child])+torch.logit(r[:,parent]))/2)
            r[:,child]=torch.where(violated,middle,r[:,child])
            r[:,parent]=torch.where(violated,middle,r[:,parent])
    return r


def enable_last_blocks(model, count=2):
    model.requires_grad_(False)
    layers=model.vision_model.encoder.layers
    if not 0<count<=len(layers): raise ValueError('Invalid number of vision blocks')
    for layer in layers[-count:]: layer.requires_grad_(True)
    model.vision_model.post_layernorm.requires_grad_(True)
    return {name:p for name,p in model.named_parameters() if p.requires_grad}


def region_features(model,processor,images):
    inputs=processor(images=images,return_tensors='pt',max_num_patches=1024).to('cuda')
    with torch.autocast('cuda',dtype=torch.bfloat16):
        features=model.get_image_region_features(**inputs,
            image_sizes=[(im.height,im.width) for im in images],
            region_infos=[[[0,0,im.width,im.height]] for im in images])
    return normalize(torch.cat(features))


def merge(args):
    args.out.mkdir(parents=True,exist_ok=False)
    chunks=[]; rows=[]; reports=[]; text=None
    for i in range(args.shards):
        p=args.features/f'shard-{i}'; e=json.loads((p/'extraction.json').read_text())
        if e['shard_index']!=i or e['shard_count']!=args.shards: raise ValueError('Missing/repeated shard')
        for f,k in [('features.npz','features_sha256'),('regions.jsonl','regions_sha256'),('inventory.json','inventory_sha256')]:
            if digest(p/f)!=e[k]: raise ValueError('Changed shard')
        if reports and any(e[k]!=reports[0][k] for k in ['model_spec','inventory_sha256','splits_sha256']): raise ValueError('Incompatible shards')
        z=np.load(p/'features.npz')
        if text is not None and not np.array_equal(text,z['text']): raise ValueError('Different text embeddings')
        text=z['text']; chunks.append(z['regions']); rows.extend(json.loads(s) for s in (p/'regions.jsonl').read_text().splitlines()); reports.append(e)
    keys=[(r['photo_id'],r['organ']) for r in rows]
    if len(set(keys))!=len(keys): raise ValueError('Overlapping regions')
    np.savez_compressed(args.out/'features.npz',regions=np.concatenate(chunks),text=text)
    (args.out/'regions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    for f in ['inventory.json','prompts.json']: (args.out/f).write_bytes((args.features/'shard-0'/f).read_bytes())
    e=dict(reports[0]);e.update(regions=len(rows),images=sum(r['images'] for r in reports),shards=reports,
        features_sha256=digest(args.out/'features.npz'),regions_sha256=digest(args.out/'regions.jsonl'),source_sha256=digest(__file__))
    (args.out/'extraction.json').write_text(json.dumps(e,indent=2)+'\n')
    inv=json.loads((args.out/'inventory.json').read_text());eligible=source_bags(rows,inv)
    coverage=[]
    for t in inv['traits']:
        matching=[(bag,ks,taxon) for bag,ks,taxon in eligible if t['index'] in ks]
        coverage.append({'trait':t['label'],'index':t['index'],
            'training_source_taxa':len({taxon for _,_,taxon in matching}),
            'unambiguous_source_taxa':len({taxon for _,ks,taxon in matching if len(ks)==1}),
            'eligible_training_regions':len({i for bag,_,_ in matching for i in bag}),
            'image_level_trait_labels':0})
    (args.out/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    print('Merged',len(rows),'regions',flush=True)


def fit(args):
    from PIL import Image,ImageOps
    if args.observations<1 or args.steps<0 or args.warmup<0:raise ValueError('Invalid training budget')
    if args.mode=='pretrained' and (args.steps!=0 or args.warmup!=0):raise ValueError('Pretrained baseline must perform zero updates')
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('Use Orix Slurm GPU allocation')
    torch.set_num_threads(4);torch.manual_seed(args.seed);rng=np.random.default_rng(args.seed);started=time.monotonic()
    ext=json.loads((args.features/'extraction.json').read_text())
    for f,k in [('features.npz','features_sha256'),('regions.jsonl','regions_sha256'),('inventory.json','inventory_sha256')]:
        if digest(args.features/f)!=ext[k]: raise ValueError('Changed feature artifact')
    inv=json.loads((args.features/'inventory.json').read_text());queries=json.loads((args.data/'queries.json').read_text())
    rows=[json.loads(s) for s in (args.features/'regions.jsonl').read_text().splitlines()]
    indices=training_subset(rows,args.observations);rows=[rows[i] for i in indices]
    features=np.load(args.features/'features.npz');x=torch.tensor(features['regions'][indices],device='cuda',dtype=torch.float32)
    text=torch.tensor(features['text'],device='cuda',dtype=torch.float32)
    if args.mode=='shuffled':
        # Permute training profiles within bearer pools. Held-out profiles remain unused.
        mapping={}; shuffler=np.random.default_rng(20261026)
        for organ in {r['organ'] for r in rows}:
            taxa=sorted({r['taxon'] for r in rows if r['organ']==organ}); mapping[organ]=dict(zip(taxa,shuffler.permutation(taxa)))
        inv={**inv,'events':[{**e,'taxon':mapping.get(e['organ'],{}).get(e['taxon'],e['taxon'])} for e in inv['events']]}
    events=source_bags(rows,inv)
    if not events: raise ValueError('No usable weak assertions')
    by_taxon=defaultdict(list)
    for i,e in enumerate(events): by_taxon[e[2]].append(i)
    taxa=sorted(by_taxon); edges=ontology_edges(inv['traits'],queries['ancestors']); pairs=negative_pairs(inv)
    possible=defaultdict(set);single=defaultdict(set)
    for e in inv['events']:
        possible[e['taxon']].update(e['any_of'])
        if len(e['any_of'])==1:single[e['taxon']].update(e['any_of'])
    centers=organ_centers(x,rows,inv['traits']);head=make_head(text,'centered',centers)
    teacher=(10*x@text.T-3).sigmoid().detach()
    model=processor=None;adapted={}
    if args.mode not in ('frozen','pretrained'):
        model,processor,_,spec=load_encoder(args.models,ext['model'])
        if spec!=ext['model_spec']: raise ValueError('Different frozen backbone')
        adapted=enable_last_blocks(model,2)
        # Disable unused global pooling; native dense region path is retained.
        model.vision_model.use_head=False
    groups=[{'params':head.parameters(),'lr':3e-4}]
    if adapted: groups.append({'params':list(adapted.values()),'lr':1e-6})
    opt=torch.optim.AdamW(groups,weight_decay=.01)
    @lru_cache(maxsize=256)
    def crop(index):
        r=rows[index];p=args.data/r['image_path']
        if digest(p)!=r['sha256']:raise ValueError('Changed image')
        with Image.open(p) as im:return ImageOps.exif_transpose(im).convert('RGB').crop(r['box'])
    args.out.mkdir(parents=True,exist_ok=True)
    if (args.out/'training.json').exists():raise ValueError('Completed run already exists')
    history=[];start=0;gradient_verified=False
    resume=args.out/'resume.pt'
    if resume.exists():
        cp=torch.load(resume,map_location='cpu',weights_only=False)
        if cp['config']!=vars_config(args) or cp['feature_hash']!=digest(args.features/'extraction.json'):raise ValueError('Incompatible resume')
        head.load_state_dict(cp['head']);opt.load_state_dict(cp['optimizer'])
        if model:model.load_state_dict(cp['adapted'],strict=False)
        rng.bit_generator.state=cp['rng'];start=cp['step'];history=cp['history'];gradient_verified=cp['gradient_verified']
    for step in range(start,args.steps):
        chosen_events=[events[int(rng.choice(by_taxon[str(t)]))] for t in rng.choice(taxa,size=2)]
        chosen=np.concatenate([rng.choice(bag,size=4,replace=len(bag)<4) for bag,_,_ in chosen_events]).tolist()
        opt.zero_grad(set_to_none=True)
        adapting=model is not None and step>=args.warmup
        z=region_features(model,processor,[crop(i) for i in chosen]) if adapting else x[chosen]
        q=head(z).sigmoid();weak=[]
        for b,(_,allowed,_) in enumerate(chosen_events):
            event=-torch.expm1(torch.log1p(-q[b*4:(b+1)*4,allowed].clamp(1e-6,1-1e-6)).sum(-1))
            weak.append(-(.05+.95*event).log().mean() if args.mode=='direct' else -(.05+.95*event.max()).log())
        weak=torch.stack(weak).mean();anchor=bernoulli_kl(teacher[chosen],q).mean()
        feature_anchor=(1-(z*x[chosen]).sum(-1)).mean()
        neg=[]
        for j,i in enumerate(chosen):
            r=rows[i]
            for a,b in pairs:
                if inv['traits'][a]['organ']!=r['organ']:continue
                if a in single[r['taxon']] and b not in possible[r['taxon']]:neg.append(-(.05+.95*(1-q[j,b])).log())
                if b in single[r['taxon']] and a not in possible[r['taxon']]:neg.append(-(.05+.95*(1-q[j,a])).log())
        negative=torch.stack(neg).mean() if neg else q.sum()*0
        penalties=[]
        for organ in {rows[i]['organ'] for i in chosen}:
            ids=[j for j,i in enumerate(chosen) if rows[i]['organ']==organ]
            typed=[(a,b) for a,b in edges if inv['traits'][a]['organ']==organ]
            if args.mode=='hierarchy':
                penalties.extend(F.relu(q[ids,a]-q[ids,b]).square().mean() for a,b in typed)
            elif args.mode=='projected' and typed:
                projected=project_implications(q[ids],typed)
                involved=sorted({k for edge in typed for k in edge})
                penalties.append(bernoulli_kl(projected[:,involved],q[ids][:,involved]).mean())
        logical=torch.stack(penalties).mean() if penalties else q.sum()*0
        loss=weak+anchor+feature_anchor+negative+logical
        if not torch.isfinite(loss):raise ValueError('Non-finite training loss')
        loss.backward()
        if adapting and not gradient_verified:
            total=sum(float(p.grad.detach().abs().sum()) for p in adapted.values() if p.grad is not None)
            if total<=0:raise ValueError('No gradient reached the encoder')
            gradient_verified=True;print('Verified nonzero encoder gradient',total,flush=True)
        torch.nn.utils.clip_grad_norm_(list(head.parameters())+list(adapted.values()),1.);opt.step()
        if (step+1)%50==0 or step+1==args.steps:
            row={'step':step+1,'weak':float(weak.detach()),'anchor':float(anchor.detach()),'feature_anchor':float(feature_anchor.detach()),'negative':float(negative.detach()),'logic':float(logical.detach())};history.append(row);print(json.dumps(row),flush=True)
        if (step+1)%200==0 or step+1==args.steps:
            cp={'config':vars_config(args),'step':step+1,'head':{k:v.detach().cpu() for k,v in head.state_dict().items()},
                'adapted':{k:p.detach().cpu() for k,p in adapted.items()},'optimizer':opt.state_dict(),'rng':rng.bit_generator.state,
                'feature_hash':digest(args.features/'extraction.json'),'history':history,'gradient_verified':gradient_verified}
            temp=resume.with_suffix('.tmp');torch.save(cp,temp);temp.replace(resume)
    if model and args.steps>args.warmup and not gradient_verified:raise ValueError('Adaptation was not exercised')
    checkpoint={'head':{k:v.detach().cpu() for k,v in head.state_dict().items()},'adapted':{k:p.detach().cpu() for k,p in adapted.items()},
        'config':vars_config(args),'traits':inv['traits'],'model':ext['model'],'model_spec':ext['model_spec']}
    torch.save(checkpoint,args.out/'model.pt')
    (args.out/'training-inventory.json').write_text(json.dumps(inv,indent=2)+'\n')
    report={'status':'pretrained_baseline' if args.mode=='pretrained' else 'trained_awaiting_independent_trait_validation','config':vars_config(args),'source_sha256':digest(__file__),
        'training_regions':len(rows),'training_taxa':len(taxa),'feature_pool_taxa':len({r['taxon'] for r in rows}),'usable_events':len(events),'source_supervised_traits':[] if args.mode=='pretrained' else sorted({k for _,ks,_ in events for k in ks}),
        'supervised_training_observations':len({rows[i]['observation_id'] for bag,_,_ in events for i in bag}),
        'trained_parameters':sum(p.numel() for p in adapted.values()),'encoder_gradient_verified':gradient_verified,
        'no_species_loss':True,'no_manual_training_traits':True,'checkpoint_sha256':digest(args.out/'model.pt'),
        'extraction_sha256':digest(args.features/'extraction.json'),'queries_sha256':digest(args.data/'queries.json'),
        'history':history,'slurm_job_id':os.environ['SLURM_JOB_ID'],'seconds':time.monotonic()-started,
        'limitations':['Frozen organ proposals are not validated visibility.','Scoped hair contrasts are the only negative source targets.',
          'Projected arm uses approximate marginal implication projections, not exact WMC or full OWL.', 'No model selection or early stopping from test traits.']}
    (args.out/'training.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='history'}),flush=True)


def vars_config(args):
    return {k:getattr(args,k) for k in ['mode','seed','steps','warmup','observations']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['merge','fit'])
    for name in ['data','features','models','out']:p.add_argument('--'+name,type=Path,required=name in ['features','out'])
    p.add_argument('--shards',type=int,default=4);p.add_argument('--mode',choices=['pretrained','frozen','direct','mil','hierarchy','projected','shuffled'],default='mil')
    p.add_argument('--seed',type=int,default=20261026);p.add_argument('--steps',type=int,default=1200);p.add_argument('--warmup',type=int,default=200)
    p.add_argument('--observations',type=int,default=200)
    a=p.parse_args(); {'merge':merge,'fit':fit}[a.command](a)


if __name__=='__main__':main()
