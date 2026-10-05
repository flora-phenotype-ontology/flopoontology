"""Shared upper-level classification for phenotype bearers.

FLOPO phenotype groupings are classified by the pinned Plant Ontology ancestry of
their bearer.  Keeping this logic next to the OWL builders prevents newly promoted
phenotype parents from becoming accidental direct children of ``flora phenotype``.
"""

from __future__ import annotations

from pathlib import Path

CONTINUANT_TARGET = "FLOPO_0980417"
ANATOMICAL_ENTITY = "FLOPO_0980418"
PLANT_STRUCTURE = "FLOPO_0018579"
ANATOMICAL_SPACE = "FLOPO_0017857"
PLANT_SUBSTANCE = "FLOPO_0900047"


def load_po_parents(path: Path) -> dict[str, set[str]]:
    """Read the asserted ``is_a`` graph from the pinned PO OBO source."""

    parents: dict[str, set[str]] = {}
    current: str | None = None
    in_term = False
    with Path(path).open(encoding="utf-8") as handle:
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


def po_ancestors(term: str, parents: dict[str, set[str]]) -> set[str]:
    """Return the reflexive transitive ``is_a`` ancestry of one PO class."""

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


def phenotype_parent_for_po(term: str, parents: dict[str, set[str]]) -> str:
    """Return the most specific approved FLOPO grouping for a PO bearer."""

    ancestry = po_ancestors(term, parents)
    if term == "PO_0009011":
        return ANATOMICAL_ENTITY
    if "PO_0009011" in ancestry:
        return PLANT_STRUCTURE
    if term == "PO_0025117":
        return CONTINUANT_TARGET
    if "PO_0025117" in ancestry:
        return ANATOMICAL_SPACE
    if term == "PO_0025161":
        return ANATOMICAL_ENTITY
    if "PO_0025161" in ancestry:
        return PLANT_SUBSTANCE
    if "PO_0025131" in ancestry:
        return ANATOMICAL_ENTITY
    raise ValueError(f"no approved upper-level category for PO bearer {term}")
