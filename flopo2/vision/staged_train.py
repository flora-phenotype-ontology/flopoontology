"""Matched frozen spatial heads with image-only teachers and flora supervision.

All hyperparameters and withheld combinations are fixed before independent review.
No species loss, test-label tuning, or inference-time taxon/profile input.
"""
import argparse
from collections import defaultdict,Counter
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from .extract import digest
from .modern_weak import source_bags,ontology_edges,negative_pairs,CONTEXT_QUALITIES,bernoulli_kl
from .staged_features import TILES
from .staged_teacher import validate
from .full_diagnostic import shape_metrics

SEEDS=[20261027,20261028,20261029]
HELDOUT=[21,34,35]  # fruit pubescent, petal oblong, fruit white; shared quality elsewhere
PRIMARY=['flora','teacher','combined','flopo','shuffled_rules','shuffled_profiles']
TRANSFER=['independent','combined','flopo','shuffled_rules']


def evidence_weights(box):
    # Soft target over whole-organ and overlapping subviews; no mask claim.
    if box is None:return np.zeros(5,dtype=np.float32)
    area=(box[2]-box[0])*(box[3]-box[1]);weights=[]
    for b in TILES:
        inter=max(0,min(box[2],b[2])-max(box[0],b[0]))*max(0,min(box[3],b[3])-max(box[1],b[1]))
        union=area+(b[2]-b[0])*(b[3]-b[1])-inter;weights.append(inter/max(union,1e-9))
    w=np.array(weights,dtype=np.float32);return w/max(w.sum(),1e-9)


def teacher_arrays(records,rows,traits,heldout=(),require_complete=True):
    y=np.full((len(rows),len(traits)),np.nan,np.float32);v=y.copy();attention=np.zeros((*y.shape,5),np.float32);seen=set()
    for record in records:
        i=record['row_index']
        if i in seen or not 0<=i<len(rows) or rows[i]['split']!='train':raise ValueError('Repeated or non-training teacher image')
        seen.add(i)
        if record['image_sha256']!=rows[i]['sha256'] or record['crop_box']!=rows[i]['box']:raise ValueError('Teacher/image join mismatch')
        validate(record['annotation'],traits,rows[i]['organ'])
        for e in record['annotation']['traits']:
            k=e['id']
            if k in heldout or e['confidence']!='high':continue
            v[i,k]=float(e['state']!='unobservable')
            if e['state']!='unobservable':y[i,k]=float(e['state']=='present');attention[i,k]=evidence_weights(e['box'])
    if require_complete and seen!={i for i,r in enumerate(rows) if r['split']=='train'}:raise ValueError('Incomplete training teacher coverage')
    return y,v,attention


def balanced_events(rows,inv,heldout=()):
    events=[e for e in source_bags(rows,inv) if not set(e[1])&set(heldout)]
    groups=defaultdict(lambda:defaultdict(list))
    for eidx,(_,ks,taxon) in enumerate(events):
        for k in ks:groups[k][taxon].append(eidx)
    return events,{k:dict(v) for k,v in groups.items()}


def sample_batch(rng,events,groups,rows):
    # Same 4 trait/taxon groups and 8 observations for every arm of a seed.
    chosen=[];selected=[]
    for k in rng.choice(sorted(groups),size=4):
        taxon=str(rng.choice(sorted(groups[int(k)])));ei=int(rng.choice(groups[int(k)][taxon]));event=events[ei]
        by_obs=defaultdict(list)
        for i in event[0]:by_obs[rows[i]['observation_id']].append(i)
        obs=sorted(by_obs);draw=rng.choice(obs,size=8,replace=len(obs)<8)
        chosen.extend(int(rng.choice(by_obs[int(o)])) for o in draw);selected.append(event)
    return chosen,selected


class SpatialTraits(nn.Module):
    def __init__(self,dim,traits,reference,centers,independent=False):
        super().__init__();qualities=sorted({t['quality'] for t in traits});organs=sorted({t['bearer'] for t in traits})
        mapping=list(range(len(traits))) if independent else [qualities.index(t['quality']) for t in traits]
        n=max(mapping)+1
        self.register_buffer('quality_ids',torch.tensor(mapping));self.register_buffer('organ_ids',torch.tensor([organs.index(t['bearer']) for t in traits]))
        self.register_buffer('reference',reference.clone());self.register_buffer('centers',centers.clone())
        self.query=nn.Parameter(torch.zeros(n,dim));self.quality=nn.Parameter(torch.zeros(n,dim))
        self.organ=nn.Parameter(torch.zeros(len(organs),dim));self.bias=nn.Parameter(torch.zeros(n))
        self.visibility=nn.Linear(dim,len(traits));nn.init.zeros_(self.visibility.weight);nn.init.constant_(self.visibility.bias,2.)
    def forward(self,x):
        weights=torch.einsum('bpd,kd->bkp',x,self.query[self.quality_ids]).softmax(-1)
        pooled=torch.einsum('bkp,bpd->bkd',weights,x)
        delta=self.quality[self.quality_ids]+self.organ[self.organ_ids]
        logits=x[:,0]@self.reference.T-3+(pooled-self.centers).mul(delta).sum(-1)+self.bias[self.quality_ids]
        return logits,self.visibility(x[:,0]),weights


