"""Predict explicit organ traits, then rank species using only those trait distributions.

Use cached region features, or --image with the pinned models inside a GPU allocation.
No observed taxon, name, observer or location is an inference input.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import torch

from .extract import digest
from .model import rank_profiles
from .multi import MultiHead, distributions


def predict(bundle,features,regions,phenotypes=None):
    schema=bundle['schema'];model=MultiHead(schema,feature_dim=bundle['feature_dim'])
    model.load_state_dict(bundle['state_dict']);model.eval()
    selected={}
    for i,r in enumerate(regions):
        b=r['box'];organ=r['organ']
        if organ not in ('leaf','petal','fruit') or r['score']<.3 or min(b[2]-b[0],b[3]-b[1])<32:continue
        if organ not in selected or r['score']>regions[selected[organ]]['score']:selected[organ]=i
    evidence={};traits=[];phenotype_scores={}
    if selected:
        indices=list(selected.values());fs=torch.tensor(features[indices],dtype=torch.float32)
        with torch.no_grad():prediction={g:p.numpy() for g,p in model(fs).items()}
        for j,i in enumerate(indices):
            r=regions[i];values=distributions(prediction,{'organ':r['organ'],'box':r['box']},schema,j)
            evidence.update({g:d for g,d in values.items() if g in bundle['reference']})
            for group,d in values.items():
                name=group.split('.',1)[1];v=schema['groups'][name]
                top=sorted(d,key=d.get,reverse=True)[:3]
                traits.append({'organ':r['organ'],'attribute':name,'box':r['box'],
                    'states':[{'name':v['colours'][int(k)]['name'],'iri':v['colours'][int(k)]['iri'],'probability':d[k]} for k in top],
                    'status':'uncalibrated_model_prediction'})
            for iri,query in (phenotypes or {}).get('supported',{}).items():
                v=schema['groups'][query['attribute']]
                if r['organ'] not in v['organs_in_scope']:continue
                if f"{r['organ']}.{query['attribute']}" not in values:continue
                oi=[o['name'] for o in v['organs']].index(r['organ']);n=len(v['colours'])
                # Keep the witness on its proposed organ and preserve neural organ uncertainty.
                mask=np.zeros(len(v['organs'])*n);mask[oi*n:(oi+1)*n]=query['mask'][oi*n:(oi+1)*n]
                support=float(prediction[query['attribute']][j]@mask)
                if support>phenotype_scores.get(iri,{}).get('best_region_support',0):
                    phenotype_scores[iri]={'iri':iri,'label':query['label'],'best_region_support':support,'box':r['box']}
    ranking=rank_profiles(evidence,bundle['catalogue'],bundle['reference'])
    for row in ranking['ranking']:row['name']=bundle['taxon_names'][row['taxon']]
    return {'traits':traits,'evidence':evidence,'species':ranking,'model_status':bundle['status'],
            'flopo_phenotypes':sorted(phenotype_scores.values(),key=lambda r:-r['best_region_support']),
            'phenotype_interpretation':'Best single-region support, not an independence-based probability across photographs.',
            'note':'Experimental evidence ranking. Unknown/missing traits do not establish biological absence.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--extraction',type=Path)
    parser.add_argument('--photo-id',type=int)
    parser.add_argument('--image',type=Path)
    parser.add_argument('--models',type=Path)
    parser.add_argument('--phenotypes',type=Path,help='Pinned phenotype-queries.json for this model schema')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();torch.set_num_threads(4)
    bundle=torch.load(args.checkpoint,map_location='cpu',weights_only=True)
    phenotypes=json.loads(args.phenotypes.read_text()) if args.phenotypes else None
    if phenotypes:
        import hashlib
        schema_hash=hashlib.sha256((json.dumps(bundle['schema'],indent=2)+'\n').encode()).hexdigest()
        if schema_hash!=phenotypes['schema_sha256']:raise ValueError('Phenotype catalogue and model schema differ')
    with tempfile.TemporaryDirectory(prefix='flopo-predict-') as temporary:
        if args.image:
            if not args.models:parser.error('--image requires --models and a GPU for feature extraction')
            data=Path(temporary);photo=1;path=args.image.resolve()
            (data/'images.jsonl').write_text(json.dumps({'photo_id':photo,'image_path':str(path),'sha256':digest(path)})+'\n')
            extraction=data/'extraction'
            subprocess.run([sys.executable,'-m','flopo2.vision.extract','--data',str(data),'--models',str(args.models),'--out',str(extraction)],check=True)
        else:
            if args.extraction is None or args.photo_id is None:parser.error('Provide --image or both --extraction and --photo-id')
            extraction,photo=args.extraction,args.photo_id
        record=next(r for r in map(json.loads,(extraction/'regions.jsonl').read_text().splitlines()) if r['photo_id']==photo)
        features=np.load(extraction/'features'/f'{photo}.npz')['region_features']
        result=predict(bundle,features,record['regions'],phenotypes)
        result['checkpoint_sha256']=digest(args.checkpoint)
        args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'traits':len(result['traits']),'abstain':result['species']['abstain'],'out':str(args.out)}))


if __name__=='__main__':main()
