#!/usr/bin/env python3
"""Embed the NCVC Saudi guide EQ phenotype module in flopo.owl and refresh the ID registry.

The module (``ontology/flopo-ncvc-eq-extension.ttl``) is added as a replaceable generated block
of the RDF/XML release. The tool refuses a module that is not identical to a fresh build of its
specification and block registry (``tools/build_flopo_ncvc_eq_extension.py``), so only accepted
rows reach the release. Afterwards the global registry ``config/flopo_id_registry.tsv`` is
regenerated from the resulting ontology, as for the machine-reviewed EQ release, and every
allocated class must appear there once with its signature.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import date
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, BNode, Graph, URIRef
from rdflib.compare import isomorphic

from flopo2.ids.registry import build_registry, write_registry_tsv
from tools.build_flopo_ncvc_eq_extension import (
    COMBINATIONS,
    FLOPO_REGISTRY,
    MODULE,
    OUTPUT,
    REGISTRY,
    SPEC,
    build_module,
)
from tools.update_flopo_release import _graph_fragment, _update_release_metadata


OBO = "http://purl.obolibrary.org/obo/"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO NCVC EQ PHENOTYPES -->"
END_MARKER = "  <!-- END GENERATED FLOPO NCVC EQ PHENOTYPES -->"
NODE_ID_PREFIX = "FLOPONcvcEQ_"


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated NCVC EQ markers in release OWL")
    if not begin_count:
        return text
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def _allocations(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {OBO + row["flopo_id"]: row for row in rows}


def module_fragment(module: Graph, allocations: dict[str, dict[str, str]]) -> tuple[str, set[str]]:
    """Return the RDF/XML fragment holding only the minted classes and their expressions."""

    if set(module.subjects(RDF.type, OWL.Ontology)) != {MODULE}:
        raise ValueError("NCVC EQ module must have exactly its expected ontology header")
    minted = {
        str(subject)
        for subject in module.subjects(DCTERMS.contributor, None)
        if isinstance(subject, URIRef) and str(subject).startswith(OBO + "FLOPO_")
    }
    if minted != set(allocations):
        raise ValueError("NCVC EQ module classes do not match the block registry")
    fragment_graph = Graph()
    for subject, predicate, obj in module:
        if subject == MODULE:
            continue
        if isinstance(subject, URIRef) and str(subject) not in minted:
            continue  # declaration of a referenced PO/PATO/FLOPO class or property
        fragment_graph.add((subject, predicate, obj))
    orphans = {s for s in fragment_graph.subjects() if isinstance(s, BNode)} - {
        o for o in fragment_graph.objects() if isinstance(o, BNode)
    }
    if orphans:
        raise ValueError("NCVC EQ module contains unreachable anonymous expressions")
    fragment, count = _graph_fragment(fragment_graph, node_id_prefix=NODE_ID_PREFIX)
    if count != len(minted):
        raise ValueError("NCVC EQ release fragment contains unexpected FLOPO classes")
    return fragment.strip(), minted


def update_release(
    release_path: Path,
    module_path: Path,
    release_date: str,
    *,
    spec_path: Path = SPEC,
    registry_path: Path = REGISTRY,
    flopo_registry_path: Path = FLOPO_REGISTRY,
    combinations_path: Path = COMBINATIONS,
) -> dict[str, object]:
    date.fromisoformat(release_date)
    module = Graph().parse(module_path.as_posix(), format="turtle")
    module_date = str(next(module.objects(MODULE, DCTERMS.created)))
    fresh = build_module(
        spec_path, registry_path, flopo_registry_path, combinations_path, module_date
    )
    if not isomorphic(module, fresh):
        raise ValueError(
            "NCVC EQ module differs from a fresh build of its specification; rebuild with "
            "`python -m tools.build_flopo_ncvc_eq_extension build`"
        )
    allocations = _allocations(registry_path)
    fragment, minted = module_fragment(module, allocations)

    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    for class_iri in minted:
        if f'"{class_iri}"' in text:
            raise ValueError(f"allocated class already occurs in the release: {class_iri}")
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    payload = text.replace(closing, f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n{closing}", 1)

    # The temporary files keep their extension: rdflib and the registry builder pick the RDF/XML
    # and TSV readers from it.
    release_temp = release_path.with_name(f"{release_path.stem}.ncvc-tmp{release_path.suffix}")
    registry_temp = flopo_registry_path.with_name(
        f"{flopo_registry_path.stem}.ncvc-tmp{flopo_registry_path.suffix}"
    )
    try:
        release_temp.write_text(payload, encoding="utf-8")
        check = Graph().parse(release_temp.as_posix())
        if (MODULE, RDF.type, OWL.Ontology) in check:
            raise ValueError("NCVC EQ module ontology header leaked into flopo.owl")
        write_registry_tsv(build_registry(release_temp), registry_temp)
        with registry_temp.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        by_iri = {row["flopo_iri"]: row for row in rows}
        active: dict[str, int] = {}
        for row in rows:
            if row["deprecated"] not in {"1", "true", "True"} and row["signature"] != "OTHER":
                active[row["signature"]] = active.get(row["signature"], 0) + 1
        for class_iri, allocation in allocations.items():
            published = by_iri.get(class_iri)
            if published is None:
                raise ValueError(f"regenerated registry omitted {class_iri}")
            if published["signature"] != allocation["signature"]:
                raise ValueError(f"signature drift for {class_iri}: {published['signature']}")
            if published["label"] != allocation["label"]:
                raise ValueError(f"label drift for {class_iri}: {published['label']}")
            if active.get(allocation["signature"]) != 1:
                raise ValueError(f"{allocation['signature']} duplicates an active FLOPO class")
        os.replace(release_temp, release_path)
        os.replace(registry_temp, flopo_registry_path)
    finally:
        release_temp.unlink(missing_ok=True)
        registry_temp.unlink(missing_ok=True)
    kinds: dict[str, int] = {}
    for allocation in allocations.values():
        kinds[allocation["kind"]] = kinds.get(allocation["kind"], 0) + 1
    ids = sorted(row["flopo_id"] for row in allocations.values())
    return {
        "classes": len(minted),
        "by_kind": dict(sorted(kinds.items())),
        "flopo_id_range": [ids[0], ids[-1]] if ids else [],
        "release_date": release_date,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--module", type=Path, default=OUTPUT)
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--id-registry", type=Path, default=REGISTRY)
    parser.add_argument("--flopo-registry", type=Path, default=FLOPO_REGISTRY)
    parser.add_argument("--combinations", type=Path, default=COMBINATIONS)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    result = update_release(
        args.release,
        args.module,
        args.date,
        spec_path=args.spec,
        registry_path=args.id_registry,
        flopo_registry_path=args.flopo_registry,
        combinations_path=args.combinations,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