def masked_bce(logits,target):
    valid=torch.isfinite(target)
    if not valid.any():return logits.sum()*0
    loss=F.binary_cross_entropy_with_logits(logits,torch.nan_to_num(target),reduction='none')
    # Balance observed signs within each trait, without Python GPU-synchronizing loops.
    mask=torch.stack([valid&(target==0),valid&(target==1)]).to(logits.dtype)
    count=mask.sum(1);means=(loss.unsqueeze(0)*mask).sum(1)/count.clamp_min(1)
    available=(count>0).to(logits.dtype)
    per_trait=(means*available).sum(0)/available.sum(0).clamp_min(1)
    usable=(available.sum(0)>0).to(logits.dtype)
    return (per_trait*usable).sum()/usable.sum().clamp_min(1)



def soft_source_loss(q,chosen_events,visibility=None):
    # Assertion support averaged across sampled observations, not max over images.
    parts=[]
    for b,(_,allowed,_) in enumerate(chosen_events):
        p=-torch.expm1(torch.log1p(-q[b*8:(b+1)*8,allowed].clamp(1e-6,1-1e-6)).sum(-1))
        weights=torch.ones_like(p) if visibility is None else visibility[b*8:(b+1)*8,allowed].mean(-1).detach().clamp_min(.05)
        support=(p*weights).sum()/weights.sum()
        parts.append(-(.05+.95*support).log())
    return torch.stack(parts).mean()


def rule_edges(traits,ancestors,shuffled=False):
    edges=ontology_edges(traits,ancestors)
    if not shuffled:return edges
    # In-degree/out-degree and organ preserved; labels permuted reproducibly.
    rng=np.random.default_rng(3291);permutation={}
    for organ in sorted({t['organ'] for t in traits}):
        ids=[t['index'] for t in traits if t['organ']==organ and t['quality_label'] not in CONTEXT_QUALITIES];permutation.update(dict(zip(ids,rng.permutation(ids).tolist())))
    return [(permutation[a],permutation[b]) for a,b in edges]


def runs():
    return [('primary','baseline',0)]+[('primary',m,s) for m in PRIMARY for s in SEEDS]+[('transfer',m,s) for m in TRANSFER for s in SEEDS]


