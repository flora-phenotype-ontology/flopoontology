#!/usr/bin/env python3
"""Keep FLOPO's upper level intact: only the two approved branches sit directly under the root.

The upper-level rebuild (2026-07-31) gave 'flora phenotype' (FLOPO:0000000) exactly two children,
the continuant- and occurrent-target phenotypes.  Several later extension builders still assert
``SubClassOf flora phenotype`` for the classes they add.  This final release pass rewrites each
such assertion to the class's place in the upper level, computed the same way the rebuild did
(``flopo2.owl.top_level``): an ``E phenotype`` class goes under the structure, anatomical-space
or substance branch of its Plant Ontology bearer, and an entity-quality class goes under its
``E phenotype`` class when FLOPO has one, otherwise under that branch.

It is a text patch on the RDF/XML, so the generated blocks of the other release tools stay in
place, and it is idempotent.  Run it after every extension release tool.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from rdflib import RDFS, Graph, URIRef

from flopo2.owl.top_level import load_po_parents, phenotype_parent_for_po

OBO = "http://purl.obolibrary.org/obo/"
ROOT_CLASS = OBO + "FLOPO_0000000"
APPROVED_CHILDREN = {OBO + "FLOPO_0980417", OBO + "FLOPO_0980422"}
ROOT_PARENT = f'<rdfs:subClassOf rdf:resource="{ROOT_CLASS}"/>'


def _po_bearer(graph: Graph, bearer: str) -> str:
    """The bearer itself, or for a FLOPO-local anatomy class its nearest PO superclass."""

    seen = set()
    while bearer.startswith("FLOPO_") and bearer not in seen:
        seen.add(bearer)
        supers = [
            str(parent).rsplit("/", 1)[1]
            for parent in graph.objects(URIRef(OBO + bearer), RDFS.subClassOf)
            if isinstance(parent, URIRef) and str(parent).startswith(OBO)
        ]
        po = [s for s in supers if s.startswith("PO_")]
        bearer = po[0] if po else (supers[0] if supers else bearer)
    return bearer


def new_parents(release: Path, registry: Path, po_obo: Path) -> dict[str, str]:
    graph = Graph().parse(release.as_posix())
    signature_of: dict[str, str] = {}
    pheno_class: dict[str, str] = {}
    with registry.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["deprecated"] == "1":
                continue
            signature_of[row["flopo_iri"]] = row["signature"]
            if row["signature"].startswith("PHENO|"):
                pheno_class[row["signature"].split("|")[1]] = row["flopo_iri"]
    po_parents = load_po_parents(po_obo)
    parents: dict[str, str] = {}
    for child in graph.subjects(RDFS.subClassOf, URIRef(ROOT_CLASS)):
        child = str(child)
        if child in APPROVED_CHILDREN or not child.startswith(OBO + "FLOPO_"):
            continue
        fields = signature_of.get(child, "").split("|")
        if fields[0] not in {"PHENO", "EQ", "EQV"} or len(fields) < 2:
            raise ValueError(f"cannot place {child} ({fields[0] or 'no signature'}) in the upper level")
        bearer = fields[1]
        if fields[0] != "PHENO" and pheno_class.get(bearer) not in {None, child}:
            parents[child] = pheno_class[bearer]
        else:
            parents[child] = OBO + phenotype_parent_for_po(_po_bearer(graph, bearer), po_parents)
    return parents


def _element_span(text: str, iri: str) -> list[tuple[int, int]]:
    spans = []
    for tag in ("owl:Class", "rdf:Description"):
        for match in re.finditer(re.escape(f'<{tag} rdf:about="{iri}">'), text):
            end = text.find(f"</{tag}>", match.end())
            spans.append((match.start(), end))
    return spans


def update_release(release: Path, registry: Path, po_obo: Path) -> dict[str, str]:
    parents = new_parents(release, registry, po_obo)
    text = release.read_text(encoding="utf-8")
    for child, parent in sorted(parents.items()):
        replaced = False
        for start, end in sorted(_element_span(text, child), reverse=True):
            element = text[start:end]
            if ROOT_PARENT in element:
                element = element.replace(ROOT_PARENT, f'<rdfs:subClassOf rdf:resource="{parent}"/>')
                text = text[:start] + element + text[end:]
                replaced = True
        if not replaced:
            raise ValueError(f"no textual root parent assertion found for {child}")
    release.write_text(text, encoding="utf-8")
    return parents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--po", type=Path, default=Path("ont/plant_ontology.obo"))
    args = parser.parse_args()
    parents = update_release(args.release, args.registry, args.po)
    print(f"re-parented {len(parents)} classes from flora phenotype into the upper level")
    for child, parent in sorted(parents.items()):
        print(f"{child.rsplit('/', 1)[1]}\t{parent.rsplit('/', 1)[1]}")


if __name__ == "__main__":
    main()
