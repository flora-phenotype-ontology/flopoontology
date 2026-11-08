"""Matched frozen-encoder shape adapters; GPU compute only under Slurm."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from .benchmark import SHAPES
from .benchmark_infer import load_bioclip
from .extract import digest
from .modern import load_encoder, normalize
from .shape_experiments import IDS, read_rows


class Adapter(nn.Module):
    def __init__(self,dim,rank):
        super().__init__()
        self.down=nn.Parameter(torch.randn(dim,rank)*.02)
        self.up=nn.Parameter(torch.zeros(rank,dim))
    def forward(self,x):return F.normalize(x+x@self.down@self.up,dim=-1)


def text_embeddings(a,proto,events):
    out=a.out/'text.npz'
    source=[e['raw_prompt'] for e in events]+[e['normalized_prompt'] for e in events]+proto['canonical_prompts']
    prompt_hash=hashlib.sha256(json.dumps(source).encode()).hexdigest()
    if out.exists():
        manifest=json.loads((a.out/'text.json').read_text())
        if manifest['sha256']!=digest(out) or manifest['prompt_sha256']!=prompt_hash:raise ValueError('Changed text cache')
        return np.load(out)
    if a.encoder=='fgclip2':
        model,_,tokenizer,spec=load_encoder(a.models,'fgclip2-large')
        def encode(texts):
            tokens=tokenizer(texts,padding='max_length',truncation=True,max_length=64,return_tensors='pt').to('cuda')
            return normalize(model.get_text_features(**tokens,walk_type='box'))
    else:
        import open_clip
        model,_,spec=load_bioclip(a.extra_models);tokenizer=open_clip.get_tokenizer('ViT-L-14')
        def encode(texts):return normalize(model.encode_text(tokenizer(texts).cuda()))
    parts=[]
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        for start in range(0,len(source),32):parts.append(encode(source[start:start+32]).cpu().numpy())
    z=np.concatenate(parts); n=len(events)
    np.savez_compressed(out,raw=z[:n],normalized=z[n:2*n],canonical=z[2*n:])
    (a.out/'text.json').write_text(json.dumps(dict(sha256=digest(out),prompt_sha256=prompt_hash,model_spec=spec),indent=2)+'\n')
    del model;torch.cuda.empty_cache()
    return np.load(out)


def grouped_loss(logits,labels):
    losses=[]
    for ds,categories in SHAPES.items():
        rows=[i for i,r in enumerate(labels) if r['dataset_id']==ds]
        if not rows:continue
        scores=torch.stack([logits[rows][:,[IDS.index(k) for k in ids]].max(-1).values for ids in categories.values()],-1)
        y=torch.tensor([list(categories).index(labels[i]['target']) for i in rows],device=logits.device)
        losses.append(F.cross_entropy(scores,y,reduction='sum'))
    return sum(losses)/len(labels)


def run(a):
    if not torch.cuda.is_available() or not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm GPU required')
    torch.set_num_threads(4); torch.backends.cuda.matmul.allow_tf32=True
    a.out.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    proto=json.loads((a.data/'protocol.json').read_text())
    for name in ['events.jsonl','records.jsonl','training-labels.json',a.encoder+'.npz']:
        if digest(a.data/name)!=proto['sha256'][name]:raise ValueError('Changed protocol input: '+name)
    identity=dict(protocol_sha256=digest(a.data/'protocol.json'),source_sha256=digest(__file__),encoder=a.encoder,preflight=a.preflight)
    ip=a.out/'identity.json'
    if ip.exists() and json.loads(ip.read_text())!=identity:raise ValueError('Incompatible resume')
    ip.write_text(json.dumps(identity,indent=2)+'\n')
    events=read_rows(a.data/'events.jsonl'); records=read_rows(a.data/'records.jsonl')
    labelmap={r['row_index']:r for r in json.loads((a.data/'training-labels.json').read_text())}
    for i in labelmap:
        if records[i]['split']!='development':raise ValueError('Test label in training input')
    arrays=np.load(a.data/(a.encoder+'.npz'));texts=text_embeddings(a,proto,events)
    x=torch.tensor(arrays['source'],device='cuda');bench=torch.tensor(arrays['benchmark'],device='cuda')
    bags=torch.tensor(arrays['bags'],device='cuda');lengths=torch.tensor(arrays['lengths'],device='cuda')
    canonical=torch.tensor(texts['canonical'],device='cuda')
    if canonical.shape[-1]!=x.shape[-1]:raise ValueError('Image/text dimensions differ')
    outputs=[]
    for seed in proto['seeds'][:1] if a.preflight else proto['seeds']:
        for mode in proto['modes']:
            torch.manual_seed(seed);head=Adapter(x.shape[-1],proto['rank']).cuda()
            optimizer=torch.optim.AdamW(head.parameters(),lr=proto['learning_rate'],weight_decay=proto['weight_decay'])
            generator=torch.Generator(device='cuda').manual_seed(seed+1000)
            schedule_hash=hashlib.sha256();history=[]
            target=None
            if mode!='native':
                target=torch.tensor(texts['raw' if mode=='raw' else 'normalized'],device='cuda')
                if mode=='shuffled':target=target[torch.tensor(np.random.default_rng(seed+5000).permutation(len(events)),device='cuda')]
                steps=5 if a.preflight else proto['pretrain_steps']
                for step in range(steps):
                    ei=torch.randint(len(events),(proto['batch_events'],),device='cuda',generator=generator)
                    positions=(torch.rand((len(ei),proto['observations_per_event']),device='cuda',generator=generator)*lengths[ei,None]).long()
                    indices=bags[ei[:,None],positions];xx=x[indices];z=head(xx)
                    loss=(1-(F.normalize(z.mean(1),dim=-1)*target[ei]).sum(-1)).mean()+proto['anchor_weight']*((z-xx)**2).sum(-1).mean()
                    optimizer.zero_grad();loss.backward();optimizer.step()
                    # Tiny fixed audit samples avoid synchronizing every training step.
                    if step%100==0 or step==steps-1:
                        schedule_hash.update(indices.detach().cpu().numpy().tobytes());history.append([step,float(loss.detach())])
                if not np.isfinite(history[-1][1]):raise ValueError('Nonfinite source training')
            pretrained=copy.deepcopy(head.state_dict())
            sizes=[0]+(proto['budget_plan']['sizes'][:1] if a.preflight else proto['budget_plan']['sizes'])
            for budget in sizes:
                name=f'{mode}-{seed}-{budget}';folder=a.out/name;folder.mkdir(exist_ok=True)
                cp=folder/'complete.json'
                if cp.exists():
                    saved=json.loads(cp.read_text())
                    if saved['identity']!=identity or any(digest(folder/n)!=h for n,h in saved['sha256'].items()):raise ValueError('Changed completed run')
                    outputs.append(name);continue
                head.load_state_dict(pretrained);fine_history=[]
                if budget:
                    indices=proto['budget_plan']['schedules'][str(seed)][str(budget)]
                    if not indices or any(i not in labelmap for i in indices):raise ValueError('Invalid budget training labels')
                    labels=[labelmap[i] for i in indices];xx=bench[indices]
                    optimizer=torch.optim.AdamW(head.parameters(),lr=proto['learning_rate'],weight_decay=proto['weight_decay'])
                    for step in range(5 if a.preflight else proto['human_steps']):
                        z=head(xx);logits=10*z@canonical.T
                        loss=grouped_loss(logits,labels)+proto['anchor_weight']*((z-xx)**2).sum(-1).mean()
                        optimizer.zero_grad();loss.backward();optimizer.step()
                        if step%100==0:fine_history.append([step,float(loss.detach())])
                else:indices=[]
                with torch.inference_mode():scores=(10*head(bench)@canonical.T-3).sigmoid().cpu().numpy()
                if not np.isfinite(scores).all():raise ValueError('Nonfinite predictions')
                q=np.zeros((len(records),36),np.float32);q[:,IDS]=scores
                np.savez_compressed(folder/'predictions.npz',probabilities=q)
                torch.save(dict(adapter=head.state_dict(),canonical=canonical.cpu(),identity=identity),folder/'model.pt')
                report=dict(identity=identity,mode=mode,seed=seed,budget=budget,training_records=indices,
                            source_history=history,human_history=fine_history,sampling_audit_sha256=schedule_hash.hexdigest(),
                            sha256={n:digest(folder/n) for n in ['predictions.npz','model.pt']})
                cp.write_text(json.dumps(report,indent=2)+'\n');outputs.append(name)
                print(a.encoder,name,'complete',round(time.monotonic()-started,1),flush=True)
    expected=len(proto['modes'])*(1 if a.preflight else len(proto['seeds']))*(2 if a.preflight else 1+len(proto['budget_plan']['sizes']))
    if len(outputs)!=expected:raise ValueError('Incomplete run grid')
    (a.out/'complete.json').write_text(json.dumps(dict(identity=identity,runs=outputs,seconds=time.monotonic()-started,
       slurm_job_id=os.environ['SLURM_JOB_ID'],sha256={name+'/complete.json':digest(a.out/name/'complete.json') for name in outputs}),indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['data','models','extra-models','out']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--encoder',choices=['fgclip2','bioclip2'],required=True);p.add_argument('--preflight',action='store_true')
    run(p.parse_args())

if __name__=='__main__':main()
