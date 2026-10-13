#!/usr/bin/env python3
"""Assert each entity-quality class beneath the phenotype class of its bearer.

A trait or value class ``E Q`` is defined as ``has_part some (E and has_quality some Q)``, and the
bearer grouping ``E phenotype`` as ``has_part some (part_of some E and has_quality some quality)``.
The second subsumes the first only if parthood is reflexive (``E SubClassOf part_of some E``),
which OWL EL cannot state, so a reasoner leaves trait classes such as "bark odor" or "abscission
zone pilosity" directly under owl:Thing and their value classes hang off them unplaced.

This final release pass asserts, for every live EQ class without an asserted FLOPO parent, the
phenotype class of its bearer: the bearer's own ``E phenotype`` class, else the nearest one along
the Plant Ontology ``is_a``/``part_of`` ancestry, else the approved upper-level grouping
(``flopo2.owl.top_level``).  The axioms are entailed under reflexive parthood, which is the
reading FLOPO's bearer groupings intend.  Marker-delimited and idempotent; run it with the other
final passes, before classification.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from rdflib import RDFS, Graph, URIRef

from flopo2.owl.top_level import load_po_parents, phenotype_parent_for_po
from tools.update_flopo_top_level_parents import _po_bearer

OBO = "http://purl.obolibrary.org/obo/"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO BEARER PHENOTYPE PARENTS -->"
END_MARKER = "  <!-- END GENERATED FLOPO BEARER PHENOTYPE PARENTS -->"


def _without_block(text: str) -> str:
    if text.count(BEGIN_MARKER) != text.count(END_MARKER) or text.count(BEGIN_MARKER) > 1:
        raise ValueError("malformed bearer-parent markers")
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def _nearest_pheno(bearer: str, po_parents: dict[str, set[str]], pheno: dict[str, str]) -> str:
    frontier, seen = [bearer], set()
    while frontier:
        current = frontier.pop(0)
        if current in pheno:
            return pheno[current]
        seen.add(current)
        frontier += sorted(p for p in po_parents.get(current, ()) if p not in seen)
    return ""


def bearer_parents(release: Path, registry: Path, po_obo: Path) -> dict[str, str]:
    graph = Graph().parse(release.as_posix())
    rows = []
    with registry.open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle, delimiter="\t") if r["deprecated"] == "0"]
    pheno = {r["signature"].split("|")[1]: r["flopo_iri"] for r in rows if r["signature"].startswith("PHENO|")}
    po_parents = load_po_parents(po_obo)
    parents: dict[str, str] = {}
    for row in rows:
        fields = row["signature"].split("|")
        if fields[0] != "EQ":
            continue
        cls = URIRef(row["flopo_iri"])
        asserted = [o for o in graph.objects(cls, RDFS.subClassOf) if isinstance(o, URIRef) and str(o).startswith(OBO + "FLOPO_")]
        if asserted:
            continue
        bearer = _po_bearer(graph, fields[1])
        parent = pheno.get(fields[1]) or (_nearest_pheno(bearer, po_parents, pheno) if bearer.startswith("PO_") else "")
        if not parent:
            try:
                parent = OBO + phenotype_parent_for_po(bearer, po_parents)
            except ValueError:
                continue
        if parent != row["flopo_iri"]:
            parents[row["flopo_iri"]] = parent
    return parents


def update_release(release: Path, registry: Path, po_obo: Path) -> int:
    text = _without_block(release.read_text(encoding="utf-8"))
    release.write_text(text, encoding="utf-8")
    parents = bearer_parents(release, registry, po_obo)
    lines = [BEGIN_MARKER]
    for child, parent in sorted(parents.items()):
        lines.append(f'  <rdf:Description rdf:about="{child}">')
        lines.append(f'    <rdfs:subClassOf rdf:resource="{parent}"/>')
        lines.append("  </rdf:Description>")
    lines.append(END_MARKER)
    closing = "</rdf:RDF>"
    text = text.replace(closing, "\n".join(lines) + "\n" + closing, 1)
    release.write_text(text, encoding="utf-8")
    return len(parents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--po", type=Path, default=Path("ont/plant_ontology.obo"))
    args = parser.parse_args()
    print(f"asserted the bearer phenotype parent of {update_release(args.release, args.registry, args.po)} EQ classes")


if __name__ == "__main__":
    main()
