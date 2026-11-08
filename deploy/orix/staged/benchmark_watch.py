"""Collect the existing pxGPT inference array, verify it, and score human labels.

Does not submit or restart jobs. Slurm state is authoritative; transport failures
leave the same job pending for another poll. Run on the workstation, not a GPU.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import traceback


ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'local-corpora/pxgpt-benchmark-v1'
REMOTE = '/mnt/data/u/hohndor/flopo-vision'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    state_path = DATA / 'workflow.json'
    state = json.loads(state_path.read_text())
    job = state['inference_job']
    if not job.isdigit(): raise ValueError('Invalid job ID')
    source_files = [ROOT / ('flopo2/vision/'+n) for n in
                    ['benchmark.py', 'benchmark_score.py', 'extract.py']]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in source_files}
    def save(status, **kwargs):
        state.update(status=status, updated=datetime.now(timezone.utc).isoformat(), **kwargs)
        tmp = state_path.with_suffix('.tmp'); tmp.write_text(json.dumps(state, indent=2)+'\n'); tmp.replace(state_path)
        print(state['updated'], status, flush=True)
    save('monitoring_inference', scoring_source_sha256=frozen)
    terminal = {'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL', 'BOOT_FAIL', 'PREEMPTED'}
    expected = {job+'_'+str(i) for i in range(state['shards'])}
    try:
        while True:
            try:
                result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', 'orix',
                    f'sacct -X -n -P -j {job} --format=JobID,State,ExitCode,Elapsed'],
                    capture_output=True, text=True, timeout=45)
                if result.returncode:
                    save('transport_retry', last_transport_error=result.stderr[-1000:])
                    time.sleep(45); continue
            except subprocess.TimeoutExpired:
                save('transport_retry', last_transport_error='Slurm observation timed out; same job retained')
                time.sleep(45); continue
            states = {}
            for line in result.stdout.splitlines():
                parts = line.split('|')
                if len(parts) >= 4 and parts[0] in expected:
                    states[parts[0]] = {'state': parts[1].split()[0], 'exit': parts[2], 'elapsed': parts[3]}
            if any(r['state'] in terminal or (r['state'] == 'COMPLETED' and r['exit'] != '0:0') for r in states.values()):
                raise RuntimeError('Terminal Slurm failure: '+json.dumps(states))
            save('inference_running_or_queued', slurm=states)
            if set(states) == expected and all(r['state'] == 'COMPLETED' and r['exit'] == '0:0' for r in states.values()):
                break
            time.sleep(45)
        save('collecting_inference')
        destination = ROOT / 'local-corpora/pxgpt-inference-v1'
        subprocess.run(['rsync', '-a', '--exclude=chunk-*.npz', '--exclude=features.npz',
                        f'orix:{REMOTE}/pxgpt-inference-v1/', str(destination)+'/'], check=True)
        for name, expected_hash in frozen.items():
            if sha(ROOT / name) != expected_hash:
                raise ValueError('Scoring source changed after launch: '+name)
        save('scoring_independent_references')
        results = ROOT / 'local-corpora/pxgpt-results-v1'
        subprocess.run([str(ROOT / 'local-corpora/benchmark-env/bin/python'), '-m', 'flopo2.vision.benchmark_score',
            '--benchmark', str(DATA), '--inference', str(destination), '--overlap', str(DATA / 'overlap.json'),
            '--out', str(results)], cwd=ROOT, check=True)
        save('independent_evaluation_complete', results=str(results / 'results.json'),
             results_sha256=sha(results / 'results.json'))
    except Exception:
        save('controller_failed', error=traceback.format_exc())
        raise


if __name__ == '__main__': main()
