"""Image-level trait audit. Never use taxon predictions or flora labels as targets.

The current reference annotations are a single AI visual review, not expert gold.
The evaluator preserves ambiguous and unassessable labels and exports every score.
"""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path

import numpy as np
import torch
from .extract import digest


def wilson(correct,total):
    if not total:return None
    z=1.959963984540054;p=correct/total;d=1+z*z/total
    c=(p+z*z/(2*total))/d;h=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d
    return [max(0,c-h),min(1,c+h)]


def binary_metrics(target,probabilities,threshold=.5):
    pairs=[(int(t),float(p)) for t,p in zip(target,probabilities) if t is not None]
    n=len(pairs);pos=sum(t for t,p in pairs);neg=n-pos
    tp=sum(t==1 and p>=threshold for t,p in pairs);fp=sum(t==0 and p>=threshold for t,p in pairs)
    fn=pos-tp;tn=neg-fp
    result=dict(n=n,positive_support=pos,negative_support=neg,tp=tp,fp=fp,fn=fn,tn=tn,
                positive_detection_rate=tp/pos if pos else None,specificity=tn/neg if neg else None)
    # One-class references cannot establish discrimination or justify a perfect F1.
    if pos and neg:
        result.update(precision=tp/(tp+fp) if tp+fp else 0.,recall=tp/pos,
                      f1=2*tp/(2*tp+fp+fn),balanced_accuracy=(tp/pos+tn/neg)/2,
                      brier=float(np.mean([(p-t)**2 for t,p in pairs])),
                      auroc=sum((p1>p0)+.5*(p1==p0) for t1,p1 in pairs if t1 for t0,p0 in pairs if not t0)/(pos*neg))
    else:result.update(precision=None,recall=None,f1=None,balanced_accuracy=None,brier=None,auroc=None,
                       limitation='Both positive and negative assessable examples are needed for discrimination metrics.')
    return result


def partial_target(possible,query):
    """Truth in the finite categorical model: ambiguity never becomes a negative."""
    possible,query=set(possible),set(query)
    if not possible:return None
    if possible<=query:return 1
    if not possible&query:return 0
    return None


def score(annotations,probabilities,vocab,phenotypes):
    names=[v['name'] for v in vocab['outline']['colours']]
    pn=probabilities['leaf.outline'];top=pn.argmax(1);assessed=[];strict=[];rows=[]
    queries={n:next((v for v in phenotypes.values() if v['label']=='leaf '+n),None) for n in names if n!='unknown'}
    possible=[]
    for i,a in enumerate(annotations):
        allowed=a['outline_allowed'];valid=bool(allowed)
        states=set()
        for n in allowed:
            q=queries[n]
            if q is None:raise ValueError('No compiled FLOPO query for '+n)
            states.update(j for j,w in enumerate(q['mask'][:len(names)]) if w)
        possible.append(states)
        hit=names[int(top[i])] in allowed if valid else None
        if valid:assessed.append(i)
        if len(allowed)==1:strict.append(i)
        rows.append({'audit_id':a['audit_id'],'allowed':allowed,'assessable':valid,
                     'prediction':names[int(top[i])],'probability':float(pn[i,top[i]]),
                     'literal_match':hit,'ontology_compatible':int(top[i]) in states if valid else None,
                     'notes':a['notes'],'probabilities':{n:float(pn[i,j]) for j,n in enumerate(names)}})
    correct=sum(rows[i]['literal_match'] for i in assessed);sc=sum(rows[i]['literal_match'] for i in strict)
    classes={}
    for n in names:
        support=sum(annotations[i]['outline_allowed']==[n] for i in strict)
        tp=sum(annotations[i]['outline_allowed']==[n] and names[int(top[i])]==n for i in strict)
        fp=sum(annotations[i]['outline_allowed']!=[n] and names[int(top[i])]==n for i in strict)
        fn=support-tp
        if support or fp:classes[n]=dict(support=support,tp=tp,fp=fp,fn=fn,
            precision=tp/(tp+fp) if tp+fp else 0.,recall=tp/support if support else None,
            f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.)
    macro=[v['f1'] for v in classes.values() if v['support']]
    ontology={}
    for iri,q in phenotypes.items():
        if q['label'] not in {'leaf '+n for n in queries}:continue
        states={i for i,w in enumerate(q['mask'][:len(names)]) if w}
        ontology[iri]={'label':q['label'],**binary_metrics([partial_target(x,states) for x in possible],pn[:,list(states)].sum(1))}
    hnames=[x['name'] for x in vocab['hairiness']['colours']]
    hair_query=next(q for q in phenotypes.values() if q['label']=='leaf hairy')
    hstates=[i for i,w in enumerate(hair_query['mask'][:len(hnames)]) if w]
    hp=probabilities['leaf.hairiness'][:,hstates].sum(1)
    for i,r in enumerate(rows):
        r['hair_present_reference']=annotations[i]['hair_present'];r['hair_present_probability']=float(hp[i])
    unassessed=[i for i in range(len(annotations)) if i not in assessed]
    report={'images':len(annotations),'outline':{'assessable':len(assessed),'coverage':len(assessed)/len(annotations),
        'set_compatible_correct':correct,'set_compatible_accuracy':correct/len(assessed) if assessed else None,
        'set_compatible_wilson95':wilson(correct,len(assessed)),
        'strict_single_label_n':len(strict),'strict_correct':sc,'strict_accuracy':sc/len(strict) if strict else None,
        'strict_macro_f1_present_classes':sum(macro)/len(macro) if macro else None,'per_class':classes,
        'ontology_compatible_correct':sum(rows[i]['ontology_compatible'] for i in assessed),
        'unassessable_images_with_max_probability_at_least_half':sum(float(pn[i].max())>=.5 for i in unassessed)},
        'hairiness':binary_metrics([a['hair_present'] for a in annotations],hp),
        'flopo_class_metrics':ontology,
        'metric_scope':'Literal category scores are primary. FLOPO query scores project the finite categorical states through existing compiled ontology masks; their negatives assume this scoped categorical model, not a complete open-world annotation of every phenotype.'}
    return report,rows


