#!/usr/bin/env python3
"""Classify FLOPO against the local PO/PATO hierarchies without broad import leakage.

The source PO and PATO snapshots declare support imports whose combined closure includes
large animal-oriented GO/UBERON modules.  Those modules are not needed to classify FLOPO
phenotypes and currently contain cross-release contradictions.  This command removes only
the import declarations, merges the local FLOPO, PO, PATO, and pinned plant-GO axioms, and
runs ELK over that controlled development closure.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from rdflib import OWL, RDFS, Graph, URIRef


OBO = "http://purl.obolibrary.org/obo/"
FLOPO_ONTOLOGY = URIRef(OBO + "flopo.owl")
FLOPO_ROOT = URIRef(OBO + "FLOPO_0000000")


def obo_without_imports(text: str) -> str:
    """Remove OBO import header clauses while preserving every local ontology stanza."""

    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not line.startswith("import: ")
    )


def _robot_command(root: Path, configured: str | None = None) -> list[str]:
    if configured:
        return [configured]
    wrapper = root / "bin" / "robot"
    if wrapper.is_file() and os.access(wrapper, os.X_OK):
        return [str(wrapper)]
    installed = shutil.which("robot")
    if installed:
        return [installed]
    java = shutil.which("java")
    jar = root / "tools" / "robot.jar"
    if java and jar.is_file():
        return [java, "-jar", str(jar)]
    raise RuntimeError("ROBOT is required to classify the FLOPO release")


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"ROBOT command failed ({completed.returncode}): {detail}")


def classify_release(
    source_path: Path,
    output_path: Path,
    po_path: Path,
    pato_path: Path,
    go_path: Path,
    robot: str | None = None,
) -> dict[str, int | str]:
    root = Path(__file__).resolve().parents[1]
    robot_command = _robot_command(root, robot)

    source = Graph().parse(source_path.as_posix())
    source_version = next(source.objects(FLOPO_ONTOLOGY, OWL.versionInfo), None)
    if source_version is None:
        raise ValueError("FLOPO source lacks owl:versionInfo")

    with tempfile.TemporaryDirectory(prefix="flopo-classify-") as directory:
        work = Path(directory)
        local_source = Graph()
        for triple in source:
            if triple[1] != OWL.imports:
                local_source.add(triple)
        source_local_path = work / "flopo-local.owl"
        local_source.serialize(source_local_path.as_posix(), format="xml")

        converted_inputs: list[Path] = []
        for name, ontology_path in (("po", po_path), ("pato", pato_path)):
            local_obo = work / f"{name}-local.obo"
            local_obo.write_text(
                obo_without_imports(ontology_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
            converted = work / f"{name}-local.owl"
            _run(
                [
                    *robot_command,
                    "convert",
                    "--input",
                    str(local_obo),
                    "--output",
                    str(converted),
                ]
            )
            converted_inputs.append(converted)

        merged = work / "flopo-classification-input.owl"
        _run(
            [
                *robot_command,
                "merge",
                "--input",
                str(source_local_path),
                "--input",
                str(converted_inputs[0]),
                "--input",
                str(converted_inputs[1]),
                "--input",
                str(go_path),
                "--output",
                str(merged),
            ]
        )
        classified = work / "flopo-inferred.owl"
        _run(
            [
                *robot_command,
                "reason",
                "--reasoner",
                "ELK",
                "--input",
                str(merged),
                "--output",
                str(classified),
            ]
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(classified, output_path)

    check = Graph().parse(output_path.as_posix())
    classified_version = next(check.objects(FLOPO_ONTOLOGY, OWL.versionInfo), None)
    if classified_version != source_version:
        raise ValueError("classified release did not preserve the source version")
    direct_root_children = {
        cls
        for cls in check.subjects(RDFS.subClassOf, FLOPO_ROOT)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    return {
        "version": str(source_version),
        "triples": len(check),
        "direct_root_children": len(direct_root_children),
        "out": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--output", type=Path, default=Path("ontology/flopo-inferred.owl")
    )
    parser.add_argument("--po", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--pato", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument(
        "--go", type=Path, default=Path("ontology/imports/go_import.owl")
    )
    parser.add_argument("--robot", default=None)
    args = parser.parse_args()
    stats = classify_release(
        args.source,
        args.output,
        args.po,
        args.pato,
        args.go,
        args.robot,
    )
    for key, value in stats.items():
        print(f"{key} {value}")


if __name__ == "__main__":
    main()
