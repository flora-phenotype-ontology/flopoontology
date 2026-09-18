"""Rebuild the pinned BSPO import module used by E3 positional part restrictions.

Downloads the BSPO release named in ``ontology/imports/bspo_import.sha256``, refuses to continue
unless its SHA-256 matches the pin, and extracts a ROBOT BOT module for the term list
``ontology/imports/bspo_terms.txt``.  The module is annotated with a FLOPO import IRI, the BSPO
release as ``dcterms:source`` and the BSPO licence.

    uv run python tools/build_bspo_import.py [--source local-bspo.owl]
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = ROOT / "ontology" / "imports"
RELEASE = "2023-05-27"
RELEASE_IRI = f"http://purl.obolibrary.org/obo/bspo/releases/{RELEASE}/bspo.owl"
SOURCE_SHA256 = "9f1a7f1d6ae88fa0831fa553abf179c6a4f252c46d1b11e2fcc8373cfe02850c"
MODULE_IRI = "http://purl.obolibrary.org/obo/flopo/imports/bspo_import.owl"
VERSION_IRI = "http://purl.obolibrary.org/obo/flopo/releases/2026-09-18/imports/bspo_import.owl"
LICENSE = "https://creativecommons.org/licenses/by/3.0/"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--source", type=Path, help="local copy of the pinned BSPO release")
    parser.add_argument("--output", type=Path, default=IMPORTS / "bspo_import.owl")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        source = args.source
        if source is None:
            source = Path(tmp) / f"bspo-{RELEASE}.owl"
            urllib.request.urlretrieve(RELEASE_IRI, source)
        digest = sha256(source)
        if digest != SOURCE_SHA256:
            raise SystemExit(f"BSPO source checksum {digest} does not match the pin {SOURCE_SHA256}")
        subprocess.run(
            [
                "java", "-jar", str(ROOT / "tools" / "robot.jar"),
                "extract", "--input", str(source), "--method", "BOT",
                "--term-file", str(IMPORTS / "bspo_terms.txt"), "--individuals", "exclude",
                "annotate", "--ontology-iri", MODULE_IRI, "--version-iri", VERSION_IRI,
                "--annotation", "owl:versionInfo", RELEASE,
                "--link-annotation", "http://purl.org/dc/terms/source", RELEASE_IRI,
                "--link-annotation", "http://purl.org/dc/terms/license", LICENSE,
                "--output", str(args.output),
            ],
            check=True,
        )
    print(f"{sha256(args.output)}  {args.output.name}")


if __name__ == "__main__":
    main()
