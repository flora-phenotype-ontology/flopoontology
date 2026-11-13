"""The ShEx shapes and SPARQL rules of docs/odp/shapes/ accept a record of each pattern and
reject the record with the pattern's defining triples broken."""

from __future__ import annotations

import pytest

pyshex = pytest.importorskip("pyshex")
from rdflib import Graph, URIRef  # noqa: E402

from tools.validate_annotation_patterns import RULES, SHAPE_BASE, SHAPES, load_rules  # noqa: E402

PREFIXES = """
@prefix fb: <http://phenomebrowser.net/flopo/browse#> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/> .
"""
BASE = """ex:r a fb:TraitRecord ; fb:taxon ex:taxon ; fb:source ex:flora ; fb:status "accepted" ;
  fb:negated false ; fb:text "source words" ; rdfs:label "label" ; """

# shape -> (triples of a conforming record, the same with the pattern broken)
CASES = {
    "ApproximateValue": ('fb:bearer obo:PO_0009047 ; fb:quality obo:PATO_0000622 ; fb:qualifier "approximately" .',
                         'fb:bearer obo:PO_0009047 ; fb:quality obo:PATO_0000622 ; fb:qualifier "roughly" .'),
    "BoundedMeasurement": ('fb:bearer obo:PO_0009031 ; fb:quality obo:PATO_0000122 ; fb:high 1.0 ; fb:highExclusive true ; '
                           'fb:unit obo:UO_0000016 ; fb:unitSymbol "mm" .',
                           'fb:bearer obo:PO_0009031 ; fb:quality obo:PATO_0000122 ; fb:low 0.5 ; fb:high 1.0 ; '
                           'fb:unit obo:UO_0000016 ; fb:unitSymbol "mm" .'),
    "CountOfParts": ('fb:bearer obo:PO_0020049 ; fb:quality obo:PATO_0000070 ; fb:low 3.0 ; fb:high 5.0 ; '
                     'fb:unit obo:UO_0000189 ; fb:container obo:PO_0025034 .',
                     'fb:bearer obo:PO_0020049 ; fb:quality obo:PATO_0000122 ; fb:low 3.0 ; fb:high 5.0 ; fb:unit obo:UO_0000189 .'),
    "BearerState": ("fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0000453 ; fb:bearerState obo:FLOPO_0991002 .",
                    "fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0000453 ; fb:bearerState obo:PO_0025034 ."),
    "RangeWithExtremes": ('fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0000122 ; fb:low 3.0 ; fb:high 8.0 ; '
                          'fb:minExtreme 2.0 ; fb:maxExtreme 11.0 ; fb:unit obo:UO_0000015 .',
                          'fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0000122 ; fb:low 3.0 ; fb:high 8.0 ; fb:unit obo:UO_0000015 .'),
    "SpecimenCondition": ('fb:bearer obo:PO_0025034 ; fb:quality obo:FLOPO_0988011 ; fb:specimenCondition "dried" ; '
                          'fb:conditionText "when dry" .',
                          'fb:bearer obo:PO_0025034 ; fb:quality obo:FLOPO_0988011 ; fb:specimenCondition "dried" ; '
                          'fb:conditionText "when dry" ; fb:phenotypeClass ex:class .'),
    "AlternativesOfOneAttribute": ('fb:bearer obo:PO_0009046 ; fb:quality obo:FLOPO_0988009, obo:FLOPO_0988007 ; '
                                   'fb:valueOperator "one_of" ; fb:attribute obo:PATO_0000014 .',
                                   'fb:bearer obo:PO_0009046 ; fb:quality obo:FLOPO_0988009, obo:FLOPO_0988007 ; '
                                   'fb:valueOperator "one_of" ; fb:attribute obo:PATO_0000001 .'),
    "AlternativesAcrossAttributes": ('fb:bearer obo:PO_0009047 ; fb:quality obo:PATO_0001503, obo:PATO_0000402 ; '
                                     'fb:valueOperator "one_of" ; fb:attribute obo:PATO_0000001 ; fb:unionScope "across_attributes" .',
                                     'fb:bearer obo:PO_0009047 ; fb:quality obo:PATO_0001503 ; '
                                     'fb:valueOperator "one_of" ; fb:attribute obo:PATO_0000001 ; fb:unionScope "across_attributes" .'),
    "AlternativeWithFrequency": ('fb:bearer obo:PO_0009001 ; fb:quality obo:PATO_0000406, obo:PATO_0002180 ; fb:valueOperator "one_of" ; '
                                 'fb:alternative ex:alt . ex:alt a fb:Alternative ; fb:quality obo:PATO_0002180 ; '
                                 'fb:frequency "rarely" ; fb:text "rarely straight" .',
                                 'fb:bearer obo:PO_0009001 ; fb:quality obo:PATO_0000406, obo:PATO_0002180 ; fb:valueOperator "one_of" ; '
                                 'fb:frequency "rarely" ; fb:alternative ex:alt . ex:alt a fb:Alternative ; '
                                 'fb:quality obo:PATO_0002180 ; fb:frequency "rarely" ; fb:text "rarely straight" .'),
    "RelationToAnotherPart": ('fb:bearer obo:PO_0009029 ; fb:quality obo:PATO_0000642 ; fb:towards obo:PO_0009032 ; '
                              'fb:comparison "adnate to" .',
                              'fb:bearer obo:PO_0009029 ; fb:quality obo:PATO_0000642 ; fb:towards obo:PATO_0000014 ; '
                              'fb:comparison "adnate to" .'),
    "RatioToAnotherPart": ('fb:bearer obo:PO_0009067 ; fb:quality obo:PATO_0000573 ; fb:towards obo:PO_0009066 ; '
                           'fb:comparison "2-3 times as long as" ; fb:ratioLow 2.0 ; fb:ratioHigh 3.0 .',
                           'fb:bearer obo:PO_0009067 ; fb:quality obo:PATO_0000014 ; fb:towards obo:PO_0009066 ; '
                           'fb:comparison "2-3 times as long as" ; fb:ratioLow 2.0 ; fb:ratioHigh 3.0 .'),
    "RatioOfTwoDimensions": ('fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0001470 ; fb:low 2.0 ; fb:high 3.0 ; '
                             'fb:unit obo:UO_0000190 ; fb:ratioNumerator obo:PATO_0000122 ; fb:ratioDenominator obo:PATO_0000921 .',
                             'fb:bearer obo:PO_0025034 ; fb:quality obo:PATO_0001470 ; fb:low 2.0 ; fb:high 3.0 ; '
                             'fb:unit obo:UO_0000190 ; fb:ratioNumerator obo:PATO_0000122 .'),
    "PartOfQualifiedWhole": ('fb:bearer obo:PO_0009060 ; fb:quality obo:PATO_0000454 ; fb:whole obo:PO_0009046 ; '
                             'fb:wholeQuality obo:PATO_0000384 ; fb:wholeText "in male flowers" .',
                             'fb:bearer obo:PO_0009060 ; fb:quality obo:PATO_0000454 ; fb:whole obo:PO_0009046 ; '
                             'fb:wholeText "in male flowers" .'),
}


