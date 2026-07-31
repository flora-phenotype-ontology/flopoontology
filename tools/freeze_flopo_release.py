#!/usr/bin/env python3
"""Freeze a compact compatibility manifest for an immutable FLOPO release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from rdflib import OWL, RDF, Graph, Literal, URIRef

OBO = "http://purl.obolibrary.org/obo/"
FLOPO_ONTOLOGY = URIRef(OBO + "flopo.owl")
FLOPO_PREFIX = OBO + "FLOPO_"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_true(value: Literal) -> bool:
    return str(value).strip().casefold() == "true"


def freeze(
    ontology_path: Path,
    inferred_path: Path,
    out_dir: Path,
    *,
    source_commit: str,
    release_name: str,
) -> dict[str, object]:
    graph = Graph().parse(ontology_path.as_posix())
    class_iris = sorted(
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(FLOPO_PREFIX)
    )
    deprecated = sum(
        1
        for class_iri in class_iris
        if any(
            isinstance(value, Literal) and _is_true(value)
            for value in graph.objects(URIRef(class_iri), OWL.deprecated)
        )
    )
    version_iris = sorted(map(str, graph.objects(FLOPO_ONTOLOGY, OWL.versionIRI)))
    version_info = sorted(map(str, graph.objects(FLOPO_ONTOLOGY, OWL.versionInfo)))
    if len(version_iris) != 1 or len(version_info) != 1:
        raise ValueError("FLOPO release must have exactly one versionIRI and versionInfo")

    artifacts = {}
    for name, path in (("flopo.owl", ontology_path), ("flopo-inferred.owl", inferred_path)):
        artifacts[name] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    manifest: dict[str, object] = {
        "release": release_name,
        "source_commit": source_commit,
        "ontology_iri": str(FLOPO_ONTOLOGY),
        "version_iri": version_iris[0],
        "version_info": version_info[0],
        "flopo_class_count": len(class_iris),
        "deprecated_class_count": deprecated,
        "artifacts": artifacts,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "flopo-class-iris.txt").write_text(
        "".join(f"{class_iri}\n" for class_iri in class_iris),
        encoding="utf-8",
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--inferred", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--release-name", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = freeze(
        args.ontology,
        args.inferred,
        args.out_dir,
        source_commit=args.source_commit,
        release_name=args.release_name,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
