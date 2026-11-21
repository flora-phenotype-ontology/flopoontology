#!/usr/bin/env python3
"""Build the FLOPO value-space module and the bridge with its numeric axioms.

A value word of a flora stands for a range on a scale: "opposite" for two parts at a node,
"linear" for a blade at least ten times as long as wide, "acute" for an apex angle below 90
degrees (docs/odp/17-value-defined-by-a-measure.md). This builder writes, from the one specification
below,

    ontology/flopo-value-space-extension.ttl   OWL 2 EL: the temporary attribute classes and
                                               relations with their definitions, and the
                                               neighbours of each value; embedded in flopo.owl by
                                               tools/update_flopo_value_space_release.py
    ontology/flopo-value-ranges.ofn            OWL 2 DL bridge: the numeric axioms. Not imported
                                               by flopo.owl (ELK passes over data ranges); read it
                                               with HermiT or another OWL DL reasoner

Identifiers are the block FLOPO_0995000-FLOPO_0995999. The classes and relations are
placeholders: they belong in PATO and are replaced when PATO has them.

Sources of the numbers
    MLA    Ellis B, Daly DC, Hickey LJ, Johnson KR, Mitchell JD, Wilf P, Wing SL. Manual of Leaf
           Architecture. Cornell University Press, Ithaca, 2009. Cited by character number.
    SA62   Systematics Association Committee for Descriptive Biological Terminology. II.
           Terminology of simple symmetrical plane shapes (Chart 1). Taxon 1962;11(5):145-156.
           doi:10.2307/1216718. Recorded as a second reading, not as axioms.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef

ROOT = Path(__file__).resolve().parents[1]
OBO = Namespace("http://purl.obolibrary.org/obo/")
OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
MODULE = URIRef(OBO + "flopo-value-space-extension.owl")
BRIDGE = "http://purl.obolibrary.org/obo/flopo/flopo-value-ranges.owl"
OUTPUT = Path("ontology/flopo-value-space-extension.ttl")
BRIDGE_OUTPUT = Path("ontology/flopo-value-ranges.ofn")
ID_BLOCK = (995000, 995999)
ADDED = "2026-11-21"
DEFINITION = OBO.IAO_0000115
EDITOR_NOTE = OBO.IAO_0000116
EXAMPLE = OBO.IAO_0000112
CURATION_STATUS = OBO.IAO_0000114
PENDING_FINAL_VETTING = OBO.IAO_0000125
HAS_CHARACTERISTIC = "obo:RO_0000053"
HAS_MAGNITUDE = "ann:has_magnitude"

MLA = ("Ellis B, Daly DC, Hickey LJ, Johnson KR, Mitchell JD, Wilf P, Wing SL. Manual of Leaf Architecture. "
       "Cornell University Press, Ithaca, 2009")
SA62 = ("Systematics Association Committee for Descriptive Biological Terminology. II. Terminology of simple "
        "symmetrical plane shapes (Chart 1). Taxon 1962;11(5):145-156. doi:10.2307/1216718")

# --- relations -----------------------------------------------------------------------------------
PARTS_PER_NODE = "FLOPO:0995001"
NUMBER_OF_ROWS = "FLOPO:0995002"
NEIGHBOUR = "FLOPO:0995003"
RELATIONS = [
    {
        "id": PARTS_PER_NODE, "kind": "data", "label": "has number of parts per node",
        "definition": "A relation between an arrangement quality of an axis and the number of parts of one kind "
                      "that the axis bears at each of its nodes. The kind of part is the second entity of the "
                      "quality (RO:0002503 towards).",
        "source": MLA + ", character 2 (Leaf Arrangement: 'the placement of adjacent leaves on the nodes of the axis').",
        "example": "'alternate placement' EquivalentTo ('has number of parts per node' value 1): the shoot axis of "
                   "a plant with alternate leaves bears one leaf at each node.",
        "comment": "Functional: an arrangement quality has one number. The number is that of the usual node of the "
                   "axis; an axis with nodes of two kinds bears two arrangement qualities. Domain: quality "
                   "(PATO:0000001); the values so defined are today filed under both spatial pattern (alternate, "
                   "whorled) and position (opposite) in PATO. Range: integers of 1 or more (the lower bound is "
                   "stated in the bridge, OWL 2 EL has no facets).",
        "domain": "PATO:0000001", "range": XSD.integer, "minimum": 1,
    },
    {
        "id": NUMBER_OF_ROWS, "kind": "data", "label": "has number of rows",
        "definition": "A relation between a spatial pattern quality of a structure and the number of rows, series "
                      "or whorls in which the members of that structure are arranged.",
        "source": "Definitions of FLOPO:0991090 uniseriate, FLOPO:0991089 biseriate and FLOPO:0991084 multiseriate.",
        "example": "biseriate EquivalentTo ('has number of rows' value 2): an involucre with its bracts in two series.",
        "comment": "Functional. Domain: quality (PATO:0000001). Range: integers of 1 or more (lower bound in the bridge).",
        "domain": "PATO:0000001", "range": XSD.integer, "minimum": 1,
    },
    {
        "id": NEIGHBOUR, "kind": "annotation", "label": "has neighbouring value",
        "definition": "A relation between two value classes that are defined by ranges on the same scales, whose "
                      "ranges do not overlap, meet at a common bound on exactly one scale (or are consecutive "
                      "counts) and overlap on every other scale, so that a small change of one measured attribute "
                      "turns the one value into the other.",
        "source": "docs/odp/17-value-defined-by-a-measure.md",
        "example": "linear (length to width 10 or more) and lanceolate (3 to below 10) meet at 10; opposite (2 parts "
                   "per node) and whorled (3 or more) are consecutive counts.",
        "comment": "Symmetric; stated in both directions because an annotation property has no characteristics. "
                   "Derived from the ranges of the bridge by tools/build_flopo_value_space_extension.py, never "
                   "asserted by hand. Two values of which one range contains the other are not neighbours.",
    },
]

# --- attribute classes (dimensions) ---------------------------------------------------------------
LW, WP, APEX, BASE = "FLOPO:0995010", "FLOPO:0995011", "FLOPO:0995012", "FLOPO:0995013"
ATTRIBUTES = [
    {"id": LW, "label": "length to width ratio", "parent": "PATO:0001470", "scale": "ratio",
     "definition": "A ratio quality inhering in a flat bearer by virtue of the bearer's length divided by its "
                   "greatest width measured at right angles to its long axis.",
     "source": MLA + ", character 9 (Laminar L:W Ratio: 'Ratio of laminar length to maximum width perpendicular to the axis of the midvein')."},
    {"id": WP, "label": "relative position of the widest point", "parent": "PATO:0000140", "scale": "fraction from 0 (base) to 1 (apex)",
     "definition": "A position quality inhering in a flat bearer by virtue of the distance from the bearer's base "
                   "to its zone of greatest width, as a fraction of the bearer's length.",
     "source": MLA + ", character 10 (Laminar Shape: 'locate the midvein and determine the zone of greatest width measured perpendicular to the midvein')."},
    {"id": APEX, "label": "apex angle", "parent": "PATO:0002326", "scale": "degrees",
     "definition": "An angle quality inhering in a flat bearer by virtue of the angle, in degrees, between the two "
                   "rays that leave the end of the bearer's midvein at its apex and are tangent to its margins, "
                   "measured on the proximal side.",
     "source": MLA + ", character 16 (Apex Angle)."},
    {"id": BASE, "label": "base angle", "parent": "PATO:0002326", "scale": "degrees",
     "definition": "An angle quality inhering in a flat bearer by virtue of the angle, in degrees, between the two "
                   "rays that leave the point where the bearer's lowest laminar tissue joins its stalk and are "
                   "tangent to its margins, measured on the distal side.",
     "source": MLA + ", character 18 (Base Angle)."},
]

# --- values ---------------------------------------------------------------------------------------
# An interval is (low, low_inclusive, high, high_inclusive); None is unbounded.
PROXIMAL = (None, True, "0.4", True)
MIDDLE = ("0.4", False, "0.6", False)
DISTAL = ("0.6", True, None, True)
BELOW_10 = (None, True, "10", False)
NARROW = ("3", True, "10", False)

# Form B: a sufficient condition on measured attributes of the same bearer. One value may have
# several alternative cores (acute: apex angle or base angle).
MEASURED = [
    {"id": "PATO:0001199", "label": "linear", "cores": [{LW: ("10", True, None, True)}], "source": "character 10.5",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being at least 10 times as long as wide, wherever its widest point lies.",
     "sa62": "Chart 1, figure 12 (linearis): oblong series, parallel-sided, at 12:1; column 1 is not delimited outwards.",
     "observed": "length:width 4.74-61.10, median 17.32, n=4597"},
    {"id": "PATO:0001877", "label": "lanceolate", "cores": [{WP: PROXIMAL, LW: NARROW}], "source": "character 10.3",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being widest in the proximal two-fifths of its length and at least 3 but less than 10 times as long as wide.",
     "sa62": "Not in Chart 1: 'lanceolatus has been so variously used (principally for figures 2 and 37) ... It has become so imprecise in meaning that we have had to eliminate it from this scheme' (p. 146). Figure 2 is narrowly elliptic, figure 37 narrowly ovate, both in the column 6:1 to 3:1.",
     "observed": "length:width 2.16-13.42, median 5.00, n=5613"},
    {"id": "PATO:0002330", "label": "oblanceolate", "cores": [{WP: DISTAL, LW: NARROW}], "source": "character 10.2",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being widest in the distal two-fifths of its length and at least 3 but less than 10 times as long as wide.",
     "sa62": "Not in Chart 1 (eliminated with lanceolatus, p. 146); figures 45-46, anguste obovatus, 6:1 to 3:1.",
     "observed": "length:width 2.33-9.58, median 4.00, n=1654"},
    {"id": "FLOPO:0991024", "label": "ovate", "cores": [{WP: PROXIMAL, LW: BELOW_10}], "source": "character 10.3",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being widest in the proximal two-fifths of its length and less than 10 times as long as wide.",
     "sa62": "Chart 1, figures 38-39 (ovatus): widest at one third of the length from the base, 2:1 to 3:2; narrower and broader shapes take anguste (6:1-3:1), late (6:5) and latissime."},
    {"id": "PATO:0001936", "label": "obovate", "cores": [{WP: DISTAL, LW: BELOW_10}], "source": "character 10.2",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being widest in the distal two-fifths of its length and less than 10 times as long as wide.",
     "sa62": "Chart 1, figures 47-48 (obovatus): widest at one third of the length from the apex, 2:1 to 3:2.",
     "observed": "length:width 1.43-3.64, median 2.13, n=1533"},
    {"id": "PATO:0000947", "label": "elliptic", "cores": [{WP: MIDDLE, LW: ("1.2", False, "10", False)}], "source": "character 10.1",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being widest in the middle fifth of its length and more than 1.2 but less than 10 times as long as wide.",
     "sa62": "Chart 1, figures 3-4 (ellipticus): widest at the middle, 2:1 to 3:2.",
     "observed": "length:width 1.63-4.08, median 2.39, n=6561"},
    {"id": "PATO:0001934", "label": "orbicular", "cores": [{WP: MIDDLE, LW: ("1", True, "1.2", True)}], "source": "character 10.1",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being widest in the middle fifth of its length and 1 to 1.2 times as long as wide.",
     "sa62": "Chart 1, figure 6 (circularis, 1:1): 'we prefer circularis and subcircularis' to orbicularis (p. 147).",
     "observed": "length:width 0.77-2.30, median 1.18, n=808"},
    {"id": "PATO:0000409", "label": "oblate", "cores": [{WP: MIDDLE, LW: (None, True, "1", False)}], "source": "character 10.1",
     "definition": "A shape quality inhering in a flat bearer by virtue of the bearer being widest in the middle fifth of its length and wider than long.",
     "sa62": "Rejected in Chart 1: 'its use seems to be confined to English-speaking countries' (p. 147); the chart has transverse late ellipticus (5:6)."},
    {"id": "FLOPO:0991095", "label": "acute (sensu botany)", "source": "characters 16 and 18",
     "cores": [{APEX: ("0", False, "90", False)}, {BASE: ("0", False, "90", False)}],
     "definition": "A shape quality inhering in the apex or base of a flat bearer by virtue of its margins meeting at an angle of less than 90 degrees."},
    {"id": "PATO:0001935", "label": "obtuse", "source": "characters 16 and 18",
     "cores": [{APEX: ("90", True, "180", False)}, {BASE: ("90", True, "180", False)}],
     "definition": "A shape quality inhering in the apex or base of a flat bearer by virtue of its margins meeting at an angle of 90 degrees or more and less than 180 degrees."},
]

# Form A: the value is a count that belongs to the quality itself; an equivalence.
COUNTED = [
    {"id": "PATO:0001932", "label": "alternate placement", "property": PARTS_PER_NODE, "low": 1, "high": 1, "source": MLA + ", character 2.1.",
     "definition": "An arrangement quality inhering in an axis by virtue of the axis bearing one part of the kind concerned at each node."},
    {"id": "PATO:0001933", "label": "opposite", "property": PARTS_PER_NODE, "low": 2, "high": 2, "source": MLA + ", character 2.3.",
     "definition": "An arrangement quality inhering in an axis by virtue of the axis bearing two parts of the kind concerned at each node, on opposite sides of the axis."},
    {"id": "PATO:0001951", "label": "whorled", "property": PARTS_PER_NODE, "low": 3, "high": None, "source": MLA + ", character 2.4.",
     "definition": "An arrangement quality inhering in an axis by virtue of the axis bearing three or more parts of the kind concerned at each node."},
    {"id": "FLOPO:0991090", "label": "uniseriate", "property": NUMBER_OF_ROWS, "low": 1, "high": 1},
    {"id": "FLOPO:0991089", "label": "biseriate", "property": NUMBER_OF_ROWS, "low": 2, "high": 2},
    {"id": "FLOPO:0991084", "label": "multiseriate", "property": NUMBER_OF_ROWS, "low": 3, "high": None},
]


def _iri(curie: str) -> URIRef:
    return OBO[curie.replace(":", "_", 1)]


def _num(text: str | None, default: float) -> float:
    return default if text is None else float(text)


def _relation(a: tuple, b: tuple) -> str:
    """How two intervals stand: 'overlap', 'touch' (a common bound, no common point), 'apart'."""

    (alo, _ali, ahi, ahi_inc), (blo, blo_inc, bhi, _bhi_inc) = a, b
    if _num(alo, float("-inf")) > _num(blo, float("-inf")):
        return _relation(b, a)
    high, low = _num(ahi, float("inf")), _num(blo, float("-inf"))
    if high > low:
        return "overlap"
    if high < low:
        return "apart"
    return "overlap" if (ahi_inc and blo_inc) else "touch"


def neighbours() -> set[tuple[str, str]]:
    """Pairs of values whose ranges meet (the definition of FLOPO:0995003), from the specification."""

    pairs: set[tuple[str, str]] = set()
    everything = (None, True, None, True)
    for index, first in enumerate(MEASURED):
        for second in MEASURED[index + 1:]:
            for a in first["cores"]:
                for b in second["cores"]:
                    if not set(a) & set(b):
                        continue  # no common scale (a shape and an angle)
                    states = [_relation(a.get(d, everything), b.get(d, everything)) for d in sorted(set(a) | set(b))]
                    if states.count("touch") == 1 and states.count("overlap") == len(states) - 1:
                        pairs.add((first["id"], second["id"]))
    for index, first in enumerate(COUNTED):
        for second in COUNTED[index + 1:]:
            if first["property"] == second["property"] and (
                first["high"] is not None and first["high"] + 1 == second["low"]
                or second["high"] is not None and second["high"] + 1 == first["low"]
            ):
                pairs.add((first["id"], second["id"]))
    return pairs


def build_module() -> Graph:
    graph = Graph()
    for prefix, namespace in (("obo", OBO), ("oboInOwl", OIO), ("dcterms", DCTERMS)):
        graph.bind(prefix, namespace)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, RDFS.comment, Literal(__doc__.split("\n\n")[0], lang="en")))
    for row in [*RELATIONS, *ATTRIBUTES]:
        number = int(row["id"].split(":")[1])
        if not ID_BLOCK[0] <= number <= ID_BLOCK[1]:
            raise ValueError(f"{row['id']} is outside the reserved block")
    for row in RELATIONS:
        prop = _iri(row["id"])
        if row["kind"] == "data":
            graph.add((prop, RDF.type, OWL.DatatypeProperty))
            graph.add((prop, RDF.type, OWL.FunctionalProperty))
            graph.add((prop, RDFS.domain, _iri(row["domain"])))
            graph.add((prop, RDFS.range, row["range"]))
        else:
            graph.add((prop, RDF.type, OWL.AnnotationProperty))
        graph.add((prop, RDFS.label, Literal(row["label"], datatype=XSD.string)))
        graph.add((prop, DEFINITION, Literal(row["definition"], lang="en")))
        graph.add((prop, OIO.hasDbXref, Literal(row["source"], datatype=XSD.string)))
        graph.add((prop, EXAMPLE, Literal(row["example"], lang="en")))
        graph.add((prop, RDFS.comment, Literal(row["comment"], lang="en")))
        graph.add((prop, EDITOR_NOTE, Literal(
            f"Temporary FLOPO relation, added {ADDED}; proposed to PATO. Provisional: pending final curator vetting.", lang="en")))
        graph.add((prop, CURATION_STATUS, PENDING_FINAL_VETTING))
        graph.add((prop, DCTERMS.date, Literal(ADDED, datatype=XSD.date)))
    for row in ATTRIBUTES:
        cls = _iri(row["id"])
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((cls, RDFS.label, Literal(row["label"], datatype=XSD.string)))
        graph.add((cls, RDFS.subClassOf, _iri(row["parent"])))
        graph.add((cls, DEFINITION, Literal(row["definition"], lang="en")))
        graph.add((cls, OIO.hasDbXref, Literal(row["source"], datatype=XSD.string)))
        graph.add((cls, OIO.inSubset, URIRef("http://purl.obolibrary.org/obo/pato#attribute_slim")))
        graph.add((cls, RDFS.comment, Literal(f"Scale: {row['scale']}.", lang="en")))
        graph.add((cls, EDITOR_NOTE, Literal(
            f"Temporary FLOPO attribute class beneath {row['parent']}, added {ADDED} as the measured attribute "
            "by which value classes are defined (docs/odp/17-value-defined-by-a-measure.md); proposed to PATO. "
            "Provisional: pending final curator vetting.", lang="en")))
        graph.add((cls, CURATION_STATUS, PENDING_FINAL_VETTING))
        graph.add((cls, DCTERMS.date, Literal(ADDED, datatype=XSD.date)))
    neighbour = _iri(NEIGHBOUR)
    for first, second in sorted(neighbours()):
        graph.add((_iri(first), neighbour, _iri(second)))
        graph.add((_iri(second), neighbour, _iri(first)))
    return graph


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _c(curie: str) -> str:
    return "obo:" + curie.replace(":", "_", 1)


def _range(interval: tuple) -> str:
    low, low_inc, high, high_inc = interval
    facets = []
    if low is not None:
        facets.append(f'xsd:{"minInclusive" if low_inc else "minExclusive"} "{low}"^^xsd:decimal')
    if high is not None:
        facets.append(f'xsd:{"maxInclusive" if high_inc else "maxExclusive"} "{high}"^^xsd:decimal')
    return f"DatatypeRestriction(xsd:decimal {' '.join(facets)})"


def _measured(attribute: str, interval: tuple) -> str:
    return (f"ObjectSomeValuesFrom({HAS_CHARACTERISTIC} ObjectIntersectionOf({_c(attribute)} "
            f"DataSomeValuesFrom({HAS_MAGNITUDE} {_range(interval)})))")


def bridge_text() -> str:
    lines = [
        "Prefix(:=<" + BRIDGE + "#>)",
        "Prefix(obo:=<http://purl.obolibrary.org/obo/>)",
        "Prefix(ann:=<http://phenomebrowser.net/flopo/annotation/>)",
        "Prefix(owl:=<http://www.w3.org/2002/07/owl#>)",
        "Prefix(xsd:=<http://www.w3.org/2001/XMLSchema#>)",
        "Prefix(rdfs:=<http://www.w3.org/2000/01/rdf-schema#>)",
        "Prefix(dct:=<http://purl.org/dc/terms/>)",
        "",
        f"Ontology(<{BRIDGE}>",
        'Annotation(dct:title "FLOPO value ranges: numeric definitions of value classes (OWL 2 DL bridge)"@en)',
        "Annotation(rdfs:comment " + _q(
            "Generated by tools/build_flopo_value_space_extension.py; pattern docs/odp/17-value-defined-by-a-measure.md. "
            "Form A: a value defined by a count is equivalent to that count. Form B: a bearer with a measured "
            "attribute in the stated range has the value (a sufficient condition from a named source; the value "
            "is not restricted to the range). Not imported by flopo.owl: OWL 2 EL has no data-range facets. "
            "obo:IAO_0000115 on a PATO class here is the definition proposed to PATO, not PATO's own.") + "@en)",
        "",
        "Declaration(AnnotationProperty(:observedRange))",
        "AnnotationAssertion(rdfs:label :observedRange \"range used in the annotated floras\")",
        "AnnotationAssertion(obo:IAO_0000115 :observedRange " + _q(
            "The middle 80% of the length to width ratios in flora descriptions that give a blade length, a blade "
            "width and this one shape word (99,412 annotated descriptions, 2026-11-21). A record of usage, not a "
            "definition.") + "@en)",
        "Declaration(AnnotationProperty(:secondReading))",
        "AnnotationAssertion(rdfs:label :secondReading \"reading of the 1962 Systematics Association chart\")",
        "AnnotationAssertion(obo:IAO_0000115 :secondReading " + _q("What " + SA62 + " gives for the same word.") + "@en)",
        "Declaration(AnnotationProperty(:proposedDefinition))",
        "AnnotationAssertion(rdfs:label :proposedDefinition \"definition proposed to PATO\")",
        f"Declaration(ObjectProperty({HAS_CHARACTERISTIC}))",
        f"Declaration(DataProperty({HAS_MAGNITUDE}))",
        f"FunctionalDataProperty({HAS_MAGNITUDE})",
    ]
    for row in RELATIONS:
        if row["kind"] != "data":
            continue
        prop = _c(row["id"])
        lines += [
            f"Declaration(DataProperty({prop}))",
            f"AnnotationAssertion(rdfs:label {prop} {_q(row['label'])})",
            f"FunctionalDataProperty({prop})",
            f"DataPropertyDomain({prop} {_c(row['domain'])})",
            f'DataPropertyRange({prop} DatatypeRestriction(xsd:integer xsd:minInclusive "{row["minimum"]}"^^xsd:integer))',
        ]
    lines.append(f"Declaration(Class({_c('PATO:0000001')})) AnnotationAssertion(rdfs:label {_c('PATO:0000001')} \"quality\")")
    for row in ATTRIBUTES:
        cls = _c(row["id"])
        lines += [f"Declaration(Class({cls})) AnnotationAssertion(rdfs:label {cls} {_q(row['label'])})",
                  f"SubClassOf({cls} {_c(row['parent'])})"]
    lines += ["", "# --- form A: values defined by a count -------------------------------------------"]
    for row in COUNTED:
        cls, prop = _c(row["id"]), _c(row["property"])
        lines.append(f"Declaration(Class({cls})) AnnotationAssertion(rdfs:label {cls} {_q(row['label'])})")
        if row.get("definition"):
            lines.append(f"AnnotationAssertion(Annotation(dct:source {_q(row['source'])}) :proposedDefinition {cls} {_q(row['definition'])})")
        if row["high"] == row["low"]:
            expression = f'DataHasValue({prop} "{row["low"]}"^^xsd:integer)'
        else:
            expression = f'DataSomeValuesFrom({prop} DatatypeRestriction(xsd:integer xsd:minInclusive "{row["low"]}"^^xsd:integer))'
        lines.append(f"EquivalentClasses({cls} {expression})")
    lines += ["", "# --- form B: values that follow from a measured attribute of the same bearer ------"]
    for row in MEASURED:
        cls = _c(row["id"])
        source = f"{MLA}, {row['source']}."
        lines.append(f"Declaration(Class({cls})) AnnotationAssertion(rdfs:label {cls} {_q(row['label'])})")
        lines.append(f"AnnotationAssertion(Annotation(dct:source {_q(source)}) :proposedDefinition {cls} {_q(row['definition'])})")
        for core in row["cores"]:
            conditions = [_measured(attribute, core[attribute]) for attribute in sorted(core)]
            body = conditions[0] if len(conditions) == 1 else f"ObjectIntersectionOf({' '.join(conditions)})"
            lines.append(f"SubClassOf(Annotation(dct:source {_q(source)}) {body} ObjectSomeValuesFrom({HAS_CHARACTERISTIC} {cls}))")
        if row.get("observed"):
            lines.append(f"AnnotationAssertion(:observedRange {cls} {_q(row['observed'])})")
        if row.get("sa62"):
            lines.append(f"AnnotationAssertion(:secondReading {cls} {_q(row['sa62'])})")
    lines += ["", "# --- neighbours, derived from the ranges above -------------------------------------",
              f"Declaration(AnnotationProperty({_c(NEIGHBOUR)}))"]
    for first, second in sorted(neighbours()):
        lines.append(f"AnnotationAssertion({_c(NEIGHBOUR)} {_c(first)} {_c(second)})")
        lines.append(f"AnnotationAssertion({_c(NEIGHBOUR)} {_c(second)} {_c(first)})")
    lines.append(")")
    return "\n".join(lines) + "\n"


def write(root: Path = ROOT) -> dict[str, int]:
    graph = build_module()
    (root / OUTPUT).write_text(
        "# FLOPO value-space module. Generated by tools/build_flopo_value_space_extension.py;\n"
        "# embedded by tools/update_flopo_value_space_release.py.\n" + graph.serialize(format="turtle"),
        encoding="utf-8",
    )
    (root / BRIDGE_OUTPUT).write_text(bridge_text(), encoding="utf-8")
    return {"relations": len(RELATIONS), "attribute_classes": len(ATTRIBUTES),
            "values": len(MEASURED) + len(COUNTED), "neighbour_pairs": len(neighbours())}


def main() -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    print(write())


if __name__ == "__main__":
    main()
