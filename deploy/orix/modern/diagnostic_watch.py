"""Wait for full training, then submit the trait diagnostic within queue limits."""
from datetime import datetime,timezone
import json
from pathlib import Path
import shlex
import subprocess
import time
import traceback

ROOT=Path(__file__).resolve().parents[3]
REMOTE='/mnt/data/u/hohndor/flopo-vision'
STATE=ROOT/'local-corpora/flopo-full-v1/diagnostic-workflow.json'


def main():
    state=json.loads(STATE.read_text()) if STATE.exists() else {}
    def save(status,**kwargs):
        state.update(status=status,updated=datetime.now(timezone.utc).isoformat(),**kwargs)
        tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(STATE)
        print(state['updated'],status,flush=True)
    def remote(command):
        argv=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=30','orix',command]
        try:return subprocess.run(argv,capture_output=True,text=True,timeout=300)
        except subprocess.TimeoutExpired:return subprocess.CompletedProcess(argv,255,stdout='',stderr='SSH command timed out; will reconcile remote state before retry.')
    def wait(job):
        for _ in range(2880):
            r=remote(shlex.join(['sacct','-X','-n','-P','-j',job,'--format=JobID,State,ExitCode']))
            if r.returncode:save('waiting_for_transport',detail=r.stderr);time.sleep(60);continue
            rows=[s.split('|') for s in r.stdout.splitlines() if s.strip()]
            if any(s[1]=='COMPLETED' and s[2]=='0:0' for s in rows):return
            if any(s[1].split()[0] in ['FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL'] for s in rows):raise RuntimeError(str(rows))
            save('waiting_for_job',active_job=job,slurm_rows=rows);time.sleep(60)
        raise TimeoutError('Wait exceeded 48 hours')
    try:
        wait('347540')
        if 'job_id' not in state:
            record=REMOTE+'/full-diagnostic-submitted.txt'
            script=REMOTE+'/full-diagnostic-source-v1/deploy/orix/modern/full-diagnostic.sbatch'
            # Slurm writes the accepted ID directly to a persistent remote file.
            # A broken SSH reply therefore does not trigger duplicate submission.
            command=f'if test -s {shlex.quote(record)}; then cat {shlex.quote(record)}; else sbatch --parsable {shlex.quote(script)} > {shlex.quote(record)}; status=$?; cat {shlex.quote(record)}; exit "$status"; fi'
            for _ in range(360):
                r=remote(command)
                if not r.returncode:
                    job=r.stdout.strip().split(';')[0]
                    if not job.isdigit():raise ValueError('Invalid accepted job ID')
                    save('submitted',job_id=job);break
                if r.returncode!=255 and 'AssocMaxSubmitJobLimit' not in r.stderr:raise RuntimeError(r.stderr)
                save('waiting_for_submission_capacity',detail=r.stderr);time.sleep(120)
            else:raise TimeoutError('Submission window exceeded 12 hours')
        wait(state['job_id'])
        subprocess.run(['rsync','-a',f'orix:{REMOTE}/full-diagnostic-v1/',str(ROOT/'local-corpora/full-diagnostic-v1')+'/'],check=True)
        save('complete_development_diagnostic',active_job=None)
    except Exception:
        save('failed',error=traceback.format_exc());raise


if __name__=='__main__':main()