def evaluate(audit,run,field,external,phenotype_path):
    from .multi import MultiHead
    from .latent_train import concepts
    torch.set_num_threads(2)
    freeze=json.loads((audit/'annotation-freeze.json').read_text())
    for name,sha in freeze['sha256'].items():
        if digest(audit/name)!=sha:raise ValueError('Annotations changed after freezing: '+name)
    p=torch.load(run/'prepared.pt',weights_only=False,map_location='cpu')
    schema=p['schema'];specs=p['specs'];models={'pretrained':[]}
    base=MultiHead(schema);base.load_state_dict(p['initial_state']);base.eval();models['pretrained']=[base]
    checkpoint_hashes={}
    for name in ('flat_weak','wmc','wmc_bears'):
        models[name]=[]
        for seed in (20261025,20261026,20261027):
            path=run/f'{name}-{seed}.pt';checkpoint_hashes[path.name]=digest(path)
            cp=torch.load(path,weights_only=False,map_location='cpu');m=MultiHead(schema);m.load_state_dict(cp['state_dict']);m.eval();models[name].append(m)
    join=json.loads((audit/'private-join.json').read_text());fa=json.loads((audit/'field-annotations.json').read_text())
    field_lookup={r['observation_id']:i for i,r in enumerate(p['rows'])}
    assert [r['audit_id'] for r in join]==[r['audit_id'] for r in fa]
    indices=[field_lookup[r['observation_id']] for r in join]
    assert all(p['rows'][i]['split']=='test' for i in indices)
    for r,i in zip(join,indices):
        if r['image_sha256']!=p['rows'][i]['sha256'] or r['box']!=p['rows'][i]['box']:raise ValueError('Audit/feature crop mismatch')
        if digest(audit/'crops'/f"{r['audit_id']}.png")!=r['crop_sha256']:raise ValueError('Changed audit crop')
    sets={'field':(fa,p['features'][indices])}
    ej=json.loads((audit/'external-join.json').read_text());ea=json.loads((audit/'external-annotations.json').read_text())
    erows=json.loads((external/'manifest.json').read_text());lookup={r['id']:i for i,r in enumerate(erows)}
    ids=[lookup[r['specimen_id']] for r in ej]
    assert [r['audit_id'] for r in ej]==[r['audit_id'] for r in ea]
    assert all(erows[i]['split']=='test' for i in ids)
    extraction=json.loads((external/'extraction.json').read_text())
    if digest(external/'features.npz')!=extraction['features_sha256']:raise ValueError('Changed external features')
    if digest(external/'manifest.json')!=extraction['manifest_sha256']:raise ValueError('Changed external manifest')
    if extraction['encoder']['revision']!=p['provenance']['encoder']['revision']:raise ValueError('Encoder mismatch')
    train_names={r['name'].casefold() for r in p['rows'] if r['split']=='train'}
    external_names={erows[i]['species'].casefold() for i in ids}
    if train_names&external_names:raise ValueError('External species overlap training')
    ext=np.load(external/'features.npz')
    for view in ('original','masked'):sets['external_'+view]=(ea,torch.tensor(ext[view][ids],dtype=torch.float32))
    phen=json.loads(phenotype_path.read_text())['supported']
    report={'annotation_quality':'provisional single-AI visual audit; not expert ground truth',
            'protocol':json.loads((audit/'audit-protocol.json').read_text()),'annotation_freeze':freeze,
            'checkpoint_sha256':checkpoint_hashes,'phenotype_queries_sha256':digest(phenotype_path),
            'external_training_species_overlap':[],'external_species_count':len(external_names),
            'no_fitting':True,'no_species_metrics':True,'results':{}}
    all_rows=[]
    with torch.inference_mode():
        for dataset,(annotations,features) in sets.items():
            report['results'][dataset]={}
            for name,members in models.items():
                probs=[concepts(m,features,specs) for m in members]
                mean={g:torch.stack([q[g] for q in probs]).mean(0).numpy() for g in specs}
                scores,rows=score(annotations,mean,schema['groups'],phen)
                report['results'][dataset][name]=scores
                all_rows.extend(dict(dataset=dataset,model=name,**r) for r in rows)
    (audit/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    (audit/'predictions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in all_rows))
    with (audit/'predictions.csv').open('w') as handle:
        fields=['dataset','model','audit_id','assessable','allowed','prediction','probability','literal_match','hair_present_reference','hair_present_probability','notes']
        writer=csv.DictWriter(handle,fields,extrasaction='ignore');writer.writeheader();writer.writerows(all_rows)
    summary={dataset:{model:{'shape':f"{v['outline']['set_compatible_correct']}/{v['outline']['assessable']}",
                            'strict_shape':f"{v['outline']['strict_correct']}/{v['outline']['strict_single_label_n']}",
                            'hair_positive_detected':v['hairiness']['tp'],'hair_positive_support':v['hairiness']['positive_support'],
                            'hair_negative_support':v['hairiness']['negative_support']}
                      for model,v in models.items()} for dataset,models in report['results'].items()}
    print(json.dumps(summary,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,required=True);parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--field',type=Path,required=True);parser.add_argument('--external',type=Path,required=True)
    parser.add_argument('--phenotypes',type=Path,required=True)
    a=parser.parse_args();evaluate(a.audit,a.run,a.field,a.external,a.phenotypes)

if __name__=='__main__':main()
