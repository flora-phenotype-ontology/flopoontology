"""Prepare a blind deterministic CotLeaf-X sample for external hairiness ranking."""
import argparse
from collections import defaultdict,Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import urllib.request
from PIL import Image
from .extract import digest


def prepare(a):
    metadata=json.loads((a.out/'collection.json').read_text()); raw=json.loads((a.out/'cotleaf-X.json').read_text())
    files=json.loads(a.links.read_text())['file'];lookup={f['filename']:f for f in files}
    groups=defaultdict(list)
    for r in raw['images']:groups[r['genotype']].append(r)
    selected=[]
    for g,rr in sorted(groups.items()):
        selected.extend(sorted(rr,key=lambda r:hashlib.sha256(('flopo-cotleaf-v1:'+r['image_id']).encode()).hexdigest())[:64])
    proto=dict(source='https://doi.org/10.25919/eqhx-1x73',release=metadata['attributionStatement'],
        sampling='64 images per released anonymized genotype, SHA256 flopo-cotleaf-v1:image_id ordering, independent of expert scores and predictions.',
        images=len(selected),primary='Mean within-population binary high-versus-low expert-score AP. Population A: low <=1, high >=3. Population B: low <=3, high >=5. Intermediate scores excluded.',
        prediction='Generic leaf hairy score (index 32); existing frozen heads, whole-image first tile plus four existing spatial tiles. No fitting or threshold selection.',
        mapping='Relative low/high hairiness only; low is not asserted to mean glabrous. Population-specific ordinal scales are kept separate.',
        models='All 38 existing primary model checkpoints plus three-seed ensembles; no encoder or arm selection.',
        uncertainty='Descriptive per-population and per-genotype metrics only: released plant_number and leaf_id collapse to four anonymized groups and do not identify independent plants. No image-IID confidence intervals.',
        scope='Fresh microscope-domain stress test of earlier hairiness models; not confirmation of new shape adapters or botanical glabrous classification.',
        selected_image_ids=[r['image_id'] for r in selected],source_sha256=digest(__file__),annotations_sha256=digest(a.out/'cotleaf-X.json'))
    pp=a.out/'protocol.json'
    if pp.exists() and json.loads(pp.read_text())!=proto:raise ValueError('Changed frozen protocol')
    pp.write_text(json.dumps(proto,indent=2)+'\n')
    (a.out/'originals').mkdir(exist_ok=True);(a.out/'images').mkdir(exist_ok=True)
    def download(row):
        f=lookup[row['image_path']];p=a.out/'originals'/row['image_name'];image=a.out/'images'/(row['image_id']+'.png')
        if not p.exists():
            request=urllib.request.Request(f['presignedLink']['href'],headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(request,timeout=90) as r, p.with_suffix('.partial').open('wb') as w:
                while chunk:=r.read(1024*1024):w.write(chunk)
            p.with_suffix('.partial').replace(p)
        if p.stat().st_size!=f['fileSize']:raise ValueError('Download size mismatch')
        with Image.open(p) as im:
            rgb=im.convert('RGB');rgb.save(image);width,height=rgb.size
        score=float(row['expert_score']);low,high=(1,3) if row['population']=='A' else (3,5)
        target=0 if score<=low else 1 if score>=high else None
        return {**row,'expert_score':score,'target':target,'image_file':str(image.relative_to(a.out)),
                'source_file_id':f['id'],'source_size':f['fileSize'],'source_sha256':digest(p),'sha256':digest(image),'width':width,'height':height}
    output=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures={pool.submit(download,r):r for r in selected}
        for future in as_completed(futures):
            output.append(future.result())
            if len(output)%32==0:print('Downloaded',len(output),'/',len(selected),flush=True)
    order={r['image_id']:i for i,r in enumerate(selected)};output.sort(key=lambda r:order[r['image_id']])
    (a.out/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in output))
    inventory=dict(images=len(output),populations={pop:dict(Counter(str(r['target']) for r in output if r['population']==pop)) for pop in ['A','B']},
                   source_sizes_verified=True,records_sha256=digest(a.out/'records.jsonl'),protocol_sha256=digest(pp))
    (a.out/'complete.json').write_text(json.dumps(inventory,indent=2)+'\n');print(json.dumps(inventory),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--links',type=Path,required=True);prepare(p.parse_args())

if __name__=='__main__':main()
