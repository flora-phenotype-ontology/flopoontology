#!/usr/bin/env python3
"""ORIX lane of the full flora run: hold an ORIX GPU only while flora LLM steps run.

ORIX kills jobs that keep a GPU below 75 % utilization, and the flora pipeline alternates Qwen
steps (transcription, re-read, term rules, relations) with deterministic annotation passes that
take an hour or more on a large flora. So the pipeline runs here step by step
(``flopo2.ingest.pipeline --steps llm|cpu``):

- several floras (largest first, WFO excluded) are worked on at once;
- their deterministic steps run on ws and need no GPU;
- their LLM steps run against vLLM jobs on ORIX freecycle GPUs (``tools/orix/qwen_flopo.sbatch``,
  one Qwen per GPU, up to ``--max-gpus``), each reached through its own SSH tunnel via the login
  node; each job serves up to ``--per-gpu`` floras' LLM steps (two measured 96-100 % on an H100);
  jobs are submitted as floras wait for LLM steps and cancelled as soon as they have none to serve,
  so a GPU never waits on an annotation pass;
- when the job is preempted or dies, the LLM steps in flight are stopped and resume from their
  caches on the next job (the pipeline's step markers skip what is complete).

Claims, done markers and the publish queue are shared with ``tools/run_floras_full.sh`` (the
unimatrix lane). State: ``local-corpora/run-logs/orix/state``, log ``.../orix/lane.log``.

    tmux new -d -s flopo-orix 'tools/orix_flora_lane.py --max-gpus 4'
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "local-corpora/run-logs"
OD = LOGS / "orix"
CLAIMS, DONE, PENDF = LOGS / "claims", LOGS / "done", LOGS / "publish-pending"
PY = Path.home() / ".cache/flopo-venv/bin/python"
RDIR = "/mnt/data/u/hohndor/flopo-qwen"
GRES = {"h100": "gpu:nvidia_h100_80gb_hbm3:1", "h200": "gpu:nvidia_h200:1"}
# Largest first (the unimatrix lane takes the smallest first; the lanes meet in the middle).
ORDER = [
    "eflora-foc", "kew-african", "eflora-fna", "nybg-naf", "fdac-genera", "fdac", "powo-neotropical", "eflora-other",
    "eflora-fop", "flora-zimbabwe", "flora-gabon", "flora-malesiana", "eflora-mfoc", "smithsonian-botany",
    "illinois-wildflowers", "flora-guianas", "feis-plants", "powo-ftea", "powo-fz", "usda-plants",
    "africa-tree-db", "plazi", "plants-tibet", "powo-ildis", "powo-kew", "powo-fwta", "phytokeys",
    "powo-fsom", "silvics-na", "powo-cayman", "korup-flora", "powo-cate", "powo-fiq", "powo-grassbase",
    "eflora-fom", "eflora-andes", "powo-tong", "wfo",
]


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"== {now()} [orix] {msg}"
    print(line, flush=True)
    for path in (OD / "lane.log", LOGS / "driver.log"):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def state(msg: str) -> None:
    (OD / "state").write_text(f"{now()} {msg}\n", encoding="utf-8")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def claim_holder(src: str) -> str | None:
    path = CLAIMS / src
    try:
        lane, pid = path.read_text().split()
    except (FileNotFoundError, ValueError):
        return None
    return lane if pid_alive(int(pid)) else None


@dataclass
class Step:
    proc: subprocess.Popen
    kind: str
    endpoint: "Endpoint | None" = None
    started: float = field(default_factory=time.time)


@dataclass
class Flora:
    src: str
    need: str = "cpu"           # what runs next: "cpu" or "llm"
    step: Step | None = None
    failures: int = 0
    retry_at: float = 0.0


def ssh(host: str, command: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15", host, command],
        capture_output=True, text=True, timeout=timeout,
    )


def idle_gpus(host: str) -> dict[str, int]:
    idle = {"h100": 0, "h200": 0}
    try:
        out = ssh(host, "scontrol show node -o", timeout=60).stdout
    except subprocess.TimeoutExpired:
        return idle
    for line in out.splitlines():
        parts = re.search(r"Partitions=(\S+)", line)
        if not parts or re.search(r"State=\S*(DOWN|DRAIN|NOT_RESPONDING)", line):
            continue
        kind = next((k for k in idle if f"freecycle-{k}" in parts.group(1)), None)
        if kind:
            cfg = re.search(r"CfgTRES=\S*gres/gpu=(\d+)", line)
            alloc = re.search(r"AllocTRES=\S*gres/gpu=(\d+)", line)
            idle[kind] += int(cfg.group(1) if cfg else 0) - int(alloc.group(1) if alloc else 0)
    return idle


def job_states(host: str, jobs: list[str]) -> dict[str, str] | None:
    """{job: 'RUNNING'|'PENDING'|...}; a job missing from the answer has ended. None: cannot tell."""
    try:
        res = ssh(host, f"squeue -h -j {','.join(jobs)} -o '%i %T' 2>&1; echo \"END $?\"", timeout=120)
    except subprocess.TimeoutExpired:
        return None
    if "END " not in res.stdout:
        return None
    body, rc = res.stdout.rsplit("END ", 1)
    if rc.strip() != "0":
        return {} if "Invalid job id" in body else None
    out = {}
    for line in body.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


class Endpoint:
    """One vLLM job on one ORIX GPU, reached through its own tunnel on 127.0.0.1:<port>."""

    def __init__(self, host: str, index: int, port: int) -> None:
        self.host, self.index, self.port = host, index, port
        self.sock = OD / f"tunnel-{index}.sock"
        self.keyfile = OD / f"key-{index}"
        self.job: str | None = None
        self.job_type = ""
        self.tunnel = False
        self.down_since: float | None = None
        self.up_since = 0.0
        self.last_util = 0.0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def submit(self, kind: str) -> None:
        try:
            res = ssh(self.host, f"cd {RDIR} && sbatch --parsable --partition=freecycle-{kind} --gres={GRES[kind]} qwen_flopo.sbatch")
        except subprocess.TimeoutExpired:
            log("sbatch timed out")
            return
        m = re.match(r"(\d+)", res.stdout.strip())
        if not m:
            log(f"sbatch: {(res.stdout + res.stderr).strip() or 'no answer'}")
            return
        self.job, self.job_type, self.up_since = m.group(1), kind, 0.0
        log(f"submitted job {self.job} to freecycle-{kind} (endpoint {self.index}, port {self.port})")

    def cancel(self, why: str) -> None:
        self.close_tunnel()
        if self.job:
            try:
                ssh(self.host, f"scancel {self.job}")
            except subprocess.TimeoutExpired:
                pass
            log(f"cancelled job {self.job}: {why}")
        self.forget()

    def forget(self) -> None:
        self.close_tunnel()
        self.job, self.up_since, self.down_since = None, 0.0, None
        self.keyfile.unlink(missing_ok=True)

    def connect(self) -> bool:
        """Fetch the endpoint and key of the running job and open the tunnel; True when healthy."""
        try:
            ep = ssh(self.host, f"cat {RDIR}/state/{self.job}.endpoint 2>/dev/null").stdout.split()
            if len(ep) != 2:
                return False
            node, port = ep
            ip = ssh(self.host, f"getent hosts {node}").stdout.split()
            key = ssh(self.host, f"cat {RDIR}/state/{self.job}.key").stdout.strip()
        except subprocess.TimeoutExpired:
            return False
        if not key:
            return False
        fd = os.open(self.keyfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(key + "\n")
        self.close_tunnel()
        res = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
             "-o", "ServerAliveCountMax=3", "-M", "-S", str(self.sock), "-f", "-N",
             "-L", f"127.0.0.1:{self.port}:{ip[0] if ip else node}:{port}", self.host],
            capture_output=True, text=True, timeout=60,
        )
        if res.returncode != 0:
            log(f"tunnel to {node}:{port} failed: {res.stderr.strip()[:200]}")
            return False
        self.tunnel = True
        for _ in range(6):
            if self.healthy():
                log(f"qwen up: job {self.job} on {node}:{port}, local port {self.port}")
                self.up_since = time.time()
                return True
            time.sleep(10)
        log(f"no answer from {node}:{port} through the tunnel")
        self.close_tunnel()
        return False

    def close_tunnel(self) -> None:
        if self.sock.exists():
            subprocess.run(["ssh", "-S", str(self.sock), "-O", "exit", self.host], capture_output=True, timeout=30)
            self.sock.unlink(missing_ok=True)
        self.tunnel = False

    def healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=10) as r:
                return r.status == 200
        except Exception:
            return False

    def ready(self) -> bool:
        return bool(self.job) and self.tunnel and self.up_since > 0 and self.down_since is None

    def gpu_utilization(self) -> str:
        """Mean utilization over the last 10 min of the job's samples."""
        try:
            out = ssh(self.host, f"tail -n 20 {RDIR}/logs/gpu-{self.job}.csv 2>/dev/null").stdout
        except subprocess.TimeoutExpired:
            return "?"
        vals = [int(m.group(1)) for m in re.finditer(r",\s*(\d+) %", out)]
        return f"{sum(vals) / len(vals):.0f}% over the last {len(vals)} samples" if vals else "?"


