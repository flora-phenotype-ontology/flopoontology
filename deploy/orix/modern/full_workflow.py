"""Persistent local driver: collect, freeze splits, extract, fit, retain predictions.

Uses only the Orix login alias and ordinary Slurm submission. No GPU is held while
waiting for data or merging CPU artifacts. Independent review is a separate gate.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import traceback


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--python',required=True);p.add_argument('--collector-pid',type=int,required=True)
    a=p.parse_args();os.chdir(a.workspace)
    data=a.workspace/'local-corpora/flopo-full-v1';state_path=data/'workflow.json'
    source=a.workspace/'local-corpora/full-source-v1';remote='/mnt/data/u/hohndor/flopo-vision'
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    def save(status,**kwargs):
        state.update(status=status,updated=datetime.now(timezone.utc).isoformat(),**kwargs)
        tmp=state_path.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(state_path)
        print(state['updated'],status,flush=True)
    def run(argv,capture=False):
        for attempt in range(3):
            try:
                result=subprocess.run([str(v) for v in argv],check=True,text=True,capture_output=capture,cwd=source,
                                      timeout=300 if capture else None)
                return result.stdout.strip() if capture else None
            except subprocess.CalledProcessError as exc:
                if str(argv[0])=='ssh' and exc.returncode==255 and attempt<2:
                    time.sleep(5*(attempt+1));continue
                raise RuntimeError(f'Command failed (exit {exc.returncode}): {shlex.join([str(v) for v in argv])}\nstdout: {exc.stdout or ""}\nstderr: {exc.stderr or ""}') from exc
            except subprocess.TimeoutExpired:
                if str(argv[0])=='ssh' and attempt<2:
                    time.sleep(5*(attempt+1));continue
                raise
    def remote_run(argv):return run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=30','orix',shlex.join([str(v) for v in argv])],capture=True)
    def submit(script,key):
        if key not in state:
            job=remote_run(['sbatch','--parsable',f'{remote}/full-source-v1/deploy/orix/modern/{script}']).split(';')[0]
            if not job.isdigit():raise ValueError('Invalid Slurm job ID')
            save('submitted_'+key,**{key:job})
        return state[key]
    def wait_job(job,count):
        for _ in range(2880):
            text=remote_run(['sacct','-X','-n','-P','-j',job,'--format=JobID,State,ExitCode'])
            rows=[line.split('|') for line in text.splitlines() if line.strip()]
            children=[r for r in rows if '_' in r[0]]
            active=children if children else rows
            bad=[r for r in active if r[1].split()[0] in ['FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE']]
            if bad:raise RuntimeError('Slurm failure: '+str(bad))
            if len(active)==count and all(r[1]=='COMPLETED' and r[2]=='0:0' for r in active):return
            save('waiting_for_slurm',active_job=job,slurm_rows=active)
            time.sleep(60)
        raise TimeoutError('Slurm monitoring exceeded 48 hours')
    try:
        manifest=json.loads((source/'manifest.json').read_text())
        for filename,expected in manifest.items():
            if hashlib.sha256((source/filename).read_bytes()).hexdigest()!=expected:raise ValueError('Changed frozen source')
        save('collecting',collector_pid=a.collector_pid)
        restarts=0;collector=None;pid=a.collector_pid
        for _ in range(2880):
            if (data/'collection.json').exists():break
            alive=True
            try:
                os.kill(pid,0)
                if Path(f'/proc/{pid}/stat').read_text().split()[2]=='Z':alive=False
            except (ProcessLookupError,FileNotFoundError):alive=False
            if not alive:
                if restarts>=3:raise RuntimeError('Collection failed after three resumptions; inspect collection.log')
                log=(data/'collection.log').open('a')
                collector=subprocess.Popen([a.python,'-u','-m','flopo2.vision.full_data','collect','--out',str(data),'--per-taxon','200','--pages','5'],cwd=source,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                pid=collector.pid;restarts+=1;save('collection_resumed',collector_pid=pid)
            time.sleep(60)
        else:raise TimeoutError('Collection exceeded 48 hours')
        save('preparing_splits',collection=json.loads((data/'collection.json').read_text()))
        if not (data/'split-audit.json').exists():
            run([a.python,'-m','flopo2.vision.full_data','split','--out',data,'--previous',a.workspace/'local-corpora/modern-cohort-v1','--legacy',a.workspace/'local-corpora/visual-small-v1'])
        review=a.workspace/'local-corpora/full-trait-review-v1'
        if not (review/'protocol.json').exists():
            run([a.python,'-m','flopo2.vision.trait_packet','--data',data,'--out',review,'--limit','1500','--fresh-only'])
        save('uploading',splits=json.loads((data/'split-audit.json').read_text()),review=json.loads((review/'protocol.json').read_text()))
        run(['rsync','-a','--exclude=api-cache/','--exclude=metadata/','--exclude=*.log','--exclude=workflow.json',str(data)+'/',f'orix:{remote}/flopo-full-v1/'])
        run(['rsync','-a',str(source)+'/',f'orix:{remote}/full-source-v1/'])
        extract=submit('full-extract.sbatch','extraction_job');wait_job(extract,4)
        save('merging_features')
        shards=a.workspace/'local-corpora/full-shards-v1';features=a.workspace/'local-corpora/full-features-v1'
        run(['rsync','-a',f'orix:{remote}/full-shards-v1/',str(shards)+'/'])
        if not (features/'extraction.json').exists():run([a.python,'-m','flopo2.vision.full_train','merge','--features',shards,'--out',features,'--shards','4'])
        run(['rsync','-a',str(features)+'/',f'orix:{remote}/full-features-v1/'])
        training=submit('full-train.sbatch','training_job');wait_job(training,state.get('training_job_tasks',15))
        save('downloading_models')
        runs=a.workspace/'local-corpora/full-runs-v1'
        run(['rsync','-a','--exclude=resume.pt',f'orix:{remote}/full-runs-v1/',str(runs)+'/'])
        expected=['pretrained']+[f'{mode}-200-{seed}' for mode in ['direct','mil','hierarchy','projected','shuffled'] for seed in range(20261026,20261029)]
        expected += [f'frozen-{n}-{seed}' for n in [10,50,200] for seed in range(20261026,20261029)]
        expected += [f'mil-{n}-{seed}' for n in [10,50] for seed in range(20261026,20261029)]
        for name in expected:
            folder=runs/name;r=json.loads((folder/'training.json').read_text());v=json.loads((folder/'prediction-manifest.json').read_text())
            if hashlib.sha256((folder/'model.pt').read_bytes()).hexdigest()!=r['checkpoint_sha256']:raise ValueError('Changed model '+name)
            if hashlib.sha256((folder/'predictions.jsonl').read_bytes()).hexdigest()!=v['predictions_sha256']:raise ValueError('Changed predictions '+name)
        save('training_and_predictions_complete_awaiting_independent_review',models_verified=len(expected),active_job=None)
    except Exception:
        save('failed',error=traceback.format_exc());raise


if __name__=='__main__':main()
