"""Multi-attribute weak training and species ranking through explicit trait evidence."""
import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import re

import numpy as np
import torch
from torch import nn

from .extract import digest
from .logic import Expr
from .model import PrimitiveHead, trait_query, rank_profiles
from .weak_train import truth_mask, balanced_weights, initialize


class MultiHead(nn.Module):
    def __init__(self, schema, priors=None, feature_dim=768):
        super().__init__()
        self.heads=nn.ModuleDict()
        shared=None
        for name,vocab in schema['groups'].items():
            head=initialize(vocab,priors/name)[0] if priors else PrimitiveHead(feature_dim,vocab['organs'],vocab['colours'])
            if shared is None:shared=head.organ
            else:head.organ=shared
            self.heads[name]=head

    def forward(self,x):
        return {k:h(x) for k,h in self.heads.items()}


def compile_profiles(profiles,queries,schema,allow_partial=False):
    """Compile representable source groups; exact single EQ records may lack a named FAC."""
    result=defaultdict(dict); excluded=Counter(); cache={}
    scope=re.compile(r'\b(young|matur\w*|ripe|unripe|becom\w*|turn\w*|sometimes|usually|often|rarely|occasionally|immature)\b',re.I)
    for name,vocab in schema['groups'].items():
        represented=set().union(*(set(queries['ancestors'].get(v['iri'],[v['iri']])) for v in vocab['colours'] if v['iri']))
        groups=defaultdict(list)
        for p in profiles:
            for r in p['records']:
                if r['bl'] not in vocab['organs_in_scope'] or r['q'] not in represented:continue
                key=(p['taxon'],r['bl'])
                if r.get('qualifier') or scope.search(r['text']) or r['status']!='accepted':
                    groups[key].append(None);excluded[f'{name}:scope']+=1;continue
                iri=r.get('pc');origin='ontology_definition'
                if iri in queries['supported']:
                    expr=Expr.from_json(queries['supported'][iri])
                elif not iri and r['text'].strip().casefold()==r['ql'].strip().casefold():
                    expr=trait_query(r['b'],[r['q']]);origin='exact_normalized_EQ'
                else:
                    groups[key].append(None);excluded[f'{name}:uncompiled']+=1;continue
                ck=(name,repr(expr))
                if ck not in cache:
                    try:cache[ck]=truth_mask(expr,vocab,queries['ancestors'])
                    except ValueError:cache[ck]=None
                if cache[ck] is None:
                    groups[key].append(None);excluded[f'{name}:unrepresented_alternative']+=1;continue
                groups[key].append({'mask':cache[ck],'record':r['r'],'origin':origin,'query_iri':iri})
        for (taxon,organ),values in groups.items():
            incomplete=any(v is None for v in values)
            if incomplete and not allow_partial:excluded[f'{name}:unresolved_group']+=1;continue
            values=[v for v in values if v is not None]
            if not values:continue
            sets=[{i for i,x in enumerate(v['mask']) if x} for v in values]
            narrow=set().union(*sets) if allow_partial else min(sets,key=len)
            if not allow_partial and not all(narrow<=s for s in sets):excluded[f'{name}:conflicting_group']+=1;continue
            group=f'{organ}.{name}'
            result[taxon][group]={'mask':[float(i in narrow) for i in range(len(values[0]['mask']))],
                'organ':organ,'attribute':name,'source_records':sorted({v['record'] for v in values}),
                'query_iris':sorted({v['query_iri'] for v in values if v['query_iri']}),
                'origins':sorted({v['origin'] for v in values}),
                'incomplete_source_group':incomplete,
                'combination':'union_of_retained_source_events' if allow_partial else 'consistent_narrowest_event'}
    return dict(result),dict(excluded)


