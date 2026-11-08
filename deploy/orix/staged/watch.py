"""Persistent controller: frozen extraction, image-only teacher, GPU preflight/train."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time
import traceback

ROOT=Path(__file__).resolve().parents[3]
REMOTE='/mnt/data/u/hohndor/flopo-vision'
OUT=ROOT/'local-corpora/staged-v1'


def main():
    OUT.mkdir(exist_ok=True);state_path=OUT/'workflow.json';state=json.loads(state_path.read_text()) if state_path.exists() else {'extraction_job':'347987'}
    teacher=ROOT/'local-corpora/staged-teacher-v2';launch=json.loads((teacher/'launch.json').read_text())
    def save(status,**kwargs):
        state.update(status=status,updated=datetime.now(timezone.utc).isoformat(),**kwargs)
        tmp=state_path.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(state_path);print(state['updated'],status,flush=True)
    def run(argv):
        for attempt in range(4):
            try:
                r=subprocess.run(argv,text=True,capture_output=True,timeout=1200)
                if r.returncode==0:return r.stdout.strip()
                if r.returncode!=255:raise RuntimeError(f'Command {shlex.join(argv)} failed: {r.stderr[-2500:]}')
            except subprocess.TimeoutExpired:
                if attempt==3:raise
            time.sleep(10)
        raise RuntimeError('Remote transport failed four attempts')
    def ssh(command):return run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=30','orix',command])
    def job(job_id):
        text=ssh(shlex.join(['sacct','-X','-n','-P','-j',job_id,'--format=JobID,State,ExitCode']))
        rows=[s.split('|') for s in text.splitlines() if s.strip()]
        if any(r[1].split()[0] in ['FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','BOOT_FAIL'] for r in rows):raise RuntimeError('Slurm failure '+str(rows))
        return bool(rows) and all(r[1]=='COMPLETED' and r[2]=='0:0' for r in rows)
    def submit(key,argument=''):
        if key in state:return state[key]
        record=f'{REMOTE}/staged-v2-{key}-submitted.txt';script=f'{REMOTE}/staged-train-source-v2/deploy/orix/staged/train.sbatch'
        command=f'if test -s {shlex.quote(record)}; then cat {shlex.quote(record)}; else sbatch --parsable {shlex.quote(script)} {shlex.quote(argument)} > {shlex.quote(record)}; result=$?; cat {shlex.quote(record)}; exit "$result"; fi'
        try:value=ssh(command).split(';')[0]
        except RuntimeError as exc:
            if 'AssocMaxSubmitJobLimit' in str(exc):save('waiting_for_submission_capacity');return None
            raise
        if not value.isdigit():raise RuntimeError('Invalid Slurm ID')
        save('submitted_'+key,**{key:value});return value
    def teacher_alive():
        try:return Path(f"/proc/{launch['pid']}/stat").read_text().split()[2]!='Z'
        except FileNotFoundError:return False
    try:
        for source_name in ['staged-teacher-source-v2','staged-train-source-v2']:
            source=ROOT/'local-corpora'/source_name
            for f,h in json.loads((source/'manifest.json').read_text()).items():
                if hashlib.sha256((source/f).read_bytes()).hexdigest()!=h:raise ValueError('Changed frozen source '+f)
        for _ in range(4320):
            if not (teacher/'complete.json').exists() and not teacher_alive():
                tries=state.get('teacher_restarts',0)
                if tries>=3:raise RuntimeError('Teacher failed after three resumptions; inspect worker.log')
                with (teacher/'worker.log').open('a') as log:p=subprocess.Popen(launch['command'],cwd=launch['cwd'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                launch['pid']=p.pid;(teacher/'launch.json').write_text(json.dumps(launch,indent=2)+'\n');save('teacher_resumed',teacher_restarts=tries+1,teacher_pid=p.pid)
            extracted=state.get('extraction_complete') or job(state['extraction_job'])
            if extracted and not state.get('extraction_complete'):save('extraction_complete',extraction_complete=True)
            if extracted and 'preflight_job' not in state:submit('preflight_job','preflight')
            ready=state.get('preflight_complete') or ('preflight_job' in state and job(state['preflight_job']))
            if ready and not state.get('preflight_complete'):save('preflight_complete',preflight_complete=True)
            complete=(teacher/'complete.json').exists()
            if complete and not state.get('teacher_uploaded'):
                run(['rsync','-a','--exclude=worker.log','--exclude=launch.json',str(teacher)+'/',f'orix:{REMOTE}/staged-teacher-v2/']);save('teacher_uploaded',teacher_uploaded=True)
            if ready and complete:
                train=submit('training_job')
                if train and job(train):break
            progress=json.loads((teacher/'progress.json').read_text()) if (teacher/'progress.json').exists() else {}
            save('training' if 'training_job' in state else 'preparing',teacher_pid=launch['pid'],teacher_progress=progress)
            time.sleep(60)
        else:raise TimeoutError('Monitoring exceeded 72 hours')
        save('downloading_outputs')
        destination=ROOT/'local-corpora/staged-runs-v1'
        run(['rsync','-a','--exclude=resume.pt',f'orix:{REMOTE}/staged-runs-v1/',str(destination)+'/'])
        count=0
        for encoder in ['fgclip2','bioclip2']:
            done=json.loads((destination/encoder/'complete.json').read_text())
            if done['models']!=31:raise ValueError('Incomplete experiment')
            reports=list((destination/encoder).glob('*/complete.json'))
            if len(reports)!=31:raise ValueError('Missing run output')
            for p in reports:
                d=json.loads(p.read_text())
                for file,key in [('model.pt','checkpoint_sha256'),('predictions.npz','predictions_sha256')]:
                    if hashlib.sha256((p.parent/file).read_bytes()).hexdigest()!=d[key]:raise ValueError('Changed output '+str(p))
                count+=1
        save('complete_awaiting_independent_trait_review',models_verified=count)
    except Exception:
        save('failed',error=traceback.format_exc());raise

if __name__=='__main__':main()
