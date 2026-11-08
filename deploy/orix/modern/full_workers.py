"""Run the frozen fifteen experiment tasks inside one four-GPU Slurm job."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess


def command(index, job):
    root=Path('/mnt/data/u/hohndor/flopo-vision')
    return ['srun','--exclusive','--exact','--nodes=1','--ntasks=1','--cpus-per-task=4',
        '--gres=gpu:nvidia_h200:1','--mem=64G',
        '--output='+str(root/f'logs/flopo-full-task-{job}-{index}.out'),
        '--error='+str(root/f'logs/flopo-full-task-{job}-{index}.err'),
        'env',f'SLURM_ARRAY_TASK_ID={index}','bash',str(root/'full-source-v1/deploy/orix/modern/full-train.sbatch')]


def main():
    job=os.environ['SLURM_JOB_ID'];root=Path('/mnt/data/u/hohndor/flopo-vision/full-source-v1')
    for filename,expected in json.loads((root/'manifest.json').read_text()).items():
        if hashlib.sha256((root/filename).read_bytes()).hexdigest()!=expected:raise ValueError('Changed experiment source')
    # Start the longer learning-curve tasks first; dynamically reuse freed GPUs.
    order=[1,6,11]+[i for i in range(15) if i not in (1,6,11)]
    failures=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending={pool.submit(subprocess.run,command(i,job),check=True):i for i in order}
        for future in as_completed(pending):
            i=pending[future]
            try:future.result();print('COMPLETED task',i,flush=True)
            except Exception as exc:failures.append(i);print('FAILED task',i,str(exc),flush=True)
    if failures:raise RuntimeError('Failed experiment tasks: '+str(failures))


if __name__=='__main__':main()
