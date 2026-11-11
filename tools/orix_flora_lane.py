#!/usr/bin/env python3
"""ORIX lane of the full flora run: hold an ORIX GPU only while flora LLM steps run.

ORIX kills jobs that keep a GPU below 75 % utilization, and the flora pipeline alternates Qwen
steps (transcription, re-read, term rules, relations) with deterministic annotation passes that
take an hour or more on a large flora. So the pipeline runs here step by step
(``flopo2.ingest.pipeline --steps llm|cpu``):

- up to ``--active`` floras (largest first, WFO excluded) are worked on at once;
- their deterministic steps run on ws and need no GPU;
- their LLM steps run against a vLLM job on an ORIX freecycle GPU (``tools/orix/qwen_flopo.sbatch``)
  through an SSH tunnel via the login node; the job is submitted when a flora waits for an LLM step
  and cancelled as soon as none does, so while one flora annotates another can use the GPU;
- when the job is preempted or dies, the LLM steps in flight are stopped and resume from their
  caches on the next job (the pipeline's step markers skip what is complete).

Claims, done markers and the publish queue are shared with ``tools/run_floras_full.sh`` (the
unimatrix lane). State: ``local-corpora/run-logs/orix/state``, log ``.../orix/lane.log``.

    tmux new -d -s flopo-orix 'tools/orix_flora_lane.py'
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
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
    "eflora-foc", "kew-african", "eflora-fna", "nybg-naf", "fdac", "powo-neotropical", "eflora-other",
    "eflora-fop", "flora-zimbabwe", "flora-gabon", "flora-malesiana", "eflora-mfoc", "smithsonian-botany",
    "illinois-wildflowers", "flora-guianas", "feis-plants", "powo-ftea", "powo-fz", "usda-plants",
    "africa-tree-db", "plazi", "plants-tibet", "powo-ildis", "powo-kew", "powo-fwta", "phytokeys",
    "powo-fsom", "silvics-na", "powo-cayman", "korup-flora", "powo-cate", "powo-fiq", "powo-grassbase",
    "eflora-fom", "eflora-andes", "powo-tong",
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
    started: float = field(default_factory=time.time)


@dataclass
class Flora:
    src: str
    need: str = "cpu"           # what runs next: "cpu" or "llm"
    step: Step | None = None
    failures: int = 0
    retry_at: float = 0.0


class Orix:
    def __init__(self, host: str, local_port: int) -> None:
        self.host, self.port = host, local_port
        self.sock = OD / "tunnel.sock"
        self.job: str | None = None
        self.job_type = ""
        self.tunnel = False
        self.down_since: float | None = None
        self.up_since = 0.0

    def ssh(self, command: str, timeout: int = 90) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15", self.host, command],
            capture_output=True, text=True, timeout=timeout,
        )

    def idle_gpus(self) -> dict[str, int]:
        idle = {"h100": 0, "h200": 0}
        try:
            out = self.ssh("scontrol show node -o", timeout=60).stdout
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

    def submit(self) -> None:
        idle = self.idle_gpus()
        kind = "h100" if idle["h100"] > 0 or idle["h200"] <= 0 else "h200"
        try:
            res = self.ssh(f"cd {RDIR} && sbatch --parsable --partition=freecycle-{kind} --gres={GRES[kind]} qwen_flopo.sbatch")
        except subprocess.TimeoutExpired:
            log("sbatch timed out")
            return
        m = re.match(r"(\d+)", res.stdout.strip())
        if not m:
            log(f"sbatch: {(res.stdout + res.stderr).strip() or 'no answer'}")
            return
        self.job, self.job_type = m.group(1), kind
        (OD / "job").write_text(self.job + "\n")
        log(f"submitted job {self.job} to freecycle-{kind}")

    def job_state(self) -> str | None:
        """'RUNNING', 'PENDING', '' (ended) or None (cannot tell)."""
        try:
            res = self.ssh(f"squeue -h -j {self.job} -o '%T' 2>&1; echo \"END $?\"", timeout=120)
        except subprocess.TimeoutExpired:
            return None
        out = res.stdout
        if "END " not in out:
            return None
        body, rc = out.rsplit("END ", 1)
        if rc.strip() != "0":
            return "" if "Invalid job id" in body else None
        return body.strip().split("\n")[0] if body.strip() else ""

    def cancel(self, why: str) -> None:
        self.close_tunnel()
        if self.job:
            try:
                self.ssh(f"scancel {self.job}")
            except subprocess.TimeoutExpired:
                pass
            log(f"cancelled job {self.job}: {why}")
        self.job = None
        (OD / "job").unlink(missing_ok=True)
        (OD / "key").unlink(missing_ok=True)

    def connect(self) -> bool:
        """Fetch the endpoint and key of the running job and open the tunnel; True when healthy."""
        try:
            ep = self.ssh(f"cat {RDIR}/state/{self.job}.endpoint 2>/dev/null").stdout.split()
            if len(ep) != 2:
                return False
            host, port = ep
            ip = self.ssh(f"getent hosts {host}").stdout.split()
            key = self.ssh(f"cat {RDIR}/state/{self.job}.key").stdout.strip()
        except subprocess.TimeoutExpired:
            return False
        if not key:
            return False
        keyfile = OD / "key"
        fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(key + "\n")
        self.close_tunnel()
        target = ip[0] if ip else host
        res = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30",
             "-o", "ServerAliveCountMax=3", "-M", "-S", str(self.sock), "-f", "-N",
             "-L", f"127.0.0.1:{self.port}:{target}:{port}", self.host],
            capture_output=True, text=True, timeout=60,
        )
        if res.returncode != 0:
            log(f"tunnel to {host}:{port} failed: {res.stderr.strip()[:200]}")
            return False
        self.tunnel = True
        for _ in range(6):
            if self.healthy():
                log(f"qwen up: job {self.job} on {host}:{port}, local port {self.port}")
                self.up_since = time.time()
                return True
            time.sleep(10)
        log(f"no answer from {host}:{port} through the tunnel")
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

    def gpu_utilization(self) -> str:
        """Mean utilization over the job's logged samples after the server came up."""
        try:
            out = self.ssh(f"tail -n 20 {RDIR}/logs/gpu-{self.job}.csv 2>/dev/null").stdout
        except subprocess.TimeoutExpired:
            return "?"
        vals = [int(m.group(1)) for m in re.finditer(r",\s*(\d+) %", out)]
        return f"{sum(vals) / len(vals):.0f}% over the last {len(vals)} samples" if vals else "?"


