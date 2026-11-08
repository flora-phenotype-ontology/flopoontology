"""Image-only, resumable Qwen trait supervision. Never supplies taxon metadata."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request

from PIL import Image, ImageOps
from .extract import digest
from .modern_weak import CONTEXT_QUALITIES
from .modern import DESCRIPTIONS

VERSION = 'flopo-visible-traits-v3-schema'
EXTRA = {
 'spherical':'approximately ball-shaped in three dimensions',
 'dentated':'margin with outward-pointing tooth-like projections',
 'serrated':'margin with saw-like teeth directed toward the tip',
 'pubescent hair':'surface bearing visible short soft hairs',
 'glabrous':'hairless surface; absence of hairs requires sufficient resolution',
 'hairy':'surface bearing visible hairs',
 'green':'visibly green','white':'visibly white','red':'visibly red',
 'yellow':'visibly yellow','brown':'visibly brown','orange':'visibly orange',
}

def eligible_traits(traits, organ):
    return [t for t in traits if t['organ']==organ and t['quality_label'] not in CONTEXT_QUALITIES]


def prompt(traits, organ):
    definitions=[]
    for t in eligible_traits(traits,organ):
        q=t['quality_label'];definition=EXTRA.get(q,DESCRIPTIONS.get(q,q)).replace('leaf',organ)
        definitions.append({'id':t['index'],'trait':t['label'],'definition':definition})
    return '''Inspect ONLY the attached plant-organ crop. Do not identify or guess the species,
use taxonomic knowledge, infer invisible organs, or assume that a trait occurs because another does.
The detector proposed an organ; it can be wrong. Background plants may be present.
Judge each listed trait independently for the main organ in this crop. Shapes may overlap.
For present/absent, the relevant structure must be clearly visible at adequate resolution.
For absence of hairs, blur or small scale is unobservable, NOT absent. A cropped-off leaf outline
is unobservable for shape. If the organ is wrong or absent, all its traits are unobservable.
Return JSON matching the response schema: {"traits":{"ID":{"s":"p|a|u","c":"h|m|l","b":box},...},"evidence":"at most 30 words describing the inspected structures"}.
Codes: state is "p" present, "a" absent or "u" unobservable; confidence is "h" high, "m" medium or "l" low.
Box is [x0,y0,x1,y1] or null. No extra fields, trait names, or per-trait explanations.
Coordinates are relative to this crop, normalized to [0,1]. For present or absent, box must cover
the region you inspected; for unobservable use null. Do not use species names in evidence.
Return exactly one entry for every ID. If uncertain, abstain. Vocabulary:\n'''+json.dumps(definitions)


def validate(value, traits, organ):
    expected={t['index'] for t in eligible_traits(traits,organ)}
    if isinstance(value,dict) and isinstance(value.get('traits'),dict):
        value={'traits':[[int(k),e['s'],e['c'],e['b']] for k,e in value['traits'].items()],'evidence':value.get('evidence')}
    if not isinstance(value,dict) or not isinstance(value.get('traits'),list):raise ValueError('Missing trait list')
    entries=value['traits'];seen=set()
    if entries and isinstance(entries[0],list):
        states={'p':'present','a':'absent','u':'unobservable'};conf={'h':'high','m':'medium','l':'low'}
        if not isinstance(value.get('evidence'),str):raise ValueError('Missing shared evidence')
        if any(len(e)!=4 or e[1] not in states or e[2] not in conf for e in entries):raise ValueError('Malformed compact annotation')
        entries=[{'id':e[0],'state':states[e[1]],'confidence':conf[e[2]],'box':e[3],'evidence':value['evidence']} for e in entries]
        value={'traits':entries}
    for e in entries:
        if type(e.get('id')) is not int or e['id'] not in expected or e['id'] in seen:raise ValueError('Wrong/repeated trait ID')
        seen.add(e['id'])
        if e.get('state') not in ('present','absent','unobservable') or e.get('confidence') not in ('high','medium','low'):raise ValueError('Invalid state/confidence')
        b=e.get('box')
        if e['state']=='unobservable':
            if b is not None:raise ValueError('Unobservable must not have an evidence box')
        elif not (isinstance(b,list) and len(b)==4 and all(type(v) in (float,int) and 0<=v<=1 for v in b) and b[0]<b[2] and b[1]<b[3]):raise ValueError('Invalid evidence box')
        if not isinstance(e.get('evidence'),str):raise ValueError('Missing evidence')
    if seen!=expected:raise ValueError('Incomplete trait coverage')
    return value


def request_payload(image_bytes, text, model, ids=None):
    # The wire payload contains neither filenames, URLs, taxonomy nor flora assertions.
    response_format={'type':'json_object'}
    if ids is not None:
        item={'type':'object','properties':{'s':{'type':'string','enum':['p','a','u']},'c':{'type':'string','enum':['h','m','l']},
           'b':{'anyOf':[{'type':'null'},{'type':'array','items':{'type':'number','minimum':0,'maximum':1},'minItems':4,'maxItems':4}]}},'required':['s','c','b'],'additionalProperties':False}
        schema={'type':'object','properties':{'traits':{'type':'object','properties':{str(k):item for k in ids},'required':[str(k) for k in ids],'additionalProperties':False},
            'evidence':{'type':'string'}},'required':['traits','evidence'],'additionalProperties':False}
        response_format={'type':'json_schema','json_schema':{'name':'visible_traits','strict':True,'schema':schema}}
    return {'model':model,'temperature':0,'max_tokens':1800,
      'messages':[{'role':'user','content':[{'type':'text','text':text},
       {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(image_bytes).decode()}}]}],
      'response_format':response_format,'chat_template_kwargs':{'enable_thinking':False}}


def atomic(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)


def run(a):
    from flopo2.ingest.collenette_llm import DEFAULT_BASE_URL,DEFAULT_MODEL,DEFAULT_KEY_FILE,_key,parse_json
    a.out.mkdir(parents=True,exist_ok=True);cache=a.out/'responses';cache.mkdir(exist_ok=True)
    inv=json.loads((a.features/'inventory.json').read_text())
    rows=[json.loads(s) for s in (a.features/'regions.jsonl').read_text().splitlines()]
    todo=[(i,r) for i,r in enumerate(rows) if r['split']=='train']
    if a.limit:todo=todo[:a.limit]
    key=_key(DEFAULT_KEY_FILE)
    protocol={'version':VERSION,'model':DEFAULT_MODEL,'regions_sha256':digest(a.features/'regions.jsonl'),
       'inventory_sha256':digest(a.features/'inventory.json'),'source_sha256':digest(__file__),
       'prompts':{o:prompt(inv['traits'],o) for o in sorted({r['organ'] for _,r in todo})},
       'images':len(todo),'input':'Only EXIF-free organ crop, vocabulary and visual definitions; no species, taxonomy, flora profile, filename or image URL.',
       'scope':'No validation/test images requested; high-confidence responses are noisy training labels, not evaluation truth.'}
    pp=a.out/'protocol.json'
    if pp.exists() and json.loads(pp.read_text())!=protocol:raise ValueError('Changed teacher protocol')
    atomic(pp,protocol);started=time.monotonic();failures=[];completed=0
    def one(pair):
        i,r=pair;p=cache/f'{i:06d}.json'
        if p.exists():
            old=json.loads(p.read_text())
            if old['image_sha256']!=r['sha256'] or old['protocol_sha256']!=digest(pp):raise ValueError('Stale teacher cache')
            validate(old['annotation'],inv['traits'],r['organ']);return
        path=a.data/r['image_path']
        if digest(path)!=r['sha256']:raise ValueError('Changed image')
        with Image.open(path) as im:im=ImageOps.exif_transpose(im).convert('RGB').crop(r['box'])
        im.thumbnail((768,768));buf=io.BytesIO();im.save(buf,format='JPEG',quality=90)
        body=request_payload(buf.getvalue(),protocol['prompts'][r['organ']],DEFAULT_MODEL,[t['index'] for t in eligible_traits(inv['traits'],r['organ'])])
        req=urllib.request.Request(DEFAULT_BASE_URL+'/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req,timeout=240) as h:reply=json.load(h)
                value=validate(parse_json(reply['choices'][0]['message']['content']),inv['traits'],r['organ'])
                atomic(p,{'row_index':i,'image_sha256':r['sha256'],'crop_box':r['box'],'protocol_sha256':digest(pp),
                  'annotation':value,'usage':reply.get('usage'),'response_model':reply.get('model'),
                  'request_sha256':hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest(),
                  'created':datetime.now(timezone.utc).isoformat()});return
            except Exception as exc:
                print(json.dumps({'row':i,'attempt':attempt+1,'error':type(exc).__name__+': '+str(exc)[:200]}),flush=True)
                if 'reply' in locals():atomic(cache/f'{i:06d}-invalid-{attempt}.json',{'response':reply,'error':str(exc)[:200]})
                if attempt==3:raise
                time.sleep(2**attempt)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(one,p):p[0] for p in todo}
        for f in as_completed(futures):
            try:f.result();completed+=1
            except Exception as exc:failures.append({'row_index':futures[f],'error':type(exc).__name__+': '+str(exc)[:200]})
            if (completed+len(failures))%10==0:
                state={'completed':completed,'failed':len(failures),'total':len(todo),'seconds':time.monotonic()-started}
                atomic(a.out/'progress.json',state);print(json.dumps(state),flush=True)
    if failures:
        atomic(a.out/'failures.json',failures);raise RuntimeError(f'{len(failures)} teacher calls failed; rerun resumes successful responses')
    values=[json.loads((cache/f'{i:06d}.json').read_text()) for i,_ in todo]
    path=a.out/'annotations.jsonl';path.write_text(''.join(json.dumps(v)+'\n' for v in values))
    atomic(a.out/'complete.json',{'images':len(values),'annotations_sha256':digest(path),'protocol_sha256':digest(pp),'seconds':time.monotonic()-started})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['features','data','out']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--limit',type=int,default=0)
    run(p.parse_args())

if __name__=='__main__':main()
