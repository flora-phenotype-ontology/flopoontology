"""Frozen small-cohort experiment. Prepare circuits on CPU, fit heads on Orix GPU.

Species profiles are weak constraints, not image-level trait ground truth.
All model selection uses validation; evaluate the frozen tests only after fitting.
"""
import argparse
import copy
import json
from pathlib import Path
from collections import Counter

import numpy as np
import torch
from torch import nn
from .extract import digest
from .multi import MultiHead
from .latent_train import concepts, group_specs, profile_formula
from .latent import LatentTaxonWMC
from .bears import diversification


def read_jsonl(path):
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def event_mask(allowed,size):
    states={int(i) for i in allowed}
    if not states or not states<=set(range(size)):raise ValueError('Invalid profile states')
    return [float(i in states) for i in range(size)]


def prepare(data, priors, out):
    protocol=json.loads((data/'protocol.json').read_text())
    audit=json.loads((data/'split-audit.json').read_text())
    if audit['status'] not in ('ready','ready_known_only'):raise ValueError('Cohort fails prespecified sample-size gate')
    for filename,expected in [('splits.jsonl',audit['split_sha256']),
                              ('images.jsonl',audit['image_manifest_sha256']),
                              ('catalogue.json',protocol['catalogue_sha256']),
                              ('multi-vocabulary.json',protocol['schema_sha256'])]:
        if digest(data/filename)!=expected:raise ValueError(f'Changed {filename}')
    extraction=json.loads((data/'extraction/run.json').read_text())
    if extraction['input_manifest_sha256']!=digest(data/'images.jsonl'):raise ValueError('Changed extraction input')
    schema=json.loads((data/'multi-vocabulary.json').read_text())
    schema['groups']={k:v for k,v in schema['groups'].items() if 'leaf.'+k in protocol['groups']}
    for attr in schema['groups']:
        meta=json.loads((priors/attr/'prototypes.json').read_text())
        if meta['encoder']['revision']!=extraction['models']['encoder']['revision']:raise ValueError('Encoder mismatch')
    rows=read_jsonl(data/'splits.jsonl');catalogue=json.loads((data/'catalogue.json').read_text())
    regions={r['photo_id']:r for r in read_jsonl(data/'extraction/regions.jsonl')}
    features=[];feature_hashes={}
    for r in rows:
        path=data/'extraction/features'/f"{r['photo_id']}.npz"
        if regions[r['photo_id']]['sha256']!=r['sha256']:raise ValueError('Image mismatch')
        feature_hashes[str(r['photo_id'])]=digest(path)
        features.append(np.load(path)['region_features'][r['region_index']])
    features=torch.tensor(np.stack(features),dtype=torch.float32)
    if not torch.isfinite(features).all():raise ValueError('Nonfinite features')
    initial=MultiHead(schema,priors);specs={g:group_specs(schema)[g] for g in protocol['groups']}
    train=[i for i,r in enumerate(rows) if r['split']=='train']
    with torch.no_grad():teacher=concepts(initial,features[train],specs)
    reference={g:((p.mean(0)+1e-6)/(p.mean(0)+1e-6).sum()).tolist() for g,p in teacher.items()}
    known=sorted({rows[i]['taxon'] for i in train});all_taxa=sorted(catalogue)
    banks={}
    for mode,taxa in [('known',known),('all',all_taxa)]:
        banks[mode]=LatentTaxonWMC({g:s['size'] for g,s in specs.items()},
            {t:profile_formula(catalogue[t],protocol['groups']) for t in taxa},reference,epsilon=.1).float()
    out.mkdir(parents=True,exist_ok=False)
    provenance={'source_sha256':{name:digest(Path(__file__).with_name(name)) for name in ('small_train.py','small.py','latent.py','bears.py','multi.py','model.py')},'protocol':protocol,'split_audit':audit,'feature_hashes':feature_hashes,
                'encoder':extraction['models']['encoder'],
                'plan':{'steps':300,'learning_rate':.001,'teacher_KL_weight':1.,
                        'bears_weight':.1,'bears_entropy_weight':.01,'ensemble_members':3,'seeds':[20261025,20261026,20261027],
                        'selection':'minimum validation species NLL, every 10 steps, including initialization',
                        'test_policy':'single final scoring after all checkpoints selected',
                        'taxonomy_prior':'uniform; reference learned from training images only',
                        'reasoning_scope':'finite two-group FLOPO-grounded profiles, not full OWL reasoning'}}
    payload=dict(schema=schema,specs=specs,features=features,rows=rows,catalogue=catalogue,
                 initial_state=initial.state_dict(),banks=banks,teacher=teacher,reference=reference,
                 provenance=provenance)
    torch.save(payload,out/'prepared.pt')
    (out/'preparation.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps({'counts':audit['counts'],'known_taxa':known,'all_taxa':all_taxa}),flush=True)


def run(out):
    if not torch.cuda.is_available():raise RuntimeError('Use an Orix GPU allocation')
    torch.set_num_threads(4)
    p=torch.load(out/'prepared.pt',weights_only=False,map_location='cpu')
    x=p['features'].cuda();rows=p['rows'];specs=p['specs']
    banks={k:v.cuda() for k,v in p['banks'].items()};known=banks['known']
    ids={s:torch.tensor([i for i,r in enumerate(rows) if r['split']==s],device='cuda')
         for s in ('train','validation','test','zero_shot_test')}
    tr,va=ids['train'],ids['validation']
    target={s:torch.tensor([known.taxa.index(rows[i]['taxon']) for i in ids[s].cpu().tolist()],device='cuda')
            for s in ('train','validation','test')}
    counts=torch.bincount(target['train'],minlength=len(known.taxa)).float()
    weights=(1/counts[target['train']]);weights/=weights.sum()
    def initial():
        m=MultiHead(p['schema']);m.load_state_dict(p['initial_state']);return m.cuda()
    base=initial().eval()
    with torch.no_grad():teacher=concepts(base,x[tr],specs)
    masks={g:torch.tensor([event_mask(p['catalogue'][rows[j]['taxon']][g]['allowed'],specs[g]['size'])
                         for j in tr.cpu().tolist()],device='cuda') for g in specs}
    history={};models={'pretrained':[base]}
    for mode in ('flat_weak','wmc','wmc_bears'):
        members=[];hist=[]
        for seed in (20261025,20261026,20261027):
            torch.manual_seed(seed);model=initial();opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=0)
            best=None
            with torch.no_grad():previous=[concepts(m,x[tr],specs) for m in members]
            for step in range(301):
                model.train();opt.zero_grad()
                # Same small feature perturbation for all adapted baselines; seeds differ.
                q=concepts(model,nn.functional.normalize(x[tr]+.01*torch.randn_like(x[tr]),dim=-1),specs)
                kl=sum((teacher[g]*(teacher[g].clamp_min(1e-8).log()-q[g].clamp_min(1e-8).log())).sum(-1) for g in specs)/len(specs)
                if mode=='flat_weak':
                    fit=sum(-(q[g]*masks[g]).sum(-1).clamp_min(1e-8).log() for g in specs)/len(specs)
                else:fit=-known(q).gather(1,target['train'][:,None])[:,0]
                loss=((fit+kl)*weights).sum()
                if mode=='wmc_bears':
                    # BEARS compares concepts on the same unperturbed images.
                    clean=concepts(model,x[tr],specs)
                    diversity,entropy=diversification(clean,previous,samples=64)
                    loss=loss-(weights*(.1*diversity+.01*entropy)).sum()
                if step%10==0:
                    model.eval()
                    with torch.no_grad():v=float(nn.functional.nll_loss(known(concepts(model,x[va],specs)),target['validation']))
                    if best is None or v<best[0]:best=(v,step,copy.deepcopy(model.state_dict()))
                if step==300:break
                loss.backward();opt.step()
            model.load_state_dict(best[2]);model.eval();members.append(model)
            torch.save({'state_dict':model.cpu().state_dict(),'schema':p['schema'],'reference':p['reference'],
                        'selected_step':best[1],'seed':seed},out/f'{mode}-{seed}.pt');model.cuda()
            hist.append({'seed':seed,'step':best[1],'validation_nll':best[0]})
            print(mode,seed,hist[-1],flush=True)
        models[mode]=members;history[mode]=hist
    # Direct classifier has identical frozen image inputs and a four-species output.
    torch.manual_seed(20261025);direct=nn.Linear(x.shape[1],len(known.taxa)).cuda()
    opt=torch.optim.AdamW(direct.parameters(),lr=.001,weight_decay=0);best=None
    for step in range(301):
        opt.zero_grad();loss=(nn.functional.cross_entropy(direct(x[tr]),target['train'],reduction='none')*weights).sum()
        if step%10==0:
            with torch.no_grad():v=float(nn.functional.cross_entropy(direct(x[va]),target['validation']))
            if best is None or v<best[0]:best=(v,step,copy.deepcopy(direct.state_dict()))
        if step==300:break
        loss.backward();opt.step()
    direct.load_state_dict(best[2]);direct.eval()
    torch.save({'state_dict':direct.cpu().state_dict(),'taxa':known.taxa,'selected_step':best[1]},out/'direct.pt');direct.cuda()
    # All model decisions are complete. Score test sets for the first time here.
    results={};predictions=[]
    with torch.no_grad():
        for mode,members in models.items():
            results[mode]={}
            evaluation_splits=['validation','test']
            if p['provenance']['split_audit']['unseen_species_ready']:evaluation_splits.append('zero_shot_test')
            for split in evaluation_splits:
                idx=ids[split];bank=banks['all'] if split=='zero_shot_test' else known
                truth=torch.tensor([bank.taxa.index(rows[i]['taxon']) for i in idx.cpu().tolist()],device='cuda')
                qs=[concepts(m,x[idx],specs) for m in members]
                prob=torch.stack([bank(q).exp() for q in qs]).mean(0)
                predicted=prob.argmax(-1);by={}
                for t in truth.unique():
                    mask=truth==t;by[bank.taxa[int(t)]]=float((predicted[mask]==truth[mask]).float().mean())
                results[mode][split]={'n':len(idx),'accuracy':float((predicted==truth).float().mean()),
                    'macro_accuracy':sum(by.values())/len(by),'per_taxon_accuracy':by,
                    'nll':float(-prob.gather(1,truth[:,None]).clamp_min(1e-8).log().mean())}
                for j,i in enumerate(idx.cpu().tolist()):
                    predictions.append({'model':mode,'split':split,'observation_id':rows[i]['observation_id'],
                        'truth':rows[i]['taxon'],'taxa':bank.taxa,'probabilities':prob[j].cpu().tolist(),
                        'trait_probabilities':{g:torch.stack([q[g][j] for q in qs]).mean(0).cpu().tolist() for g in specs}})
        results['direct']={s:{'n':len(ids[s]),'accuracy':float((direct(x[ids[s]]).argmax(-1)==target[s]).float().mean())}
                           for s in ('validation','test')}
    report={'results':results,'selection':history,'direct_selected_step':best[1],
            'provenance':p['provenance'],'gpu':torch.cuda.get_device_name(),
            'caveats':['No categorical image-level trait gold: species accuracy does not validate trait meaning.',
                       'Only five selected species and two groups; not evidence of broad FLOPO coverage.',
                       'Held-out-species result is a small compositional transfer check, not general open-set recognition.',
                       'No full-ontology reasoning ablation or published PlantTraitNet reproduction.',
                       'Overlap with foundation-model pretraining images is unknown.']}
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'predictions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in predictions))
    print(json.dumps(results),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run'])
    p.add_argument('--data',type=Path);p.add_argument('--priors',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.data,a.priors,a.out)
    else:run(a.out)

if __name__=='__main__':main()
