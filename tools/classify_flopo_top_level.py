#!/usr/bin/env python3
"""Create the complete, deterministic FLOPO root-child reparenting ledger."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef

OBO = "http://purl.obolibrary.org/obo/"
FLOPO_ROOT = URIRef(OBO + "FLOPO_0000000")
CONTINUANT = "FLOPO_0980417"
OCCURRENT = "FLOPO_0980422"
ANATOMICAL_ENTITY = "FLOPO_0980418"
PLANT_STRUCTURE = "FLOPO_0018579"
ANATOMICAL_SPACE = "FLOPO_0017857"
PLANT_SUBSTANCE = "FLOPO_0900047"

MANUAL_PARENTS = {
    "FLOPO_0980068": {
        "bearer_po_id": "PO:0009052",
        "category": "manual_pedicel",
        "new_parent": "FLOPO_0000201",
        "classification_method": (
            "approved manual repair: pedicel ciliatedness is placed under the existing "
            "pedicel phenotype"
        ),
        "review_status": "approved",
    }
}

FIELDS = (
    "flopo_id",
    "label",
    "signature",
    "bearer_po_id",
    "category",
    "new_parent",
    "classification_method",
    "review_status",
)


def _registry(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    result = {
        row["flopo_iri"].removeprefix(OBO): row
        for row in rows
        if row["flopo_iri"].startswith(OBO + "FLOPO_")
    }
    if len(result) != len(rows):
        raise ValueError("registry contains duplicate or noncanonical FLOPO IRIs")
    return result


def _po_parents(path: Path) -> dict[str, set[str]]:
    parents: dict[str, set[str]] = {}
    current: str | None = None
    in_term = False
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line == "[Term]":
                in_term = True
                current = None
                continue
            if line.startswith("[") and line != "[Term]":
                in_term = False
                current = None
                continue
            if not in_term:
                continue
            if line.startswith("id: PO:"):
                current = line.removeprefix("id: ").replace(":", "_", 1)
                parents.setdefault(current, set())
            elif current is not None and line.startswith("is_a: PO:"):
                parent = line.removeprefix("is_a: ").split(" ! ", 1)[0]
                parents[current].add(parent.replace(":", "_", 1))
    return parents


def _ancestors(term: str, parents: dict[str, set[str]]) -> set[str]:
    if term not in parents:
        raise ValueError(f"PO bearer is absent from the pinned source: {term}")
    result = {term}
    frontier = [term]
    while frontier:
        current = frontier.pop()
        for parent in parents.get(current, set()):
            if parent not in result:
                result.add(parent)
                frontier.append(parent)
    return result


def _classify_po_bearer(term: str, parents: dict[str, set[str]]) -> dict[str, str]:
    ancestry = _ancestors(term, parents)
    if term == "PO_0009011":
        return {
            "category": "plant_structure_root",
            "new_parent": ANATOMICAL_ENTITY,
        }
    if "PO_0009011" in ancestry:
        return {
            "category": "plant_structure",
            "new_parent": PLANT_STRUCTURE,
        }
    if term == "PO_0025117":
        return {
            "category": "anatomical_space_root",
            "new_parent": CONTINUANT,
        }
    if "PO_0025117" in ancestry:
        return {
            "category": "anatomical_space",
            "new_parent": ANATOMICAL_SPACE,
        }
    if term == "PO_0025161":
        return {
            "category": "plant_substance_root",
            "new_parent": ANATOMICAL_ENTITY,
        }
    if "PO_0025161" in ancestry:
        return {
            "category": "plant_substance",
            "new_parent": PLANT_SUBSTANCE,
        }
    if "PO_0025131" in ancestry:
        return {
            "category": "anatomical_entity",
            "new_parent": ANATOMICAL_ENTITY,
        }
    raise ValueError(f"no approved upper-level category for PO bearer {term}")


def classify(
    release_path: Path,
    registry_path: Path,
    po_path: Path,
) -> list[dict[str, str]]:
    graph = Graph().parse(release_path.as_posix())
    registry = _registry(registry_path)
    po_parents = _po_parents(po_path)
    direct_children = {
        str(child).removeprefix(OBO)
        for child in graph.subjects(RDFS.subClassOf, FLOPO_ROOT)
        if isinstance(child, URIRef)
        and str(child).startswith(OBO + "FLOPO_")
        and (child, RDF.type, OWL.Class) in graph
    }
    legacy_children = direct_children - {CONTINUANT, OCCURRENT}

    rows: list[dict[str, str]] = []
    for flopo_id in sorted(legacy_children):
        if flopo_id not in registry:
            raise ValueError(f"direct root child is absent from the registry: {flopo_id}")
        registry_row = registry[flopo_id]
        signature = registry_row["signature"]
        if flopo_id in MANUAL_PARENTS:
            classification = MANUAL_PARENTS[flopo_id]
            bearer = classification["bearer_po_id"]
        else:
            if not signature.startswith("PHENO|PO_"):
                raise ValueError(
                    f"direct root child has no PHENO bearer and no approved exception: "
                    f"{flopo_id} ({signature})"
                )
            bearer_token = signature.split("|", 1)[1]
            bearer = bearer_token.replace("_", ":", 1)
            classification = _classify_po_bearer(bearer_token, po_parents)
            classification = {
                **classification,
                "classification_method": "transitive is_a ancestry in ont/plant_ontology.obo",
                "review_status": "deterministic",
            }
        rows.append(
            {
                "flopo_id": flopo_id,
                "label": registry_row["label"],
                "signature": signature,
                "bearer_po_id": bearer,
                "category": classification["category"],
                "new_parent": classification["new_parent"],
                "classification_method": classification["classification_method"],
                "review_status": classification["review_status"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--po", type=Path, default=Path("ont/plant_ontology.obo")
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("curation/flopo_top_level_reparenting.tsv"),
    )
    parser.add_argument("--expected-count", type=int, default=256)
    args = parser.parse_args()

    rows = classify(args.release, args.registry, args.po)
    if len(rows) != args.expected_count:
        raise ValueError(
            f"expected {args.expected_count} legacy root children, found {len(rows)}"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(row["category"] for row in rows)
    print(f"root_children {len(rows) + 2}")
    print(f"reparented {len(rows)}")
    for category, count in sorted(counts.items()):
        print(f"{category} {count}")
    print(f"output {args.out}")


if __name__ == "__main__":
    main()