def load_regions(data,rows):
    metadata={r['photo_id']:r for r in map(json.loads,(data/'extraction/regions.jsonl').read_text().splitlines())}
    features=[];samples=[];seen=set();ambiguous=defaultdict(set)
    for r in rows:ambiguous[r['photo_id']].add(r['taxon'])
    for row in rows:
        photo=row['photo_id']
        if photo in seen or len(ambiguous[photo])!=1:continue
        seen.add(photo);record=metadata[photo]
        if row['sha256']!=record['sha256']:raise ValueError('Image/feature mismatch')
        fs=np.load(data/'extraction/features'/f'{photo}.npz')['region_features']
        if len(fs)!=len(record['regions']) or not np.isfinite(fs).all():raise ValueError('Invalid features')
        chosen={}
        for i,r in enumerate(record['regions']):
            box=r['box'];organ=r['organ']
            if organ not in ('leaf','petal','fruit') or r['score']<.3 or min(box[2]-box[0],box[3]-box[1])<32:continue
            if organ not in chosen or r['score']>record['regions'][chosen[organ]]['score']:chosen[organ]=i
        for organ,i in chosen.items():
            features.append(fs[i]);samples.append({**row,'organ':organ,'region_index':i,
                'box':record['regions'][i]['box'],'detector_score':record['regions'][i]['score']})
    return torch.tensor(np.stack(features),dtype=torch.float32),samples


def event_rows(samples,profiles,schema):
    events=[]
    for i,s in enumerate(samples):
        if s['split']!='train':continue
        for group,event in profiles.get(s['taxon'],{}).items():
            if event['organ']!=s['organ']:continue
            # Hair visibility needs more pixels than gross shape/colour; still an uncalibrated gate.
            if event['attribute']=='hairiness' and min(s['box'][2]-s['box'][0],s['box'][3]-s['box'][1])<96:continue
            events.append({**event,'sample_index':i,'taxon':s['taxon'],'observation_id':s['observation_id'],
                          'photo_id':s['photo_id'],'group':group,'supervision':'unreviewed_weak'})
    return events


def fit(initial,features,samples,events,epochs=150):
    train=[i for i,s in enumerate(samples) if s['split']=='train']
    if not train or not events:raise ValueError('No training data or events')
    # No validation/test features enter even the frozen-prior regularizer.
    train_x=features[train];lookup={old:new for new,old in enumerate(train)}
    model=copy.deepcopy(initial);opt=torch.optim.AdamW(model.parameters(),lr=1e-3,weight_decay=0)
    with torch.no_grad():teacher=initial(train_x)
    weights=balanced_weights([samples[i] for i in train]).to(features.device)
    event_weights=balanced_weights(events).to(features.device)
    masks={}
    for group in teacher:
        positions=[j for j,e in enumerate(events) if e['attribute']==group]
        if positions:
            masks[group]=(torch.tensor([lookup[events[j]['sample_index']] for j in positions],device=features.device),
                torch.tensor([events[j]['mask'] for j in positions],device=features.device),event_weights[positions])
    history=[]
    for step in range(epochs+1):
        opt.zero_grad();pred=model(train_x);weak=features.sum()*0;kl=features.sum()*0
        for group,p in pred.items():
            kl=kl+((teacher[group]*(teacher[group].clamp_min(1e-9).log()-p.clamp_min(1e-9).log())).sum(-1)*weights).sum()/len(pred)
            if group in masks:
                indices,mask,ew=masks[group];weak=weak+(-(.3+.7*(p[indices]*mask).sum(-1)).log()*ew).sum()
        loss=weak+kl
        if step in (0,epochs):history.append({'step':step,'weak_loss':weak.item(),'prior_kl':kl.item(),'objective':loss.item()})
        if step==epochs:break
        loss.backward();opt.step()
    return model,history


def distributions(pred,sample,schema,index):
    """Only explicit conditional trait states leave the visual model."""
    evidence={};organ=sample['organ']
    for name,v in schema['groups'].items():
        if organ not in v['organs_in_scope']:continue
        if name=='hairiness' and min(sample['box'][2]-sample['box'][0],sample['box'][3]-sample['box'][1])<96:continue
        oi=[o['name'] for o in v['organs']].index(organ)
        vector=pred[name][index].reshape(len(v['organs']),-1)[oi]
        vector=vector/max(float(vector.sum()),1e-12)
        evidence[f'{organ}.{name}']={str(i):float(p) for i,p in enumerate(vector)}
    return evidence