class Lane:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.orix = Orix(args.host, args.local_port)
        self.floras: dict[str, Flora] = {}
        self.publisher: subprocess.Popen | None = None
        self.stopping = False
        self.last_util = 0.0

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
    def start_step(self, fl: Flora) -> None:
        cmd = [str(PY), "-m", "flopo2.ingest.pipeline", fl.src, "--limit", "0", "--steps", fl.need]
        if fl.need == "llm":
            cmd += ["--workers", str(self.args.workers), "--base-url", f"http://127.0.0.1:{self.args.local_port}/v1",
                    "--model", "qwen3.8-27b", "--key-file", str(OD / "key")]
        else:
            cmd += ["--workers", "4"]
        logf = (LOGS / f"{fl.src}.log").open("a", encoding="utf-8")
        logf.write(f"== {now()} [orix] {fl.need} steps\n")
        logf.flush()
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        fl.step = Step(proc, fl.need)

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

    def reap(self) -> None:
        for fl in list(self.floras.values()):
            if not fl.step or fl.step.proc.poll() is None:
                continue
            rc, kind = fl.step.proc.returncode, fl.step.kind
            fl.step = None
            if rc == 0:
                self.complete(fl)
            elif rc == 10:
                fl.need, fl.failures = "llm", 0
            elif rc == 11:
                fl.need, fl.failures = "cpu", 0
            elif kind == "llm" and not self.orix.healthy():
                pass  # the endpoint went away; rerun the LLM steps on the next job
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
                stdout=(LOGS / "orix/publish-console.log").open("a"), stderr=subprocess.STDOUT,
            )

    def release(self, fl: Flora) -> None:
        holder = (CLAIMS / fl.src)
        if holder.exists() and holder.read_text().split()[-1] == str(os.getpid()):
            holder.unlink()
        self.floras.pop(fl.src, None)

    # --- GPU ---------------------------------------------------------------------------------
    def tend_gpu(self) -> None:
        want = [f for f in self.floras.values() if f.need == "llm" and time.time() >= f.retry_at]
        running_llm = [f for f in self.floras.values() if f.step and f.step.kind == "llm"]
        o = self.orix
        if not want and not running_llm:
            if o.job:
                o.cancel("no flora waits for an LLM step")
            return
        if not o.job:
            o.submit()
            return
        st = o.job_state()
        if st is None:  # controller unreachable: trust the endpoint while it answers
            st = "RUNNING" if o.tunnel and o.healthy() else "UNKNOWN"
        if st == "":
            log(f"job {o.job} ended")
            for f in running_llm:
                self.stop_step(f)
            o.close_tunnel()
            o.job = None
            return
        if st == "PENDING":
            state(f"queued job {o.job} (freecycle-{o.job_type}); {len(want)} flora(s) wait for LLM steps")
            return
        if st != "RUNNING":
            return
        if not o.tunnel and not o.connect():
            return
        if not o.healthy():
            o.down_since = o.down_since or time.time()
            if time.time() - o.down_since > 120:
                log(f"endpoint of job {o.job} has not answered for 2 min; stopping its LLM steps")
                for f in running_llm:
                    self.stop_step(f)
                o.cancel("endpoint down")
                o.down_since = None
            return
        o.down_since = None
        for f in want:
            if not f.step:
                self.start_step(f)
        # Every 15 min, over the last 10 min (the model-loading minutes at 0 % are left out).
        if time.time() - max(self.last_util, o.up_since) > 900:
            self.last_util = time.time()
            log(f"job {o.job}: GPU utilization {o.gpu_utilization()}")

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
            what = f"{f.step.kind} steps running" if f.step else f"waits for {f.need}"
            parts.append(f"{f.src}: {what}")
        job = f"job {self.orix.job}" if self.orix.job else "no GPU job"
        state(f"{job}; " + ("; ".join(parts) if parts else "no flora left"))

    # --- main loop ---------------------------------------------------------------------------
    def shutdown(self, *_: object) -> None:
        self.stopping = True

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGHUP, self.shutdown)
        OD.mkdir(parents=True, exist_ok=True)
        CLAIMS.mkdir(parents=True, exist_ok=True)
        DONE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ssh", self.args.host, f"mkdir -p {RDIR}/logs {RDIR}/state"], check=True, timeout=60)
        subprocess.run(["scp", "-q", str(ROOT / "tools/orix/qwen_flopo.sbatch"), f"{self.args.host}:{RDIR}/"], check=True, timeout=60)
        log(f"lane start: up to {self.args.active} floras, {self.args.workers} LLM workers each, local port {self.args.local_port}")
        try:
            while not self.stopping:
                self.reap()
                self.pick_new()
                if not self.floras:
                    log("no flora left for the ORIX lane")
                    break
                self.tend_cpu()
                self.tend_gpu()
                self.report()
                for _ in range(30):
                    if self.stopping:
                        break
                    time.sleep(1)
        finally:
            for f in list(self.floras.values()):
                self.stop_step(f)
                self.release(f)
            if self.orix.job:
                self.orix.cancel("lane stopped")
            self.orix.close_tunnel()
            state("stopped")
            log("lane stopped")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("ORIX_HOST", "orix"))
    parser.add_argument("--local-port", type=int, default=int(os.environ.get("ORIX_LOCAL_PORT", 8200)))
    parser.add_argument("--active", type=int, default=2, help="floras worked on at once")
    parser.add_argument("--workers", type=int, default=48, help="concurrent requests per flora LLM step")
    parser.add_argument("--cpu-parallel", type=int, default=2, help="deterministic steps run at once on ws")
    parser.add_argument("--skip", default=os.environ.get("ORIX_SKIP", "wfo"), help="floras this lane leaves alone")
    return Lane(parser.parse_args()).run()


if __name__ == "__main__":
    random.seed()
    sys.exit(main())
