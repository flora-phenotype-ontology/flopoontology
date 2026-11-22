#!/usr/bin/env python3
"""Write every FLOPO phenotype class as a phene: a quality of the plant, defined by a property.

    P EquivalentTo: 'has part' some (E and 'has characteristic' some Q)

becomes

    P EquivalentTo: 'flora phenotype' and 'phenotype of' some
                        ('has part' some (E and 'has characteristic' some Q))

and a necessary condition ``P SubClassOf: 'has part' some ...`` of a phenotype class becomes
``P SubClassOf: 'phenotype of' some ('has part' some ...)`` (see ``flopo2/owl/phene.py``).
The expression inside is untouched, so identifiers, signatures and the classified hierarchy stay
as they are. Axioms about plants are left alone: the anatomy classes, the value classes and the
general class axioms that rule out a process quality on a plant part.

The pass also declares 'phenotype of' (RO:0002201, functional) and 'has phenotype' (RO:0002200,
its inverse) in a marker-delimited block.

Final release pass, idempotent: generated modules still write the defining property alone, and
this pass wraps what they add. Run it after ``prune_orphan_blank_nodes`` and before the registry.

    python -m tools.update_flopo_phene_form [--release ontology/flopo.owl] [--check]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from lxml import etree
from rdflib import OWL, RDFS, Graph, URIRef

from flopo2.owl.phene import (
    HAS_PART,
    HAS_PHENOTYPE,
    HAS_PHENOTYPE_LABEL,
    PHENOTYPE,
    PHENOTYPE_OF,
    PHENOTYPE_OF_LABEL,
    phene_body,
)

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
OWL_NS = "http://www.w3.org/2002/07/owl#"
RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#"
ABOUT, NODE_ID, RESOURCE, PARSE_TYPE = (f"{{{RDF_NS}}}{name}" for name in ("about", "nodeID", "resource", "parseType"))
EQUIVALENT = f"{{{OWL_NS}}}equivalentClass"
SUBCLASS = f"{{{RDFS_NS}}}subClassOf"
ON_PROPERTY = f"{{{OWL_NS}}}onProperty"
FLOPO_PREFIX = "http://purl.obolibrary.org/obo/FLOPO_"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO PHENE RELATIONS -->"
END_MARKER = "  <!-- END GENERATED FLOPO PHENE RELATIONS -->"
RELATIONS = f"""{BEGIN_MARKER}
  <owl:ObjectProperty rdf:about="{PHENOTYPE_OF}">
    <rdf:type rdf:resource="{OWL_NS}FunctionalProperty"/>
    <rdfs:label xml:lang="en">{PHENOTYPE_OF_LABEL}</rdfs:label>
  </owl:ObjectProperty>
  <owl:ObjectProperty rdf:about="{HAS_PHENOTYPE}">
    <rdfs:label xml:lang="en">{HAS_PHENOTYPE_LABEL}</rdfs:label>
    <owl:inverseOf rdf:resource="{PHENOTYPE_OF}"/>
  </owl:ObjectProperty>
{END_MARKER}
"""


def phenotype_classes(graph: Graph) -> set[str]:
    """FLOPO classes that are phenotypes: every FLOPO class that is not an anatomy or a value
    class, that is, has no Plant Ontology, PATO or other foreign class above it in the asserted
    hierarchy. (The asserted hierarchy under 'flora phenotype' is no guide: a module update
    removes the materialized classification until the final passes restore it.)"""

    foreign: dict[URIRef, bool] = {}

    def under_foreign(cls: URIRef, seen: frozenset = frozenset()) -> bool:
        if cls in foreign:
            return foreign[cls]
        if not str(cls).startswith(FLOPO_PREFIX):
            return cls != OWL.Thing
        result = any(
            under_foreign(parent, seen | {cls})
            for parent in graph.objects(cls, RDFS.subClassOf)
            if isinstance(parent, URIRef) and parent not in seen
        )
        foreign[cls] = result
        return result

    classes = {s for s in graph.subjects(RDFS.subClassOf, None) if isinstance(s, URIRef)}
    classes |= {s for s in graph.subjects(OWL.equivalentClass, None) if isinstance(s, URIRef)}
    return {str(c) for c in classes if str(c).startswith(FLOPO_PREFIX) and not under_foreign(c)}


def _property_of(element, defined: dict[str, etree._Element]) -> str:
    """The property of a restriction element (or of the node it refers to)."""

    target = _expression(element, defined)
    if target is None:
        return ""
    for child in target:
        if child.tag == ON_PROPERTY:
            if child.get(RESOURCE):
                return child.get(RESOURCE)
            if len(child) and child[0].get(ABOUT):
                return child[0].get(ABOUT)
    return ""


def _expression(axiom, defined: dict[str, etree._Element]):
    """The element that carries the class expression of an axiom element."""

    if len(axiom):
        nested = axiom[0]
        if not len(nested) and nested.get(NODE_ID) in defined:
            return defined[nested.get(NODE_ID)]
        return nested
    if axiom.get(NODE_ID) in defined:
        return defined[axiom.get(NODE_ID)]
    return None


def _indent(element) -> str:
    """The indentation of an element, read from the text before it."""

    previous = element.getprevious()
    before = previous.tail if previous is not None else (element.getparent().text if element.getparent() is not None else "")
    return (before or "\n").rsplit("\n", 1)[-1]


def _wrap(axiom, equivalent: bool) -> None:
    """Put the expression of an axiom element inside the phene form."""

    pad = _indent(axiom)
    restriction = etree.Element(f"{{{OWL_NS}}}Restriction")
    on_property = etree.SubElement(restriction, ON_PROPERTY)
    on_property.set(RESOURCE, str(PHENOTYPE_OF))
    filler = etree.SubElement(restriction, f"{{{OWL_NS}}}someValuesFrom")
    if len(axiom):
        body = axiom[0]
        axiom.remove(body)
        filler.append(body)
    else:
        filler.set(NODE_ID, axiom.attrib.pop(NODE_ID))
    if equivalent:
        outer = etree.SubElement(axiom, f"{{{OWL_NS}}}Class")
        members = etree.SubElement(outer, f"{{{OWL_NS}}}intersectionOf")
        members.set(PARSE_TYPE, "Collection")
        root = etree.SubElement(members, f"{{{RDF_NS}}}Description")
        root.set(ABOUT, str(PHENOTYPE))
        members.append(restriction)
    else:
        axiom.append(restriction)
    _reindent(axiom, pad)


def _reindent(axiom, pad: str) -> None:
    """Indent the new wrapper elements; the expression that was moved keeps its own layout."""

    def walk(element, depth: int) -> None:
        if element.get(NODE_ID) and element.tag != f"{{{OWL_NS}}}someValuesFrom" and depth > 1:
            return  # the moved expression
        children = list(element)
        if not children:
            return
        element.text = "\n" + pad + "  " * depth
        for index, child in enumerate(children):
            child.tail = "\n" + pad + "  " * (depth if index < len(children) - 1 else depth - 1)
            if child.tag in {f"{{{OWL_NS}}}Class", f"{{{OWL_NS}}}Restriction", f"{{{OWL_NS}}}intersectionOf",
                             f"{{{OWL_NS}}}someValuesFrom"} and not child.get(NODE_ID):
                walk(child, depth + 1)

    walk(axiom, 1)


def wrap_text(text: str) -> tuple[str, dict[str, int]]:
    """The release with every phenotype class axiom in the phene form, and what was changed."""

    graph = Graph().parse(data=text, format="xml")
    phenotypes = phenotype_classes(graph)
    parser = etree.XMLParser(remove_blank_text=False, huge_tree=True, resolve_entities=False)
    root = etree.fromstring(text.encode("utf-8"), parser)
    defined = {el.get(NODE_ID): el for el in root.iter() if isinstance(el.tag, str) and el.get(NODE_ID) and len(el)}
    counts = {"equivalent": 0, "subclass": 0, "already": 0}
    for element in root.iter():
        if not isinstance(element.tag, str) or element.get(ABOUT) not in phenotypes:
            continue
        for axiom in list(element):
            if axiom.tag not in (EQUIVALENT, SUBCLASS) or axiom.get(RESOURCE):
                continue
            prop = _property_of(axiom, defined)
            if prop == str(HAS_PART):
                _wrap(axiom, axiom.tag == EQUIVALENT)
                counts["equivalent" if axiom.tag == EQUIVALENT else "subclass"] += 1
            elif prop == str(PHENOTYPE_OF) or _is_phene_class(axiom, defined):
                counts["already"] += 1
    out = etree.tostring(root, encoding="unicode")
    start = text.index("<rdf:RDF")
    opening = text[: text.index(">", start) + 1]  # the declaration and the root tag as they were written
    out = opening + out[out.index(">") + 1 :] + ("\n" if text.endswith("\n") else "")
    out = _with_relations(out)
    return out, counts


def _is_phene_class(axiom, defined: dict[str, etree._Element]) -> bool:
    target = _expression(axiom, defined)
    if target is None:
        return False
    for members in target:
        if members.tag == f"{{{OWL_NS}}}intersectionOf":
            return any(_property_of_element(item, defined) == str(PHENOTYPE_OF) for item in members)
    return False


def _property_of_element(item, defined: dict[str, etree._Element]) -> str:
    target = defined.get(item.get(NODE_ID), item) if not len(item) else item
    for child in target:
        if child.tag == ON_PROPERTY:
            return child.get(RESOURCE) or (child[0].get(ABOUT) if len(child) else "") or ""
    return ""


def _with_relations(text: str) -> str:
    if text.count(BEGIN_MARKER) != text.count(END_MARKER) or text.count(BEGIN_MARKER) > 1:
        raise ValueError("malformed phene relation markers")
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    text = pattern.sub("\n", text, count=1)
    closing = "</rdf:RDF>"
    index = text.rindex(closing)
    return text[:index] + RELATIONS + text[index:]


def unwrapped(graph: Graph) -> list[str]:
    """Phenotype class axioms that are still written about the plant (for --check and tests)."""

    phenotypes = phenotype_classes(graph)
    wrong = []
    for predicate in (OWL.equivalentClass, RDFS.subClassOf):
        for cls, expression in graph.subject_objects(predicate):
            if not str(cls).startswith(FLOPO_PREFIX) or (expression, OWL.onProperty, HAS_PART) not in graph:
                continue
            if str(cls) in phenotypes:
                wrong.append(str(cls))
    return sorted(set(wrong))


def update_release(release: Path, release_date: str = "") -> dict[str, int]:
    text = release.read_text(encoding="utf-8")
    if release_date:
        from tools.update_flopo_release import _update_release_metadata

        text = _update_release_metadata(text, release_date)
    text, counts = wrap_text(text)
    release.write_text(text, encoding="utf-8")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--check", action="store_true", help="change nothing; fail if a class is not in the phene form")
    parser.add_argument("--release-date", default="", help="also set the version of the release (YYYY-MM-DD)")
    args = parser.parse_args()
    if args.check:
        graph = Graph().parse(args.release.as_posix())
        wrong = unwrapped(graph)
        phenes = sum(1 for _c, e in graph.subject_objects(OWL.equivalentClass) if phene_body(graph, e) is not None)
        print(f"{phenes} phene definitions, {len(wrong)} phenotype classes not in the phene form")
        for cls in wrong[:20]:
            print("  " + cls)
        raise SystemExit(1 if wrong else 0)
    counts = update_release(args.release, args.release_date)
    print(f"phene form: {counts['equivalent']} definitions and {counts['subclass']} necessary conditions "
          f"rewritten, {counts['already']} already in the form")


if __name__ == "__main__":
    main()
