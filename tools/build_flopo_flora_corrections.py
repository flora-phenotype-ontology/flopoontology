#!/usr/bin/env python3
"""Build the FLOPO flora corrections module: plane vs solid egg shapes, length words, disjointness.

1. Ovate and ovoid.  PATO:0001891 is defined as a solid (3-D) egg shape but was labelled
   "ovate", the botanical word for the plane (2-D) outline of a leaf or petal (UPOV TGP/14).
   pato-ontology/pato#627 relabels it "ovoid" and adds a plane ovate (PATO:0104368).  Until that
   is merged, FLOPO uses the temporary class FLOPO:0991024 (ovate, beneath PATO 2-D shape).
   Every live FLOPO class ``E ovate`` built on PATO:0001891 keeps its IRI: on a flat organ
   (``FLAT_BEARERS``) its quality becomes FLOPO:0991024; on any other bearer it keeps
   PATO:0001891 and is relabelled ``E ovoid``.
2. Length words.  Floras say "long" and "short", which PATO records as exact synonyms of
   increased length (PATO:0000573) and decreased length (PATO:0000574); every live ``E increased
   length`` / ``E decreased length`` class gets the exact synonym ``E long`` / ``E short``.
3. Disjointness.  For each row of ``config/flopo_disjoint_values.tsv`` the module states
   ``DisjointClasses(E and has_quality some A, E and has_quality some B)``: no single plant is,
   for example, both herbaceous and arborescent.  A taxon is a class of plants and may still be
   described with both values by different sources; the axioms constrain individuals only.

Output: ontology/flopo-flora-corrections.ttl (embedded by
tools/update_flopo_flora_corrections_release.py).
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection

OBO = Namespace("http://purl.obolibrary.org/obo/")
OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
MODULE = URIRef(OBO + "flopo-flora-corrections.owl")
HAS_PART = OBO.BFO_0000051
HAS_QUALITY = OBO.RO_0000053
DEFINITION = OBO.IAO_0000115
EDITOR_NOTE = OBO.IAO_0000116
SOLID_OVATE = OBO.PATO_0001891
PLANE_OVATE = OBO.FLOPO_0991024
LENGTH_WORDS = {"PATO_0000573": ("increased length", "long"), "PATO_0000574": ("decreased length", "short")}
DISJOINT = Path("config/flopo_disjoint_values.tsv")
REGISTRY = Path("config/flopo_id_registry.tsv")
OUTPUT = Path("ontology/flopo-flora-corrections.ttl")
PR = "pato-ontology/pato#627"
# Laminar organs, whose shape words describe a plane outline.
FLAT_BEARERS = {
    "PO_0025034", "PO_0009025", "PO_0020046", "PO_0025335",  # leaf, vascular/palmate leaf, phyllode
    "PO_0020049", "PO_0025060", "PO_0020039", "PO_0020040", "PO_0020137",  # leaflet, lamina, base, apex
    "PO_0009031", "PO_0025245", "PO_0009032", "PO_0025324", "PO_0025327", "PO_0009033",  # perianth parts
    "PO_0009055", "PO_0009054", "PO_0009043", "PO_0009063",  # bract, inflorescence bract, bracteole, epicalyx
    "PO_0009039", "PO_0006002", "PO_0006004", "PO_0009037", "PO_0009041", "PO_0009038",  # grass bracts
    "PO_0009036", "PO_0020041", "PO_0020051", "PO_0020105", "PO_0020030",  # lodicule, stipule, stipel, ligule, cotyledon
}
# Materialized blocks; this module's own block stays, so a re-run rebuilds the same classes.
GENERATED_BLOCKS = ("FLOPO INFERRED SUPERCLASSES", "FLOPO BEARER PHENOTYPE PARENTS")


def _local(term: URIRef | str) -> str:
    return str(term).rsplit("/", 1)[-1]


def release_graph(release: Path) -> Graph:
    """The release without its materialized blocks."""

    text = release.read_text(encoding="utf-8")
    for marker in GENERATED_BLOCKS:
        text = re.sub(
            rf"\n?  <!-- BEGIN GENERATED {marker} -->.*?  <!-- END GENERATED {marker} -->\n?",
            "\n", text, count=1, flags=re.DOTALL,
        )
    return Graph().parse(data=text, format="xml")


def eq_parts(graph: Graph, cls: URIRef) -> tuple[URIRef, URIRef] | None:
    """(E, Q) of ``cls EquivalentTo has_part some (E and has_quality some Q)``, else None."""

    for outer in graph.objects(cls, OWL.equivalentClass):
        if graph.value(outer, OWL.onProperty) != HAS_PART:
            continue
        members = graph.value(graph.value(outer, OWL.someValuesFrom), OWL.intersectionOf)
        if members is None:
            continue
        items = list(Collection(graph, members))
        named = [i for i in items if isinstance(i, URIRef)]
        quality = [graph.value(i, OWL.someValuesFrom) for i in items
                   if isinstance(i, BNode) and graph.value(i, OWL.onProperty) == HAS_QUALITY]
        if len(items) == 2 and len(named) == 1 and len(quality) == 1:
            return named[0], quality[0]
    return None


def _copy(source: Graph, target: Graph, node, rename: dict, prefix: str, swap: dict) -> object:
    if not isinstance(node, BNode):
        return swap.get(node, node)
    if node not in rename:
        rename[node] = BNode(f"{prefix}_{len(rename)}")
        for p, o in source.predicate_objects(node):
            target.add((rename[node], p, _copy(source, target, o, rename, prefix, swap)))
    return rename[node]


def _live_flopo(graph: Graph) -> list[URIRef]:
    return sorted(
        c for c in graph.subjects(RDF.type, OWL.Class)
        if isinstance(c, URIRef) and str(c).startswith(str(OBO) + "FLOPO_")
        and (c, OWL.deprecated, Literal(True, datatype=XSD.boolean)) not in graph
        and (c, OWL.deprecated, Literal(True)) not in graph
    )


def ovate_classes(graph: Graph, out: Graph) -> dict[str, int]:
    counts = {"plane_ovate": 0, "solid_ovoid": 0}
    for cls in _live_flopo(graph):
        parts = eq_parts(graph, cls)
        if not parts or parts[1] not in (SOLID_OVATE, PLANE_OVATE):
            continue
        flat = _local(parts[0]) in FLAT_BEARERS
        if parts[1] == PLANE_OVATE and not flat:
            continue  # a deliberate plane-ovate class on another bearer
        swap = {SOLID_OVATE: PLANE_OVATE} if flat else {}
        rename: dict = {}
        for p, o in graph.predicate_objects(cls):
            if p == RDFS.label and not flat and str(o).endswith(" ovate"):
                o = Literal(str(o)[: -len(" ovate")] + " ovoid", datatype=o.datatype, lang=o.language)
            elif p == DEFINITION and not flat:
                text = str(o).replace("being ovate.", "being ovoid.").replace("exhibits ovate.", "exhibits ovoid.")
                o = Literal(text, lang=o.language, datatype=o.datatype)
            out.add((cls, p, _copy(graph, out, o, rename, f"FLOPOShape_{_local(cls)}", swap)))
        note = (
            f"Plane (2-D) outline: uses the temporary class FLOPO:0991024 (ovate) for PATO:0104368, "
            f"requested in {PR}; previously the solid egg shape PATO:0001891." if flat else
            f"Solid (3-D) egg shape PATO:0001891, which {PR} relabels ovoid; formerly labelled ovate."
        )
        out.add((cls, EDITOR_NOTE, Literal(note, lang="en")))
        counts["plane_ovate" if flat else "solid_ovoid"] += 1
    return counts


def length_synonyms(registry: Path, out: Graph) -> int:
    count = 0
    with registry.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            quality = row["signature"].rsplit("|", 1)[-1]
            if row["deprecated"] != "0" or not row["signature"].startswith("EQ|") or quality not in LENGTH_WORDS:
                continue
            phrase, word = LENGTH_WORDS[quality]
            if not row["label"].endswith(" " + phrase):
                raise ValueError(f"unexpected length label: {row['label']}")
            synonym = row["label"][: -len(phrase)] + word
            out.add((URIRef(row["flopo_iri"]), OIO.hasExactSynonym, Literal(synonym, datatype=XSD.string)))
            count += 1
    return count


def _entity_quality(out: Graph, entity: URIRef, quality: URIRef, name: str) -> BNode:
    restriction, expression, members = BNode(f"{name}_q"), BNode(name), BNode(f"{name}_m")
    out.add((restriction, RDF.type, OWL.Restriction))
    out.add((restriction, OWL.onProperty, HAS_QUALITY))
    out.add((restriction, OWL.someValuesFrom, quality))
    Collection(out, members, [entity, restriction])
    out.add((expression, RDF.type, OWL.Class))
    out.add((expression, OWL.intersectionOf, members))
    return expression


def disjointness(spec: Path, out: Graph) -> int:
    with spec.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for n, row in enumerate(rows):
        bearer = OBO[row["bearer"]]
        a = _entity_quality(out, bearer, OBO[row["value_a"]], f"FLOPODisjoint_{n}_a")
        b = _entity_quality(out, bearer, OBO[row["value_b"]], f"FLOPODisjoint_{n}_b")
        out.add((a, OWL.disjointWith, b))
    return len(rows)


def build(release: Path, registry: Path = REGISTRY, spec: Path = DISJOINT) -> tuple[Graph, dict[str, int]]:
    graph = release_graph(release)
    out = Graph()
    out.bind("obo", OBO)
    out.bind("oboInOwl", OIO)
    out.add((MODULE, RDF.type, OWL.Ontology))
    out.add((MODULE, RDFS.comment, Literal(__doc__.split("\n\n")[0], lang="en")))
    counts = ovate_classes(graph, out)
    counts["length_synonyms"] = length_synonyms(registry, out)
    counts["disjoint_pairs"] = disjointness(spec, out)
    return out, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    graph, counts = build(args.release)
    args.out.write_text(
        "# FLOPO flora corrections module. Generated by tools/build_flopo_flora_corrections.py;\n"
        "# embedded by tools/update_flopo_flora_corrections_release.py.\n"
        + graph.serialize(format="turtle"),
        encoding="utf-8",
    )
    print(counts)


if __name__ == "__main__":
    main()
