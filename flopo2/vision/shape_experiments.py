"""Frozen matched raw-text/FLOPO supervision and human-label budget study.

Preparation and scoring use CPU. GPU training is in shape_experiments_train.
This is exploratory follow-up on the already inspected pxGPT test cohort.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
from .benchmark import SHAPES, average_precision
from .extract import digest

IDS = [0, 1, 2, 6, 10, 14, 15, 22, 28, 29]
SEEDS = [20261029, 20261030, 20261031]
MODES = ['native', 'raw', 'normalized', 'shuffled']


def read_rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines()]


def unit(x):
    return (x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-10)).astype(np.float32)


def excluded_taxa(rows):
    # Family exclusion is deliberately broader than Brassica, covering synonym gaps.
    return {r['taxon'] for r in rows if r.get('genus', '').lower() == 'brassica'
            or r.get('family', '').lower() == 'brassicaceae'
            or r.get('name', '').lower().startswith('brassica ')}


def budgets(records, annotations):
    keys = {(x['dataset_id'], x['record_id']): i for i, x in enumerate(records)}
    eligible = {keys[x['dataset_id'], x['record_id']] for x in annotations
                if x['task'] == 'shape' and x['strict_target'] is not None}
    dev = sorted({r['cultivar_id'] for i, r in enumerate(records)
                  if i in eligible and r['split'] == 'development'})
    validation = {c for c in dev if int(hashlib.sha256(('shape-validation-v1:' + c).encode()).hexdigest()[:8],16) % 5 == 0}
    pool = sorted(set(dev)-validation)
    sizes = [n for n in [8,16,32,64] if n < len(pool)] + [len(pool)]
    schedules = {}
    for seed in SEEDS:
        order = np.random.default_rng(seed).permutation(pool).tolist()
        schedules[str(seed)] = {str(n): [i for i, r in enumerate(records) if i in eligible
                                       and r['split'] == 'development' and r['cultivar_id'] in order[:n]] for n in sizes}
    return dict(sizes=sizes, available_cultivars=len(pool), validation_cultivars=sorted(validation), schedules=schedules)


def prepare(a):
    a.out.mkdir(parents=True,exist_ok=False)
    rows=read_rows(a.regions); inv=json.loads(a.inventory.read_text()); excluded=excluded_taxa(rows)
    allowed=[i for i,r in enumerate(rows) if r['split']=='train' and r['organ']=='leaf' and r['taxon'] not in excluded]
    obs=defaultdict(list)
    for i in allowed: obs[rows[i]['taxon'],rows[i]['observation_id']].append(i)
    obskeys=sorted(obs); taxonobs=defaultdict(list)
    for i,(taxon,_) in enumerate(obskeys):taxonobs[taxon].append(i)
    events=[]
    for e in inv['events']:
        if e['organ']=='leaf' and e['any_of'] and set(e['any_of'])<=set(IDS) and e['taxon'] in taxonobs:
            qualities=' or '.join(inv['traits'][i]['quality_label'] for i in e['any_of'])
            events.append({**e,'raw_prompt':'A photograph of a plant. Its leaves are described as: '+e['text'],
                           'normalized_prompt':'A photograph of a plant. Its leaves are described as: '+qualities+' leaves.',
                           'observations':taxonobs[e['taxon']]})
    if not events:raise ValueError('No eligible source events')
    used=sorted({i for e in events for i in e['observations']}); remap={old:new for new,old in enumerate(used)}
    obskeys=[obskeys[i] for i in used]
    for e in events:e['observations']=[remap[i] for i in e['observations']]
    records=read_rows(a.benchmark/'records.jsonl'); images=read_rows(a.benchmark/'images.jsonl'); annotations=read_rows(a.benchmark/'annotations.jsonl')
    rowids={(r['dataset_id'],r['record_id']):i for i,r in enumerate(records)}
    bag=np.zeros((len(events),max(len(e['observations']) for e in events)),np.int64)
    lengths=np.array([len(e['observations']) for e in events],np.int64)
    for i,e in enumerate(events):bag[i,:lengths[i]]=e['observations']
    source_hashes={str(p):digest(p) for p in [a.regions,a.inventory,a.benchmark/'protocol.json']}
    for encoder in ['fgclip2','bioclip2']:
        path=a.features/encoder/'features.npz'; manifest=json.loads((a.features/encoder/'extraction.json').read_text())
        if digest(path)!=manifest['sha256']['features.npz'] or digest(a.features/encoder/'regions.jsonl')!=digest(a.regions):raise ValueError('Source feature identity mismatch')
        z=np.load(path)['regions'][:,0]; train=unit(np.stack([z[obs[k]].mean(0) for k in obskeys]))
        result=np.zeros((len(records),z.shape[-1]),np.float64); counts=np.zeros(len(records),np.int64); seen=set()
        for shard in sorted(a.benchmark_features.glob('shard-*')):
            pp=shard/encoder/'features.npz'
            if digest(pp)!=json.loads((shard/encoder/'features.json').read_text())['sha256']:raise ValueError('Benchmark feature identity mismatch')
            rr=read_rows(shard/'images.jsonl'); xx=np.load(pp)['whole_image'][:,0]
            for row,x in zip(rr,xx):
                if row['image_file'] in seen:raise ValueError('Repeated benchmark image')
                seen.add(row['image_file']); i=rowids[row['dataset_id'],row['record_id']];result[i]+=x;counts[i]+=1
            source_hashes[str(pp)]=digest(pp)
        if seen!={r['image_file'] for r in images} or counts.tolist()!=[r['n_images'] for r in records]:raise ValueError('Incomplete benchmark feature coverage')
        np.savez_compressed(a.out/(encoder+'.npz'),source=train,benchmark=unit(result/counts[:,None]),bags=bag,lengths=lengths)
        source_hashes[str(path)]=digest(path)
    for name,data in [('events',events),('records',records),('annotations',annotations)]:
        (a.out/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in data))
    source_rows=[rows[i] for key in obskeys for i in obs[key]]
    (a.out/'training-images.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in source_rows))
    proto=dict(version='shape-experiments-v1',analysis_role='Exploratory: pxGPT test results previously inspected; no confirmatory claim.',
        encoders=['fgclip2','bioclip2'],modes=MODES,seeds=SEEDS,shape_indices=IDS,
        shape_labels=[inv['traits'][i]['quality_label'] for i in IDS],
        canonical_prompts=['A photograph of a plant with '+inv['traits'][i]['quality_label']+' leaves.' for i in IDS],
        source_events=len(events),source_taxa=len({e['taxon'] for e in events}),source_observations=len(obskeys),source_regions=len(source_rows),
        excluded_taxa=sorted(excluded),exclusion='All Brassicaceae plus any Brassica genus/name, applied to every source arm before fitting.',
        benchmark_aggregation='Mean whole-image first-tile features across every photo of a set, then unit normalization; shared across arms. Different from previous score averaging.',
        source_aggregation='Mean leaf-region first-tile features per observation; sample four observations from each source event bag.',
        architecture='Rank-64 residual linear image adapter followed by unit normalization; native image/text encoders frozen.',
        source_objective='1 minus cosine of normalized mean adapted bag to raw or normalized sentence embedding, plus mean squared L2 displacement from input. Identical objective for shuffled targets.',
        pretrain_steps=1500,human_steps=400,learning_rate=.001,weight_decay=.01,batch_events=32,observations_per_event=4,anchor_weight=1.,rank=64,
        human_objective='Cross entropy over stage-specific represented shape categories using maximum cosine logit within a grouped category; temperature 10; anchor to original image features.',
        evaluation='Equal-dataset average supported-category AP, >=5 positives and negatives; strict test references. Three-seed probability ensembles, paired cultivar bootstrap. All budgets and arms reported.',
        budget_plan=budgets(records,annotations),calibration='No hyperparameter or threshold fitting; held-out development cultivars retained for diagnostic validation only.',
        shuffle='Seed-specific event-target permutation; bag identity, source records, images, loss and step schedule unchanged.',
        attribution='Tests the FLOPO text normalization pipeline against original selected source phrases. Shared event eligibility already uses the normalized inventory; not an end-to-end raw-flora extraction comparison.',
        training_reference_policy='Only development records selected in budget_plan are exposed to supervised fitting; test labels remain local to scorer.',
        source_hashes=source_hashes,source_code_sha256=digest(__file__))
    training=[]
    for r in annotations:
        if records[rowids[r['dataset_id'],r['record_id']]]['split']=='development' and r['task']=='shape' and r['strict_target'] is not None:
            training.append(dict(row_index=rowids[r['dataset_id'],r['record_id']],dataset_id=r['dataset_id'],target=r['strict_target']))
    (a.out/'training-labels.json').write_text(json.dumps(training,indent=2)+'\n')
    proto['sha256']={p.name:digest(p) for p in a.out.iterdir() if p.is_file()}
    (a.out/'protocol.json').write_text(json.dumps(proto,indent=2)+'\n')
    print(json.dumps({k:proto[k] for k in ['source_events','source_taxa','source_observations','source_regions','excluded_taxa']}));print('Budgets',proto['budget_plan']['sizes'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['regions','inventory','features','benchmark-features','benchmark','out']:p.add_argument('--'+n,type=Path,required=True)
    prepare(p.parse_args())

if __name__=='__main__':main()
