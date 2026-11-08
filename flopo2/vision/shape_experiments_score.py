"""Score all matched shape arms and nested human-label budgets without selection."""
import argparse
import json
from pathlib import Path
import numpy as np
from .benchmark import SHAPES,average_precision
from .extract import digest
from .shape_experiments import read_rows
from .benchmark_secondary import shape_endpoint


def score(a):
    proto=json.loads((a.data/'protocol.json').read_text()); protocol_hash=digest(a.data/'protocol.json')
    records=read_rows(a.data/'records.jsonl');annotations=read_rows(a.data/'annotations.jsonl')
    keys={(r['dataset_id'],r['record_id']):i for i,r in enumerate(records)}
    truth=np.full(len(records),'',object);datasets=np.array([r['dataset_id'] for r in records]);cultivars=np.array([r['cultivar_id'] for r in records])
    for r in annotations:
        i=keys[r['dataset_id'],r['record_id']]
        if r['task']=='shape' and r['strict_target'] is not None and records[i]['split']=='test':truth[i]=r['strict_target']
    groups={}
    for ds,categories in SHAPES.items():
        y=truth[(datasets==ds)&(truth!='')]
        groups[ds]=[c for c in categories if min(int((y==c).sum()),int((y!=c).sum()))>=5]
    groups={k:v for k,v in groups.items() if v};include=(truth!='')&np.isin(datasets,list(groups))
    y,ds,cs=truth[include],datasets[include],cultivars[include]
    unique=sorted(set(cs));clusters={c:np.flatnonzero(cs==c) for c in unique}
    rng=np.random.default_rng(20261029)
    draws=[np.concatenate([clusters[c] for c in rng.choice(unique,len(unique),replace=True)]) for _ in range(2000)]
    valid=[]
    # A draw is eligible independently of model scores, and is shared across every contrast.
    for draw in draws:
        if all(0<int((y[draw][ds[draw]==stage]==category).sum())<int((ds[draw]==stage).sum()) for stage,cc in groups.items() for category in cc):valid.append(draw)
    sizes=[0]+proto['budget_plan']['sizes'];report={};prediction_export={};identities={}
    expected={f'{m}-{seed}-{n}' for m in proto['modes'] for seed in proto['seeds'] for n in sizes}
    for encoder in proto['encoders']:
        folder=a.runs/encoder;complete=json.loads((folder/'complete.json').read_text())
        if complete['identity']['preflight'] or complete['identity']['protocol_sha256']!=protocol_hash or set(complete['runs'])!=expected:raise ValueError('Incomplete/wrong training grid')
        identities[encoder]=complete
        for name,h in complete['sha256'].items():
            if digest(folder/name)!=h:raise ValueError('Changed completion record')
        values={};samples={};seedscores={};training_counts={}
        for mode in proto['modes']:
            for budget in sizes:
                arrays=[];seed_values=[]
                for seed in proto['seeds']:
                    name=f'{mode}-{seed}-{budget}';meta=json.loads((folder/name/'complete.json').read_text())
                    if meta['identity']!=complete['identity']:raise ValueError('Mixed run identities')
                    for f,h in meta['sha256'].items():
                        if digest(folder/name/f)!=h:raise ValueError('Changed model/prediction')
                    planned=[] if budget==0 else proto['budget_plan']['schedules'][str(seed)][str(budget)]
                    if meta['training_records']!=planned:raise ValueError('Wrong human training budget')
                    q=np.load(folder/name/'predictions.npz')['probabilities']
                    if q.shape!=(len(records),36) or not np.isfinite(q).all():raise ValueError('Invalid predictions')
                    arrays.append(q);seed_values.append(shape_endpoint(y,q[include],ds,groups))
                full=np.mean(arrays,axis=0);q=full[include];key=f'{mode}/{budget}'
                prediction_export[encoder+'/'+key]=full
                values[key]=shape_endpoint(y,q,ds,groups);seedscores[key]=seed_values
                training_counts[str(budget)]=[0 if budget==0 else len(proto['budget_plan']['schedules'][str(seed)][str(budget)]) for seed in proto['seeds']]
                samples[key]=np.array([shape_endpoint(y[draw],q[draw],ds[draw],groups) for draw in valid])
                print(encoder,key,values[key],flush=True)
        # Sampling audit must match across all three source-label arms for each seed.
        for seed in proto['seeds']:
            hashes={json.loads((folder/f'{m}-{seed}-0/complete.json').read_text())['sampling_audit_sha256'] for m in ['raw','normalized','shuffled']}
            if len(hashes)!=1:raise ValueError('Unmatched source sampling')
        contrasts={}
        for budget in sizes:
            for first,second in [('normalized','native'),('normalized','raw'),('normalized','shuffled'),('raw','native'),('shuffled','native')]:
                ka,kb=f'{first}/{budget}',f'{second}/{budget}'
                contrasts[f'{first} minus {second} at {budget}']=dict(difference=values[ka]-values[kb],CI95=np.quantile(samples[ka]-samples[kb],[.025,.975]).tolist())
        curve={}
        for first,second in [('normalized','native'),('normalized','raw'),('normalized','shuffled'),('raw','native')]:
            d=np.mean([samples[f'{first}/{n}']-samples[f'{second}/{n}'] for n in sizes if n],axis=0)
            curve[first+' minus '+second]=dict(difference=float(np.mean([values[f'{first}/{n}']-values[f'{second}/{n}'] for n in sizes if n])),CI95=np.quantile(d,[.025,.975]).tolist())
        report[encoder]=dict(macro_AP=values,individual_seed_AP=seedscores,contrasts=contrasts,equal_budget_mean_contrasts=curve,human_training_record_counts=training_counts)
    a.out.mkdir(parents=True,exist_ok=False)
    result=dict(protocol_sha256=protocol_hash,scoring_source_sha256=digest(__file__),role='Exploratory follow-up, nominal unadjusted 95% CIs; fixed trained three-seed ensembles; all budgets reported.',
       metric='Equal-dataset mean of supported-category AP; curve summary is equal mean over positive human-label budgets.',test_sets=len(y),test_cultivars=len(unique),groups=groups,bootstrap_requested=2000,bootstrap_valid=len(valid),results=report,
       training_manifest_sha256={e:digest(a.runs/e/'complete.json') for e in proto['encoders']})
    (a.out/'results.json').write_text(json.dumps(result,indent=2)+'\n');np.savez_compressed(a.out/'ensemble-predictions.npz',**prediction_export)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['data','runs','out']:p.add_argument('--'+n,type=Path,required=True)
    score(p.parse_args())

if __name__=='__main__':main()