def train_all(a):
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Orix Slurm GPU required')
    torch.set_num_threads(4);device='cuda';a.out.mkdir(parents=True,exist_ok=True)
    ext=json.loads((a.features/'extraction.json').read_text())
    for f,h in ext['sha256'].items():
        if digest(a.features/f)!=h:raise ValueError('Changed spatial features')
    done=json.loads((a.teacher/'complete.json').read_text());protocol=json.loads((a.teacher/'protocol.json').read_text())
    if digest(a.teacher/'annotations.jsonl')!=done['annotations_sha256'] or digest(a.teacher/'protocol.json')!=done['protocol_sha256']:raise ValueError('Changed teacher')
    if digest(a.features/'regions.jsonl')!=protocol['regions_sha256'] or digest(a.features/'inventory.json')!=protocol['inventory_sha256']:raise ValueError('Teacher feature mismatch')
    rows=[json.loads(s) for s in (a.features/'regions.jsonl').read_text().splitlines()];inv=json.loads((a.features/'inventory.json').read_text());traits=inv['traits']
    teacher=[json.loads(s) for s in (a.teacher/'annotations.jsonl').read_text().splitlines()]
    if any(r['protocol_sha256']!=done['protocol_sha256'] for r in teacher):raise ValueError('Mixed teacher protocols')
    queries=json.loads((a.data/'queries.json').read_text());arrays=np.load(a.features/'features.npz');x=torch.tensor(arrays['regions'],device=device)
    # Use the original frozen FG-CLIP teacher logits for both encoders: same initial
    # target function, fit reference projection on TRAINING features only for BioCLIP.
    old_manifest=json.loads((a.base_features/'extraction.json').read_text())
    if digest(a.base_features/'features.npz')!=old_manifest['features_sha256'] or digest(a.base_features/'regions.jsonl')!=digest(a.features/'regions.jsonl'):raise ValueError('Changed baseline or row alignment')
    old=np.load(a.base_features/'features.npz');text=torch.tensor(old['text'],device=device);train_ids=[i for i,r in enumerate(rows) if r['split']=='train']
    base_logits=torch.tensor(old['regions'],device=device)@text.T*10-3
    if ext['encoder']=='fgclip2':reference=10*text
    else:
        design=x[train_ids,0];target=base_logits[train_ids]+3
        reference=torch.linalg.solve(design.T@design+torch.eye(design.shape[1],device=device)*1.,design.T@target).T
    centers=torch.stack([x[[i for i in train_ids if rows[i]['organ']==t['organ']]].mean((0,1)) for t in traits])
    frozen=(x[:,0]@reference.T-3).sigmoid().detach()
    for regime,mode,seed in runs():
        if a.preflight and (regime,mode,seed)!=('primary','combined',SEEDS[0]):continue
        name=f'{regime}-{mode}-{seed}';folder=a.out/name;folder.mkdir(exist_ok=True)
        if (folder/'complete.json').exists():continue
        heldout=HELDOUT if regime=='transfer' else []
        if heldout:
            for k in heldout:
                if not any(t['quality']==traits[k]['quality'] and t['organ']!=traits[k]['organ'] and t['index'] not in heldout for t in traits):raise ValueError('Heldout quality has no seen bearer')
        y,v,att=teacher_arrays(teacher,rows,traits,heldout,require_complete=not a.preflight);y=torch.tensor(y,device=device);v=torch.tensor(v,device=device);att=torch.tensor(att,device=device)
        event_rows=rows
        if a.preflight:
            annotated={r['row_index'] for r in teacher};event_rows=[r if i in annotated else {**r,'split':'unused'} for i,r in enumerate(rows)]
        events,groups=balanced_events(event_rows,inv,heldout);rng=np.random.default_rng(seed);torch.manual_seed(seed)
        head=SpatialTraits(x.shape[-1],traits,reference,centers,independent=mode=='independent').to(device)
        optimizer=torch.optim.AdamW(head.parameters(),lr=3e-4,weight_decay=.01)
        edges=rule_edges(traits,queries['ancestors'],mode=='shuffled_rules')
        pairs=negative_pairs(inv);single=defaultdict(set);possible=defaultdict(set)
        for e in inv['events']:
            if set(e['any_of'])&set(heldout):continue
            possible[e['taxon']].update(e['any_of'])
            if len(e['any_of'])==1:single[e['taxon']].update(e['any_of'])
        # Reassign source targets but retain exactly the same sampled images/events.
        source_map={}
        if mode=='shuffled_profiles':
            srng=np.random.default_rng(714)
            for organ in sorted({t['organ'] for t in traits}):
                ids=[i for i,e in enumerate(events) if rows[e[0][0]]['organ']==organ]
                source_map.update({id(events[i]):events[j][1] for i,j in zip(ids,srng.permutation(ids))})
        history=[];exposure=Counter();seen=set();started=time.monotonic();steps=0 if mode=='baseline' else (3 if a.preflight else a.steps)
        checkpoint=folder/'resume.pt';start=0
        if checkpoint.exists():
            cp=torch.load(checkpoint,map_location=device,weights_only=False)
            if cp['inputs']!=[digest(a.features/'extraction.json'),done['annotations_sha256'],digest(__file__),a.steps]:raise ValueError('Resume inputs changed')
            head.load_state_dict(cp['head']);optimizer.load_state_dict(cp['optimizer']);rng.bit_generator.state=cp['rng'];start=cp['step'];history=cp['history'];seen=set(cp['seen']);exposure=Counter(cp['exposure'])
        for step in range(start,steps):
            ids,chosen=sample_batch(rng,events,groups,rows);seen.update(ids)
            for _,ks,_ in chosen:exposure.update(ks)
            logits,visibility,weights=head(x[ids]);q=logits.sigmoid();zero=q.sum()*0
            teach=masked_bce(logits,y[ids]) if mode!='flora' else zero
            vis=masked_bce(visibility,v[ids]) if mode!='flora' else zero
            valid=torch.isfinite(y[ids]);spatial=-(att[ids]*weights.clamp_min(1e-8).log()).sum(-1)
            grounding=spatial[valid].mean() if valid.any() and mode!='flora' else zero
            targets=[(bag,source_map.get(id(e),ks),taxon) for e in chosen for bag,ks,taxon in [e]]
            weak=soft_source_loss(q,targets,visibility.sigmoid() if mode!='flora' else None) if mode!='teacher' else zero
            neg=[]
            if mode not in ('teacher','shuffled_profiles'):
                for j,i in enumerate(ids):
                    for k,l in pairs:
                        if k in heldout or l in heldout or traits[k]['organ']!=rows[i]['organ']:continue
                        for positive,negative in [(k,l),(l,k)]:
                            if positive in single[rows[i]['taxon']] and negative not in possible[rows[i]['taxon']]:neg.append(-(.05+.95*(1-q[j,negative])).log())
            negative=torch.stack(neg).mean() if neg else zero
            anchor=bernoulli_kl(frozen[ids],q)
            allowed=[k for k in range(len(traits)) if k not in heldout and traits[k]['quality_label'] not in CONTEXT_QUALITIES]
            anchor=anchor[:,allowed].mean()
            penalties=[]
            if mode in ('flopo','shuffled_rules'):
                for k,l in edges:
                    js=[j for j,i in enumerate(ids) if rows[i]['organ']==traits[k]['organ']]
                    if js:penalties.append(F.relu(q[js,k]-q[js,l]).square().mean())
            logic=torch.stack(penalties).mean() if penalties else zero
            loss=teach+weak+negative+.25*vis+.1*grounding+anchor+logic
            if not torch.isfinite(loss):raise ValueError('Nonfinite loss')
            optimizer.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(head.parameters(),1.);optimizer.step()
            if step==0 or (step+1)%500==0 or step+1==steps:
                r={'step':step+1,**{k:float(val.detach()) for k,val in [('loss',loss),('teacher',teach),('flora',weak),('negative',negative),('visibility',vis),('grounding',grounding),('anchor',anchor),('logic',logic)]}}
                history.append(r);print(name,json.dumps(r),flush=True)
                tmp=folder/'resume.tmp';torch.save({'head':head.state_dict(),'optimizer':optimizer.state_dict(),'rng':rng.bit_generator.state,'step':step+1,'history':history,'seen':list(seen),'exposure':dict(exposure),'inputs':[digest(a.features/'extraction.json'),done['annotations_sha256'],digest(__file__),a.steps]},tmp);tmp.replace(checkpoint)
        torch.save({'head':head.state_dict(),'traits':traits,'independent':mode=='independent'},folder/'model.pt')
        output={}
        with torch.inference_mode():
            for ds in arrays.files:
                prob=[];visibility=[]
                cached=x if ds=='regions' else torch.tensor(arrays[ds],device=device)
                for start in range(0,len(cached),128):
                    logit,vis,_=head(cached[start:start+128]);prob.append(logit.sigmoid().cpu().numpy());visibility.append(vis.sigmoid().cpu().numpy())
                output[ds]=np.concatenate(prob);output[ds+'_visibility']=np.concatenate(visibility)
                if not np.isfinite(output[ds]).all():raise ValueError('Nonfinite predictions')
        np.savez_compressed(folder/'predictions.npz',**output)
        (folder/'training-inventory.json').write_text(json.dumps(inv)+'\n')
        with (folder/'predictions.jsonl').open('w') as handle:
            for i,r in enumerate(rows):
                ks=[t['index'] for t in traits if t['organ']==r['organ'] and t['quality_label'] not in CONTEXT_QUALITIES]
                handle.write(json.dumps({'photo_id':r['photo_id'],'observation_id':r['observation_id'],'organ':r['organ'],'split':r['split'],
                    'probabilities':{str(k):float(output['regions'][i,k]) for k in ks},
                    'visibility':{str(k):float(output['regions_visibility'][i,k]) for k in ks}})+'\n')
        (folder/'prediction-manifest.json').write_text(json.dumps({'predictions_sha256':digest(folder/'predictions.jsonl')})+'\n')

        report={'name':name,'initialization':('Frozen FG-CLIP 2 text scores' if ext['encoder']=='fgclip2' else 'Training-only ridge distillation of FG-CLIP scores onto frozen BioCLIP features; not native BioCLIP zero-shot'), 'regime':regime,'mode':mode,'seed':seed,'steps':steps,'heldout_traits':heldout,'traits':traits,'history':history,
           'unique_training_regions_seen':len(seen),'sampled_trait_events':dict(exposure),'seconds':time.monotonic()-started,'slurm_job_id':os.environ['SLURM_JOB_ID'],
           'checkpoint_sha256':digest(folder/'model.pt'),'predictions_sha256':digest(folder/'predictions.npz'),
           'feature_manifest_sha256':digest(a.features/'extraction.json'),'teacher_sha256':done['annotations_sha256'],'source_sha256':digest(__file__),
           'limitations':['Source loss averages sampled observation support; it is not a calibrated population prevalence estimate.',
             'Teacher abstention is a noisy visibility target, not verified visibility truth.','Five overlapping views, not pixel segmentation.',
             'FLOPO implications may connect withheld combinations; direct teacher/source/anchor targets for them are removed.',
             'Independent review pending; no model selection on development audit.']}
        (folder/'complete.json').write_text(json.dumps(report,indent=2)+'\n')
    if not a.preflight:
        diagnostic(a,traits)
        (a.out/'complete.json').write_text(json.dumps({'models':len(runs()),'encoder':ext['encoder'],'status':'trained_awaiting_independent_trait_validation'})+'\n')