def reference_distribution(pred,samples,schema):
    collected=defaultdict(list)
    for i,s in enumerate(samples):
        if s['split']=='train':
            for group,d in distributions(pred,s,schema,i).items():collected[group].append(d)
    return {g:{k:float(np.mean([d[k] for d in ds])) for k in ds[0]} for g,ds in collected.items()}


def ranking_profiles(compiled,schema):
    result={}
    for taxon,groups in compiled.items():
        result[taxon]={}
        for group,event in groups.items():
            v=schema['groups'][event['attribute']];oi=[o['name'] for o in v['organs']].index(event['organ'])
            n=len(v['colours']);mask=event['mask'][oi*n:(oi+1)*n]
            if not any(mask):continue
            result[taxon][group]={'allowed':[str(i) for i,x in enumerate(mask) if x],'reliability':1.0}
    return result


def evaluate(pred,samples,rows,schema,catalogue,reference,split,colour_only=False):
    # Focal region selected once per organ/observation, without using species identity.
    focal={}
    for i,s in enumerate(samples):
        if s['split']!=split:continue
        key=(s['observation_id'],s['organ'])
        if key not in focal or s['detector_score']>samples[focal[key]]['detector_score']:focal[key]=i
    evidence=defaultdict(dict)
    for (obs,organ),i in focal.items():
        evidence[obs].update({g:d for g,d in distributions(pred,samples[i],schema,i).items()
                              if g in reference and (not colour_only or g.endswith('.colour'))})
    expected={r['observation_id']:r for r in rows if r['split']==split}
    # Include every held-out species in the fixed full catalogue, even if its profile is empty.
    results=[]
    for obs,row in expected.items():
        ranking=rank_profiles(evidence[obs],catalogue,reference)
        ranked=ranking['ranking'];truth=row['taxon'];true_score=next(x['score'] for x in ranked if x['taxon']==truth)
        better=sum(x['score']>true_score+1e-9 for x in ranked);tied=sum(abs(x['score']-true_score)<=1e-9 for x in ranked)
        # Expected credit under uniform tie-breaking; alphabetical order is never a win.
        top1=1/tied if better==0 else 0;top5=max(0,min(tied,5-better))/tied
        if not evidence[obs] or ranking['abstain']:top1=0;top5=0
        results.append({'observation_id':obs,'taxon':truth,'genus':row['genus'],
            'evidence':evidence[obs],'abstain':ranking['abstain'],'top1_credit':top1,'top5_credit':top5,
            'top_candidates':ranked[:5],'ties':len(ranking['ties'])})
    metrics={'observations':len(results),'candidate_species':len(catalogue),
        'coverage':np.mean([not r['abstain'] for r in results]).item() if results else 0,
        'top1':np.mean([r['top1_credit'] for r in results]).item() if results else 0,
        'top5':np.mean([r['top5_credit'] for r in results]).item() if results else 0}
    taxa={r['taxon'] for r in results}
    metrics['macro_top1']=float(np.mean([np.mean([r['top1_credit'] for r in results if r['taxon']==t]) for t in taxa])) if taxa else 0
    return metrics,results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--device',choices=['cpu','cuda'],default='cpu');parser.add_argument('--epochs',type=int,default=150)
    parser.add_argument('--source-policy',choices=['strict','partial'],default='strict')
    parser.add_argument('--validation-only',action='store_true',help='Development iterations must not repeatedly evaluate the frozen test')
    args=parser.parse_args();torch.set_num_threads(4);torch.manual_seed(0)
    data=args.data;schema=json.loads((data/'multi-vocabulary.json').read_text());protocol=json.loads((data/'protocol.json').read_text())
    if protocol['split_sha256']!=digest(data/'splits.jsonl') or protocol['schema_sha256']!=digest(data/'multi-vocabulary.json'):raise ValueError('Protocol changed')
    for name in ('profiles.json','queries.json'):
        if schema[name.replace('.json','_sha256')]!=digest(data/name):raise ValueError('Frozen source/schema mismatch')
    extraction=json.loads((data/'extraction/run.json').read_text())
    if extraction['input_manifest_sha256']!=digest(data/'images.jsonl'):raise ValueError('Extraction manifest changed')
    for group in schema['groups']:
        meta=json.loads((data/'multi-priors'/group/'prototypes.json').read_text())
        if meta['vocabulary_sha256']!=digest(data/f'vocabulary-{group}.json'):raise ValueError('Prototype vocabulary mismatch')
        if meta['encoder']['revision']!=extraction['models']['encoder']['revision']:raise ValueError('Image/text encoder mismatch')
    rows=[json.loads(x) for x in (data/'splits.jsonl').read_text().splitlines()]
    profiles=json.loads((data/'profiles.json').read_text());queries=json.loads((data/'queries.json').read_text())
    compiled,excluded=compile_profiles(profiles,queries,schema,allow_partial=args.source_policy=='partial')
    features,samples=load_regions(data,rows);features=features.to(args.device)
    initial=MultiHead(schema,data/'multi-priors').to(args.device)
    events=event_rows(samples,compiled,schema);trained,history=fit(initial,features,samples,events,args.epochs)
    with torch.no_grad():
        prior={g:p.cpu().numpy() for g,p in initial(features).items()}
        posterior={g:p.cpu().numpy() for g,p in trained(features).items()}
    reference=reference_distribution(prior,samples,schema)
    catalogue=ranking_profiles(compiled,schema)
    for p in profiles:catalogue.setdefault(p['taxon'],{})
    args.out.mkdir(parents=True,exist_ok=False)
    bundle={'state_dict':trained.cpu().state_dict(),'schema':schema,'catalogue':catalogue,'reference':reference,
        'taxon_names':{p['taxon']:p['name'] for p in profiles},'status':'experimental_weak_model',
        'feature_dim':features.shape[-1]}
    torch.save(bundle,args.out/'model.pt')
    evaluation={}
    for split in (('validation',) if args.validation_only else ('validation','test')):
        for name,pred,colour in [('pretrained_traits',prior,False),('weak_traits',posterior,False),('weak_colour_only',posterior,True)]:
            metrics,results=evaluate(pred,samples,rows,schema,catalogue,reference,split,colour)
            evaluation[f'{split}:{name}']=metrics
            (args.out/f'{split}-{name}.json').write_text(json.dumps(results,indent=2)+'\n')
    np.savez_compressed(args.out/'trait-predictions.npz',**posterior)
    (args.out/'samples.json').write_text(json.dumps(samples,indent=2)+'\n')
    (args.out/'training-events.json').write_text(json.dumps(events,indent=2)+'\n')
    report={'status':'trained_and_exploratorily_evaluated','history':history,'evaluation':evaluation,
        'groups':{g:len(v['colours'])-1 for g,v in schema['groups'].items()},'training_events':len(events),
        'events_by_attribute':dict(Counter(e['attribute'] for e in events)),
        'training_species':len({e['taxon'] for e in events}),'excluded_sources':excluded,
        'inputs_sha256':{f:digest(data/f) for f in ['profiles.json','queries.json','splits.jsonl','multi-vocabulary.json','protocol.json','extraction/run.json']},
        'epochs':args.epochs,'epsilon':.3,'prior_weight':1,'manual_training_annotations':0,
        'source_policy':args.source_policy,'validation_only':args.validation_only,
        'note':'Exploratory held-out species identification, not direct trait accuracy or proof of ontology benefit. One sampled species per genus. Missing profiles contribute no evidence. Scores use only explicit traits.'}
    (args.out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
