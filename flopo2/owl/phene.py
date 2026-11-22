"""Phenotype classes as phenes: qualities of the plant, not classes of plants.

A phenotype class P is defined by a property Y that its bearers have:

    P EquivalentTo: 'flora phenotype' and 'phenotype of' some Y

where Y is the *defining property*, for example ``'has part' some (leaf and 'has characteristic'
some glabrous)``. This is the form of Hoehndorf, Oellrich and Rebholz-Schuhmann 2010
(doi:10.1093/bioinformatics/btq578: ``Phene and phene-of some Y``) and the quality reading of
Gkoutos, Schofield and Hoehndorf 2018 (doi:10.1093/bib/bbx035). ``'phenotype of'`` (RO:0002201) is
functional and the inverse of ``'has phenotype'`` (RO:0002200), as in the Relations Ontology: a
phene has one bearer, so a plant that has the phene of Y is itself a Y.

Subsumption between phenes follows subsumption between their defining properties, which OWL 2 EL
(ELK) computes. What needs the functionality, and so a complete OWL 2 DL reasoner, is the step
from two phenes of one plant to that plant; ``bearer_axioms`` states that step in OWL 2 EL, once
per class (``'has phenotype' some P SubClassOf Y``).

Code that analyses defining properties reads a release through ``defining_view``, which gives
every phene class its defining property as the class expression, the form the classes had before
2026-11-22.
"""

from __future__ import annotations

from rdflib import OWL, RDF, RDFS, BNode, Graph, URIRef
from rdflib.collection import Collection

OBO = "http://purl.obolibrary.org/obo/"
PHENOTYPE = URIRef(OBO + "FLOPO_0000000")  # 'flora phenotype'
PHENOTYPE_OF = URIRef(OBO + "RO_0002201")
HAS_PHENOTYPE = URIRef(OBO + "RO_0002200")
HAS_PART = URIRef(OBO + "BFO_0000051")
PHENOTYPE_OF_LABEL = "phenotype of"
HAS_PHENOTYPE_LABEL = "has phenotype"


def _phene_restriction(graph: Graph, node) -> object | None:
    if (node, OWL.onProperty, PHENOTYPE_OF) in graph:
        return graph.value(node, OWL.someValuesFrom)
    return None


def phene_body(graph: Graph, expression) -> object | None:
    """The defining property Y of ``phenotype and 'phenotype of' some Y`` (or of the bare
    restriction, as in a SubClassOf axiom); None when the expression is not of that form.
    Further conjuncts beside the two (the season in which an annotation class holds) are allowed."""

    if not isinstance(expression, BNode):
        return None
    body = _phene_restriction(graph, expression)
    if body is not None:
        return body
    members = graph.value(expression, OWL.intersectionOf)
    if members is None:
        return None
    items = list(Collection(graph, members))
    if not any(isinstance(item, URIRef) for item in items):
        return None
    for item in items:
        if isinstance(item, BNode):
            body = _phene_restriction(graph, item)
            if body is not None:
                return body
    return None


def _is_plain_phene(graph: Graph, expression) -> bool:
    """Exactly ``phenotype and 'phenotype of' some Y`` or the bare restriction."""

    members = graph.value(expression, OWL.intersectionOf)
    return members is None or len(list(Collection(graph, members))) == 2


def phene(graph: Graph, body, phenotype: URIRef = PHENOTYPE, *, restriction: BNode | None = None,
          node: BNode | None = None) -> BNode:
    """Write ``phenotype and 'phenotype of' some body`` and return its node."""

    restriction = restriction if restriction is not None else BNode()
    graph.add((restriction, RDF.type, OWL.Restriction))
    graph.add((restriction, OWL.onProperty, PHENOTYPE_OF))
    graph.add((restriction, OWL.someValuesFrom, body))
    node = node if node is not None else BNode()
    graph.add((node, RDF.type, OWL.Class))
    Collection(graph, _list_head(graph, node), [phenotype, restriction])
    return node


def _list_head(graph: Graph, node: BNode) -> BNode:
    head = BNode()
    graph.add((node, OWL.intersectionOf, head))
    return head


def declare_relations(graph: Graph) -> None:
    """The two relations with the axioms the form rests on (as in RO)."""

    graph.add((PHENOTYPE_OF, RDF.type, OWL.ObjectProperty))
    graph.add((PHENOTYPE_OF, RDF.type, OWL.FunctionalProperty))
    graph.add((PHENOTYPE_OF, RDFS.label, _label(PHENOTYPE_OF_LABEL)))
    graph.add((HAS_PHENOTYPE, RDF.type, OWL.ObjectProperty))
    graph.add((HAS_PHENOTYPE, RDFS.label, _label(HAS_PHENOTYPE_LABEL)))
    graph.add((HAS_PHENOTYPE, OWL.inverseOf, PHENOTYPE_OF))


def _label(text: str):
    from rdflib import Literal

    return Literal(text, lang="en")


def defining_view(graph: Graph) -> Graph:
    """Give every phene class its defining property as its class expression (in place).

    ``P EquivalentTo: phenotype and 'phenotype of' some Y`` becomes ``P EquivalentTo: Y`` and
    ``P SubClassOf: 'phenotype of' some Y`` becomes ``P SubClassOf: Y``; the wrapping nodes are
    removed. A graph without phene classes is returned unchanged.
    """

    changes = []
    for predicate in (OWL.equivalentClass, RDFS.subClassOf):
        for cls, expression in graph.subject_objects(predicate):
            body = phene_body(graph, expression)
            if body is not None and _is_plain_phene(graph, expression):
                changes.append((cls, predicate, expression, body))
    for cls, predicate, expression, body in changes:
        graph.remove((cls, predicate, expression))
        graph.add((cls, predicate, body))
    for _cls, _predicate, expression, _body in changes:
        if any(graph.subjects(None, expression)):
            continue  # still used by another axiom
        members = graph.value(expression, OWL.intersectionOf)
        if members is not None:
            for item in list(Collection(graph, members)):
                if isinstance(item, BNode):
                    graph.remove((item, None, None))
            Collection(graph, members).clear()
        graph.remove((expression, None, None))
    return graph


def phene_classes(graph: Graph) -> dict[URIRef, list]:
    """Named class -> defining properties of its EquivalentTo and SubClassOf phene axioms."""

    found: dict[URIRef, list] = {}
    for predicate in (OWL.equivalentClass, RDFS.subClassOf):
        for cls, expression in graph.subject_objects(predicate):
            if isinstance(cls, URIRef):
                body = phene_body(graph, expression)
                if body is not None:
                    found.setdefault(cls, []).append(body)
    return found


def bearer_axioms(graph: Graph, out: Graph | None = None) -> Graph:
    """``'has phenotype' some P SubClassOf Y`` for every phene class P with defining property Y.

    These follow from the functionality of 'phenotype of' and its inverse; they are in OWL 2 EL,
    so ELK finds a bearer of two incompatible phenes unsatisfiable. The expressions Y are shared
    with ``graph`` (the axioms are meant to be read together with it).
    """

    out = out if out is not None else Graph()
    for cls, bodies in sorted(phene_classes(graph).items()):
        for body in bodies:
            bearer = BNode()
            out.add((bearer, RDF.type, OWL.Restriction))
            out.add((bearer, OWL.onProperty, HAS_PHENOTYPE))
            out.add((bearer, OWL.someValuesFrom, cls))
            out.add((bearer, RDFS.subClassOf, body))
    return out
