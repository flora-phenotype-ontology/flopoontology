"""The position of a part among the parts of its kind: 'has position' (pattern 18).

"Basal leaves spatulate" is a statement about those leaves that are basal. The position selects
the bearer; the trait is what is said of it. Both are qualities of the same part, so both could be
written with 'has characteristic' (RO:0000053), and until 2026-11-23 they were. A relation of its
own keeps them apart:

    'has position' SubPropertyOf 'has characteristic'
    has part some (leaf and 'has position' some basal and 'has characteristic' some spatulate)

and gives the positioned part a class expression, ``leaf and 'has position' some basal``. FLOPO
names the frequent ones (``'basal leaf' EquivalentTo leaf and 'has position' some basal``,
``config/flopo_positioned_parts.tsv``); the others stay expressions in the annotation, and a
reasoner treats both alike.

The position values are PATO position qualities and FLOPO value classes beneath PATO:0000140.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

OBO = "http://purl.obolibrary.org/obo/"
HAS_POSITION = URIRef(OBO + "FLOPO_0995004")
HAS_POSITION_LABEL = "has position"
HAS_CHARACTERISTIC = URIRef(OBO + "RO_0000053")
POSITIONS = Path("config/bearer_positions.tsv")
POSITIONED_PARTS = Path("config/flopo_positioned_parts.tsv")


@lru_cache(maxsize=1)
def position_values(path: Path = POSITIONS) -> dict[str, str]:
    """``{value class (PATO_n / FLOPO_n): label}`` of the values that are positions of a bearer."""

    with path.open(encoding="utf-8", newline="") as handle:
        return {row["value"]: row["label"] for row in csv.DictReader(handle, delimiter="\t")}


def is_position(value: str) -> bool:
    return str(value or "").strip().replace(":", "_").rsplit("/", 1)[-1] in position_values()


def declare(graph: Graph) -> None:
    graph.add((HAS_POSITION, RDF.type, OWL.ObjectProperty))
    graph.add((HAS_POSITION, RDFS.subPropertyOf, HAS_CHARACTERISTIC))
    graph.add((HAS_POSITION, RDFS.label, Literal(HAS_POSITION_LABEL, lang="en")))


@lru_cache(maxsize=1)
def positioned_parts(path: Path = POSITIONED_PARTS) -> dict[tuple[str, str], tuple[str, str]]:
    """``{(part, position): (FLOPO id, label)}`` of the positioned parts that FLOPO names."""

    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {(r["part"], r["position"]): (r["flopo_id"], r["label"]) for r in csv.DictReader(handle, delimiter="\t")}


@lru_cache(maxsize=1)
def synonyms(path: Path = POSITIONED_PARTS) -> dict[str, list[str]]:
    """``{FLOPO id: synonyms}`` of the named positioned parts ("lateral vein" for 'lateral vascular bundle')."""

    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            r["flopo_id"]: [entry.partition(":")[2] for entry in (r.get("synonyms") or "").split("|") if entry]
            for r in csv.DictReader(handle, delimiter="\t")
        }
