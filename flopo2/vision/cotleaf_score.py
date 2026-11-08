"""Descriptive external hairiness scoring with duplicate and provenance audits."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import numpy as np
from .benchmark import average_precision
from .benchmark_overlap import signatures,segments
from .extract import digest
from .shape_experiments import read_rows

MODES=['baseline','flora','teacher','combined','flopo','shuffled_rules','shuffled_profiles']
SEEDS=[20261027,20261028,20261029]


def audit(a):
    rows=read_rows(a.data/'records.jsonl');train=[r for r in read_rows(a.training) if r['split']=='train']
    if not rows or not train:raise ValueError('Nonempty benchmark and final training split are required')
    buckets=defaultdict(set);byhash=defaultdict(set)
    for i,r in enumerate(train):
        byhash[r['sha256']].add(i)
        for key in segments(int(r['dhash'],16)):buckets[key].add(i)
    matched=[];excluded=set();decoded=defaultdict(list);sigs=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i,sig in enumerate(pool.map(signatures,[a.data/r['image_file'] for r in rows])):
            r=rows[i]
            if sig['sha256']!=r['sha256']:raise ValueError('Changed decoded image')
            h=int(sig['dhash'],16);candidates=set(byhash[sig['sha256']])|set(byhash[r['source_sha256']])
            for k in segments(h):candidates.update(buckets[k])
            for j in candidates:
                other=train[j];distance=(h^int(other['dhash'],16)).bit_count()
                if distance<=4 or other['sha256'] in [sig['sha256'],r['source_sha256']]:
                    excluded.add(i);matched.append(dict(image_id=r['image_id'],training_photo_id=other['photo_id'],dhash_distance=distance))
            decoded[sig['decoded_rgb_sha256']].append(i);sigs.append(dict(image_id=r['image_id'],**sig))
    duplicates=[v for v in decoded.values() if len(v)>1]
    for ids in duplicates:excluded.update(ids)
    images=[{k:r[k] for k in ['image_id','image_file','sha256','width','height']} for r in rows]
    (a.data/'images.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in images))
    report=dict(records_sha256=digest(a.data/'records.jsonl'),images_sha256=digest(a.data/'images.jsonl'),
       training_manifest_sha256=digest(a.training),training_images=len(train),training_gossypium_photos=sum(r.get('genus')=='Gossypium' for r in train),
       matched_training=matched,within_benchmark_identical_pixels=duplicates,excluded_indices=sorted(excluded),
       source_sha256=digest(__file__),policy='Exclude <=4-bit training dHash candidates and all members of identical decoded benchmark image groups before scoring. Unknown foundation-model pretraining overlap.')
    (a.data/'overlap.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


def metrics(rows,q):
    per_pop={};per_genotype={}
    for group,field,output in [(sorted({r['population'] for r in rows}),'population',per_pop),(sorted({r['genotype'] for r in rows}),'genotype',per_genotype)]:
        for key in group:
            ids=[i for i,r in enumerate(rows) if r[field]==key and r['target'] is not None];y=np.array([rows[i]['target'] for i in ids])
            output[key]=dict(AP=average_precision(y,q[ids,32]),positive=int(y.sum()),negative=int((1-y).sum()),images=len(ids),prevalence=float(y.mean()) if len(y) else None)
    eligible=[v['AP'] for v in per_pop.values() if min(v['positive'],v['negative'])>=5]
    return dict(high_hairiness_macro_AP=float(np.mean(eligible)) if eligible else None,populations=per_pop,genotypes=per_genotype)


def score(a):
    rows=read_rows(a.data/'records.jsonl');audit=json.loads((a.data/'overlap.json').read_text())
    if digest(a.data/'records.jsonl')!=audit['records_sha256']:raise ValueError('Changed references')
    keep=np.array([i not in audit['excluded_indices'] for i in range(len(rows))]);kept=[r for r,k in zip(rows,keep) if k]
    expected={'primary-baseline-0'}|{f'primary-{m}-{seed}' for m in MODES if m!='baseline' for seed in SEEDS}
    result={};manifests={}
    for encoder in ['fgclip2','bioclip2']:
        folder=a.runs/encoder;meta=json.loads((folder/'complete.json').read_text());manifests[encoder]=digest(folder/'complete.json')
        if meta['identity']['images_sha256']!=audit['images_sha256'] or meta['images']!=len(rows) or set(meta['checkpoints'])!=expected:raise ValueError('Wrong inference cohort/model grid')
        for f,h in meta['sha256'].items():
            if digest(folder/f)!=h:raise ValueError('Changed prediction provenance')
        for name,h in meta['checkpoints'].items():
            prior=json.loads((a.original_runs/encoder/name/'complete.json').read_text())
            if h!=prior['checkpoint_sha256']:raise ValueError('Not the original checkpoint')
        arrays=np.load(folder/'predictions.npz')
        if set(arrays.files)!=expected:raise ValueError('Incomplete predictions')
        output={}
        for name in arrays.files:
            if arrays[name].shape!=(len(rows),36) or not np.isfinite(arrays[name]).all():raise ValueError('Invalid predictions')
            output[name]=metrics(kept,arrays[name][keep])
        for mode in MODES:
            if mode!='baseline':output['ensemble-'+mode]=metrics(kept,np.mean([arrays[f'primary-{mode}-{seed}'][keep] for seed in SEEDS],axis=0))
        result[encoder]=output
    a.out.mkdir(parents=True,exist_ok=False)
    report=dict(protocol_sha256=digest(a.data/'protocol.json'),overlap_sha256=digest(a.data/'overlap.json'),source_sha256=digest(__file__),inference_manifests=manifests,
        images_selected=len(rows),images_after_overlap_audit=len(kept),population_scales_kept_separate=True,
        uncertainty='Descriptive only: released plant IDs collapse to four groups; no image-IID confidence interval and no confirmation of shape benefit.',results=result)
    (a.out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    for encoder,out in result.items():print(encoder,{m:out['primary-baseline-0' if m=='baseline' else 'ensemble-'+m]['high_hairiness_macro_AP'] for m in MODES},flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['audit','score'])
    for n in ['data','training','runs','original-runs','out']:p.add_argument('--'+n,type=Path)
    a=p.parse_args();(audit if a.command=='audit' else score)(a)

if __name__=='__main__':main()
