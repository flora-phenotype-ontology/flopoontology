#!/usr/bin/env python3
"""Run the official OBO Dashboard against the local FLOPO release artifact.

The Dashboard combines checks of the OWL release with checks of FLOPO's live OBO
registry entry.  This wrapper runs the exact container used by the public Dashboard,
then fails unless every currently implemented check ran and the Dashboard considers
the ontology to have passed (that is, no ERROR result).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from re import search

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ONTOLOGY = ROOT / "ontology" / "flopo.owl"
DEFAULT_CONFIG = ROOT / "config" / "obo_dashboard.yml"
DEFAULT_IMAGE = (
    "anitacaron/obo-dashboard@"
    "sha256:2cccfdb398af41d475ed3a5730e0a69c25a7434a0c45e8d00a44ff1aaee0a817"
)
OBO_DASHBOARD_COMMIT = "c3601a04810d5298643bcc6468acd2a5c3d0f08e"
ROBOT_VERSION = "1.9.8"
ROBOT_GATEWAY_VERSION = "1.9.5"
ROBOT_GATEWAY_SHA256 = "21e96a9f6ac90dacdb6fa1303ac9b49b0d2be3594ecacf4c0e3d0e68e86def57"
PUBLIC_DASHBOARD_URL = "https://dashboard.obofoundry.org/dashboard/index.html"

EXPECTED_RESULTS = {
    "FP01 Open",
    "FP02 Common Format",
    "FP03 URIs",
    "FP04 Versioning",
    "FP05 Scope",
    "FP06 Textual Definitions",
    "FP07 Relations",
    "FP08 Documented",
    "FP09 Plurality of Users",
    "FP11 Locus of Authority",
    "FP12 Naming Conventions",
    "FP16 Maintenance",
    "FP20 Responsiveness",
    "ROBOT Report",
}
VALID_STATUSES = {"PASS", "INFO", "WARN", "ERROR"}


@dataclass(frozen=True)
class GateAssessment:
    failures: tuple[str, ...]
    notices: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def load_dashboard(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Dashboard result is not a YAML mapping: {path}")
    return data


def assess_public_dashboard_version(html: str) -> GateAssessment:
    """Confirm that our reproducible runner is still the public runner."""

    failures: list[str] = []
    commit_match = search(
        r"github\.com/OBOFoundry/OBO-Dashboard/commit/([0-9a-f]{40})", html
    )
    robot_match = search(r"ROBOT version ([0-9]+(?:\.[0-9]+)+)", html)
    if commit_match is None:
        failures.append("Public Dashboard page does not advertise its source commit")
    elif commit_match.group(1) != OBO_DASHBOARD_COMMIT:
        failures.append(
            "Public Dashboard now uses OBO-Dashboard commit "
            f"{commit_match.group(1)}; review its checks and update the pinned image"
        )
    if robot_match is None:
        failures.append("Public Dashboard page does not advertise its ROBOT version")
    elif robot_match.group(1) != ROBOT_VERSION:
        failures.append(
            f"Public Dashboard now uses ROBOT {robot_match.group(1)}; "
            "review the report changes and update the pinned profile"
        )
    return GateAssessment(tuple(failures), ())


def verify_public_dashboard_version(timeout: float = 30.0) -> None:
    """Fail closed if the public Dashboard no longer matches our pinned runner."""

    request = urllib.request.Request(
        PUBLIC_DASHBOARD_URL,
        headers={"User-Agent": "FLOPO-OBO-Dashboard-gate/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8")
    except (OSError, UnicodeError, urllib.error.URLError) as error:
        raise RuntimeError(
            f"could not verify the public Dashboard version at {PUBLIC_DASHBOARD_URL}: {error}"
        ) from error
    assessment = assess_public_dashboard_version(html)
    if not assessment.passed:
        raise RuntimeError("; ".join(assessment.failures))


def assess_dashboard(data: dict, *, require_all_pass: bool = False) -> GateAssessment:
    """Assess a Dashboard YAML result using the public Dashboard's pass policy."""

    failures: list[str] = []
    notices: list[str] = []

    if data.get("failure"):
        failures.append(f"Dashboard preprocessing failed: {data['failure']}")

    results = data.get("results")
    if not isinstance(results, dict):
        failures.append("Dashboard produced no results mapping")
        results = {}

    missing = sorted(EXPECTED_RESULTS - set(results))
    unexpected = sorted(set(results) - EXPECTED_RESULTS)
    if missing:
        failures.append("Dashboard did not run checks: " + ", ".join(missing))
    if unexpected:
        failures.append("Unreviewed Dashboard checks appeared: " + ", ".join(unexpected))

    for name in sorted(EXPECTED_RESULTS & set(results)):
        result = results[name]
        if not isinstance(result, dict):
            failures.append(f"{name} has a malformed result")
            continue
        status = result.get("status")
        comment = result.get("comment", "")
        suffix = f": {comment}" if comment else ""
        if status not in VALID_STATUSES:
            failures.append(f"{name} has unknown status {status!r}")
        elif status == "ERROR":
            failures.append(f"{name} = ERROR{suffix}")
        elif require_all_pass and status != "PASS":
            failures.append(f"{name} = {status}{suffix}")
        elif status != "PASS":
            notices.append(f"{name} = {status}{suffix}")

    summary = data.get("summary")
    if not isinstance(summary, dict) or summary.get("status") not in VALID_STATUSES:
        failures.append("Dashboard produced no valid summary status")
        summary = {}
    elif summary.get("status") == "ERROR":
        failures.append(f"Dashboard summary = ERROR: {summary.get('comment', '')}".rstrip())
    if require_all_pass and summary.get("status") != "PASS":
        failures.append(f"Dashboard summary is not PASS: {summary.get('status')!r}")

    robot_report = results.get("ROBOT Report")
    robot_counts = robot_report.get("results") if isinstance(robot_report, dict) else None
    if not isinstance(robot_counts, dict) or not isinstance(robot_counts.get("ERROR"), int):
        failures.append("Dashboard produced no valid ROBOT Report error count")
    elif robot_counts["ERROR"] != 0:
        failures.append(f"ROBOT Report contains {robot_counts['ERROR']} errors")

    metrics = data.get("metrics") or {}
    if metrics.get("Info: Logical consistency") is not True:
        failures.append("Dashboard did not establish logical consistency")
    unsatisfiable = metrics.get("Entities: Number of unsatisfiable classes")
    if unsatisfiable != 0:
        failures.append(f"Dashboard found {unsatisfiable!r} unsatisfiable classes")
    if metrics.get("Info: Syntax") != "RDF/XML Syntax":
        failures.append(
            f"Dashboard did not recognize RDF/XML: {metrics.get('Info: Syntax')!r}"
        )

    return GateAssessment(tuple(dict.fromkeys(failures)), tuple(notices))


