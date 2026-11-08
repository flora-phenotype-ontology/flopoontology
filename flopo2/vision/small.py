"""Build the bounded leaf experiment before fitting or looking at model predictions."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
from pathlib import Path
import shutil

from .extract import digest
from .logic import probability
from .multi import compile_profiles, ranking_profiles
from .pilot import API, ALLOWED_LICENSES, observation_rows, download, read_jsonl, write_jsonl
from .latent_train import profile_formula

NAMES = ('Arnoglossum plantagineum', 'Abutilon grandifolium', 'Pistia stratiotes',
         'Allium canadense', 'Ziziphus nummularia')
UNSEEN = 'Ziziphus nummularia'
GROUPS = ('leaf.outline', 'leaf.hairiness')


def freeze(source, out):
    profiles = json.loads((source/'profiles.json').read_text())
    selected = [next(p for p in profiles if p['name']==n) for n in NAMES]
    schema = json.loads((source/'multi-vocabulary.json').read_text())
    queries = json.loads((source/'queries.json').read_text())
    compiled, _ = compile_profiles(selected, queries, schema, allow_partial=True)
    ranked = ranking_profiles(compiled,schema)
    catalogue = {p['taxon']:{g:ranked[p['taxon']][g] for g in GROUPS} for p in selected}
    for taxon, gs in catalogue.items():
        for g,v in gs.items():
            n = len(schema['groups'][g.split('.')[1]]['colours'])
            if not v['allowed'] or len(v['allowed']) >= n-1:
                raise ValueError('Missing or non-diagnostic profile group')
    overlaps = []
    for a,b in itertools.combinations(catalogue,2):
        if all(set(catalogue[a][g]['allowed']) & set(catalogue[b][g]['allowed']) for g in GROUPS):
            overlaps.append((a,b))
    if overlaps:
        raise ValueError(f'Overlapping species profiles: {overlaps}')
    # Check every true-profile-compatible world, not just one invented exact trait label.
    worlds = 0
    for taxon,gs in catalogue.items():
        for values in itertools.product(*(gs[g]['allowed'] for g in GROUPS)):
            ps={g:[float(i==int(v)) for i in range(len(schema['groups'][g.split('.')[1]]['colours']))]
                for g,v in zip(GROUPS,values)}
            accepted=[t for t in catalogue if probability(profile_formula(catalogue[t],GROUPS),ps)==1]
            if accepted != [taxon]:raise ValueError('Ideal-trait oracle is ambiguous')
            worlds+=1
    out.mkdir(parents=True,exist_ok=False)
    (out/'profiles.json').write_text(json.dumps(selected,indent=2)+'\n')
    (out/'catalogue.json').write_text(json.dumps(catalogue,indent=2)+'\n')
    for name in ('queries.json','multi-vocabulary.json'):
        shutil.copy2(source/name,out/name)
    protocol={'status':'frozen_before_new_images_and_predictions','names':NAMES,
        'unseen_species':UNSEEN,'groups':GROUPS,'profile_worlds_checked':worlds,
        'pairwise_profile_overlap':0,'ideal_trait_species_accuracy':1.,
        'source_profiles_sha256':digest(source/'profiles.json'),
        'catalogue_sha256':digest(out/'catalogue.json'),
        'schema_sha256':digest(out/'multi-vocabulary.json'),
        'weak_label_warning':'Flora profiles are not individual-image trait labels.',
        'visibility_gate':{'organ':'leaf','minimum_side_pixels':192,'minimum_detector_score':.4},
        'training':'four species; pretrained heads reset, no earlier adapted checkpoints',
        'splits':'observer-disjoint train/validation/test; fifth species only zero_shot_test',
        'test_policy':'Freeze split before training; inspect no test predictions during development.',
        'baselines':['pretrained traits + WMC','flat weak trait predictor + WMC',
                     'taxon-trained WMC','taxon-trained WMC + BEARS','direct image classification (known species only)'],
        'comparison_note':'Categorical flat baseline is an adaptation, not the released numerical PlantTraitNet model.'}
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    print(json.dumps(protocol),flush=True)


def collect(data, previous, per_taxon=45, since='2024-01-01', max_pages=10):
    old=[r for path in previous for r in read_jsonl(path/'images.jsonl')]
    old_obs={r['observation_id'] for r in old};old_users={r['observer_id'] for r in old}
    old_hashes={r['sha256'] for r in old};old_dhashes={int(r['dhash'],16) for r in old}
    api=API(data/'api-cache');rows=[];counts={}
    for p in json.loads((data/'profiles.json').read_text()):
        taken={};users=set()
        for page in range(1,max_pages+1):
            response=api.get('observations',taxon_id=p['inat_id'],quality_grade='research',photos='true',
                photo_license=','.join(sorted(ALLOWED_LICENSES)),captive='false',d1=since,
                per_page=100,page=page,order_by='id',order='desc')
            for r in sorted(response.get('results',[]),key=lambda r:hashlib.sha256(str(r['id']).encode()).hexdigest()):
                user=r.get('user',{}).get('id')
                if r['id'] in old_obs or user is None or user in old_users or user in users:continue
                photos=observation_rows(r,p,3)
                if not photos:continue
                taken[r['id']]=photos;users.add(user)
                if len(taken)>=per_taxon:break
            if len(taken)>=per_taxon or len(response.get('results',[]))<100:break
        rows.extend(r for photos in taken.values() for r in photos)
        counts[p['name']]=len(taken)
        print('Collected metadata',p['name'],len(taken),flush=True)
    unique={r['photo_id']:r for r in rows}
    def fetch(r):
        try:return download(r,data),None
        except Exception as e:return None,dict(photo_id=r['photo_id'],error=str(e))
    downloaded={};errors=[];excluded=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for r,error in pool.map(fetch,unique.values()):
            if error:errors.append(error);continue
            if r['sha256'] in old_hashes or any((int(r['dhash'],16)^h).bit_count()<=3 for h in old_dhashes):
                excluded.append(r['photo_id']);continue
            downloaded[r['photo_id']]=r
    complete=[{**downloaded[r['photo_id']],**r} for r in rows if r['photo_id'] in downloaded]
    write_jsonl(data/'images.jsonl',complete)
    summary={'requested_per_taxon':per_taxon,'maximum_pages':max_pages,'observed_since':since,'metadata_observations':counts,'images':len(downloaded),
        'observations':len({r['observation_id'] for r in complete}),'download_errors':errors,
        'excluded_prior_duplicate_photos':excluded,'excluded_prior_observers':len(old_users),
        'previous_manifest_sha256':{str(p/'images.jsonl'):digest(p/'images.jsonl') for p in previous},
        'licenses':dict(Counter(r['license'] for r in complete))}
    (data/'collection.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)


def components(rows):
    """Join shared observers/observations and exact or near-duplicate photographs."""
    parent=list(range(len(rows)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        a,b=root(a),root(b)
        if a!=b:parent[b]=a
    seen={}
    for i,r in enumerate(rows):
        for key in ('observer_id','observation_id','photo_id','sha256'):
            value=(key,r[key])
            if value in seen:union(i,seen[value])
            seen[value]=i
        for j,s in enumerate(rows[:i]):
            if (int(r['dhash'],16)^int(s['dhash'],16)).bit_count()<=3:union(i,j)
    return [root(i) for i in range(len(rows))]


def partition(data):
    rows=read_jsonl(data/'images.jsonl')
    meta={r['photo_id']:r for r in read_jsonl(data/'extraction/regions.jsonl')}
    proto=json.loads((data/'protocol.json').read_text());gate=proto['visibility_gate']
    selected=[];eligible_obs=set()
    for r in rows:
        rs=meta[r['photo_id']]['regions']
        good=[(i,x) for i,x in enumerate(rs) if x['organ']=='leaf' and x['score']>=gate['minimum_detector_score']
              and min(x['box'][2]-x['box'][0],x['box'][3]-x['box'][1])>=gate['minimum_side_pixels']]
        if not good:continue
        i,x=max(good,key=lambda z:z[1]['score'])
        selected.append({**r,'region_index':i,'box':x['box'],'detector_score':x['score']})
        eligible_obs.add(r['observation_id'])
    # Group all original photographs, including rejected views, to detect shared observers/duplicates.
    roots=components(rows);keymap={r['photo_id']:root for r,root in zip(rows,roots)}
    comp=defaultdict(list)
    for r in selected:comp[keymap[r['photo_id']]].append(r)
    assignment={};counts=Counter()
    for c,rr in sorted(comp.items(),key=lambda x:hashlib.sha256(('small-v1:'+str(min(r['observation_id'] for r in x[1]))).encode()).hexdigest()):
        if any(r['name']==UNSEEN for r in rr):split='zero_shot_test'
        else:
            # Whole connected components stay together; balance by counts without prediction access.
            names={r['name'] for r in rr}
            goals={'train':.6,'validation':.2,'test':.2}
            split=min(goals,key=lambda s:sum(counts[(n,s)]/goals[s] for n in names))
        assignment[c]=split
        for obs in {r['observation_id'] for r in rr}:
            n=next(r['name'] for r in rr if r['observation_id']==obs);counts[(n,split)]+=1
    # Focal crop per observation, selected entirely by detector confidence.
    focal={}
    for r in selected:
        obs=r['observation_id']
        if obs not in focal or r['detector_score']>focal[obs]['detector_score']:focal[obs]=r
    output=[{**r,'split':assignment[keymap[r['photo_id']]]} for r in focal.values()]
    write_jsonl(data/'splits.jsonl',output)
    tally={n:{s:sum(r['name']==n and r['split']==s for r in output)
              for s in ('train','validation','test','zero_shot_test')} for n in NAMES}
    known_ready=all(tally[n]['train']>=8 and tally[n]['validation']>=3 and tally[n]['test']>=3 for n in NAMES if n!=UNSEEN)
    unseen_ready=tally[UNSEEN]['zero_shot_test']>=8
    ready=known_ready and unseen_ready
    known_only=known_ready and proto.get('allow_known_only',False)
    report={'status':'ready' if ready else 'ready_known_only' if known_only else 'insufficient_eligible_observations','counts':tally,
        'unseen_species_ready':unseen_ready,
        'total_observations':len({r['observation_id'] for r in rows}),'eligible_observations':len(output),
        'split_sha256':digest(data/'splits.jsonl'),'image_manifest_sha256':digest(data/'images.jsonl'),
        'extraction_sha256':digest(data/'extraction/run.json'),
        'note':'No model predictions or species correctness used for eligibility or splitting. Leaf visibility is machine-estimated.'}
    (data/'split-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['freeze','collect','partition'])
    p.add_argument('--source',type=Path);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--previous',type=Path,nargs='*',default=[]);p.add_argument('--per-taxon',type=int,default=45)
    p.add_argument('--since',default='2024-01-01')
    p.add_argument('--max-pages',type=int,default=10)
    a=p.parse_args()
    if a.command=='freeze':freeze(a.source,a.data)
    elif a.command=='collect':collect(a.data,a.previous,a.per_taxon,a.since,a.max_pages)
    else:partition(a.data)

if __name__=='__main__':main()
