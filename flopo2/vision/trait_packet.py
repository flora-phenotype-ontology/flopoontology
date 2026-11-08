"""Prepare a blinded, image-level trait review packet without model predictions.

The packet is initially unannotated. Creating it does not create expert labels.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .extract import digest


HTML = '''<!doctype html><meta charset="utf-8"><title>FLOPO image trait review</title>
<style>body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#243529}
button,input,select{font:inherit;margin:.3rem;padding:.4rem}main{display:grid;grid-template-columns:1fr 1fr;gap:2rem}
img{max-width:100%;max-height:75vh;object-fit:contain}table{width:100%;border-collapse:collapse}td{padding:.3rem;border-bottom:1px solid #ddd}
@media(max-width:800px){main{display:block}}.note{color:#536258}textarea{width:95%}</style>
<h1>Image-level phenotype review</h1>
<p>Label only what the photograph supports. An invisible or unresolved trait is <b>unassessable</b>, not absent.
If the target plant is ambiguous, leave its traits unassessable. Taxon names, flora statements and predictions are hidden.</p>
<label>Reviewer <input id="reviewer" placeholder="Name / identifier"></label>
<label>Review type <select id="role"><option>human</option><option>AI</option></select></label>
<button id="download">Export annotations</button><p class="note">Work is saved in this browser. Export a file to retain or share it.</p>
<button id="prev">Previous</button><span id="position"></span><button id="next">Next</button>
<main><section><a id="link" target="_blank"><img id="photo"></a><p id="imageid"></p>
<label><input type="checkbox" id="reviewed">I have reviewed this image</label><p>Notes</p><textarea id="notes" rows="4"></textarea></section>
<section><table id="traits"></table></section></main>
<script>
const packet=__PACKET__;const storageKey='flopo-traits-'+packet.packet_id;
let state=JSON.parse(localStorage.getItem(storageKey)||'null')||{index:0,reviewer:'',role:'human',annotations:{}};
const el=id=>document.getElementById(id);function save(){localStorage.setItem(storageKey,JSON.stringify(state))}
function render(){const image=packet.images[state.index];let a=state.annotations[image.audit_id];
 if(!a)a=state.annotations[image.audit_id]={audit_id:image.audit_id,image_sha256:image.image_sha256,reviewed:false,notes:'',traits:{}};
 el('position').textContent=` ${state.index+1} / ${packet.images.length} `;el('imageid').textContent=image.audit_id;
 el('photo').src=image.image;el('link').href=image.image;el('reviewer').value=state.reviewer;el('role').value=state.role;
 el('reviewed').checked=a.reviewed;el('notes').value=a.notes;el('traits').replaceChildren();
 for(const trait of packet.traits){const tr=document.createElement('tr'),label=document.createElement('td'),cell=document.createElement('td');
 label.textContent=trait.label;const select=document.createElement('select');
 for(const [value,text] of [['unknown','Unassessable / uncertain'],['present','Present'],['absent','Absent']]){
 const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option)}
 select.value=a.traits[trait.index]||'unknown';select.onchange=()=>{a.traits[trait.index]=select.value;save()};cell.append(select);tr.append(label,cell);el('traits').append(tr)}save()}
el('prev').onclick=()=>{state.index=Math.max(0,state.index-1);render()};el('next').onclick=()=>{state.index=Math.min(packet.images.length-1,state.index+1);render()};
el('reviewer').oninput=e=>{state.reviewer=e.target.value;save()};el('role').onchange=e=>{state.role=e.target.value;save()};
el('reviewed').onchange=e=>{state.annotations[packet.images[state.index].audit_id].reviewed=e.target.checked;save()};
el('notes').oninput=e=>{state.annotations[packet.images[state.index].audit_id].notes=e.target.value;save()};
el('download').onclick=()=>{if(!state.reviewer.trim()){alert('Enter a reviewer identifier before exporting.');return}
 const annotations=packet.images.map(im=>state.annotations[im.audit_id]||{audit_id:im.audit_id,image_sha256:im.image_sha256,reviewed:false,traits:{}});
 const body={packet_id:packet.packet_id,reviewer:state.reviewer,review_type:state.role,exported:new Date().toISOString(),annotations};
 const url=URL.createObjectURL(new Blob([JSON.stringify(body,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='trait-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
render();
</script>'''


def prepare(data, out, limit=200, fresh_only=False):
    from PIL import Image, ImageOps
    if limit < 1: raise ValueError('Packet size must be positive')
    rows = [json.loads(s) for s in (data / 'splits.jsonl').read_text().splitlines()]
    inventory = json.loads((data / 'trait-inventory.json').read_text())
    # One photograph per observation; deterministic selection without predictions.
    rows.sort(key=lambda r: hashlib.sha256(('trait-review-v1:' + str(r['photo_id'])).encode()).hexdigest())
    selected, observations = [], set()
    for r in rows:
        if fresh_only and r.get('previous_image'): continue
        if r['split'] not in ('validation', 'test') or r['observation_id'] in observations: continue
        observations.add(r['observation_id']); selected.append(r)
        if len(selected) == limit: break
    if not selected: raise ValueError('No reserved images')
    out.mkdir(parents=True, exist_ok=False); (out / 'images').mkdir()
    images, private = [], []
    for i, r in enumerate(selected):
        aid = f'R{i+1:04d}'; path = data / r['image_path']
        if digest(path) != r['sha256']: raise ValueError('Changed source photo')
        target = out / 'images' / (aid + '.jpg')
        with Image.open(path) as im:
            ImageOps.exif_transpose(im).convert('RGB').save(target, quality=95)
        images.append({'audit_id': aid, 'image': 'images/' + target.name, 'image_sha256': digest(target)})
        private.append({'audit_id': aid, **r})
    traits = [{k: t[k] for k in ('index', 'label', 'bearer', 'quality')} for t in inventory['traits']]
    packet_id = hashlib.sha256(json.dumps({'images': images, 'traits': traits}, sort_keys=True).encode()).hexdigest()
    packet = {'packet_id': packet_id, 'images': images, 'traits': traits}
    (out / 'packet.json').write_text(json.dumps(packet, indent=2)+'\n')
    (out / 'private-join.json').write_text(json.dumps(private, indent=2)+'\n')
    (out / 'review.html').write_text(HTML.replace('__PACKET__', json.dumps(packet).replace('<', '\\u003c')))
    protocol = {'status': 'unannotated', 'images': len(images), 'traits': len(traits),
        'splits': dict(Counter(r['split'] for r in selected)), 'selection': 'Hash-random, one image per reserved observation, no model outputs used.',
        'packet_id': packet_id, 'packet_sha256': digest(out / 'packet.json'),
        'private_join_sha256': digest(out / 'private-join.json'), 'source_splits_sha256': digest(data / 'splits.jsonl'),
        'source_inventory_sha256': digest(data / 'trait-inventory.json'),
        'fresh_only': fresh_only,
        'reference_policy': 'Unknown is not absent. Only explicitly reviewed images can enter evaluation; retain ambiguity. Human review/adjudication is required for an independent expert benchmark.',
        'blinding': 'UI excludes taxon IDs/names, source profiles, predictions and EXIF; private-join.json is for the study administrator, not the annotator.'}
    (out / 'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    print(json.dumps(protocol, indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--limit', type=int, default=200)
    p.add_argument('--fresh-only', action='store_true')
    a=p.parse_args();prepare(a.data,a.out,a.limit,a.fresh_only)


if __name__=='__main__':main()
