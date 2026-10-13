"""Labels and browse groups for the PO, PATO and FLOPO terms used in Saudi-flora annotations.

The browser groups every bearer into an organ group (flower, leaf, fruit, ...) by its Plant
Ontology ``is_a``/``part_of`` ancestry, and every quality into a trait group (colour, shape, size,
...) by its PATO ``is_a`` ancestry.  FLOPO local terms are placed through their registry signature
(an EQ class's bearer and quality) or, for value modules, through their identifier block.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

OBO = "http://purl.obolibrary.org/obo/"

ORGAN_GROUPS: list[tuple[str, str, list[str]]] = [
    ("seed", "Seed", ["PO:0009010"]),
    ("fruit", "Fruit", ["PO:0009001", "PO:0006342"]),
    ("flower", "Flower", ["PO:0009046"]),
    ("inflorescence", "Inflorescence", ["PO:0009049"]),
    ("leaf", "Leaf", ["PO:0025034", "PO:0009025", "PO:0006001"]),
    ("root", "Root", ["PO:0009005", "PO:0025025"]),
    ("stem", "Stem, branches and spines", ["PO:0025029", "PO:0009047", "PO:0004518"]),
    ("surface", "Hairs and glands", ["PO:0000282"]),
    ("plant", "Whole plant", ["PO:0000003", "PO:0009006"]),
]

TRAIT_GROUPS: list[tuple[str, str, list[str]]] = [
    ("colour", "Colour", ["PATO:0000014"]),
    ("size", "Size and measurements", ["PATO:0000117"]),
    ("shape", "Shape", ["PATO:0000052"]),
    ("surface", "Surface and hairs", ["PATO:0000150"]),
    ("position", "Arrangement and position", ["PATO:0000140", "PATO:0000060"]),
    ("habit", "Habit and life cycle", ["PATO:0000050", "PATO:0001995", "PATO:0000165"]),
    ("presence", "Presence of structures", ["PATO:0000070"]),
    ("scent", "Scent", ["PATO:0000058", "PATO:0002190"]),
    ("structure", "Structure and texture", ["PATO:0000141", "PATO:0001018"]),
]


@dataclass
class OboTerm:
    id: str
    name: str = ""
    is_a: list[str] = field(default_factory=list)
    part_of: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)


def parse_obo(path: Path) -> dict[str, OboTerm]:
    terms: dict[str, OboTerm] = {}
    current: OboTerm | None = None
    for line in Path(path).open(encoding="utf-8"):
        line = line.rstrip("\n")
        if line == "[Term]":
            current = OboTerm("")
            continue
        if line.startswith("["):
            current = None
            continue
        if current is None:
            continue
        if line.startswith("id: "):
            current.id = line[4:].strip()
            terms[current.id] = current
        elif line.startswith("name: "):
            current.name = line[6:].strip()
        elif line.startswith("is_a: "):
            current.is_a.append(line[6:].split()[0])
        elif line.startswith("relationship: part_of "):
            current.part_of.append(line.split()[2])
        elif line.startswith("synonym: ") and "EXACT" in line:
            current.synonyms.append(line.split('"')[1])
    return terms


def curie(identifier: str) -> str:
    """PO_0000003 / http://.../PO_0000003 -> PO:0000003."""

    local = identifier.rsplit("/", 1)[-1]
    return local.replace("_", ":", 1)


def iri(identifier: str) -> str:
    return OBO + curie(identifier).replace(":", "_", 1)


class Vocabulary:
    def __init__(
        self,
        po_obo: Path = Path("ont/plant_ontology.obo"),
        pato_obo: Path = Path("ont/quality.obo"),
        registry: Path = Path("config/flopo_id_registry.tsv"),
    ) -> None:
        self.po = parse_obo(po_obo)
        self.pato = parse_obo(pato_obo)
        self.flopo: dict[str, tuple[str, str]] = {}  # FLOPO:n -> (label, signature)
        with Path(registry).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                self.flopo[curie(row["flopo_iri"])] = (row["label"], row["signature"])
        self._organ: dict[str, str] = {}
        self._trait: dict[str, str] = {}

    def label(self, identifier: str) -> str:
        c = curie(identifier)
        for table in (self.po, self.pato):
            if c in table:
                return table[c].name
        return self.flopo.get(c, ("", ""))[0] or c

    def _ancestors(self, table: dict[str, OboTerm], start: str, part_of: bool) -> list[str]:
        seen, queue, order = {start}, [start], [start]
        while queue:
            term = table.get(queue.pop(0))
            if term is None:
                continue
            for parent in term.is_a + (term.part_of if part_of else []):
                if parent not in seen:
                    seen.add(parent)
                    queue.append(parent)
                    order.append(parent)
        return order

    def _flopo_bearer(self, c: str) -> str:
        """Nearest PO class for a FLOPO-local anatomy class (via EQ signature or registry)."""

        label, signature = self.flopo.get(c, ("", ""))
        parts = signature.split("|")
        if parts[0] in {"EQ", "PHENO", "EQV"} and len(parts) > 1:
            return curie(parts[1])
        return ""

    def organ_group(self, bearer: str) -> str:
        c = curie(bearer)
        if c in self._organ:
            return self._organ[c]
        start = c if c.startswith("PO:") else self._flopo_bearer(c) or c
        ancestors = set(self._ancestors(self.po, start, part_of=True))
        group = "other"
        for key, _label, roots in ORGAN_GROUPS:
            if ancestors & set(roots):
                group = key
                break
        self._organ[c] = group
        return group

    def trait_group(self, quality: str, attribute: str = "") -> str:
        c = curie(quality)
        key = (c, curie(attribute) if attribute else "")
        cache_key = "|".join(key)
        if cache_key in self._trait:
            return self._trait[cache_key]
        group = "other"
        if c.startswith("FLOPO:"):
            number = int(c.split(":")[1])
            if 988000 <= number < 989000:
                group = "colour"
            elif 985000 <= number < 988000:
                group = "habit"
            elif attribute:
                group = self.trait_group(attribute)
        else:
            ancestors = set(self._ancestors(self.pato, c, part_of=False))
            for gkey, _label, roots in TRAIT_GROUPS:
                if ancestors & set(roots):
                    group = gkey
                    break
            if group == "other" and attribute and curie(attribute) != c:
                group = self.trait_group(attribute)
        self._trait[cache_key] = group
        return group
