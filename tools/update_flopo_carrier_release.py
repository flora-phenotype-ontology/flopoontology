#!/usr/bin/env python3
"""Redefine the named FLOPO classes of arrangements and whorl relations on the structure that
carries the parts, and embed them in flopo.owl (marker-delimited and idempotent).

"leaf alternate placement" (FLOPO:0001032) was ``has part some (leaf and has characteristic some
'alternate placement')``. No single leaf is alternate: it becomes ``has part some ('shoot axis'
and has characteristic some ('alternate placement' and towards some leaf))``, the form of
docs/odp/16-quality-of-a-whole-towards-its-parts.md. Which classes change, and to which
carrier, follows from the tables of ``flopo2.owl.carrier``. Each class keeps its identifier, its
label and its annotations; it gets the new definition, a text definition that names the carrier,
and the phenotype class of the carrier as its parent. The identifier registry still files it
under the part the flora names and the value (``flopo2.ids.registry``).

Writes ``ontology/flopo-carrier-migration.ttl`` (the module, for the record) and embeds it. After
this run the final passes of the README release procedure.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection

from flopo2.ids.registry import _signature_of
from flopo2.owl import carrier
from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _graph_fragment, _update_release_metadata

OBO = Namespace("http://purl.obolibrary.org/obo/")
MODULE = URIRef(OBO + "flopo-carrier-migration.owl")
OUTPUT = Path("ontology/flopo-carrier-migration.ttl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO CARRIER MIGRATION -->"
END_MARKER = "  <!-- END GENERATED FLOPO CARRIER MIGRATION -->"
HAS_PART, HAS_CHARACTERISTIC, TOWARDS = OBO.BFO_0000051, OBO.RO_0000053, OBO.RO_0002503
DEFINITION, EDITOR_NOTE = OBO.IAO_0000115, OBO.IAO_0000116
ADDED = "2026-11-21"
NOTE = ("Redefined {date}: the quality inheres in the {carrier} with respect to the {part} "
        "(RO:0002503 towards), not in the {part} (docs/odp/16-quality-of-a-whole-towards-its-parts.md; "
        "Ellis et al. 2009, Manual of Leaf Architecture, character 2: leaf arrangement is 'the placement "
        "of adjacent leaves on the nodes of the axis'). Identifier and label unchanged; earlier definition: "
        "has part some ({part} and has characteristic some {value}).")
PLURAL = {"leaf": "leaves", "vascular leaf": "vascular leaves", "branch": "branches", "pinna": "pinnae",
          "anther": "anthers", "involucral bract": "involucral bracts"}
ARRANGEMENT_WORD = {"alternate placement": "alternate"}
AMONG = {"connate": " with one another", "free": " from one another", "unequal": " among themselves",
         "equal": " among themselves"}
# Parents kept from the earlier declaration: none that is a FLOPO class (the phenotype class of
# the part, an inferred superclass); the final passes assert the classified hierarchy again.


_OBO_LABELS: dict[str, str] = {}


def _label(graph: Graph, term: URIRef) -> str:
    """The label in the release, else in the pinned PO and PATO files (flopo.owl imports them)."""

    label = graph.value(term, RDFS.label)
    if label:
        return str(label).strip()
    if not _OBO_LABELS:
        for name in ("plant_ontology.obo", "quality.obo"):
            current = ""
            for line in (Path(__file__).resolve().parents[1] / "ont" / name).open(encoding="utf-8", errors="replace"):
                if line.startswith("id: "):
                    current = line[4:].strip().replace(":", "_")
                elif line.startswith("name: ") and current:
                    _OBO_LABELS.setdefault(current, line[6:].strip())
                    current = ""
    key = str(term).rsplit("/", 1)[-1]
    if key not in _OBO_LABELS:
        raise ValueError(f"no label for {term}")
    return _OBO_LABELS[key]


def _some(graph: Graph, prop: URIRef, filler) -> BNode:
    node = BNode()
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, prop))
    graph.add((node, OWL.someValuesFrom, filler))
    return node


def _and(graph: Graph, members: list) -> BNode:
    node, head = BNode(), BNode()
    graph.add((node, RDF.type, OWL.Class))
    Collection(graph, head, members)
    graph.add((node, OWL.intersectionOf, head))
    return node


def affected(release: Graph) -> dict[URIRef, dict]:
    """Live FLOPO classes of a part and a value for which the tables name a carrier."""

    found = {}
    for cls in set(release.subjects(RDF.type, OWL.Class)):
        if not isinstance(cls, URIRef) or not str(cls).startswith(str(OBO) + "FLOPO_"):
            continue
        if (cls, OWL.deprecated, Literal(True)) in release:
            continue
        signature = _signature_of(release, cls).split("|")
        if signature[0] != "EQ" or len(signature) != 3:
            continue
        slot = carrier.expected(signature[1], signature[2])
        if slot is not None:
            found[cls] = {**slot, "part": signature[1], "value": signature[2]}
    return found


def build_module(release: Graph, pheno_of: dict[str, URIRef]) -> tuple[Graph, dict[URIRef, dict]]:
    classes = affected(release)
    module = Graph()
    module.add((MODULE, RDF.type, OWL.Ontology))
    module.add((MODULE, RDFS.comment, Literal(__doc__.split("\n\n")[0], lang="en")))
    for cls, slot in sorted(classes.items()):
        part, value, whole = OBO[slot["part"]], OBO[slot["value"]], OBO[slot["carrier_term"]]
        names = {"part": _label(release, part), "value": _label(release, value), "carrier": _label(release, whole)}
        for predicate, obj in release.predicate_objects(cls):
            if isinstance(obj, BNode) or predicate in (OWL.equivalentClass, DEFINITION):
                continue
            if predicate == RDFS.subClassOf and str(obj).startswith(str(OBO) + "FLOPO_"):
                continue
            if predicate == EDITOR_NOTE and str(obj).startswith("Redefined "):
                continue
            module.add((cls, predicate, obj))
        module.add((cls, RDF.type, OWL.Class))
        relational = _and(module, [value, _some(module, TOWARDS, part)])
        bearer = _and(module, [whole, _some(module, HAS_CHARACTERISTIC, relational)])
        module.add((cls, OWL.equivalentClass, _some(module, HAS_PART, bearer)))
        module.add((cls, RDFS.subClassOf, pheno_of[slot["carrier_term"]]))
        parts = PLURAL.get(names["part"], names["part"] + "s")
        article = "an" if names["carrier"][0] in "aeiou" else "a"
        if slot["kind"] == "arrangement":
            word = ARRANGEMENT_WORD.get(names["value"], names["value"])
            text = (f"A flora phenotype in which {article} {names['carrier']} bears its {parts} in "
                    f"{'an' if word[0] in 'aeiou' else 'a'} {word} arrangement.")
        else:
            text = (f"A flora phenotype in which the {parts} of {article} {names['carrier']} are "
                    f"{names['value']}{AMONG.get(names['value'], '')}.")
        module.add((cls, DEFINITION, Literal(text, lang="en")))
        module.add((cls, EDITOR_NOTE, Literal(NOTE.format(date=ADDED, **names), lang="en")))
        module.add((cls, DCTERMS.modified, Literal(ADDED, datatype=XSD.date)))
    for prop in (HAS_PART, HAS_CHARACTERISTIC, TOWARDS):
        module.add((prop, RDF.type, OWL.ObjectProperty))
    return module, classes


def _without_generated_block(text: str) -> str:
    begin_count, end_count = text.count(BEGIN_MARKER), text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated carrier-migration markers")
    if not begin_count:
        return text
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def update_release(release_path: Path, module_path: Path, registry_path: Path, release_date: str) -> dict[str, int]:
    import csv

    release = Graph().parse(release_path.as_posix())
    with registry_path.open(encoding="utf-8", newline="") as handle:
        pheno_of = {
            row["signature"].split("|")[1]: URIRef(row["flopo_iri"])
            for row in csv.DictReader(handle, delimiter="\t")
            if row["signature"].startswith("PHENO|") and row["deprecated"] == "0"
        }
    module, classes = build_module(release, pheno_of)
    module_path.write_text(
        "# FLOPO carrier migration. Generated and embedded by tools/update_flopo_carrier_release.py.\n"
        + module.serialize(format="turtle"), encoding="utf-8")
    body = Graph()
    for triple in module:
        if triple[0] != MODULE and not (triple[1] == RDF.type and triple[2] == OWL.ObjectProperty):
            body.add(triple)
    fragment, _count = _graph_fragment(body, node_id_prefix="FLOPOCarrier_")
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    replaced = 0
    for cls in sorted(classes):
        text, removed = _remove_named_owl_class(text, str(cls))
        replaced += removed
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    text = text.replace(closing, f"{BEGIN_MARKER}\n{fragment.strip()}\n{END_MARKER}\n{closing}", 1)
    release_path.write_text(text, encoding="utf-8")

    check = Graph().parse(release_path.as_posix())
    for cls, slot in classes.items():
        definitions = list(check.objects(cls, OWL.equivalentClass))
        if len(definitions) != 1:
            raise ValueError(f"{cls} has {len(definitions)} definitions after the migration")
        if _signature_of(check, cls) != f"EQ|{slot['part']}|{slot['value']}":
            raise ValueError(f"{cls} lost its registry signature")
        if not check.value(cls, RDFS.label):
            raise ValueError(f"{cls} lost its label")
    return {"classes": len(classes), "arrangement": sum(s["kind"] == "arrangement" for s in classes.values()),
            "set": sum(s["kind"] == "set" for s in classes.values()), "replaced_declarations": replaced}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--module", type=Path, default=OUTPUT)
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    print(update_release(args.release, args.module, args.registry, args.date))


if __name__ == "__main__":
    main()