def _chown_cache(cache: Path, image: str) -> None:
    """Return container-created cache files to the invoking user."""

    if not cache.exists() or not hasattr(os, "getuid"):
        return
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{cache.resolve()}:/cache",
            image,
            "chown",
            "-R",
            f"{os.getuid()}:{os.getgid()}",
            "/cache",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _clear_previous_run(cache: Path) -> None:
    dashboard = cache / "dashboard"
    if dashboard.exists():
        shutil.rmtree(dashboard)
    dashboard.mkdir(parents=True)

    ontology_dir = cache / "build" / "ontologies"
    ontology_dir.mkdir(parents=True, exist_ok=True)
    for name in ("flopo-raw.owl", "flopo.owl", "flopo-metrics.yml"):
        path = ontology_dir / name
        if path.exists():
            path.unlink()


def _verify_robot_gateway(cache: Path) -> None:
    """Pin the Java gateway jar that the upstream Dashboard Makefile downloads."""

    robot_jar = cache / "build" / "robot.jar"
    if not robot_jar.is_file():
        raise RuntimeError("official Dashboard did not materialize build/robot.jar")
    digest = hashlib.sha256(robot_jar.read_bytes()).hexdigest()
    if digest != ROBOT_GATEWAY_SHA256:
        raise RuntimeError(
            "official Dashboard ROBOT gateway jar changed: "
            f"expected {ROBOT_GATEWAY_SHA256}, found {digest}"
        )