def diagnostic(a,traits):
    freeze=json.loads((a.audit/'annotation-freeze.json').read_text())
    for f,h in freeze['sha256'].items():
        if digest(a.audit/f)!=h:raise ValueError('Changed development reference')
    field=json.loads((a.features/'field-rows.json').read_text());external=json.loads((a.features/'external-rows.json').read_text())
    fj=json.loads((a.audit/'private-join.json').read_text());ej=json.loads((a.audit/'external-join.json').read_text())
    fa=json.loads((a.audit/'field-annotations.json').read_text());ea=json.loads((a.audit/'external-annotations.json').read_text())
    fi_lookup={r['observation_id']:i for i,r in enumerate(field)};ei_lookup={r['id']:i for i,r in enumerate(external)}
    fi=[fi_lookup[r['observation_id']] for r in fj];ei=[ei_lookup[r['specimen_id']] for r in ej]
    for ann,j,i in zip(fa,fj,fi):
        if ann['audit_id']!=j['audit_id'] or field[i]['sha256']!=j['image_sha256'] or field[i]['box']!=j['box']:raise ValueError('Field join mismatch')
    for ann,j,i in zip(ea,ej,ei):
        if ann['audit_id']!=j['audit_id'] or external[i]['sha256']!=j['image_sha256']:raise ValueError('External join mismatch')
    training=[json.loads(line) for line in (a.features/'regions.jsonl').read_text().splitlines() if json.loads(line)['split']=='train']
    if {r['genus'] for r in training}&{field[i]['genus'] for i in fi}:raise ValueError('Field training genus overlap')
    if {r['sha256'] for r in training}&({field[i]['sha256'] for i in fi}|{external[i]['sha256'] for i in ei}):raise ValueError('Image overlap')
    outline={'ovate','lanceolate','oblong','linear','elliptic','obovate','oblanceolate','orbicular','heart shaped','spatulate'}
    shape_traits=[t for t in traits if t['organ']=='leaf' and t['quality_label'] in outline];ks=[t['index'] for t in shape_traits]
    results={};grouped=defaultdict(list)
    for regime,mode,seed in runs():
        name=f'{regime}-{mode}-{seed}';folder=a.out/name;report=json.loads((folder/'complete.json').read_text())
        if digest(folder/'predictions.npz')!=report['predictions_sha256']:raise ValueError('Changed output')
        z=np.load(folder/'predictions.npz');values={}
        for ds,ids,annotations in [('field',fi,fa),('external_original',ei,ea),('external_masked',ei,ea)]:
            q=z[ds][ids][:,ks];values[ds]=q
            results.setdefault(name,{})[ds]=shape_metrics(annotations,q,shape_traits)
        grouped[f'{regime}-{mode}'].append(values)
    ensembles={}
    for name,values in grouped.items():
        ensembles[name]={ds:shape_metrics(ref,np.stack([v[ds] for v in values]).mean(0),shape_traits) for ds,ref in [('field',fa),('external_original',ea),('external_masked',ea)]}
    result={'reference_quality':'Previously inspected single-AI development audit; not independent expert validation.',
      'selection':'None. All arms and seeds retained. Independent review needed for heldout fruit/petal combinations.',
      'results':results,'ensembles':ensembles,'annotation_freeze':freeze,
      'external_genus_overlap':sorted({r['genus'] for r in training}&{external[i]['species'].split()[0] for i in ei}),
      'scope':'Leaf-shape diagnostic only; not validation of all 36 outputs or the three withheld combinations.'}
    (a.out/'diagnostic.json').write_text(json.dumps(result,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['features','base-features','data','teacher','audit','out']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--steps',type=int,default=6000);p.add_argument('--preflight',action='store_true');train_all(p.parse_args())

if __name__=='__main__':main()