def conforms(shape: str, triples: str) -> bool:
    graph = Graph().parse(data=PREFIXES + BASE + triples, format="turtle")
    result = pyshex.ShExEvaluator(rdf=graph, schema=SHAPES.read_text(encoding="utf-8"),
                                  focus=URIRef("http://example.org/r"), start=URIRef(SHAPE_BASE + shape)).evaluate()[0]
    return bool(result.result)


@pytest.mark.parametrize("shape", sorted(CASES))
def test_shape_accepts_the_pattern_and_rejects_it_broken(shape):
    good, bad = CASES[shape]
    assert conforms(shape, good)
    assert not conforms(shape, bad)


def test_every_pattern_of_the_validator_has_a_shape_case():
    from tools.validate_annotation_patterns import PATTERNS

    assert {shape for shape, _ in PATTERNS.values()} == set(CASES)


BROKEN = {
    "extreme_outside_usual_range": "fb:low 3.0 ; fb:high 8.0 ; fb:maxExtreme 7.0 .",
    "range_low_not_above_high": "fb:low 9.0 ; fb:high 8.0 .",
    "specimen_condition_without_phenotype_class": 'fb:specimenCondition "dried" ; fb:phenotypeClass ex:class .',
    "alternative_is_a_value_of_its_record": "fb:quality obo:PATO_0000406 ; fb:alternative ex:alt . ex:alt fb:quality obo:PATO_0002180 .",
    "relation_target_is_not_the_bearer": "fb:bearer obo:PO_0009029 ; fb:towards obo:PO_0009029 .",
    "ratio_bounds_ordered_and_positive": "fb:ratioLow 3.0 ; fb:ratioHigh 2.0 .",
    "ratio_quality_agrees_with_ratio": "fb:quality obo:PATO_0000574 ; fb:ratioLow 2.0 ; fb:ratioHigh 3.0 .",
    "ratio_of_two_different_dimensions": "fb:ratioNumerator obo:PATO_0000122 ; fb:ratioDenominator obo:PATO_0000122 .",
    "whole_is_not_the_bearer": "fb:bearer obo:PO_0009046 ; fb:whole obo:PO_0009046 .",
    "count_is_a_whole_number": "fb:unit obo:UO_0000189 ; fb:low 2.5 .",
}


def test_each_rule_finds_the_record_that_breaks_it_and_passes_a_sound_one():
    rules = dict(load_rules(RULES))
    assert set(rules) == set(BROKEN)
    sound = Graph().parse(data=PREFIXES + "".join(BASE.replace("ex:r", f"ex:r{i}") + t
                                                  for i, (t, _bad) in enumerate(CASES.values())), format="turtle")
    for name, query in rules.items():
        assert not list(sound.query(query)), name
        broken = Graph().parse(data=PREFIXES + "ex:r " + BROKEN[name], format="turtle")
        assert [str(row[0]) for row in broken.query(query)] == ["http://example.org/r"], name
