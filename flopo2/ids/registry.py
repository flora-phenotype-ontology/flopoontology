"""FLOPO identifier registry — the guarantee that existing FLOPO IRIs never change.

The 2016 FLOPO release (``ontology/flopo.owl``) assigned a numeric ``FLOPO_<n>`` IRI to every
phenotype class. Those IRIs are part of the public contract: downstream annotations, mappings, and
the OBO PURLs depend on them. When we regenerate FLOPO from the curated trait database, every
class whose logical signature already existed MUST be re-emitted under its original IRI, and new
classes MUST take the next free numeric ID — never a reused or shuffled one.

This module extracts, for each existing FLOPO class, the canonical *signature* of its logical
definition (the entity-quality combination), so the build step can look up "does this combination
already have an IRI?" and reuse it. It also records deprecated classes (whose IRIs must stay
reserved) and the current maximum numeric ID (so new IRIs continue the sequence).

Signature scheme (matches the 2016 EQ design pattern; ``|`` separates fields):
  * ``EQ|<PO>|<QUALITY>``  — ``has_part some (E and has_quality some Q)``  (the "E Q" / "E T" class)
  * ``PHENO|<PO>``         — ``has_part some ((part_of some E) and has_quality some quality)``
  * ``OTHER``              — class without the EQ equivalent-class pattern (manual / subclass-only)

Structurally the "E Q" (value) and "E T" (trait/attribute) classes are identical
(``has_part some (E and has_quality some PATO)``); they differ only in whether the PATO term is a
value or an attribute. The (PO, PATO) pair is therefore a sufficient canonical key for both.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.collection import Collection

OBO = "http://purl.obolibrary.org/obo/"
HAS_PART = URIRef(OBO + "BFO_0000051")
PART_OF = URIRef(OBO + "BFO_0000050")
HAS_QUALITY = URIRef(OBO + "RO_0000053")
QUALITY_ROOT = URIRef(OBO + "PATO_0000001")  # PATO:quality, used by the "E phenotype" pattern

FLOPO_IRI_RE = re.compile(r"^http://purl\.obolibrary\.org/obo/FLOPO_(\d+)$")


@dataclass(frozen=True)
class RegistryEntry:
    iri: str
    flopo_num: int
    label: str
    signature: str
    deprecated: bool


def _curie(uri: URIRef | None) -> str:
    if uri is None:
        return ""
    return str(uri).replace(OBO, "")


def _restriction(g: Graph, node) -> tuple[URIRef | None, object] | None:
    """Return (onProperty, someValuesFrom) if ``node`` is an owl:Restriction, else None."""
    if (node, RDF.type, OWL.Restriction) not in g and not list(g.objects(node, OWL.onProperty)):
        return None
    prop = next(g.objects(node, OWL.onProperty), None)
    filler = next(g.objects(node, OWL.someValuesFrom), None)
    if prop is None:
        return None
    return prop, filler


def _intersection_members(g: Graph, node) -> list:
    """Members of an ``owl:intersectionOf`` collection on ``node``, or []."""
    coll_head = next(g.objects(node, OWL.intersectionOf), None)
    if coll_head is None:
        return []
    return list(Collection(g, coll_head))


def _signature_of(g: Graph, cls: URIRef) -> str:
    """Compute the canonical EQ signature of a FLOPO class from its equivalentClass axiom."""
    for eq in g.objects(cls, OWL.equivalentClass):
        outer = _restriction(g, eq)
        if not outer:
            continue
        prop, filler = outer
        if prop != HAS_PART or filler is None:
            continue
        members = _intersection_members(g, filler)
        if not members:
            continue

        named_entity: URIRef | None = None  # direct PO entity  → "E Q" / "E T"
        partof_entity: URIRef | None = None  # part_of some PO   → "E phenotype"
        quality: URIRef | None = None
        for m in members:
            if isinstance(m, URIRef):
                named_entity = m
                continue
            r = _restriction(g, m)
            if not r:
                continue
            mprop, mfiller = r
            if mprop == HAS_QUALITY:
                quality = mfiller if isinstance(mfiller, URIRef) else None
            elif mprop == PART_OF and isinstance(mfiller, URIRef):
                partof_entity = mfiller

        if partof_entity is not None and quality == QUALITY_ROOT:
            return f"PHENO|{_curie(partof_entity)}"
        if named_entity is not None and quality is not None:
            return f"EQ|{_curie(named_entity)}|{_curie(quality)}"
    return "OTHER"


def build_registry(owl_path: Path) -> list[RegistryEntry]:
    """Parse a FLOPO OWL file and build the signature→IRI registry entries."""
    g = Graph()
    g.parse(owl_path.as_posix())
    entries: list[RegistryEntry] = []
    for cls in g.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef):
            continue
        m = FLOPO_IRI_RE.match(str(cls))
        if not m:
            continue
        label = next((str(o) for o in g.objects(cls, RDFS.label)), "")
        deprecated = (cls, OWL.deprecated, None) in g and any(
            str(o).lower() == "true" for o in g.objects(cls, OWL.deprecated)
        )
        entries.append(
            RegistryEntry(
                iri=str(cls),
                flopo_num=int(m.group(1)),
                label=label,
                signature=_signature_of(g, cls),
                deprecated=deprecated,
            )
        )
    entries.sort(key=lambda e: e.flopo_num)
    return entries


def write_registry_tsv(entries: list[RegistryEntry], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["flopo_iri", "flopo_num", "label", "signature", "deprecated"])
        for e in entries:
            w.writerow([e.iri, e.flopo_num, e.label, e.signature, int(e.deprecated)])


def load_registry(tsv_path: Path) -> list[RegistryEntry]:
    """Read back a registry TSV written by :func:`write_registry_tsv`."""
    entries: list[RegistryEntry] = []
    with tsv_path.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            entries.append(
                RegistryEntry(
                    iri=row["flopo_iri"],
                    flopo_num=int(row["flopo_num"]),
                    label=row["label"],
                    signature=row["signature"],
                    deprecated=row["deprecated"] == "1",
                )
            )
    return entries


class IdAllocator:
    """Assigns FLOPO IRIs: reuse the existing IRI for a known signature, else mint the next id.

    This is the enforcement point for the identifier-stability directive. Construct it from the
    registry, then call :meth:`iri_for` during the OWL build. Newly minted ids are tracked so the
    same new signature gets a stable id within a single build run.
    """

    def __init__(self, entries: list[RegistryEntry]):
        # Only EQ/PHENO signatures key reusable IRIs; OTHER (manual/subclass-only) classes are kept
        # reserved by number but are not signature-addressable.
        self._by_sig: dict[str, str] = {
            e.signature: e.iri for e in entries if e.signature != "OTHER"
        }
        self._reserved_nums: set[int] = {e.flopo_num for e in entries}
        self._next = max(self._reserved_nums, default=0) + 1
        self.minted: dict[str, str] = {}

    def iri_for(self, signature: str) -> str:
        """Return the stable FLOPO IRI for a signature, reusing or minting as needed."""
        if signature in self._by_sig:
            return self._by_sig[signature]
        if signature in self.minted:
            return self.minted[signature]
        while self._next in self._reserved_nums:
            self._next += 1
        iri = f"{OBO}FLOPO_{self._next:07d}"
        self._reserved_nums.add(self._next)
        self.minted[signature] = iri
        return iri


def summarize(entries: list[RegistryEntry]) -> dict:
    patterns: dict[str, int] = {}
    for e in entries:
        kind = e.signature.split("|", 1)[0]
        patterns[kind] = patterns.get(kind, 0) + 1
    return {
        "total_classes": len(entries),
        "deprecated": sum(e.deprecated for e in entries),
        "patterns": patterns,
        "max_flopo_num": max((e.flopo_num for e in entries), default=0),
        "distinct_signatures": len({e.signature for e in entries if e.signature != "OTHER"}),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the immutable FLOPO IRI registry from an OWL file.")
    ap.add_argument("owl", type=Path, help="Path to ontology/flopo.owl")
    ap.add_argument(
        "-o", "--out", type=Path, default=Path("config/flopo_id_registry.tsv"),
        help="Output TSV (default: config/flopo_id_registry.tsv)",
    )
    args = ap.parse_args()
    entries = build_registry(args.owl)
    write_registry_tsv(entries, args.out)
    s = summarize(entries)
    print(f"Wrote {s['total_classes']} FLOPO classes to {args.out}")
    print(f"  deprecated:           {s['deprecated']}")
    print(f"  max FLOPO_ id:        {s['max_flopo_num']:07d}")
    print(f"  distinct signatures:  {s['distinct_signatures']}")
    print(f"  patterns:             {s['patterns']}")


if __name__ == "__main__":
    main()
