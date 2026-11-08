"""Fixed full-cohort models on the previously inspected AI shape audit.

Development evidence only. All declared checkpoints and seed ensembles are
reported; this script cannot train, select checkpoints or change model settings.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from .extract import digest
from .modern import load_encoder, load_images, average_precision
from .full_train import region_features, enable_last_blocks
from .trait_heads import make_head
from .trait_eval import binary_metrics
from .modern_weak import CONTEXT_QUALITIES


def shape_metrics(annotations, probabilities, traits):
    names=[t['quality_label'] for t in traits]
    top=probabilities.argmax(-1);assessed=[i for i,a in enumerate(annotations) if a['outline_allowed']]
    correct=sum(names[top[i]] in annotations[i]['outline_allowed'] for i in assessed)
    metrics={}
    for k,name in enumerate(names):
        truth=[int(a['outline_allowed'][0]==name) if len(a['outline_allowed'])==1 else None for a in annotations]
        metrics[name]={**binary_metrics(truth,probabilities[:,k]),'average_precision':average_precision(truth,probabilities[:,k])}
    aps=[r['average_precision'] for r in metrics.values() if r['average_precision'] is not None]
    return {'assessable':len(assessed),'correct':correct,'accuracy':correct/len(assessed) if assessed else None,
        'macro_AP':float(np.mean(aps)) if aps else None,'per_literal_shape':metrics}


def expected_runs():
    seeds=range(20261026,20261029)
    return ['pretrained']+[f'{mode}-200-{s}' for mode in ['direct','mil','hierarchy','projected','shuffled'] for s in seeds]+\
        [f'frozen-{n}-{s}' for n in [10,50,200] for s in seeds]+[f'mil-{n}-{s}' for n in [10,50] for s in seeds]


def paired_control_metrics(original, erased, traits, rows):
    results={}
    for t in traits:
        ids=[i for i,r in enumerate(rows) if r['organ']==t['organ']]
        if not ids or t['quality_label'] in CONTEXT_QUALITIES:continue
        a=original[ids,t['index']];b=erased[ids,t['index']]
        results[t['label']]={'images':len(ids),'mean_original':float(a.mean()),'mean_erased':float(b.mean()),
            'mean_paired_change':float((a-b).mean()),'fraction_lower_after_erasure':float((a>b).mean())}
    return results


def evaluate(args):
    from PIL import Image,ImageOps,ImageDraw
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Use Orix Slurm GPU allocation')
    torch.set_num_threads(4);started=time.monotonic()
    freeze=json.loads((args.audit/'annotation-freeze.json').read_text())
    for f,h in freeze['sha256'].items():
        if digest(args.audit/f)!=h:raise ValueError('Changed audit reference')
    screen=json.loads((args.screen/'extraction.json').read_text())
    for f,k in [('features.npz','features_sha256'),('rows.json','rows_sha256'),('external-rows.json','external_rows_sha256')]:
        if digest(args.screen/f)!=screen[k]:raise ValueError('Changed screen input')
    ext=json.loads((args.features/'extraction.json').read_text())
    for f,k in [('features.npz','features_sha256'),('regions.jsonl','regions_sha256'),('inventory.json','inventory_sha256')]:
        if digest(args.features/f)!=ext[k]:raise ValueError('Changed full-cohort features')
    if ext['model_spec']!=screen['model_spec']:raise ValueError('Screen and full encoder differ')
    inv=json.loads((args.features/'inventory.json').read_text())
    full_rows=[json.loads(s) for s in (args.features/'regions.jsonl').read_text().splitlines()]
    train=[r for r in full_rows if r['split']=='train']
    train_taxa={r['taxon'] for r in train};train_genera={r['genus'] for r in train};train_hashes={r['sha256'] for r in train}
    train_names={r['name'].casefold() for r in train}
    images,field,external=load_images(args.small,args.external)
    if field!=json.loads((args.screen/'rows.json').read_text()) or external!=json.loads((args.screen/'external-rows.json').read_text()):raise ValueError('Screen image rows changed')
    fa=json.loads((args.audit/'field-annotations.json').read_text());ea=json.loads((args.audit/'external-annotations.json').read_text())
    fj=json.loads((args.audit/'private-join.json').read_text());ej=json.loads((args.audit/'external-join.json').read_text())
    fi_lookup={r['observation_id']:i for i,r in enumerate(field)};ei_lookup={r['id']:i for i,r in enumerate(external)}
    fi=[fi_lookup[r['observation_id']] for r in fj];ei=[ei_lookup[r['specimen_id']] for r in ej]
    if len(fa)!=len(fi) or len(ea)!=len(ei):raise ValueError('Audit size mismatch')
    for a,j,i in zip(fa,fj,fi):
        if a['audit_id']!=j['audit_id'] or field[i]['sha256']!=j['image_sha256'] or field[i]['box']!=j['box']:raise ValueError('Field image join mismatch')
    for a,j,i in zip(ea,ej,ei):
        if a['audit_id']!=j['audit_id'] or external[i]['sha256']!=j['image_sha256']:raise ValueError('External image join mismatch')
    if train_taxa&{field[i]['taxon'] for i in fi} or train_genera&{field[i]['genus'] for i in fi}:raise ValueError('Field training taxon/genus overlap')
    if train_hashes&({field[i]['sha256'] for i in fi}|{external[i]['sha256'] for i in ei}):raise ValueError('Audit/training exact image overlap')
    indices={'field':fi,'external_original':ei,'external_masked':ei}
    refs={'field':fa,'external_original':ea,'external_masked':ea}
    selected={name:[images[name][i] for i in ids] for name,ids in indices.items()}
    control_rows=sorted([r for r in full_rows if r['split']!='train'],key=lambda r:hashlib.sha256(str(r['photo_id']).encode()).hexdigest())[:200]
    original_images=[];erased_images=[]
    for r in control_rows:
        p=args.data/r['image_path']
        if digest(p)!=r['sha256']:raise ValueError('Changed control image')
        with Image.open(p) as im:original=ImageOps.exif_transpose(im).convert('RGB')
        erased=original.copy();ImageDraw.Draw(erased).rectangle(r['box'],fill=(127,127,127))
        original_images.append(original);erased_images.append(erased)
    arrays=np.load(args.screen/'features.npz');text=torch.tensor(np.load(args.features/'features.npz')['text'],device='cuda',dtype=torch.float32)
    schema=json.loads((args.screen/'schema.json').read_text());names={v['name'] for v in schema['groups']['outline']['colours']}-{'unknown'}
    traits=[t for t in inv['traits'] if t['organ']=='leaf' and t['quality_label'] in names];trait_ids=[t['index'] for t in traits]
    model,processor,_,spec=load_encoder(args.models,ext['model']);model.vision_model.use_head=False
    adapted_keys=set(enable_last_blocks(model));model.eval()
    args.out.mkdir(parents=True,exist_ok=False)
    raw={};results={};groups=defaultdict(list);manifests={};control_raw={};control_results={};control_cache=None
    unseen=[j for j,i in enumerate(ei) if external[i]['species'].split()[0] not in train_genera]
    with torch.inference_mode():
        for name in expected_runs():
            directory=args.runs/name;report=json.loads((directory/'training.json').read_text())
            if digest(directory/'model.pt')!=report['checkpoint_sha256'] or digest(args.features/'extraction.json')!=report['extraction_sha256']:raise ValueError('Checkpoint/feature mismatch')
            cp=torch.load(directory/'model.pt',map_location='cpu',weights_only=False)
            if cp['traits']!=inv['traits'] or cp['model_spec']!=spec:raise ValueError('Checkpoint schema/backbone mismatch')
            head=make_head(text,'centered');head.load_state_dict(cp['head']);head.eval()
            if cp['adapted']:
                if set(cp['adapted'])!=adapted_keys:raise ValueError('Incomplete adapted state')
                model.load_state_dict(cp['adapted'],strict=False)
            raw[name]={};results[name]={}
            for dataset,imgs in selected.items():
                if cp['adapted']:
                    z=torch.cat([region_features(model,processor,imgs[i:i+8]) for i in range(0,len(imgs),8)])
                else:z=torch.tensor(arrays[dataset+'_region'][indices[dataset]],device='cuda',dtype=torch.float32)
                probabilities=head(z).sigmoid().cpu().numpy()[:,trait_ids]
                if not np.isfinite(probabilities).all():raise ValueError('Nonfinite predictions')
                raw[name][dataset]=probabilities;results[name][dataset]=shape_metrics(refs[dataset],probabilities,traits)
            raw[name]['external_unseen_genera']=raw[name]['external_original'][unseen]
            results[name]['external_unseen_genera']=shape_metrics([ea[j] for j in unseen],raw[name]['external_unseen_genera'],traits)
            cfg=cp['config'];group='pretrained' if cfg['mode']=='pretrained' else f"{cfg['mode']}-{cfg['observations']}"
            if cp['adapted'] or control_cache is None:
                control_z=[torch.cat([region_features(model,processor,imgs[i:i+8]) for i in range(0,len(imgs),8)]) for imgs in [original_images,erased_images]]
                if not cp['adapted']:control_cache=control_z
            else:control_z=control_cache
            a,b=[head(z).sigmoid().cpu().numpy() for z in control_z]
            control_raw[name+'__original']=a;control_raw[name+'__erased']=b
            control_results[name]=paired_control_metrics(a,b,inv['traits'],control_rows)
            groups[group].append(name);manifests[name]={'training_sha256':digest(directory/'training.json'),'checkpoint_sha256':report['checkpoint_sha256']}
            print(name,{d:(r['correct'],r['assessable'],r['macro_AP']) for d,r in results[name].items()},flush=True)
    refs['external_unseen_genera']=[ea[j] for j in unseen]
    ensembles={}
    for group,members in groups.items():
        if group!='pretrained' and len(members)!=3:raise ValueError('Incomplete seed group')
        ensembles[group]={}
        for dataset,annotations in refs.items():
            q=np.stack([raw[m][dataset] for m in members]).mean(0)
            ensembles[group][dataset]=shape_metrics(annotations,q,traits)
            ensembles[group][dataset]['individual_seed_macro_AP']=[results[m][dataset]['macro_AP'] for m in members]
    np.savez_compressed(args.out/'probabilities.npz',**{name+'__'+dataset:q for name,ds in raw.items() for dataset,q in ds.items()})
    np.savez_compressed(args.out/'paired-controls.npz',**control_raw)
    output={'reference_quality':'Previously inspected single-AI shape audit; development evidence, not expert gold or independent final test.',
        'selection':'None; every fixed model and ordinary three-seed probability ensemble reported. No fitting or threshold tuning.',
        'results':results,'ensembles':ensembles,'shape_traits':traits,'annotation_freeze':freeze,'models':manifests,
        'external_name_overlap':sorted(train_names&{external[i]['species'].casefold() for i in ei}),
        'external_genus_overlap':sorted(train_genera&{external[i]['species'].split()[0] for i in ei}),
        'name_overlap_limitation':'Exact names, not a synonym-normalized crosswalk.',
        'external_unseen_genus_indices':unseen,'field_training_genus_overlap':[],
        'paired_controls':control_results,
        'paired_control_rows':[{k:r[k] for k in ['photo_id','organ','box','split']} for r in control_rows],
        'paired_control_scope':'Same whole-image view before/after erasing the detected box; not a verified organ segmentation. Score changes are dependence diagnostics, not accuracy. Training-run crop-versus-erased-whole-image controls are view-confounded and are not used as a causal comparison.',
        'paired_controls_sha256':digest(args.out/'paired-controls.npz'),
        'probabilities_sha256':digest(args.out/'probabilities.npz'),'source_sha256':digest(__file__),
        'slurm_job_id':os.environ['SLURM_JOB_ID'],'seconds':time.monotonic()-started,
        'limitations':['Literal outline diagnostics do not validate all 36 trait outputs.','Hair references have no reliable negative class.',
                        'Field singleton shape labels are strongly imbalanced.','Only traits with both positive and negative reference examples enter macro AP.']}
    (args.out/'diagnostic.json').write_text(json.dumps(output,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['runs','features','models','small','external','screen','audit','out','data']:p.add_argument('--'+name,type=Path,required=True)
    evaluate(p.parse_args())


if __name__=='__main__':main()