def run_dashboard(ontology: Path, config: Path, cache: Path, image: str) -> Path:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is required to run the official OBO Dashboard")
    if not ontology.is_file():
        raise FileNotFoundError(f"FLOPO release artifact is missing: {ontology}")
    if not config.is_file():
        raise FileNotFoundError(f"Dashboard configuration is missing: {config}")

    cache.mkdir(parents=True, exist_ok=True)
    _chown_cache(cache, image)
    _clear_previous_run(cache)
    ontology_dir = cache / "build" / "ontologies"
    shutil.copy2(ontology, ontology_dir / "flopo-raw.owl")
    # The official runner skips its download when this fresh base placeholder exists,
    # then regenerates the real base and metrics from flopo-raw.owl.
    shutil.copy2(ontology, ontology_dir / "flopo.owl")
    (cache / "dependencies").mkdir(exist_ok=True)

    command = [
        "docker",
        "run",
        "--rm",
        "-e",
        "ROBOT_JAVA_ARGS=-Xmx16G",
        "-e",
        "JAVA_OPTS=-Xmx16G",
        "-v",
        f"{config.resolve()}:/tools/dashboard-config.yml:ro",
        "-v",
        f"{(cache / 'build').resolve()}:/tools/build",
        "-v",
        f"{(cache / 'dashboard').resolve()}:/tools/dashboard",
        "-v",
        f"{(cache / 'dependencies').resolve()}:/tools/dependencies",
        "-w",
        "/tools",
        image,
        "python",
        "util/dashboard_config.py",
        "rundashboard",
        "-C",
        "dashboard-config.yml",
    ]
    try:
        subprocess.run(command, check=True)
        _verify_robot_gateway(cache)
    finally:
        _chown_cache(cache, image)

    result = cache / "dashboard" / "flopo" / "dashboard.yml"
    if not result.is_file():
        raise RuntimeError(
            "The official Dashboard produced no FLOPO result; inspect "
            f"{cache / 'dashboard'} and the command output above"
        )
    return result


def _default_cache() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "flopo-obo-dashboard"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache-dir", type=Path, default=_default_cache())
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument(
        "--results",
        type=Path,
        help="Assess an existing dashboard.yml instead of running Docker.",
    )
    parser.add_argument(
        "--all-pass",
        action="store_true",
        help="Also reject INFO and WARN results (stricter than OBO's pass definition).",
    )
    parser.add_argument(
        "--skip-upstream-pin-check",
        action="store_true",
        help="Do not verify that the pinned runner still matches the public Dashboard.",
    )
    args = parser.parse_args()

    try:
        if args.results is None and not args.skip_upstream_pin_check:
            verify_public_dashboard_version()
        result_path = args.results or run_dashboard(
            args.ontology, args.config, args.cache_dir, args.image
        )
        assessment = assess_dashboard(
            load_dashboard(result_path), require_all_pass=args.all_pass
        )
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"OBO Dashboard gate failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    for notice in assessment.notices:
        print(f"NOTICE: {notice}")
    if not assessment.passed:
        for failure in assessment.failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        print(f"OBO Dashboard result: {result_path}", file=sys.stderr)
        raise SystemExit(1)

    print(f"OBO Dashboard gate passed ({len(EXPECTED_RESULTS)} checks, zero errors)")
    print(f"OBO Dashboard result: {result_path}")


if __name__ == "__main__":
    main()