class Lane:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.endpoints = [Endpoint(args.host, i, args.local_port + i) for i in range(args.max_gpus)]
        self.floras: dict[str, Flora] = {}
        self.publisher: subprocess.Popen | None = None
        self.stopping = False

    # --- flora selection ---------------------------------------------------------------------
    def pick_new(self) -> None:
        skip = set(self.args.skip.split())
        for src in ORDER:
            if len(self.floras) >= self.args.active:
                return
            if src in skip or src in self.floras or (DONE / src).exists() or (LOGS / f"{src}.failed").exists():
                continue
            if claim_holder(src):
                continue
            (CLAIMS / src).write_text(f"orix {os.getpid()}\n")
            self.floras[src] = Flora(src)
            log(f"{src}: taken by the ORIX lane")

    # --- steps -----------------------------------------------------------------------------------
    def start_step(self, fl: Flora, endpoint: Endpoint | None = None) -> None:
        cmd = [str(PY), "-m", "flopo2.ingest.pipeline", fl.src, "--limit", "0", "--steps", fl.need]
        if endpoint is not None:
            cmd += ["--workers", str(self.args.workers), "--base-url", endpoint.base_url,
                    "--model", "qwen3.8-27b", "--key-file", str(endpoint.keyfile)]
        else:
            cmd += ["--workers", "4"]
        logf = (LOGS / f"{fl.src}.log").open("a", encoding="utf-8")
        where = f" on job {endpoint.job}" if endpoint else ""
        logf.write(f"== {now()} [orix] {fl.need} steps{where}\n")
        logf.flush()
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        fl.step = Step(proc, fl.need, endpoint)

    def stop_step(self, fl: Flora) -> None:
        if fl.step and fl.step.proc.poll() is None:
            try:
                os.killpg(fl.step.proc.pid, signal.SIGTERM)
                fl.step.proc.wait(timeout=60)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(fl.step.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        fl.step = None

    def steps_on(self, endpoint: Endpoint) -> list[Flora]:
        return [f for f in self.floras.values() if f.step and f.step.endpoint is endpoint]

    def reap(self) -> None:
        for fl in list(self.floras.values()):
            if not fl.step or fl.step.proc.poll() is None:
                continue
            rc, kind, endpoint = fl.step.proc.returncode, fl.step.kind, fl.step.endpoint
            fl.step = None
            if rc == 0:
                self.complete(fl)
            elif rc == 10:
                fl.need, fl.failures = "llm", 0
            elif rc == 11:
                fl.need, fl.failures = "cpu", 0
            elif kind == "llm" and endpoint is not None and not endpoint.healthy():
                pass  # the endpoint went away; the LLM steps rerun on another job
            else:
                fl.failures += 1
                if fl.failures >= 4:
                    log(f"{fl.src} FAILED four times in its {kind} steps; moving on (see {LOGS / (fl.src + '.log')})")
                    (LOGS / f"{fl.src}.failed").touch()
                    self.release(fl)
                else:
                    log(f"{fl.src}: {kind} steps exited with {rc}; retrying in 10 min")
                    fl.retry_at = time.time() + 600

    def complete(self, fl: Flora) -> None:
        (DONE / fl.src).write_text(now() + "\n")
        log(f"{fl.src} complete")
        self.release(fl)
        with PENDF.open("a") as handle:
            handle.write(fl.src + "\n")
        if not self.publisher or self.publisher.poll() is not None:
            self.publisher = subprocess.Popen(
                ["tools/run_floras_full.sh", "--publish-pending"], cwd=ROOT, start_new_session=True,
                env={**os.environ, "LANE": "orix"},
                stdout=(OD / "publish-console.log").open("a"), stderr=subprocess.STDOUT,
            )

    def release(self, fl: Flora) -> None:
        holder = CLAIMS / fl.src
        if holder.exists() and holder.read_text().split()[-1] == str(os.getpid()):
            holder.unlink()
        self.floras.pop(fl.src, None)

    # --- GPUs ----------------------------------------------------------------------------------
    def tend_gpus(self) -> None:
        waiting = [f for f in self.floras.values() if f.need == "llm" and not f.step and time.time() >= f.retry_at]
        with_job = [e for e in self.endpoints if e.job]

        # 1. Follow the jobs we have.
        if with_job:
            states = job_states(self.args.host, [e.job for e in with_job])
            for e in with_job:
                st = None if states is None else states.get(e.job, "")
                if st is None:  # controller unreachable: trust the endpoint while it answers
                    st = "RUNNING" if e.tunnel and e.healthy() else "UNKNOWN"
                if st == "":
                    log(f"job {e.job} ended")
                    for f in self.steps_on(e):
                        self.stop_step(f)
                    e.forget()
                    continue
                if st != "RUNNING":
                    continue
                if not e.tunnel:
                    e.connect()
                    continue
                if e.healthy():
                    e.down_since = None
                    if e.up_since and time.time() - max(e.last_util, e.up_since) > 900:
                        e.last_util = time.time()
                        log(f"job {e.job}: GPU utilization {e.gpu_utilization()} serving {len(self.steps_on(e))} flora(s)")
                    continue
                e.down_since = e.down_since or time.time()
                if time.time() - e.down_since > 120:
                    log(f"endpoint of job {e.job} has not answered for 2 min; stopping its LLM steps")
                    for f in self.steps_on(e):
                        self.stop_step(f)
                    e.cancel("endpoint down")

        # 2. Hand waiting floras to ready endpoints with room.
        for e in self.endpoints:
            while waiting and e.ready() and len(self.steps_on(e)) < self.args.per_gpu:
                self.start_step(waiting.pop(0), e)

        # 3. Size the pool: one GPU per --per-gpu floras in LLM steps or waiting for them.
        busy = sum(len(self.steps_on(e)) for e in self.endpoints)
        demand = busy + len(waiting)
        wanted = min(self.args.max_gpus, -(-demand // self.args.per_gpu))
        jobs = [e for e in self.endpoints if e.job]
        for e in sorted(jobs, key=lambda e: e.ready()):  # pending and starting jobs go first
            if len(jobs) <= wanted:
                break
            if not self.steps_on(e):
                e.cancel("no LLM step to serve")
                jobs.remove(e)
        free = [e for e in self.endpoints if not e.job]
        if len(jobs) < wanted and free:
            idle = idle_gpus(self.args.host)
            for e in free[: wanted - len(jobs)]:
                kind = "h100" if idle["h100"] > 0 or idle["h200"] <= 0 else "h200"
                idle[kind] -= 1
                e.submit(kind)

    def tend_cpu(self) -> None:
        busy = sum(1 for f in self.floras.values() if f.step and f.step.kind == "cpu")
        for f in self.floras.values():
            if busy >= self.args.cpu_parallel:
                return
            if f.need == "cpu" and not f.step and time.time() >= f.retry_at:
                self.start_step(f)
                busy += 1

    def report(self) -> None:
        parts = []
        for f in self.floras.values():
            if f.step:
                where = f" on job {f.step.endpoint.job}" if f.step.endpoint else " on ws"
                parts.append(f"{f.src}: {f.step.kind}{where}")
            else:
                parts.append(f"{f.src}: waits for {f.need}")
        jobs = [f"{e.job}{'' if e.ready() else ' (starting)'}" for e in self.endpoints if e.job]
        state(f"jobs: {', '.join(jobs) or 'none'}; " + ("; ".join(parts) if parts else "no flora left"))

    # --- main loop ---------------------------------------------------------------------------
    def shutdown(self, *_: object) -> None:
        self.stopping = True

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGHUP, self.shutdown)
        for d in (OD, CLAIMS, DONE):
            d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ssh", self.args.host, f"mkdir -p {RDIR}/logs {RDIR}/state"], check=True, timeout=60)
        subprocess.run(["scp", "-q", str(ROOT / "tools/orix/qwen_flopo.sbatch"), f"{self.args.host}:{RDIR}/"], check=True, timeout=60)
        log(f"lane start: up to {self.args.max_gpus} GPUs, {self.args.per_gpu} floras per GPU, "
            f"{self.args.active} floras active, {self.args.workers} LLM workers per flora")
        try:
            while not self.stopping:
                self.reap()
                self.pick_new()
                if not self.floras:
                    log("no flora left for the ORIX lane")
                    break
                self.tend_cpu()
                self.tend_gpus()
                self.report()
                for _ in range(30):
                    if self.stopping:
                        break
                    time.sleep(1)
        finally:
            for f in list(self.floras.values()):
                self.stop_step(f)
                self.release(f)
            for e in self.endpoints:
                if e.job:
                    e.cancel("lane stopped")
            state("stopped")
            log("lane stopped")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("ORIX_HOST", "orix"))
    parser.add_argument("--local-port", type=int, default=int(os.environ.get("ORIX_LOCAL_PORT", 8200)),
                        help="first local tunnel port; endpoint i listens on this + i")
    parser.add_argument("--max-gpus", type=int, default=4, help="Qwen jobs (one GPU each) at most")
    parser.add_argument("--per-gpu", type=int, default=2, help="floras whose LLM steps share one GPU")
    parser.add_argument("--active", type=int, default=0,
                        help="floras worked on at once (default: max-gpus * per-gpu + 2, so GPUs have work "
                             "while some floras annotate)")
    parser.add_argument("--workers", type=int, default=64, help="concurrent requests per flora LLM step")
    parser.add_argument("--cpu-parallel", type=int, default=3, help="deterministic steps run at once on ws")
    parser.add_argument("--skip", default=os.environ.get("ORIX_SKIP", ""), help="floras this lane leaves alone")
    args = parser.parse_args()
    args.active = args.active or args.max_gpus * args.per_gpu + 2
    return Lane(args).run()


if __name__ == "__main__":
    sys.exit(main())
