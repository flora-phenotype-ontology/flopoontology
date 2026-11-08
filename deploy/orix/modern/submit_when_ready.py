"""Retry ordinary Slurm submission while a stale quota block is refreshed.

Never changes quota or scheduler policy. Stops on any other rejection, or after
the bounded retry window. Stores the accepted job ID for monitoring.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--script', required=True)
    p.add_argument('--record', type=Path, required=True)
    p.add_argument('--attempts', type=int, default=30)
    p.add_argument('--interval', type=int, default=120)
    args = p.parse_args()
    if args.record.exists():
        previous = json.loads(args.record.read_text())
        if previous.get('status') == 'submitted':
            print('Already submitted', previous['job_id'], flush=True); return
    history = []
    for attempt in range(args.attempts):
        result = subprocess.run(['sbatch', '--parsable', args.script], capture_output=True, text=True)
        row = {'time': datetime.now(timezone.utc).isoformat(), 'returncode': result.returncode,
               'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}
        history.append(row)
        status = {'status': 'waiting_for_quota_refresh', 'attempts': history}
        if result.returncode == 0:
            job_id = result.stdout.strip().split(';')[0]
            if not job_id.isdigit(): raise ValueError('Unexpected sbatch job ID')
            status.update(status='submitted', job_id=job_id)
        elif 'Exceeding storage quota' not in result.stderr:
            status['status'] = 'rejected_other_reason'
        elif attempt + 1 == args.attempts:
            status['status'] = 'quota_retry_window_exhausted'
        args.record.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.record.with_suffix('.tmp'); tmp.write_text(json.dumps(status, indent=2)+'\n'); tmp.replace(args.record)
        print(row['time'], status['status'], status.get('job_id', ''), flush=True)
        if status['status'] != 'waiting_for_quota_refresh': return
        time.sleep(args.interval)


if __name__ == '__main__': main()
