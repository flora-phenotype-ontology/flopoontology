#!/usr/bin/env python3
"""Record the post-publication validation of a FLOPO release in ``releases/<date>/validation.json``.

Run after the GitHub release with its three assets exists and the full Dashboard gate
(``tools/obo_dashboard_gate.py`` without ``--pending-version``) has passed on it:

- downloads the three published assets and records byte counts and SHA-256 digests, checking
  that they equal the local artifacts;
- resolves the dated version PURL and checks it serves the same bytes;
- copies the official Dashboard result from the gate's cache;
- runs the frozen-release compatibility test and the release test set and records their output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("flopo.owl", "flopo-inferred.owl", "flopo-light.owl")
REPO = "https://github.com/flora-phenotype-ontology/flopoontology"
DASHBOARD = Path.home() / ".cache/flopo-obo-dashboard/dashboard/flopo/dashboard.yml"
RELEASE_TESTS = [
    "tests/test_flopo_release_compatibility.py",
    "tests/test_flopo_anatomy_support_extension.py",
    "tests/test_flopo_botanical_extension_2.py",
    "tests/test_flopo_growth_form_extension.py",
    "tests/test_flopo_pubescent_materialization.py",
    "tests/test_flora_value_terms.py",
    "tests/test_trait_phenotype.py",
    "tests/test_flopo_flora_corrections.py",
    "tests/test_eq_release.py",
]


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        return response.read()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(command: list[str]) -> dict:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    return {"command": " ".join(command), "exit_code": completed.returncode, "output": completed.stdout[-1500:]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, help="YYYY-MM-DD")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--prepublication-summary", default="")
    args = parser.parse_args()
    out_dir = ROOT / "releases" / args.release
    out_dir.mkdir(parents=True, exist_ok=True)

    assets = {}
    for name in ASSETS:
        url = f"{REPO}/releases/download/v{args.release}/{name}"
        data = _fetch(url)
        local = (ROOT / "ontology" / name).read_bytes()
        if _digest(data) != _digest(local):
            print(f"published {name} differs from the local artifact", file=sys.stderr)
            return 1
        assets[name] = {"bytes": len(data), "sha256": _digest(data), "url": url}
    purl = f"http://purl.obolibrary.org/obo/flopo/releases/{args.release}/flopo.owl"
    purl_bytes = _fetch(purl)
    if _digest(purl_bytes) != assets["flopo.owl"]["sha256"]:
        print("the version PURL does not serve the published flopo.owl", file=sys.stderr)
        return 1

    dashboard = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    if dashboard.get("version") != purl:
        print(f"dashboard cache is for {dashboard.get('version')}, not {purl}; rerun the full gate", file=sys.stderr)
        return 1
    if dashboard["summary"]["summary_count"].get("ERROR", 0):
        print("dashboard reports errors; not recording a passing validation", file=sys.stderr)
        return 1
    if isinstance(dashboard.get("date"), (dt.date, dt.datetime)):
        dashboard["date"] = dashboard["date"].isoformat()

    compat = _run([".venv/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   f"tests/test_flopo_release_compatibility.py::test_later_public_releases_are_preserved[{args.release}]"])
    tests = _run([".venv/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *RELEASE_TESTS])
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    record = {
        "release": args.release,
        "release_url": f"{REPO}/releases/tag/v{args.release}",
        "source_commit": args.source_commit,
        "verified_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "assets": assets,
        "version_purl": {"url": purl, "bytes": len(purl_bytes), "sha256": _digest(purl_bytes)},
        "artifact_verification": {
            "frozen_class_count": manifest["flopo_class_count"],
            "deprecated_class_count": manifest["deprecated_class_count"],
            "published_assets_equal_local_artifacts": True,
        },
        "official_obo_dashboard": dashboard,
        "frozen_release_compatibility_test": compat,
        "tests": tests,
        "prepublication_summary": args.prepublication_summary,
    }
    (out_dir / "validation.json").write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"assets": {k: v["sha256"][:12] for k, v in assets.items()},
                      "dashboard": dashboard["summary"], "compat_exit": compat["exit_code"], "tests_exit": tests["exit_code"]}, indent=1))
    return 0 if compat["exit_code"] == 0 and tests["exit_code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
