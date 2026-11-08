"""Bounded, resumable collection for the full weak trait experiment."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path

from .pilot import API, ALLOWED_LICENSES, observation_rows, download, write_jsonl, freeze
from .cohort import inventory, hash_bucket
from .extract import digest


def prepare(args):
    freeze(args.release, args.out, 500, diverse_only=False)
    profiles = json.loads((args.out/'profiles.json').read_text())
    inv = inventory(profiles, max_traits=40, minimum_taxa=10)
    inv['profiles_sha256'] = digest(args.out/'profiles.json')
    (args.out/'trait-inventory.json').write_text(json.dumps(inv, indent=2)+'\n')
    print(json.dumps({'traits':len(inv['traits']), 'taxa_with_events':inv['taxa_with_events'], 'events':len(inv['events'])}), flush=True)


def collect(args):
    profiles = json.loads((args.out/'profiles.json').read_text())
    inv = json.loads((args.out/'trait-inventory.json').read_text())
    eligible = {e['taxon'] for e in inv['events']}
    profiles = [p for p in profiles if p['taxon'] in eligible]
    api = API(args.out/'api-cache'); rows=[]; shortfalls=[]
    def fetch(row):
        try: return row['photo_id'],download(row,args.out),None
        except Exception as exc: return row['photo_id'],None,str(exc)
    executor=ThreadPoolExecutor(max_workers=8);futures=[];submitted=set()
    (args.out/'metadata').mkdir(exist_ok=True)
    for i,p in enumerate(profiles):
        path = args.out/'metadata'/f"{p['inat_id']}.json"
        if path.exists():
            saved=json.loads(path.read_text()); selected=saved['rows']
        else:
            selected=[]; observers=Counter(); seen=set()
            for page in range(1, args.pages+1):
                response=api.get('observations',taxon_id=p['inat_id'],quality_grade='research',
                    photos='true',photo_license=','.join(sorted(ALLOWED_LICENSES)),captive='false',
                    d1='2020-01-01',per_page=200,page=page,order_by='id',order='desc')
                pool=response.get('results',[])
                for r in sorted(pool,key=lambda r:hashlib.sha256(str(r['id']).encode()).hexdigest()):
                    observer=r.get('user',{}).get('id')
                    if observer is None or observers[observer]>=2 or r['id'] in seen: continue
                    photos=observation_rows(r,p,3)
                    if not photos: continue
                    selected.extend(photos); seen.add(r['id']); observers[observer]+=1
                    if len(seen)>=args.per_taxon: break
                if len(seen)>=args.per_taxon or len(pool)<200: break
            path.write_text(json.dumps({'rows':selected})+'\n')
        rows.extend(selected)
        for r in selected:
            if r['photo_id'] not in submitted:
                futures.append(executor.submit(fetch,r));submitted.add(r['photo_id'])
        n=len({r['observation_id'] for r in selected})
        if n<args.per_taxon: shortfalls.append({'taxon':p['taxon'],'observations':n})
        print(f'Metadata {i+1}/{len(profiles)}: {n} observations; {len(rows)} photos planned',flush=True)
        write_jsonl(args.out/'planned-images.jsonl',rows)
    unique={r['photo_id']:r for r in rows}; downloaded={}; errors=[]
    with (args.out/'downloaded.jsonl').open('w') as journal:
        for i,future in enumerate(as_completed(futures),1):
            pid,r,error=future.result()
            if r:
                downloaded[pid]=r; journal.write(json.dumps(r)+'\n'); journal.flush()
            else: errors.append({'photo_id':pid,'error':error})
            if i%250==0: print(f'Downloaded {i}/{len(unique)}; errors {len(errors)}',flush=True)
    executor.shutdown()
    complete=[{**downloaded[r['photo_id']],**r} for r in rows if r['photo_id'] in downloaded]
    write_jsonl(args.out/'images.jsonl',complete)
    report={'observations':len({r['observation_id'] for r in complete}),'images':len(downloaded),
        'taxa':len({r['taxon'] for r in complete}),'shortfalls':shortfalls,'download_errors':errors,
        'licenses':dict(Counter(r['license'] for r in downloaded.values())),
        'sampling':f'Up to {args.per_taxon} observations/taxon, 2 per observer, 3 photos/observation; bounded recent pool since 2020, not global random sampling.',
        'planned_sha256':digest(args.out/'planned-images.jsonl'),'images_sha256':digest(args.out/'images.jsonl')}
    report['source_sha256']=digest(__file__)
    (args.out/'collection.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['observations','images','taxa']}),flush=True)


def split(args):
    # Preserve previous genus partitions. Previously trained genera cannot become new test genera.
    prior=[json.loads(s) for s in (args.previous/'splits.jsonl').read_text().splitlines()]
    assignments={}; old_hashes={r['sha256'] for r in prior}
    for r in prior:
        if r['genus'] in assignments and assignments[r['genus']] != r['split']: raise ValueError('Prior genus split conflict')
        assignments[r['genus']]=r['split']
    if args.legacy:
        legacy=[json.loads(s) for s in (args.legacy/'splits.jsonl').read_text().splitlines()]
        for r in legacy:
            if assignments.get(r['genus'],'test')!='test': raise ValueError('Legacy audit genus would enter training')
            assignments[r['genus']]='test'
        prior += [{**r,'split':'test'} for r in legacy]
        old_hashes.update(r['sha256'] for r in legacy)
    rows=[json.loads(s) for s in (args.out/'images.jsonl').read_text().splitlines()]
    rejected=Counter(); observers=defaultdict(set); sha_taxa=defaultdict(set)
    for r in rows: sha_taxa[r['sha256']].add(r['taxon'])
    for r in rows:
        b=hash_bucket(r['genus']); r['split']=assignments.get(r['genus'],'train' if b<70 else 'validation' if b<85 else 'test')
    # Reserve previous observers. New observers get one deterministic partition;
    # retain only photographs whose genus partition agrees with their observer.
    for r in prior: observers[r['observer_id']].add(r['split'])
    kept=[]; seen=set()
    for r in sorted(rows,key=lambda r:(r['observation_id'],r['photo_id'])):
        if len(sha_taxa[r['sha256']])>1: rejected['conflicting_taxon']+=1; continue
        old_splits=observers[r['observer_id']]
        b=hash_bucket('observer:'+str(r['observer_id']))
        assigned=next(iter(old_splits)) if len(old_splits)==1 else 'train' if b<70 else 'validation' if b<85 else 'test'
        if len(old_splits)>1 or assigned!=r['split']: rejected['observer_partition_mismatch']+=1; continue
        if r['sha256'] in seen: rejected['duplicate']+=1; continue
        seen.add(r['sha256']); r['previous_image']=r['sha256'] in old_hashes; kept.append(r)
    # Pigeonhole index: <=3 bit errors in a 64-bit dHash imply an identical 16-bit block.
    buckets=defaultdict(list); remove=set(); history=list(prior)
    for j,r in enumerate(history):
        h=int(r['dhash'],16)
        for block in range(4): buckets[(block,(h>>(16*block))&65535)].append(j)
    for i,r in enumerate(kept):
        h=int(r['dhash'],16); candidates=set()
        for block in range(4): candidates.update(buckets[(block,(h>>(16*block))&65535)])
        for j in candidates:
            s=history[j]
            if s['split']!=r['split'] and (h^int(s['dhash'],16)).bit_count()<=3:
                remove.add(i)
                if j>=len(prior): remove.add(j-len(prior))
        for block in range(4): buckets[(block,(h>>(16*block))&65535)].append(len(history))
        history.append(r)
    rejected['cross_split_near_duplicate']=len(remove); kept=[r for i,r in enumerate(kept) if i not in remove]
    write_jsonl(args.out/'splits.jsonl',kept)
    report={'images':dict(Counter(r['split'] for r in kept)),'taxa':{s:len({r['taxon'] for r in kept if r['split']==s}) for s in ['train','validation','test']},
        'observations':{s:len({r['observation_id'] for r in kept if r['split']==s}) for s in ['train','validation','test']},
        'rejected':dict(rejected),'splits_sha256':digest(args.out/'splits.jsonl'),'source_sha256':digest(__file__),
        'previous_splits_sha256':digest(args.previous/'splits.jsonl'),'reference_status':'Unannotated; split excludes cross-partition observers and dHash<=3 candidates.',
        'observer_policy':'Preserve prior observer partitions; hash new observers 70/15/15 independently of genus and retain matching photographs only.'}
    (args.out/'split-audit.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','collect','split'])
    p.add_argument('--out',type=Path,required=True);p.add_argument('--release',type=Path);p.add_argument('--previous',type=Path)
    p.add_argument('--legacy',type=Path)
    p.add_argument('--per-taxon',type=int,default=200);p.add_argument('--pages',type=int,default=5)
    a=p.parse_args(); {'prepare':prepare,'collect':collect,'split':split}[a.command](a)


if __name__=='__main__':main()
